"""Florence-2 provider (microsoft/Florence-2-base).

Used for region captions (`<REGION_TO_DESCRIPTION>`). Object detection is served
by the OWL-ViT provider; Florence's OD output parsing is tied to the
tokenizer/processor internals of older transformers, which the current
transformers/tokenizers pins do not expose cleanly.

Model inputs are built manually (raw tokenizers backend + image processor) to
avoid HF fast-tokenizer normalizer incompatibilities. Loads once per process.
Requires `pip install "vi3ion[semantic]"`.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from ...schemas import BBox
from .interface import SemanticCaption, SemanticResult

MODEL_ID = "microsoft/Florence-2-base"
MAX_SIDE = 768
IMAGE_TOKEN = "<image>"


class FlorenceProvider:
    name = "florence"
    version = "2-base"

    def __init__(self, model_id: str = MODEL_ID):
        self.model_id = model_id
        self._tokenizer = None
        self._image_processor = None
        self._model = None
        self._num_image_tokens = 1024
        self._load_error: str | None = None

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        if self._load_error:
            return False
        try:
            from pathlib import Path as _Path

            from transformers import AutoImageProcessor, AutoModelForCausalLM, BertTokenizer
        except Exception as exc:  # noqa: BLE001
            self._load_error = (
                f"Florence requires the optional dependency set: "
                f"pip install \"vi3ion[semantic]\" ({type(exc).__name__}: {exc})"
            )
            return False
        try:
            import json as _json

            from pathlib import Path as _Path

            snapshot = _Path.home() / ".cache" / "huggingface" / "hub" / (
                "models--microsoft--Florence-2-base"
            )
            vocab_path = next(snapshot.rglob("vocab.json"))
            self._tokenizer = BertTokenizer(
                vocab_file=str(vocab_path),
                bos_token="<s>",
                eos_token="</s>",
                unk_token="<unk>",
                pad_token="<pad>",
            )
            if self._tokenizer.convert_tokens_to_ids(IMAGE_TOKEN) is None:
                self._tokenizer.add_special_tokens(
                    {"additional_special_tokens": [IMAGE_TOKEN]}
                )
            self._image_processor = AutoImageProcessor.from_pretrained(self.model_id)
            self._num_image_tokens = int(
                getattr(self._image_processor, "image_seq_length", 1024)
            )

            def _patch_remote_class() -> None:
                import sys

                for module in list(sys.modules.values()):
                    cls = getattr(module, "Florence2ForConditionalGeneration", None)
                    if cls is not None:
                        cls._supports_sdpa = False

            self._model = None
            last_error: Exception | None = None
            for attempt in range(2):
                try:
                    self._model = AutoModelForCausalLM.from_pretrained(
                        self.model_id, trust_remote_code=True
                    )
                    break
                except AttributeError:
                    _patch_remote_class()
                    last_error = None
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    break
            if self._model is None:
                if last_error is not None:
                    raise last_error
                raise AttributeError("Florence remote model load failed twice")
            self._grow_embeddings(len(self._tokenizer))
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"Florence load failed: {type(exc).__name__}: {exc}"
            return False
        return True

    @staticmethod
    def _grow_embeddings(model, new_size: int) -> None:
        """Grow every Embedding sized like the original vocab to new_size."""
        import torch

        original = None
        for module in model.modules():
            if isinstance(module, torch.nn.Embedding):
                original = module.num_embeddings
                break
        if original is None or new_size <= original:
            return
        for name, module in model.named_modules():
            if isinstance(module, torch.nn.Embedding) and module.num_embeddings == original:
                grown = torch.nn.Embedding(
                    new_size, module.embedding_dim, padding_idx=module.padding_idx
                )
                with torch.no_grad():
                    grown.weight[:original] = module.weight.data
                parts = name.split(".")
                parent = model
                for part in parts[:-1]:
                    parent = getattr(parent, part)
                setattr(parent, parts[-1], grown)

    @staticmethod
    def _fit(image: np.ndarray) -> tuple[np.ndarray, float]:
        height, width = image.shape[:2]
        longest = max(width, height)
        scale = 1.0 if longest <= MAX_SIDE else MAX_SIDE / float(longest)
        if abs(scale - 1.0) > 1e-6:
            size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
            image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        return image, scale

    def _caption(self, pil_image, task: str) -> str:
        pixel_values = self._image_processor(pil_image, return_tensors="pt")[
            "pixel_values"
        ]
        image_id = self._tokenizer.convert_tokens_to_ids(IMAGE_TOKEN)
        bos_id = self._tokenizer.convert_tokens_to_ids("<s>")
        eos_id = self._tokenizer.convert_tokens_to_ids("</s>")
        task_ids = self._tokenizer.encode(task, add_special_tokens=False)
        # Keep the total prompt within the learned positional-embedding width.
        num_image_tokens = max(1, self._num_image_tokens - len(task_ids) - 2)
        input_ids = [image_id] * num_image_tokens + [bos_id] + task_ids + [eos_id]
        import torch

        tensors = {
            "input_ids": torch.tensor([input_ids], dtype=torch.long),
            "attention_mask": torch.tensor([[1] * len(input_ids)], dtype=torch.long),
            "pixel_values": pixel_values,
        }
        outputs = self._model.generate(**tensors, max_new_tokens=256, num_beams=3, do_sample=False)
        return self._tokenizer.decode(outputs[0].tolist(), skip_special_tokens=True)

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
                model=self.model_id,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        from PIL import Image

        fitted, scale = self._fit(image)
        captions: list[SemanticCaption] = []
        try:
            if regions:
                for region in regions:
                    crop = fitted[
                        int(region.y0 * scale): int(region.y1 * scale),
                        int(region.x0 * scale): int(region.x1 * scale),
                    ]
                    if crop.size == 0:
                        continue
                    description = self._caption(
                        Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)),
                        "<REGION_TO_DESCRIPTION>",
                    )
                    text = description.strip()
                    if not text:
                        continue
                    captions.append(
                        SemanticCaption(
                            text=text[:300],
                            bbox=region,
                            confidence=0.6,
                            source=self.name,
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            return SemanticResult(
                error=f"Florence inference failed: {type(exc).__name__}: {exc}",
                warning=f"Florence inference failed: {type(exc).__name__}: {exc}",
                provider=self.name,
                model=self.model_id,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        return SemanticResult(
            captions=captions[:20],
            provider=self.name,
            model=self.model_id,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
