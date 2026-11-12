"""Schema contracts: BBox, Evidence, ToolResponse, verification results."""

from __future__ import annotations

import pytest

from vi3ion.schemas import (
    BBox,
    ClaimStatus,
    Evidence,
    EvidenceKind,
    Provenance,
    ToolResponse,
    VerificationResult,
)


def test_bbox_validation():
    bbox = BBox(x0=1, y0=2, x1=3, y1=4)
    assert bbox.width == 2
    assert bbox.height == 2
    assert bbox.center == (2.0, 3.0)

    with pytest.raises(ValueError):
        BBox(x0=5, y0=0, x1=3, y1=4)  # x1 < x0


def test_bbox_from_list():
    bbox = BBox.from_any([10, 20, 30, 40])
    assert bbox.as_list() == [10.0, 20.0, 30.0, 40.0]
    assert BBox.from_any(bbox) is bbox
    assert BBox.from_any({"x0": 0, "y0": 0, "x1": 4, "y1": 5}).width == 4


def test_evidence_defaults():
    evidence = Evidence(
        evidence_id="ev_1",
        image_id="img_1",
        kind=EvidenceKind.TEXT,
        label="hi",
        bbox=None,
        observed=True,
        attributes={},
        provenance=Provenance(module="test", method="unit"),
    )
    assert evidence.confidence is None
    assert evidence.scope == "image"
    assert evidence.is_inferred is False


def test_evidence_compact_detail():
    evidence = Evidence(
        evidence_id="ev_1",
        image_id="img_1",
        kind=EvidenceKind.SHAPE,
        label="rectangle",
        bbox=BBox.from_any([1, 2, 3, 4]),
        confidence=0.9,
        attributes={"corners": 4, "mask": "hidden"},
        observed=True,
        provenance=Provenance(module="test", method="unit"),
    )
    compact = evidence.compact("compact")
    assert compact.keys() == {"id", "kind", "label", "bbox", "confidence"}
    standard = evidence.compact("standard")
    assert standard["attributes"]["corners"] == 4
    assert "mask" not in standard["attributes"]


def test_tool_response_minimal():
    response = ToolResponse(tool="inspect_image", summary="s")
    assert response.ok is True
    assert response.evidence == []
    assert response.evidence_total == 0
    payload = response.to_payload("standard")
    assert payload["ok"] is True
    assert payload["tool"] == "inspect_image"
    assert "evidence" not in payload


def test_tool_response_json():
    response = ToolResponse(tool="inspect_image", summary="s", cached=True)
    text = response.to_json("compact")
    assert '"cached": true' in text


def test_verification_result():
    result = VerificationResult(
        claim="A is aligned with B",
        status=ClaimStatus.VERIFIED,
        confidence=0.9,
        explanation="measured",
        measurements=[],
        evidence_ids=["ev_1"],
        method="geometry.alignment",
    )
    assert result.status == "verified"
    assert result.confidence == 0.9
    assert "VERIFIED" in result.summary()
