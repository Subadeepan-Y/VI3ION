"""Claim verification against measured evidence.

Verdicts are limited to verified / contradicted / inconclusive. A claim is never
verified by another model's opinion; it is checked against geometry, OCR or
pixel measurements. Unsupported claims return inconclusive, not a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from ...schemas import (
    BBox,
    ClaimStatus,
    Evidence,
    EvidenceKind,
    VerificationMeasurement,
    VerificationResult,
)
from ..pixels.colors import NAMED_COLORS, delta_e, describe_color, dominant_colors, rgb_to_lab
from .claims import COLOR_WORDS, ORDINAL_WORDS, ParsedClaim, ordinal_reference, parse_claim

SHAPE_NOUNS: dict[str, set[str]] = {
    "button": {"rectangle", "square"},
    "box": {"rectangle", "square"},
    "card": {"rectangle", "square"},
    "panel": {"rectangle", "square"},
    "window": {"rectangle", "square"},
    "dialog": {"rectangle", "square"},
    "modal": {"rectangle", "square"},
    "input": {"rectangle", "square"},
    "field": {"rectangle", "square"},
    "textbox": {"rectangle", "square"},
    "rectangle": {"rectangle"},
    "rect": {"rectangle"},
    "square": {"square"},
    "circle": {"circle"},
    "icon": {"square", "rectangle", "polygon"},
    "element": {"rectangle", "square", "circle", "polygon", "triangle", "ellipse"},
    "region": {"rectangle", "square", "circle", "polygon", "triangle", "ellipse"},
}

# Function words never help disambiguate a visual reference.
_REFERENCE_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "with", "is", "are",
    "that", "this", "for", "in", "on", "at", "by", "as", "it",
}

# Which perception module produced the measurements behind each verdict.
METHOD_BY_INTENT = {
    "alignment": "geometry.alignment",
    "distance": "geometry.distance",
    "size": "geometry.size",
    "containment": "geometry.containment",
    "overlap": "geometry.overlap",
    "text_present": "ocr.text_present",
    "color": "pixels.color",
    "dimensions": "image.dimensions",
    "existence": "evidence.existence",
}

ALIGNMENT_ATTRS = {
    "left": "left",
    "right": "right",
    "top": "top",
    "bottom": "bottom",
    "center": "center_x",
    "center_x": "center_x",
    "center_y": "center_y",
}


@dataclass
class RefElement:
    id: str
    label: str
    bbox: BBox
    kind: str
    text: str | None = None


@dataclass
class Resolution:
    element: RefElement | None
    note: str = ""
    ambiguous: bool = False


class Resolver:
    def __init__(self, evidence: list[Evidence]):
        self.texts = [e for e in evidence if e.kind == EvidenceKind.TEXT and e.bbox]
        self.texts.sort(key=lambda e: int(e.attributes.get("reading_order", 9999)))
        self.shapes = [e for e in evidence if e.kind == EvidenceKind.SHAPE and e.bbox]
        self.shapes.sort(key=lambda e: (e.bbox.center_y, e.bbox.x0) if e.bbox else (0, 0))
        self.objects = [e for e in evidence if e.kind == EvidenceKind.OBJECT and e.bbox]
        self.by_id = {e.evidence_id: e for e in evidence}

    def _ref(self, e: Evidence) -> RefElement:
        text = e.attributes.get("text")
        kind = "text" if e.kind == EvidenceKind.TEXT else "object" if e.kind == EvidenceKind.OBJECT else "shape"
        return RefElement(
            id=e.evidence_id,
            label=str(e.label),
            bbox=e.bbox,
            kind=kind,
            text=str(text) if text else None,
        )

    def resolve(self, reference: str | None, quoted: bool = False) -> Resolution:
        if not reference:
            return Resolution(None, "no subject reference in claim")
        ref = reference.strip().strip("\"'").strip()
        if ref in self.by_id and self.by_id[ref].bbox is not None:
            return Resolution(self._ref(self.by_id[ref]), "matched by evidence id")
        ref_l = ref.lower()

        ordinal, noun = ordinal_reference(ref_l)
        noun = noun.strip()

        # Exact OCR text is the strongest human reference.
        exact = [t for t in self.texts if (t.attributes.get("text") or t.label).strip().lower() == ref_l]
        if exact:
            if len(exact) == 1:
                return Resolution(self._ref(exact[0]), "matched exact OCR text")
            labels = ", ".join(f"{e.label!r} at {e.bbox.as_rounded() if e.bbox else ''}" for e in exact[:4])
            return Resolution(None, f"reference {ref!r} matches {len(exact)} text items: {labels}", True)

        contains = [
            t for t in self.texts
            if ref_l in (t.attributes.get("text") or t.label).strip().lower()
        ]
        if len(contains) == 1:
            return Resolution(self._ref(contains[0]), "matched OCR text (substring)")

        # Ordinal + noun ("third button").
        if ordinal is not None and noun:
            candidates = self._noun_candidates(noun)
            if candidates:
                index = ordinal if ordinal >= 0 else len(candidates) + ordinal
                if 0 <= index < len(candidates):
                    return Resolution(
                        self._ref(candidates[index]),
                        f"resolved {ordinal} {noun} as geometry proxy {candidates[index].label!r}",
                    )
                return Resolution(None, f"only {len(candidates)} {noun}-like element(s) found; ordinal out of range")

        # Bare noun ("button", "rectangle").
        if noun:
            candidates = self._noun_candidates(noun)
            objects = [e for e in candidates if e.kind == EvidenceKind.OBJECT]
            if len(objects) == 1:
                return Resolution(self._ref(objects[0]), f"matched semantic object {objects[0].label!r}")
            if len(candidates) == 1:
                return Resolution(self._ref(candidates[0]), f"matched single {noun} candidate")
            if len(candidates) > 1:
                labels = ", ".join(f"{e.label!r}" for e in candidates[:5])
                return Resolution(
                    None,
                    f"{len(candidates)} {noun}-like elements match; be specific or use an evidence id ({labels})",
                    True,
                )

        # Exact shape/object label.
        label_matches = [
            e for e in [*self.shapes, *self.objects] if e.label.strip().lower() == ref_l
        ]
        if len(label_matches) == 1:
            return Resolution(self._ref(label_matches[0]), "matched evidence label")

        # "Save button": the shape that holds the text, not the text itself.
        shape = self._shape_containing_text(ref_l)
        if shape is not None:
            return Resolution(self._ref(shape), "matched the shape holding that text")

        # Token overlap: "save button" resolves to the text/shape whose label or
        # OCR text shares a distinctive token ("save"). Prefer single matches.
        tokens = [
            token for token in ref_l.replace("-", " ").split()
            if len(token) >= 3 and token not in _REFERENCE_STOPWORDS
        ]
        if tokens:
            scored: list[tuple[int, int, Evidence]] = []
            for element in [*self.shapes, *self.texts, *self.objects]:
                hay = (
                    element.label.lower()
                    + " "
                    + str(element.attributes.get("text") or "").lower()
                )
                hits = sum(
                    1 for token in tokens if re.search(rf"\b{re.escape(token)}\b", hay)
                )
                if hits:
                    scored.append((hits, -len(hay), element))
            if scored:
                best_hits = max(score[0] for score in scored)
                top = [score for score in scored if score[0] == best_hits]
                if len(top) == 1:
                    element = top[0][2]
                    return Resolution(
                        self._ref(element),
                        f"matched by token overlap ({element.label!r})",
                    )
                if len(top) > 1:
                    labels = ", ".join(f"{e.label!r}" for _, _, e in top[:5])
                    return Resolution(None, f"reference {ref!r} is ambiguous: {labels}", True)

        # Last resort: substring over labels.
        loose = [e for e in [*self.texts, *self.objects, *self.shapes] if ref_l in e.label.lower()]
        if len(loose) == 1:
            return Resolution(self._ref(loose[0]), "matched label substring")
        if len(loose) > 1:
            labels = ", ".join(f"{e.label!r}" for e in loose[:5])
            return Resolution(None, f"reference {ref!r} is ambiguous: {labels}", True)
        return Resolution(None, f"no visible element matches {ref!r}")

    def _shape_containing_text(self, ref_l: str) -> Evidence | None:
        """The shape that visually holds the text named in a reference.

        "the Save button" is the blue rectangle around the word Save, not the
        letters themselves, so a colour claim about the button is about the
        shape's fill.
        """
        if not any(noun in ref_l for noun in SHAPE_NOUNS):
            return None
        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", ref_l)
            if len(token) >= 3 and token not in _REFERENCE_STOPWORDS
        ]
        if not tokens:
            return None
        text_hits = [
            text
            for text in self.texts
            if any(
                re.search(rf"\b{re.escape(token)}\b", (text.attributes.get("text") or text.label).lower())
                for token in tokens
            )
        ]
        if not text_hits:
            return None
        containing: dict[str, Evidence] = {}
        for shape in self.shapes:
            if shape.bbox is None:
                continue
            for text in text_hits:
                if text.bbox is not None and shape.bbox.contains(text.bbox, tolerance=2.0):
                    containing[shape.evidence_id] = shape
                    break
        if len(containing) == 1:
            return next(iter(containing.values()))
        return None

    def _noun_candidates(self, noun: str) -> list[Evidence]:
        objects = [e for e in self.objects if noun in e.label.lower()]
        if objects:
            return objects
        shapes = [e for e in self.shapes if e.attributes.get("shape") in SHAPE_NOUNS.get(noun, set())]
        if shapes:
            return shapes
        if noun in SHAPE_NOUNS:
            return []
        return [e for e in self.shapes if noun in e.label.lower()]


class ClaimVerifier:
    def __init__(
        self,
        image_id: str,
        evidence: list[Evidence],
        width: int,
        height: int,
        bgr: np.ndarray | None = None,
        ocr_available: bool = False,
    ):
        self.image_id = image_id
        self.evidence = evidence
        self.width = width
        self.height = height
        self.bgr = bgr
        self.ocr_available = ocr_available
        # Reference resolution operates on whole-image evidence only. Region crops
        # are derived views and must not shadow the canonical elements.
        base = [e for e in evidence if e.scope == "image"]
        self.resolver = Resolver(base) if base else Resolver([])

    @property
    def tolerance(self) -> float:
        return max(2.0, min(self.width, self.height) * 0.004)

    # ------------------------------------------------------------------ public
    def verify(self, claim: str | dict) -> VerificationResult:
        parsed = parse_claim(claim)
        raw = parsed.raw or str(claim)
        if parsed.intent == "alignment":
            result = self._alignment(parsed, raw)
        elif parsed.intent == "distance":
            result = self._distance(parsed, raw)
        elif parsed.intent == "size":
            result = self._size(parsed, raw)
        elif parsed.intent == "containment":
            result = self._containment(parsed, raw)
        elif parsed.intent == "overlap":
            result = self._overlap(parsed, raw)
        elif parsed.intent == "text_present":
            result = self._text(parsed, raw)
        elif parsed.intent == "color":
            result = self._color(parsed, raw)
        elif parsed.intent == "dimensions":
            result = self._dimensions(parsed, raw)
        elif parsed.intent == "existence":
            result = self._existence(parsed, raw)
        else:
            return self._inconclusive(
                raw,
                "This claim type cannot be checked by deterministic evidence. Vi3ion supports "
                "alignment, pixel distance, size comparison, containment, overlap, visible text, "
                "region colour and image dimensions. Use inspect_region to gather more evidence first.",
            )
        if result.method == "rule_based":
            result.method = METHOD_BY_INTENT.get(parsed.intent, "rule_based")
        return result

    # ---------------------------------------------------------------- helpers
    def _both(self, parsed: ParsedClaim) -> tuple[RefElement | None, RefElement | None, list[str]]:
        notes: list[str] = []
        subject = self.resolver.resolve(parsed.subject)
        if subject.element is None:
            notes.append(f"subject: {subject.note}")
        obj = self.resolver.resolve(parsed.object)
        if obj.element is None:
            notes.append(f"object: {obj.note}")
        if subject.element is not None and subject.note.startswith("resolved"):
            notes.append(subject.note)
        if obj.element is not None and obj.note.startswith("resolved"):
            notes.append(obj.note)
        return subject.element, obj.element, notes

    def _result(
        self,
        claim: str,
        status: ClaimStatus,
        confidence: float,
        explanation: str,
        measurements: list[VerificationMeasurement] | None = None,
        evidence_ids: list[str] | None = None,
    ) -> VerificationResult:
        return VerificationResult(
            claim=claim,
            status=status,
            confidence=round(confidence, 3),
            explanation=explanation,
            measurements=measurements or [],
            evidence_ids=evidence_ids or [],
        )

    def _inconclusive(self, claim: str, reason: str, notes: list[str] | None = None) -> VerificationResult:
        detail = reason
        if notes:
            detail = detail + " " + " ".join(notes)
        return self._result(claim, ClaimStatus.INCONCLUSIVE, 0.35, detail)

    # ------------------------------------------------------------------ checks
    def _alignment(self, parsed: ParsedClaim, raw: str) -> VerificationResult:
        a, b, notes = self._both(parsed)
        if a is None or b is None:
            return self._inconclusive(raw, "Cannot resolve both elements for an alignment check.", notes)
        tolerance = self.tolerance
        deltas = {
            "left": b.bbox.x0 - a.bbox.x0,
            "right": b.bbox.x1 - a.bbox.x1,
            "top": b.bbox.y0 - a.bbox.y0,
            "bottom": b.bbox.y1 - a.bbox.y1,
            "center_x": b.bbox.center_x - a.bbox.center_x,
            "center_y": b.bbox.center_y - a.bbox.center_y,
        }
        requested = None
        if parsed.attribute:
            key = parsed.attribute.lower().replace(" ", "_")
            requested = ALIGNMENT_ATTRS.get(key, key)
        candidates = [requested] if requested and requested in deltas else list(deltas)
        measurements = [
            VerificationMeasurement(
                name=f"{edge}_edge_delta",
                subject=a.label,
                value=round(deltas[edge], 2),
                expected=0.0,
                delta=round(abs(deltas[edge]), 2),
                unit="px",
                tolerance=round(tolerance, 2),
            )
            for edge in candidates
        ]
        aligned = [edge for edge in candidates if abs(deltas[edge]) <= tolerance]
        closest = min(candidates, key=lambda edge: abs(deltas[edge]))
        if aligned:
            edges = ", ".join(aligned)
            return self._result(
                raw,
                ClaimStatus.VERIFIED,
                min(0.98, 0.8 + 0.1 * len(aligned)),
                f"{a.label!r} and {b.label!r} share {edges} alignment within {tolerance:.1f} px "
                f"({closest} delta {deltas[closest]:+.1f} px).",
                measurements,
                [a.id, b.id],
            )
        return self._result(
            raw,
            ClaimStatus.CONTRADICTED,
            0.9,
            f"Not aligned: the closest matching edge is {closest} with a {deltas[closest]:+.1f} px "
            f"difference; tolerance is {tolerance:.1f} px.",
            measurements,
            [a.id, b.id],
        )

    def _distance(self, parsed: ParsedClaim, raw: str) -> VerificationResult:
        a, b, notes = self._both(parsed)
        if a is None or b is None:
            return self._inconclusive(raw, "Cannot resolve both elements for a distance check.", notes)
        if parsed.value is None:
            return self._inconclusive(raw, "No pixel distance was specified in the claim.")
        direction = (parsed.direction or "").lower()
        if "right" in direction:
            measured = a.bbox.center_x - b.bbox.center_x
            gap = max(0.0, a.bbox.x0 - b.bbox.x1)
            axis, sign = "x", 1
        elif "left" in direction:
            measured = b.bbox.center_x - a.bbox.center_x
            gap = max(0.0, b.bbox.x0 - a.bbox.x1)
            axis, sign = "x", -1
        elif "above" in direction or "higher" in direction:
            measured = b.bbox.center_y - a.bbox.center_y
            gap = max(0.0, b.bbox.y1 - a.bbox.y0)
            axis, sign = "y", -1
        else:
            measured = a.bbox.center_y - b.bbox.center_y
            gap = max(0.0, a.bbox.y0 - b.bbox.y1)
            axis, sign = "y", 1

        expected = float(parsed.value)
        tolerance = max(2.0, expected * 0.02, min(self.width, self.height) * 0.002)
        delta = measured - expected
        measurements = [
            VerificationMeasurement(
                name=f"center_distance_{axis}",
                subject=f"{a.label} relative to {b.label}",
                value=round(measured, 2),
                expected=expected,
                delta=round(delta, 2),
                unit="px",
                tolerance=round(tolerance, 2),
            ),
            VerificationMeasurement(
                name=f"edge_gap_{axis}",
                subject=f"{a.label} relative to {b.label}",
                value=round(gap, 2),
                expected=None,
                unit="px",
            ),
        ]
        if measured < 0:
            return self._result(
                raw,
                ClaimStatus.CONTRADICTED,
                0.95,
                f"{a.label!r} is on the opposite side of {b.label!r} along {axis} "
                f"(signed centre distance {measured:+.1f} px).",
                measurements,
                [a.id, b.id],
            )
        if abs(delta) <= tolerance:
            return self._result(
                raw,
                ClaimStatus.VERIFIED,
                0.95,
                f"{a.label!r} is {measured:.1f} px from {b.label!r} along {axis} "
                f"(claimed {expected:.1f} px, tolerance {tolerance:.1f} px). Edge gap is {gap:.1f} px.",
                measurements,
                [a.id, b.id],
            )
        return self._result(
            raw,
            ClaimStatus.CONTRADICTED,
            0.9,
            f"Measured {measured:.1f} px along {axis}, not {expected:.1f} px "
            f"(difference {delta:+.1f} px, tolerance {tolerance:.1f} px).",
            measurements,
            [a.id, b.id],
        )

    def _size(self, parsed: ParsedClaim, raw: str) -> VerificationResult:
        a, b, notes = self._both(parsed)
        if a is None or b is None:
            return self._inconclusive(raw, "Cannot resolve both elements for a size comparison.", notes)
        comparison = parsed.comparison or ""
        if comparison in ("wider", "narrower"):
            av, bv, label = a.bbox.width, b.bbox.width, "width"
        elif comparison in ("taller", "shorter"):
            av, bv, label = a.bbox.height, b.bbox.height, "height"
        else:
            av, bv, label = a.bbox.area, b.bbox.area, "area"
        holds = av > bv if comparison in ("wider", "taller", "larger", "bigger") else av < bv
        measurements = [
            VerificationMeasurement(
                name=f"{label}_comparison",
                subject=a.label,
                value=round(av, 1),
                expected=None,
                unit="px" if label != "area" else "px^2",
            ),
            VerificationMeasurement(
                name=f"{label}_comparison",
                subject=b.label,
                value=round(bv, 1),
                expected=None,
                unit="px" if label != "area" else "px^2",
            ),
        ]
        detail = (
            f"{a.label!r} {label} is {av:.1f}, {b.label!r} {label} is {bv:.1f}. "
            f"Claim that {a.label!r} is {comparison} than {b.label!r} is "
            f"{'supported' if holds else 'not supported'}."
        )
        return self._result(
            raw,
            ClaimStatus.VERIFIED if holds else ClaimStatus.CONTRADICTED,
            0.93,
            detail,
            measurements,
            [a.id, b.id],
        )

    def _containment(self, parsed: ParsedClaim, raw: str) -> VerificationResult:
        a, b, notes = self._both(parsed)
        if a is None or b is None:
            return self._inconclusive(raw, "Cannot resolve both elements for a containment check.", notes)
        contained = b.bbox.contains(a.bbox, tolerance=2.0)
        iou = a.bbox.iou(b.bbox)
        measurements = [
            VerificationMeasurement(
                name="containment",
                subject=a.label,
                value=round(iou, 3),
                expected="fully inside " + b.label,
                unit="iou",
            ),
            VerificationMeasurement(
                name="inset_left_px", subject=a.label, value=round(a.bbox.x0 - b.bbox.x0, 1), unit="px"
            ),
            VerificationMeasurement(
                name="inset_top_px", subject=a.label, value=round(a.bbox.y0 - b.bbox.y0, 1), unit="px"
            ),
        ]
        if contained:
            return self._result(
                raw, ClaimStatus.VERIFIED, 0.95,
                f"{a.label!r} is fully inside {b.label!r}; IoU is {iou:.3f}.",
                measurements, [a.id, b.id],
            )
        return self._result(
            raw, ClaimStatus.CONTRADICTED, 0.9,
            f"{a.label!r} is not fully inside {b.label!r} (IoU {iou:.3f}); bounding boxes intersect "
            f"or are disjoint.",
            measurements, [a.id, b.id],
        )

    def _overlap(self, parsed: ParsedClaim, raw: str) -> VerificationResult:
        a, b, notes = self._both(parsed)
        if a is None or b is None:
            return self._inconclusive(raw, "Cannot resolve both elements for an overlap check.", notes)
        intersection = a.bbox.intersect(b.bbox)
        iou = a.bbox.iou(b.bbox)
        measurements = [
            VerificationMeasurement(
                name="intersection_area_px2",
                subject=f"{a.label} / {b.label}",
                value=round(intersection.area, 1) if intersection else 0.0,
                expected=None,
                unit="px^2",
            ),
            VerificationMeasurement(
                name="iou", subject=f"{a.label} / {b.label}", value=round(iou, 3), unit="ratio"
            ),
        ]
        if intersection is not None and intersection.area > 0:
            return self._result(
                raw, ClaimStatus.VERIFIED, 0.95,
                f"Bounding boxes overlap: {intersection.area:.0f} px^2, IoU {iou:.3f}.",
                measurements, [a.id, b.id],
            )
        return self._result(
            raw, ClaimStatus.CONTRADICTED, 0.95,
            "Bounding boxes do not overlap.", measurements, [a.id, b.id],
        )

    def _text(self, parsed: ParsedClaim, raw: str) -> VerificationResult:
        needle = (parsed.text or "").strip()
        if not needle:
            return self._inconclusive(raw, "No text was specified in the claim.")
        needle_l = " ".join(needle.lower().split())
        matches = [
            e for e in self.resolver.texts
            if needle_l in " ".join(str(e.attributes.get("text", e.label)).lower().split())
        ]
        measurements = [
            VerificationMeasurement(
                name="text_occurrences",
                subject=needle,
                value=len(matches),
                expected=">=1",
                unit="count",
            )
        ]
        if matches:
            best = matches[0]
            measurements.append(
                VerificationMeasurement(
                    name="bbox",
                    subject=needle,
                    value=best.bbox.as_rounded() if best.bbox else None,
                    expected=None,
                    unit="px",
                )
            )
            return self._result(
                raw, ClaimStatus.VERIFIED, 0.93,
                f"Visible text {needle!r} found {len(matches)} time(s); first at "
                f"{best.bbox.as_rounded() if best.bbox else 'unknown'}.",
                measurements,
                [e.evidence_id for e in matches[:5]],
            )
        if self.ocr_available:
            return self._result(
                raw, ClaimStatus.CONTRADICTED, 0.8,
                f"Text {needle!r} was not found by OCR. OCR can miss very small, stylised or "
                f"low-contrast text, so treat this as strong but not absolute evidence.",
                measurements,
            )
        return self._inconclusive(
            raw, "OCR is unavailable, so absence of text cannot be established.", []
        )

    def _color(self, parsed: ParsedClaim, raw: str) -> VerificationResult:
        subject = self.resolver.resolve(parsed.subject)
        if subject.element is None:
            return self._inconclusive(raw, "Cannot resolve the element whose colour is claimed.", [subject.note])
        element = subject.element
        claimed = (parsed.color or "").lower()

        # Prefer the element's own measured colour (ink on its background) over
        # the average of its box: "the text 'Save' is white" is about the
        # letters, "the button is blue" is about the fill.
        measured = self._measured_element_color(element.id)
        if measured:
            return self._color_against_measured(element, measured, claimed, raw)

        if self.bgr is None:
            return self._inconclusive(raw, "Pixel data is unavailable for this verification call.")
        sampled = _sample_region_color(self.bgr, element.bbox)
        if sampled is None:
            return self._inconclusive(raw, "The resolved region is empty.")

        measurements = [
            VerificationMeasurement(
                name="region_hex", subject=element.label, value=sampled["hex"], expected=None
            ),
            VerificationMeasurement(
                name="region_color_name",
                subject=element.label,
                value=sampled["name"],
                expected=claimed,
            ),
            VerificationMeasurement(
                name="region_share",
                subject=element.label,
                value=sampled["share"],
                expected=None,
                unit="ratio",
            ),
        ]
        if claimed in ("dark", "light"):
            brightness = sampled["lightness"] / 100.0
            ok = brightness < 0.4 if claimed == "dark" else brightness > 0.6
            measurements.append(
                VerificationMeasurement(
                    name="lightness", subject=element.label, value=round(brightness, 3), unit="ratio"
                )
            )
            return self._result(
                raw,
                ClaimStatus.VERIFIED if ok else ClaimStatus.CONTRADICTED,
                0.85,
                f"{element.label!r} has mean lightness {brightness:.2f}; the claim {claimed!r} is "
                f"{'consistent' if ok else 'inconsistent'} with it.",
                measurements,
                [element.id],
            )

        if claimed.startswith("#") and re.fullmatch(r"#[0-9a-f]{6}", claimed):
            target_rgb = tuple(int(claimed[i : i + 2], 16) for i in (1, 3, 5))
            target_lab = rgb_to_lab(target_rgb)
            name = claimed
        else:
            key = "gray" if claimed == "grey" else claimed
            if key not in NAMED_COLORS:
                return self._inconclusive(
                    raw, f"Colour {claimed!r} is not in the named-colour reference set."
                )
            target_lab = rgb_to_lab(NAMED_COLORS[key])
            name = key

        difference = delta_e(target_lab, tuple(sampled["lab"]))
        measurements.append(
            VerificationMeasurement(
                name="delta_e",
                subject=element.label,
                value=round(difference, 1),
                expected=f"<= {26}",
                unit="CIELAB",
            )
        )
        if difference <= 26 or sampled["name"] == name:
            return self._result(
                raw, ClaimStatus.VERIFIED, 0.9,
                f"Dominant colour of {element.label!r} is {sampled['hex']} ({sampled['name']}), "
                f"which is consistent with {claimed!r} (ΔE {difference:.1f}).",
                measurements, [element.id],
            )
        if difference >= 45:
            return self._result(
                raw, ClaimStatus.CONTRADICTED, 0.85,
                f"Dominant colour of {element.label!r} is {sampled['hex']} ({sampled['name']}), "
                f"not {claimed!r} (ΔE {difference:.1f}).",
                measurements, [element.id],
            )
        return self._inconclusive(
            raw,
            f"Dominant colour {sampled['hex']} ({sampled['name']}) is perceptually between the claim "
            f"and a contradiction (ΔE {difference:.1f}).",
            [f"element: {element.label}"],
        )

    def _measured_element_color(self, element_id: str) -> dict | None:
        """The colour measured for an element during analysis, if any."""
        for item in self.evidence:
            if item.evidence_id != element_id:
                continue
            attributes = item.attributes or {}
            if not attributes.get("ink_hex"):
                return None
            return {
                "hex": attributes.get("ink_hex"),
                "rgb": attributes.get("ink_rgb") or [],
                "name": attributes.get("ink_name") or "",
                "bg_hex": attributes.get("bg_hex"),
                "bg_name": attributes.get("bg_name"),
                "contrast": attributes.get("contrast"),
                "share": attributes.get("ink_share"),
            }
        return None

    def _color_against_measured(
        self,
        element: RefElement,
        measured: dict,
        claimed: str,
        raw: str,
    ) -> VerificationResult:
        """Compare a claim with an element's measured ink/fill colour."""
        hex_value = str(measured.get("hex") or "")
        rgb = measured.get("rgb") or []
        if not hex_value or len(rgb) != 3:
            return self._inconclusive(raw, "The element has no usable measured colour.")
        actual_rgb = tuple(int(v) for v in rgb)
        actual_lab = rgb_to_lab(actual_rgb)
        name = str(measured.get("name") or "")

        measurements = [
            VerificationMeasurement(
                name="element_hex", subject=element.label, value=hex_value, expected=None
            ),
            VerificationMeasurement(
                name="element_color_name",
                subject=element.label,
                value=name,
                expected=claimed,
            ),
        ]
        if measured.get("bg_hex"):
            measurements.append(
                VerificationMeasurement(
                    name="background_hex",
                    subject=element.label,
                    value=str(measured.get("bg_hex")),
                    expected=None,
                )
            )
        if isinstance(measured.get("contrast"), (int, float)):
            measurements.append(
                VerificationMeasurement(
                    name="contrast",
                    subject=element.label,
                    value=measured.get("contrast"),
                    unit="ratio",
                )
            )

        background = (
            f" on {measured.get('bg_hex')}" if measured.get("bg_hex") else ""
        )
        if claimed in ("dark", "light"):
            lightness = actual_lab[0] / 100.0
            ok = lightness < 0.4 if claimed == "dark" else lightness > 0.6
            return self._result(
                raw,
                ClaimStatus.VERIFIED if ok else ClaimStatus.CONTRADICTED,
                0.9,
                f"Measured colour of {element.label!r} is {hex_value} ({name}){background}, "
                f"lightness {lightness:.2f}; the claim {claimed!r} is "
                f"{'consistent' if ok else 'inconsistent'} with it.",
                measurements,
                [element.id],
            )

        if claimed.startswith("#"):
            if not re.fullmatch(r"#[0-9a-f]{6}", claimed):
                return self._inconclusive(raw, f"Colour {claimed!r} is not a hex value.")
            target_rgb = tuple(int(claimed[i : i + 2], 16) for i in (1, 3, 5))
            target_lab = rgb_to_lab(target_rgb)
            target_name = claimed
        else:
            key = "gray" if claimed == "grey" else claimed
            if key not in NAMED_COLORS:
                return self._inconclusive(
                    raw, f"Colour {claimed!r} is not in the named-colour reference set."
                )
            target_lab = rgb_to_lab(NAMED_COLORS[key])
            target_name = key

        difference = delta_e(target_lab, tuple(actual_lab))
        measurements.append(
            VerificationMeasurement(
                name="delta_e",
                subject=element.label,
                value=round(difference, 1),
                expected="<= 26",
                unit="CIELAB",
            )
        )
        if difference <= 26 or (name and name == target_name):
            return self._result(
                raw,
                ClaimStatus.VERIFIED,
                0.92,
                f"Measured colour of {element.label!r} is {hex_value} ({name}){background}, "
                f"consistent with {claimed!r} (ΔE {difference:.1f}).",
                measurements,
                [element.id],
            )
        if difference >= 45:
            return self._result(
                raw,
                ClaimStatus.CONTRADICTED,
                0.88,
                f"Measured colour of {element.label!r} is {hex_value} ({name}){background}, "
                f"not {claimed!r} (ΔE {difference:.1f}).",
                measurements,
                [element.id],
            )
        return self._inconclusive(
            raw,
            f"Measured colour {hex_value} ({name}){background} is perceptually between the "
            f"claim and a contradiction (ΔE {difference:.1f}).",
            [f"element: {element.label}"],
        )

    def _dimensions(self, parsed: ParsedClaim, raw: str) -> VerificationResult:
        if parsed.width is None or parsed.height is None:
            return self._inconclusive(raw, "No dimensions were specified.")
        claimed = (parsed.width, parsed.height)
        actual = (self.width, self.height)
        measurements = [
            VerificationMeasurement(
                name="width", subject="image", value=actual[0], expected=claimed[0], unit="px"
            ),
            VerificationMeasurement(
                name="height", subject="image", value=actual[1], expected=claimed[1], unit="px"
            ),
        ]
        if claimed == actual:
            return self._result(
                raw, ClaimStatus.VERIFIED, 1.0,
                f"Image dimensions are {actual[0]}x{actual[1]}.",
                measurements,
            )
        if claimed == (actual[1], actual[0]):
            return self._result(
                raw, ClaimStatus.CONTRADICTED, 0.98,
                f"Image is {actual[0]}x{actual[1]}; the claim swaps width and height.",
                measurements,
            )
        return self._result(
            raw, ClaimStatus.CONTRADICTED, 1.0,
            f"Image is {actual[0]}x{actual[1]}, not {claimed[0]}x{claimed[1]}.",
            measurements,
        )

    def _existence(self, parsed: ParsedClaim, raw: str) -> VerificationResult:
        resolution = self.resolver.resolve(parsed.subject)
        if resolution.element is not None:
            e = resolution.element
            return self._result(
                raw, ClaimStatus.VERIFIED, 0.8,
                f"An element matching {parsed.subject!r} is present ({e.label!r} at {e.bbox.as_rounded()}).",
                [
                    VerificationMeasurement(
                        name="bbox", subject=e.label, value=e.bbox.as_rounded(), unit="px"
                    )
                ],
                [e.id],
            )
        return self._inconclusive(
            raw,
            f"Absence of {parsed.subject!r} cannot be proven: only visible geometry and recognised "
            f"text were checked. {resolution.note}",
        )


def _sample_region_color(bgr: np.ndarray, bbox: BBox) -> dict | None:
    height, width = bgr.shape[:2]
    x0 = int(max(0, min(width - 1, round(bbox.x0))))
    y0 = int(max(0, min(height - 1, round(bbox.y0))))
    x1 = int(max(x0 + 1, min(width, round(bbox.x1))))
    y1 = int(max(y0 + 1, min(height, round(bbox.y1))))
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    if crop.shape[0] * crop.shape[1] > 400_000:
        step = int(max(1, (crop.shape[0] * crop.shape[1] / 400_000) ** 0.5))
        crop = crop[::step, ::step]
    palette = dominant_colors(crop, k=3, sample_limit=12000)
    if not palette:
        return None
    chosen = palette[0]
    for entry in palette:
        name = entry["name"]
        # Skip a dominant near-white background when a more chromatic cluster exists.
        if name in ("white", "off-white", "light-gray") and entry["share"] > 0.6 and len(palette) > 1:
            continue
        chosen = entry
        break
    description = describe_color(tuple(chosen["rgb"]))
    return {
        **description,
        "hex": description["hex"],
        "name": chosen["name"],
        "share": chosen["share"],
        "lightness": description["lab"][0],
    }
