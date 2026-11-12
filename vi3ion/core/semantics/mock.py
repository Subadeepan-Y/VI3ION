"""Deterministic mock provider: fixed results keyed by image hash.

Used in tests and offline development. Never loads a model.

Resolution order:
1. `VI3ION_SEMANTIC_MOCK` JSON file (path), keyed by image sha256.
2. Package default `mock_results.json` next to this module.
3. Fallback: empty result with a warning.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from ...schemas import BBox
from .interface import SemanticCaption, SemanticObject, SemanticResult, SceneTag

MOCK_DEFAULT = Path(__file__).with_name("mock_results.json")


class MockSemanticProvider:
    name = "mock"
    version = "1.0.0"

    def __init__(self, results_path: str | Path | None = None):
        self.results_path = Path(results_path) if results_path else MOCK_DEFAULT

    def _load(self) -> dict:
        try:
            return json.loads(self.results_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def detect(
        self,
        image: np.ndarray,
        regions: list[BBox] | None = None,
    ) -> SemanticResult:
        digest = hashlib.sha256(cv2.imencode(".png", image)[1]).hexdigest()
        table = self._load()
        key = table.get(digest) or table.get("default") or {}
        objects = [
            SemanticObject(
                label=str(item.get("label", "object"))[:80],
                bbox=BBox.from_any(item["bbox"]) if item.get("bbox") else None,
                confidence=float(item.get("confidence", 0.6)),
                source="mock",
            )
            for item in key.get("objects", [])
        ]
        captions = [
            SemanticCaption(
                text=str(item.get("text", ""))[:300],
                bbox=BBox.from_any(item["bbox"]) if item.get("bbox") else None,
                confidence=float(item.get("confidence", 0.6)),
                source="mock",
            )
            for item in key.get("captions", [])
        ]
        tags = [
            SceneTag(
                tag=str(item.get("tag", ""))[:80],
                confidence=float(item.get("confidence", 0.6)),
                source="mock",
            )
            for item in key.get("scene_tags", [])
        ]
        warning = None
        if not objects and not captions and not tags:
            warning = "mock semantic provider: no fixture for this image hash"
        return SemanticResult(
            objects=objects,
            captions=captions,
            scene_tags=tags,
            warning=warning,
            provider=self.name,
            model="mock",
        )
