"""Step 3: merge rules — confidence/area cap, NMS, text-wins, region, captions, tags."""

from __future__ import annotations

from vi3ion.core.semantics.merge import merge
from vi3ion.schemas import BBox, Evidence, EvidenceKind, Provenance

PROV = Provenance(module="test", method="merge")


def obj(label: str, bbox: list[float], confidence: float = 0.8, source: str = "mock") -> Evidence:
    return Evidence(
        evidence_id=f"obj_{label}_{''.join(str(int(v)) for v in bbox)}",
        image_id="img_t",
        kind=EvidenceKind.OBJECT,
        label=label,
        bbox=BBox.from_any(bbox),
        confidence=confidence,
        attributes={"source": source, "provider": source},
        provenance=PROV,
        observed=False,
    )


def txt(label: str, bbox: list[float], order: int = 0) -> Evidence:
    return Evidence(
        evidence_id=f"txt_{order}",
        image_id="img_t",
        kind=EvidenceKind.TEXT,
        label=label,
        bbox=BBox.from_any(bbox),
        confidence=0.9,
        attributes={"text": label, "reading_order": order},
        provenance=PROV,
        observed=True,
    )


def shape(label: str, bbox: list[float]) -> Evidence:
    return Evidence(
        evidence_id=f"shp_{label}",
        image_id="img_t",
        kind=EvidenceKind.SHAPE,
        label=label,
        bbox=BBox.from_any(bbox),
        confidence=0.9,
        attributes={},
        provenance=PROV,
        observed=True,
    )


def caption(text: str, bbox: list[float] | None) -> Evidence:
    return Evidence(
        evidence_id=f"cap_{text[:8]}",
        image_id="img_t",
        kind=EvidenceKind.NOTE,
        label="region caption",
        bbox=BBox.from_any(bbox) if bbox else None,
        confidence=0.7,
        attributes={"text": text, "source": "florence"},
        provenance=PROV,
        observed=False,
    )


def tag(name: str, confidence: float = 0.9) -> Evidence:
    return Evidence(
        evidence_id=f"tag_{name[:8]}",
        image_id="img_t",
        kind=EvidenceKind.NOTE,
        label="scene tag",
        bbox=None,
        confidence=confidence,
        attributes={"tag": name, "source": "clip", "suggested": True},
        provenance=PROV,
        observed=False,
    )


def test_confidence_and_area_filtering():
    evidence = [
        obj("small", [0, 0, 10, 10], confidence=0.9),       # area 100 * .9 = 90
        obj("big", [0, 0, 100, 100], confidence=0.6),       # area 10000 * .6
        obj("weak", [0, 0, 50, 50], confidence=0.2),        # dropped
    ]
    merged = merge(evidence)
    assert [o.label for o in merged.objects] == ["big", "small"]


def test_nms_suppresses_same_label_overlap():
    evidence = [
        obj("red sun", [0, 0, 100, 100], confidence=0.95),
        obj("red sun", [10, 10, 110, 110], confidence=0.6),  # IoU ~0.68 -> suppressed
        obj("pagoda", [0, 0, 100, 100], confidence=0.5),     # different label kept
    ]
    merged = merge(evidence)
    labels = [o.label for o in merged.objects]
    assert labels.count("red sun") == 1
    assert "pagoda" in labels


def test_text_wins_over_object():
    evidence = [
        txt("Save", [40, 40, 80, 70], order=0),
        obj("button", [30, 30, 90, 80], confidence=0.9),
    ]
    merged = merge(evidence)
    assert merged.objects == []
    assert len(merged.text_containers) == 1
    assert merged.text_containers[0]["text_index"] == 0
    assert merged.text_containers[0]["label"] == "button"


def test_region_membership():
    evidence = [
        obj("red sun", [10, 10, 40, 40], confidence=0.9),
        shape("rectangle 1", [0, 0, 200, 200]),
        shape("rectangle 2", [100, 100, 180, 180]),
    ]
    merged = merge(evidence)
    assert merged.objects[0].regions == ["rectangle 1"]


def test_caption_attachment_and_scene_notes():
    evidence = [
        obj("red sun", [10, 10, 60, 60], confidence=0.9),
        caption("a red sun over the gate", [15, 15, 55, 55]),       # attaches to object
        shape("rectangle 1", [200, 200, 400, 400]),
        caption("a pillar on the right", [210, 210, 390, 390]),      # region caption
        caption("overall moody light", None),                        # scene note
    ]
    merged = merge(evidence)
    assert merged.objects[0].caption == "a red sun over the gate"
    assert [c.text for c in merged.region_captions] == ["a pillar on the right"]
    assert [c.text for c in merged.scene_notes] == ["overall moody light"]


def test_scene_tags_sorted_and_inferred():
    evidence = [
        tag("web page", confidence=0.5),
        tag("illustrated 3D scene", confidence=0.95),
        tag("diagram", confidence=0.6),
        tag("chart", confidence=0.9),
    ]
    merged = merge(evidence)
    assert [t.tag for t in merged.scene_tags] == [
        "illustrated 3D scene", "chart", "diagram",
    ]


def test_brief_renders_may_contain_text():
    from vi3ion.core.summary import summarize

    evidence = [
        txt("Save", [40, 40, 80, 70], order=0),
        obj("button", [30, 30, 90, 80], confidence=0.9),
    ]
    merged = merge(evidence)
    record = {"width": 1280, "height": 800, "format": "PNG", "size_bytes": 10_000}
    summary = summarize(record, evidence, merged=merged)
    assert "(may contain: button)" in summary
    assert "Objects:" not in summary  # suppressed object is not listed separately
