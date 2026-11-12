"""Open-vocabulary detector provider (OWL-ViT).

Queries a fixed label vocabulary (config file, JSON with a "labels" list)
against the image. Boxes are returned in the coordinate frame of the image
argument. Requires `pip install "vi3ion[semantic]"`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np

from ...schemas import BBox
from .interface import SemanticObject, SemanticResult

VOCAB_DEFAULT = Path(__file__).with_name("vocabulary.json")


class OpenVocabDetector:
    name = "owlvit"
    version = "owlv2-base"

    def __init__(
        self,
        vocab_path: str | Path | None = None,
        min_confidence: float = 0.35,
        model_id: str = "google/owlv2-base-patch16",
    ):
        self.vocab_path = Path(vocab_path) if vocab_path else VOCAB_DEFAULT
        self.min_confidence = min_confidence
        self.model_id = model_id
        self._model = None
        self._processor = None
        self._load_error: str | None = None

    def _load_labels(self) -> list[str]:
        try:
            data = json.loads(self.vocab_path.read_text(encoding="utf-8"))
            labels = data.get("labels", [])
        except Exception:
            labels = []
        return [str(label).strip() for label in labels if str(label).strip()][:80]

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        if self._load_error:
            return False
        try:
            from transformers import Owlv2ForObjectDetection, Owlv2Processor
        except Exception as exc:  # noqa: BLE001
            self._load_error = (
                f"OWL-ViT requires the optional dependency set: "
                f"pip install \"vi3ion[semantic]\" ({type(exc).__name__}: {exc})"
            )
            return False
        try:
            self._processor = Owlv2Processor.from_pretrained(self.model_id)
            self._model = Owlv2ForObjectDetection.from_pretrained(self.model_id)
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"OWL-ViT load failed: {type(exc).__name__}: {exc}"
            return False
        return True

    def detect(
        self,
        image: np.ndarray,
        regions: list[BBox] | None = None,
    ) -> SemanticResult:
        started = time.perf_counter()
        if not self._ensure_loaded():
            return SemanticResult(
                error=self._load_error,
                warning=self._load_error,
                provider=self.name,
                model=self.version,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        labels = self._load_labels()
        if not labels:
            return SemanticResult(
                error="open-vocabulary vocabulary is empty",
                warning="open-vocabulary vocabulary is empty",
                provider=self.name,
                model=self.version,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        from PIL import Image

        pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        try:
            inputs = self._processor(text=labels, images=pil, return_tensors="pt")
            with __import__("torch").no_grad():
                outputs = self._model(**inputs)
            target_sizes = __import__("torch").tensor([pil.size[::-1]])
            results = self._processor.post_process_object_detection(
                outputs, threshold=self.min_confidence, target_sizes=target_sizes
            )[0]
            width, height = pil.size
            objects: list[SemanticObject] = []
            for box, score, label_id in zip(
                results["boxes"], results["scores"], results["labels"]
            ):
                x0, y0, x1, y1 = [float(v) for v in box]
                box = BBox(x0=x0, y0=y0, x1=x1, y1=y1).clamp(width, height)
                objects.append(
                    SemanticObject(
                        label=labels[int(label_id)][:80],
                        bbox=box,
                        confidence=float(score),
                        source=self.name,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            return SemanticResult(
                error=f"OWL-ViT inference failed: {type(exc).__name__}: {exc}",
                warning=f"OWL-ViT inference failed: {type(exc).__name__}: {exc}",
                provider=self.name,
                model=self.version,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        objects.sort(key=lambda obj: obj.confidence, reverse=True)
        return SemanticResult(
            objects=objects[:40],
            provider=self.name,
            model=self.version,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
