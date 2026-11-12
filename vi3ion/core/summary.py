"""Compact, factual summaries for text-only agents.

The summary is a convenience layer over the evidence. It must never state more
than the evidence supports.

Layout convention (Step 1):
- Observed facts only in the main prose. Inferred page-level statements go
  under an "Inferred:" heading and are produced by the semantic layer.
- Spatial names ("top bar", "left column", "centre", "right column",
  "bottom bar") in prose; exact boxes are kept per item for follow-up.
- OCR items are grouped by row, then paired (number + label) where they form
  one unit. Digit sequences are checked against the expected 00–09 pattern;
  corrections are annotated, never silently rewritten.
- Low-confidence CJK and short monospaced text is flagged "(uncertain)".
- Items removed by confidence cutoffs or display truncation are logged with a
  reason, and the brief states how many were omitted and in which region.
- Graph statistics live in debug output (analysis data), not in the brief.
"""

from __future__ import annotations

import logging
import re

from ..schemas import BBox, Evidence, EvidenceKind
from .geometry.measurements import group_rows

logger = logging.getLogger("vi3ion.brief")

NUMBER_RE = re.compile(r"^\d{1,4}$")
SHORT_MONO_RE = re.compile(r"^[\dA-Z\[\]()\-/.:+]{1,8}$")
CJK_RANGE = ("\u4e00", "\u9fff")

TEXTS_MAX = 24          # max text items shown in the brief before explicit omission
CONF_DROP = 0.30        # hard floor used for the drop report (pipeline uses its own)

# Expected short sequence values in numbered lists (00..09).
EXPECTED_SEQ = {f"{i:02d}" for i in range(10)}


def _is_seq_number(text: str) -> bool:
    """Numbered-list tokens are short digit runs (1–2 digits).

    Longer runs (years, ids) are not sequence candidates.
    """
    return NUMBER_RE.match(text) is not None and len(text) <= 2


# --------------------------------------------------------------------------- helpers

def _spatial_band(bbox, width: int, height: int) -> str:
    """Name the screen region a box lives in, for prose."""
    y0, y1, x0, x1 = bbox.y0, bbox.y1, bbox.x0, bbox.x1
    if y0 <= height * 0.12:
        return "top bar"
    if y0 >= height * 0.78:
        return "bottom bar"
    cx = (x0 + x1) / 2.0
    if cx < width / 3.0:
        return "left column"
    if cx > width * 2.0 / 3.0:
        return "right column"
    return "centre"


def _script_of(item: Evidence) -> str:
    return str(item.attributes.get("script", ""))


def _is_cjk(script: str) -> bool:
    return script in ("cjk", "mixed")


def _annotate_text(item: Evidence, container_label: str | None = None) -> str:
    """Render a text item, flagging uncertain reads and text containers."""
    text = (item.attributes.get("text") or item.label).strip()
    confidence = item.confidence if item.confidence is not None else 0.0
    script = _script_of(item)
    flags: list[str] = []
    if _is_cjk(script) and confidence < 0.70:
        flags.append("uncertain")
    elif SHORT_MONO_RE.match(text) and len(text) <= 6 and confidence < 0.45:
        flags.append("uncertain")
    rendered = f'"{text}"'
    if flags:
        rendered += f" ({'; '.join(flags)})"
    if container_label:
        rendered += f" (may contain: {container_label})"
    return rendered


def _box(item: Evidence) -> list[int]:
    return [round(v) for v in item.bbox.as_rounded()] if item.bbox else []


def _fmt_box(bbox: BBox | None) -> list[int]:
    return [round(v) for v in bbox.as_rounded()] if bbox else []


