"""Engine orchestration: inspect, region crop, evidence queries, compare, sessions."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from vi3ion.errors import NotFoundError, ValidationError
from vi3ion.image_memory import SIGNATURE_VERSION


def test_inspect_image_full(sample_ui_id, engine):
    response = engine.inspect_image(image_id=sample_ui_id, tasks=None, detail="full")
    assert response.ok is True
    assert response.tool == "inspect_image"
    assert response.image_id == sample_ui_id
    assert response.data["image"]["width"] == 1280
    assert response.data["image"]["height"] == 800
    assert response.evidence_total >= 20
    kinds = {e.kind.value for e in response.evidence}
    assert "text" in kinds
    assert "shape" in kinds
    assert "color" in kinds
    # coordinates are original-pixel space
    for e in response.evidence:
        if e.bbox is not None:
            assert 0 <= e.bbox.x0 <= e.bbox.x1 <= 1280
            assert 0 <= e.bbox.y0 <= e.bbox.y1 <= 800


def test_inspect_image_cached(sample_ui_id, engine):
    engine.inspect_image(image_id=sample_ui_id)
    second = engine.inspect_image(image_id=sample_ui_id)
    assert second.cached is True


def test_image_registry_remember_and_diff(sample_ui_id, engine):
    engine.inspect_image(image_id=sample_ui_id, detail="compact")
    known = {item["image_id"]: item for item in engine.list_known_images(limit=100)}
    assert sample_ui_id in known
    assert known[sample_ui_id]["text_count"] > 0
    # The perceptual hash makes "same screen" detection work even when the
    # wording changed.
    assert known[sample_ui_id]["phash"]

    engine.remember_image(image_id=sample_ui_id, label="settings screen")
    known = {item["image_id"]: item for item in engine.list_known_images(limit=100)}
    assert known[sample_ui_id]["label"] == "settings screen"

    response = engine.diff_images(older_id=sample_ui_id, newer_id=sample_ui_id)
    assert response.ok is True
    assert response.data["diff"]["overall_similarity"] == 1.0
    assert response.data["diff"]["change_count"] == 0
    assert response.next_actions


def test_diff_upgrades_stale_signature(sample_ui_id, engine):
    engine.inspect_image(image_id=sample_ui_id, detail="compact")
    registry = engine.db.get_image_registry(sample_ui_id)
    stale = dict(registry["signature"])
    stale["version"] = 1
    stale.pop("label_list", None)
    engine.db.upsert_image_registry(sample_ui_id, stale)

    response = engine.diff_images(older_id=sample_ui_id, newer_id=sample_ui_id)
    assert response.ok is True
    upgraded = engine.db.get_image_registry(sample_ui_id)["signature"]
    assert upgraded["version"] == SIGNATURE_VERSION
    assert upgraded["label_list"]


def test_inspect_image_detail_trimming(sample_ui_id, engine):
    compact = engine.inspect_image(image_id=sample_ui_id, detail="compact")
    full = engine.inspect_image(image_id=sample_ui_id, detail="full")
    assert compact.evidence_returned <= 10
    assert full.evidence_returned > compact.evidence_returned


def test_query_evidence_by_kind(sample_ui_id, engine):
    response = engine.query_evidence(image_id=sample_ui_id, kind="text", limit=100)
    assert response.ok is True
    assert len(response.evidence) > 0
    assert all(e.kind.value == "text" for e in response.evidence)


def test_inspect_region_maps_back(sample_ui_id, engine):
    # A region around the Save button.
    response = engine.inspect_region(
        image_id=sample_ui_id, region=[329, 599, 491, 653], upscale=2.0, tasks=None
    )
    assert response.ok is True
    assert response.summary
    # All fresh evidence must be in ORIGINAL coordinates (region bounds).
    for e in response.evidence:
        if e.bbox is not None:
            assert 0 <= e.bbox.x0 <= e.bbox.x1 <= 1280
            assert 0 <= e.bbox.y0 <= e.bbox.y1 <= 800


def test_compare_regions(sample_ui_id, engine):
    response = engine.compare_regions(
        image_id=sample_ui_id,
        region_a=[329, 599, 491, 653],
        region_b=[509, 599, 692, 654],
    )
    assert response.ok is True
    assert "comparison" in response.data or response.summary


def test_unknown_image_raises(engine):
    with pytest.raises(NotFoundError):
        engine.get_record("img_does_not_exist")
    with pytest.raises(NotFoundError):
        engine.inspect_image(image_id="img_does_not_exist")


def test_invalid_bbox_rejected(sample_ui_id, engine):
    with pytest.raises(ValidationError):
        engine.inspect_region(image_id=sample_ui_id, region=[500, 500, 100, 100])


def test_sessions_recorded(sample_ui_id, engine):
    engine.inspect_image(image_id=sample_ui_id, agent="test-agent")
    sessions = engine.list_sessions(image_id=sample_ui_id)
    assert sessions
    assert all("agent" in s and "session_id" in s for s in sessions)


def test_delete_image(engine):
    # A distinct image so dedup cannot alias the shared sample fixture.
    unique = np.zeros((32, 32, 3), dtype=np.uint8)
    unique[:, :] = (33, 44, 55)
    buffer = io.BytesIO()
    Image.fromarray(unique).save(buffer, format="PNG")
    record, _ = engine.ingest_bytes(buffer.getvalue(), filename="todelete.png")
    engine.delete_image(record["image_id"])
    with pytest.raises(NotFoundError):
        engine.get_record(record["image_id"])
