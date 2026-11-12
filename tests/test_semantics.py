"""Step 2: semantic provider interface, mock determinism, provider factory, engine wiring."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from vi3ion.config import Settings
from vi3ion.core.engine import Vi3ionEngine
from vi3ion.core.semantics import (
    ClipSceneTagger,
    FlorenceProvider,
    MockSemanticProvider,
    OpenVocabDetector,
    create_providers,
)
from vi3ion.core.semantics.mock import MockSemanticProvider as MockProvider
from vi3ion.schemas import BBox


def tiny_image(width: int = 64, height: int = 48) -> np.ndarray:
    image = np.full((height, width, 3), 200, dtype=np.uint8)
    cv2.circle(image, (16, 16), 8, (0, 0, 220), -1)  # red "sun"
    cv2.rectangle(image, (30, 10), (52, 40), (90, 60, 40), -1)
    return image


def image_sha(image: np.ndarray) -> str:
    import hashlib

    return hashlib.sha256(cv2.imencode(".png", image)[1]).hexdigest()


@pytest.fixture
def mock_results(tmp_path, ):
    image = tiny_image()
    digest = image_sha(image)
    payload = {
        digest: {
            "objects": [
                {"label": "red sun", "bbox": [8, 8, 24, 24], "confidence": 0.92},
                {"label": "stone pillar", "bbox": [30, 10, 52, 40], "confidence": 0.81},
            ],
            "captions": [
                {"text": "a curved red sun over a brown pillar", "bbox": [8, 8, 52, 40], "confidence": 0.7}
            ],
            "scene_tags": [{"tag": "illustrated 3D scene", "confidence": 0.88}],
        }
    }
    path = tmp_path / "mock_results.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, image


def test_mock_provider_deterministic(mock_results):
    path, image = mock_results
    provider = MockProvider(path)
    result = provider.detect(image)
    assert result.error is None
    assert [obj.label for obj in result.objects] == ["red sun", "stone pillar"]
    assert all(obj.source == "mock" for obj in result.objects)
    assert result.objects[0].confidence == pytest.approx(0.92)
    assert [cap.text for cap in result.captions] == [
        "a curved red sun over a brown pillar"
    ]
    assert result.scene_tags[0].tag == "illustrated 3D scene"


def test_mock_provider_unknown_image_warns(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"default": {}}), encoding="utf-8")
    provider = MockProvider(path)
    result = provider.detect(tiny_image(width=32, height=32))
    assert result.objects == []
    assert result.warning is not None


def test_provider_factory_parses_combos(monkeypatch, tmp_path):
    monkeypatch.setenv("VI3ION_SEMANTIC_PROVIDER", "mock")
    settings = Settings()
    providers = create_providers(settings)
    assert [p.name for p in providers] == ["mock"]

    monkeypatch.setenv("VI3ION_SEMANTIC_PROVIDER", "florence,owlvit,clip")
    settings = Settings()
    providers = create_providers(settings)
    assert [p.name for p in providers] == ["florence", "owlvit", "clip"]
    assert isinstance(providers[0], FlorenceProvider)
    assert isinstance(providers[1], OpenVocabDetector)
    assert isinstance(providers[2], ClipSceneTagger)

    monkeypatch.setenv("VI3ION_SEMANTIC_PROVIDER", "none")
    assert create_providers(Settings()) == []


def test_settings_reject_invalid_provider(monkeypatch):
    monkeypatch.setenv("VI3ION_SEMANTIC_PROVIDER", "banana")
    with pytest.raises(ValueError):
        Settings()
    monkeypatch.setenv("VI3ION_SEMANTIC_PROVIDER", "none,florence")
    with pytest.raises(ValueError):
        Settings()


def test_mock_through_engine(tmp_path, mock_results):
    path, image = mock_results
    settings = Settings(
        data_dir=tmp_path / "data",
        semantic_provider="mock",
        semantic_mock_path=str(path),
        allowed_roots=[tmp_path],
    )
    engine = Vi3ionEngine(settings)
    buffer = cv2.imencode(".png", image)[1].tobytes()
    record, _ = engine.ingest_bytes(buffer, filename="mock.png")
    response = engine.inspect_image(image_id=record["image_id"], tasks=["identify_elements"], detail="full")

    assert response.ok is True
    assert response.data["analysis"]["semantic"]["object_count"] == 2
    objects = [e for e in response.evidence if e.kind.value == "object"]
    assert len(objects) == 2
    assert {o.label for o in objects} == {"red sun", "stone pillar"}
    assert all(o.observed is False for o in objects)
    # boxes map back to original pixels (within the 64x48 canvas)
    for obj in objects:
        assert obj.bbox is not None
        assert 0 <= obj.bbox.x0 <= obj.bbox.x1 <= 64
        assert 0 <= obj.bbox.y0 <= obj.bbox.y1 <= 48
    notes = [e for e in response.evidence if e.kind.value == "note"]
    assert any("suggested" in e.attributes and e.attributes["suggested"] for e in notes)
    assert any(e.attributes.get("tag") == "illustrated 3D scene" for e in notes)
    assert any(e.label == "region caption" for e in notes)
    # Step 4 sections appear in the brief.
    assert "Objects:" in response.summary
    assert "Inferred:" in response.summary
    assert "suggested" in response.summary