def _sequence_note(raw: str, siblings: list[tuple[float, str]], center_y: float) -> str:
    """Validate a digit token against the expected 00–09 pattern.

    Out-of-range values are checked against the digit sequence around them in
    reading order (by vertical centre). When exactly one gap can be inferred, a
    correction is *suggested* in an annotation. Otherwise the token is marked
    uncertain. The raw text is never rewritten.
    """
    value_text = raw.strip()
    if not value_text.isdigit():
        return ""
    value = int(value_text)
    if value < 10:
        return ""
    ordered = [
        int(text) for cy, text in sorted(siblings, key=lambda pair: pair[0])
        if text.isdigit() and int(text) < 10
    ]
    position = sum(1 for cy, _ in siblings if cy < center_y)
    seq = sorted(set(ordered))
    if not seq:
        return f'"{value_text}" (uncertain sequence; expected 00–09)'
    index = min(position, len(seq))
    lo = seq[index - 1] if index > 0 else None
    hi = seq[index] if index < len(seq) else None
    if lo is not None and hi is not None and hi > lo + 1:
        hole = [d for d in range(lo + 1, hi) if d not in seq]
        if len(hole) == 1:
            return f'"{hole[0]:02d}" (corrected from "{value_text}", sequence inferred)'
    return f'"{value_text}" (uncertain sequence; expected 00–09)'


