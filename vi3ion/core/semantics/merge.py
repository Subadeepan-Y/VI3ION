"""Merge semantic output with deterministic analysis (Step 3).

Rules
----
1. Objects below confidence 0.35 are dropped; at most 25 remain, sorted by
   confidence * area.
2. Non-maximum suppression per label: keep detections with IoU < 0.5 against
   a higher-confidence detection of the same label.
3. If an object overlaps an OCR text box by more than 50% of the text box,
   the text is authoritative: the object becomes a "may contain text: tN"
   note and is NOT listed as a separate object.
4. Each object lists the regions (geometry shapes) it sits inside or overlaps
   by more than 70% of its own area.
5. Captions with a box attach to the matching object or region; captions
   without a box go under Scene notes.
6. Scene tags go under Inferred and never appear in the object list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...schemas import BBox, Evidence, EvidenceKind
from .interface import SemanticCaption, SceneTag

OBJECT_MIN_CONFIDENCE = 0.35
MAX_OBJECTS = 25
TEXT_OVERLAP = 0.5
REGION_OVERLAP = 0.7
NMS_IOU = 0.5


@dataclass
class MergedObject:
    label: str
    bbox: BBox
    confidence: float
    source: str
    regions: list[str] = field(default_factory=list)
    may_contain_text: str | None = None
    caption: str | None = None
    evidence_id: str = ""


@dataclass
class MergedAnalysis:
    objects: list[MergedObject] = field(default_factory=list)
    region_captions: list[SemanticCaption] = field(default_factory=list)
    scene_notes: list[SemanticCaption] = field(default_factory=list)
    scene_tags: list[SceneTag] = field(default_factory=list)
    text_containers: list[dict] = field(default_factory=list)  # {text_index, label, bbox}


def _iou(a: BBox, b: BBox) -> float:
    inter_w = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    inter_h = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def _overlap_fraction_of(a: BBox, container: BBox) -> float:
    """Fraction of `a` covered by `container` (0..1)."""
    inter_w = max(0.0, min(a.x1, container.x1) - max(a.x0, container.x0))
    inter_h = max(0.0, min(a.y1, container.y1) - max(a.y0, container.y0))
    inter = inter_w * inter_h
    return inter / a.area if a.area > 0 else 0.0


def _nms(objects: list[MergedObject]) -> list[MergedObject]:
    kept: list[MergedObject] = []
    by_label: dict[str, list[MergedObject]] = {}
    for obj in objects:
        by_label.setdefault(obj.label.lower(), []).append(obj)
    for label, group in by_label.items():
        order = sorted(group, key=lambda obj: (-obj.confidence, -obj.bbox.area))
        survivors: list[MergedObject] = []
        for candidate in order:
            if any(_iou(candidate.bbox, kept_box.bbox) >= NMS_IOU for kept_box in survivors):
                continue
            survivors.append(candidate)
        kept.extend(survivors)
    return kept


def merge(evidence: list[Evidence]) -> MergedAnalysis:
    texts = [
        e for e in evidence
        if e.kind == EvidenceKind.TEXT and e.bbox is not None
    ]
    texts.sort(key=lambda e: int(e.attributes.get("reading_order", 9999)))
    shapes = [e for e in evidence if e.kind == EvidenceKind.SHAPE and e.bbox is not None]
    obj_evidence = [e for e in evidence if e.kind == EvidenceKind.OBJECT and e.bbox is not None]
    cap_evidence = [e for e in evidence if e.kind == EvidenceKind.NOTE and e.label == "region caption"]
    tag_evidence = [
        e for e in evidence
        if e.kind == EvidenceKind.NOTE and e.label == "scene tag"
    ]

    # 1 + 2: filter by confidence, sort by confidence*area, NMS per label.
    candidates: list[MergedObject] = []
    for item in obj_evidence:
        confidence = item.confidence if item.confidence is not None else 0.0
        if confidence < OBJECT_MIN_CONFIDENCE:
            continue
        candidates.append(
            MergedObject(
                label=item.label,
                bbox=item.bbox,
                confidence=confidence,
                source=str(item.attributes.get("source") or item.attributes.get("provider") or "?"),
                evidence_id=item.evidence_id,
            )
        )
    candidates.sort(key=lambda obj: obj.confidence * obj.bbox.area, reverse=True)
    candidates = _nms(candidates)[:MAX_OBJECTS]

    # 3: text overlap -> authoritative text wins.
    final_objects: list[MergedObject] = []
    text_containers: list[dict] = []
    for index, text in enumerate(texts):
        for obj in list(candidates):
            if obj.may_contain_text:
                continue
            if _overlap_fraction_of(text.bbox, obj.bbox) > TEXT_OVERLAP:
                obj.may_contain_text = f"t{index}"
                text_containers.append(
                    {"text_index": index, "label": obj.label, "bbox": obj.bbox.as_list()}
                )
                candidates.remove(obj)
    final_objects = candidates

    # 4: region membership (geometric regions only).
    regions = [e for e in shapes if e.label.lower().startswith("rectangle") or e.label.lower().startswith("square") or e.label.lower().startswith("polygon")]
    if not regions:
        regions = shapes
    for obj in final_objects:
        inside = [
            e.label for e in regions
            if _overlap_fraction_of(obj.bbox, e.bbox) >= REGION_OVERLAP
        ]
        obj.regions = inside[:4]

    # 5: captions attach to objects/regions; others are scene notes.
    region_captions: list[SemanticCaption] = []
    scene_notes: list[SemanticCaption] = []
    for cap in cap_evidence:
        text = str(cap.attributes.get("text") or "")
        confidence = cap.confidence if cap.confidence is not None else 0.5
        caption = SemanticCaption(
            text=text, bbox=cap.bbox, confidence=confidence,
            source=str(cap.attributes.get("source") or "?"),
        )
        attached = False
        if cap.bbox is not None:
            for obj in final_objects:
                if _iou(cap.bbox, obj.bbox) >= 0.3 and obj.caption is None:
                    obj.caption = text
                    attached = True
                    break
            if not attached:
                for region in regions:
                    if _overlap_fraction_of(cap.bbox, region.bbox) >= REGION_OVERLAP:
                        region_captions.append(caption)
                        attached = True
                        break
        if not attached:
            scene_notes.append(caption)

    # 6: scene tags -> inferred only.
    tags = [
        SceneTag(
            tag=str(e.attributes.get("tag") or e.label)[:80],
            confidence=e.confidence if e.confidence is not None else 0.5,
            source=str(e.attributes.get("source") or "?"),
        )
        for e in tag_evidence
    ]
    tags.sort(key=lambda tag: tag.confidence, reverse=True)

    return MergedAnalysis(
        objects=final_objects,
        region_captions=region_captions[:10],
        scene_notes=scene_notes[:10],
        scene_tags=tags[:3],
        text_containers=text_containers,
    )
