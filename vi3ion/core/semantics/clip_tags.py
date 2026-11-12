"""Scene-tag provider: CLIP zero-shot classification over a fixed scene list.

Tags are whole-image suggestions. They are marked `suggested` by the engine
(observed=False) and never appear in the object list.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from .interface import SceneTag, SemanticResult

SCENE_TYPES = [
    "illustrated 3D scene",
    "web page",
    "terminal",
    "code editor",
    "chart",
    "photograph",
    "error dialog",
    "settings screen",
    "diagram",
    "game UI",
    "text document",
    "map",
]


class ClipSceneTagger:
    name = "clip"
    version = "vit-base-patch32"

    def __init__(self, model_id: str = "openai/clip-vit-base-patch32", top_k: int = 3):
        self.model_id = model_id
        self.top_k = top_k
        self._model = None
        self._processor = None
        self._load_error: str | None = None

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        if self._load_error:
            return False
        try:
            from transformers import CLIPModel, CLIPProcessor
        except Exception as exc:  # noqa: BLE001
            self._load_error = (
                f"CLIP requires the optional dependency set: "
                f"pip install \"vi3ion[semantic]\" ({type(exc).__name__}: {exc})"
            )
            return False
        try:
            self._processor = CLIPProcessor.from_pretrained(self.model_id)
            self._model = CLIPModel.from_pretrained(self.model_id)
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"CLIP load failed: {type(exc).__name__}: {exc}"
            return False
        return True

    def detect(
        self,
        image: np.ndarray,
        regions: list | None = None,
    ) -> SemanticResult:
        started = time.perf_counter()
        if not self._ensure_loaded():
            return SemanticResult(
                error=self._load_error,
                warning=self._load_error,
                provider=self.name,
                model=self.model_id,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        from PIL import Image

        try:
            pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            inputs = self._processor(
                text=SCENE_TYPES, images=pil, return_tensors="pt", padding=True
            )
            import torch

            with torch.no_grad():
                outputs = self._model(**inputs)
            probs = outputs.logits_per_image.softmax(dim=1)[0]
            tags = sorted(
                zip(SCENE_TYPES, probs.tolist()),
                key=lambda pair: pair[1],
                reverse=True,
            )[: self.top_k]
        except Exception as exc:  # noqa: BLE001
            return SemanticResult(
                error=f"CLIP inference failed: {type(exc).__name__}: {exc}",
                warning=f"CLIP inference failed: {type(exc).__name__}: {exc}",
                provider=self.name,
                model=self.model_id,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        return SemanticResult(
            scene_tags=[SceneTag(tag=tag, confidence=float(prob), source=self.name) for tag, prob in tags],
            provider=self.name,
            model=self.model_id,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