def _pair_row(
    items: list[Evidence],
    band_of: dict[str, str],
    siblings_by_band: dict[str, list[tuple[float, str]]],
    container_by_id: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """Render one row. Adjacent number + label become one unit.

    Each rendered piece is tagged with its own spatial band so a row spanning
    left and right columns splits correctly.
    """
    container_by_id = container_by_id or {}
    parts: list[tuple[str, str]] = []
    index = 0
    while index < len(items):
        item = items[index]
        text = (item.attributes.get("text") or item.label).strip()
        band = band_of.get(item.evidence_id, "centre")
        siblings = siblings_by_band.get(band, [])
        container_label = container_by_id.get(item.evidence_id)
        note = (
            _sequence_note(text, siblings, item.bbox.center_y)
            if _is_seq_number(text) and item.bbox
            else ""
        )
        number_display = note if note else _annotate_text(item, container_label)
        next_text = (
            (items[index + 1].attributes.get("text") or items[index + 1].label).strip()
            if index + 1 < len(items)
            else ""
        )
        if _is_seq_number(text) and next_text and not _is_seq_number(next_text):
            # Number + label pair on the same row -> one unit.
            label_item = items[index + 1]
            parts.append(
                (
                    band_of.get(label_item.evidence_id, band),
                    f"{number_display} "
                    f"{_annotate_text(label_item, container_by_id.get(label_item.evidence_id))} "
                    f"@{_box(label_item)}",
                )
            )
            index += 2
        else:
            parts.append((band, f"{number_display} @{_box(item)}"))
            index += 1
    return parts


def _render_merged(merged) -> list[str]:
    """Step 4 sections: Objects / Region notes / Scene notes / Inferred."""
    lines: list[str] = []
    if getattr(merged, "objects", None):
        rendered = []
        for obj in merged.objects:
            parts = [
                f'"{obj.label}" @{_fmt_box(obj.bbox)} '
                f"({obj.confidence:.2f}, {obj.source})"
            ]
            if obj.may_contain_text:
                parts.append(f"may contain text: {obj.may_contain_text}")
            if obj.regions:
                parts.append("in " + ", ".join(obj.regions))
            if obj.caption:
                parts.append(f"caption: {obj.caption!r}")
            rendered.append(" ".join(parts))
        lines.append("Objects: " + "; ".join(rendered) + ".")
    if getattr(merged, "region_captions", None):
        lines.append(
            "Region notes: "
            + "; ".join(
                f"{caption.text!r} @{_fmt_box(caption.bbox)}"
                for caption in merged.region_captions
            )
            + "."
        )
    if getattr(merged, "scene_notes", None):
        lines.append(
            "Scene notes: "
            + "; ".join(f"{caption.text!r}" for caption in merged.scene_notes)
            + "."
        )
    if getattr(merged, "scene_tags", None):
        inferred = [
            f"{tag.tag!r} ({tag.confidence * 100:.0f}% suggested, {tag.source})"
            for tag in merged.scene_tags
        ]
        lines.append("Inferred: " + ", ".join(inferred) + ".")
    return lines


def _omit_report(dropped: list[tuple[Evidence, str]], width: int, height: int) -> str | None:
    if not dropped:
        return None
    by_band: dict[str, list[str]] = {}
    for item, reason in dropped:
        band = _spatial_band(item.bbox, width, height) if item.bbox else "unknown"
        by_band.setdefault(band, []).append(reason)
    bits = []
    for band, reasons in sorted(by_band.items()):
        low = sum(1 for r in reasons if "confidence" in r)
        cut = len(reasons) - low
        detail = []
        if low:
            detail.append(f"{low} low-confidence (below {CONF_DROP:.2f})")
        if cut:
            detail.append(f"{cut} truncated for length")
        bits.append(f"{band}: {', '.join(detail)}")
    return "Omitted from brief: " + "; ".join(bits) + "."


# --------------------------------------------------------------------------- main

def summarize(
    record: dict,
    evidence: list[Evidence],
    palette: list[dict] | None = None,
    scene: dict | None = None,
    warnings: list[str] | None = None,
    ocr_filtered: list[dict] | None = None,
    merged=None,
) -> str:
    width, height = record.get("width"), record.get("height")
    lines: list[str] = [
        f"Image {width}x{height} {record.get('format', '')} "
        f"({_human_bytes(record.get('size_bytes', 0))})."
    ]

    texts = [
        e for e in evidence
        if e.kind == EvidenceKind.TEXT and e.bbox is not None
    ]
    texts.sort(key=lambda e: int(e.attributes.get("reading_order", 9999)))
    shapes = [e for e in evidence if e.kind == EvidenceKind.SHAPE and e.bbox is not None]
    objects = [e for e in evidence if e.kind == EvidenceKind.OBJECT and e.bbox is not None]

    stats = next((e.attributes for e in evidence if e.label == "image_statistics"), {})
    if stats:
        tone = stats.get("tone", "mid")
        background = stats.get("background_hex", "?")
        lines[0] += f" {tone.capitalize()} image, background {background}."

    counts = [f"{len(texts)} text line(s)", f"{len(shapes)} shape(s)"]
    if objects:
        counts.append(f"{len(objects)} semantic object(s) (inferred)")
    lines.append("Contains " + ", ".join(counts) + ".")

    # ---- OCR: drop report, then row-grouped spatial prose -------------------
    dropped: list[tuple[Evidence, str]] = []
    for item in texts:
        if item.confidence is not None and item.confidence < CONF_DROP:
            dropped.append((item, f"confidence {item.confidence:.2f} < {CONF_DROP:.2f}"))
    dropped_ids = {item.evidence_id for item, _ in dropped}
    kept = [item for item in texts if item.evidence_id not in dropped_ids]
    if len(kept) > TEXTS_MAX:
        for item in kept[TEXTS_MAX:]:
            dropped.append((item, "truncated for length"))
        kept = kept[:TEXTS_MAX]

    if kept:
        boxes = [item.bbox for item in kept]
        rows = group_rows(boxes, tolerance=max(2.0, min(width, height) * 0.004))
        # Numeric siblings from the same spatial band feed sequence checks.
        siblings_by_band: dict[str, list[tuple[float, str]]] = {}
        for item in kept:
            if item.bbox:
                band = _spatial_band(item.bbox, width, height)
                text = (item.attributes.get("text") or item.label).strip()
                if _is_seq_number(text):
                    siblings_by_band.setdefault(band, []).append((item.bbox.center_y, text))

        by_band: dict[str, list[str]] = {}
        band_of = {
            item.evidence_id: _spatial_band(item.bbox, width, height)
            for item in kept
            if item.bbox
        }
        container_by_id: dict[str, str] = {}
        if merged is not None and getattr(merged, "text_containers", None):
            idx_to_id = {
                i: item.evidence_id for i, item in enumerate(texts)
            }
            for entry in merged.text_containers:
                evidence_id = idx_to_id.get(entry.get("text_index"))
                if evidence_id:
                    container_by_id[evidence_id] = entry.get("label", "object")
        for row in rows:
            row_items = [kept[i] for i in row]
            if not row_items:
                continue
            for band, piece in _pair_row(row_items, band_of, siblings_by_band, container_by_id):
                by_band.setdefault(band, []).append(piece)

        for band in ("top bar", "left column", "centre", "right column", "bottom bar"):
            items = by_band.get(band)
            if items:
                lines.append(f"{band.capitalize()}: " + "; ".join(items) + ".")

    omitted = _omit_report(dropped, width, height)
    if omitted:
        lines.append(omitted)

    lines.extend(_render_merged(merged))

    for item in dropped:
        logger.debug(
            "brief omitted %s (%s) reason=%s",
            item[0].evidence_id, item[0].label, item[1],
        )
    if ocr_filtered:
        low_by_band: dict[str, int] = {}
        for entry in ocr_filtered:
            band = _spatial_band(entry["bbox"], width, height) if entry.get("bbox") else "unknown"
            low_by_band[band] = low_by_band.get(band, 0) + 1
            logger.debug("ocr pipeline dropped %r reason=%s", entry.get("text"), entry.get("reason"))
        if low_by_band:
            detail = ", ".join(f"{band}: {count}" for band, count in sorted(low_by_band.items()))
            lines.append(f"Omitted by OCR confidence filter: {detail}.")

    # ---- shapes: observed geometry, no graph statistics ----------------------
    if shapes:
        rendered = []
        for item in shapes[:8]:
            attrs = item.attributes
            size = f"{attrs.get('width_px', 0):.0f}x{attrs.get('height_px', 0):.0f}"
            rendered.append(f"{item.label} @{_box(item)} ({size})")
        more = f" (+{len(shapes) - 8} more)" if len(shapes) > 8 else ""
        lines.append("Shapes: " + "; ".join(rendered) + more + ".")

    if palette:
        rendered = [
            f"{entry['hex']} {entry['name']} {entry['share'] * 100:.0f}%"
            for entry in palette[:3]
        ]
        lines.append("Palette: " + ", ".join(rendered) + ".")

    for warning in warnings or []:
        if warning:
            lines.append(f"Warning: {warning}")
    return " ".join(lines)


def summarize_region(
    record: dict,
    bbox: list[float],
    evidence: list[Evidence],
    warnings: list[str] | None = None,
    merged=None,
) -> str:
    texts = [e for e in evidence if e.kind == EvidenceKind.TEXT]
    shapes = [e for e in evidence if e.kind == EvidenceKind.SHAPE]
    width = round(bbox[2] - bbox[0], 1)
    height = round(bbox[3] - bbox[1], 1)
    lines = [
        f"Region {bbox} ({width}x{height} px) of image {record['width']}x{record['height']}."
    ]
    counts = [f"{len(texts)} text line(s)", f"{len(shapes)} shape(s)"]
    lines.append("Contains " + ", ".join(counts) + ".")
    if texts:
        texts.sort(key=lambda e: int(e.attributes.get("reading_order", 9999)))
        rendered = [
            f"{e.label!r} @{e.bbox.as_rounded() if e.bbox else []}" for e in texts[:10]
        ]
        lines.append("Text: " + "; ".join(rendered) + ".")
    if shapes:
        rendered = [
            f"{e.label} @{e.bbox.as_rounded() if e.bbox else []}" for e in shapes[:8]
        ]
        lines.append("Shapes: " + "; ".join(rendered) + ".")
    lines.extend(_render_merged(merged))
    for warning in warnings or []:
        if warning:
            lines.append(f"Warning: {warning}")
    return " ".join(lines)


def _human_bytes(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
