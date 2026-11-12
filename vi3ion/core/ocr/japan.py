"""Japanese character recognizer (rec-only) built on a bundled ONNX model.

The detector is expensive and language-agnostic; the provided Japanese model is
a recognition-only CRNN (PaddleOCR v1 `japan_rec_crnn`), so this engine is
used only after a crop has already been located (by the main pipeline or by
the CJK margin recovery). It decodes CTC output with the character table
embedded in the ONNX metadata, mirroring the Paddle rec pre/post-processing.
"""

from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np

_HERE = Path(__file__).resolve().parent
JAPAN_MODEL = _HERE / "models" / "japan_rec_crnn.onnx"

_ENGINE = None
_ENGINE_LOCK = threading.Lock()


class JapanRecognizer:
    """Recognition-only session with Paddle-style normalization + CTC decode."""

    def __init__(self, model_path: Path = JAPAN_MODEL) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        # The v1 CRNN exposes a fixed example output length; the real CTC
        # length follows the input width, so disable strict output verification.
        options.add_session_config_entry("session.verify_output_sizes", "false")
        self.session = ort.InferenceSession(
            str(model_path), options, providers=["CPUExecutionProvider"]
        )
        meta = self.session.get_modelmeta().custom_metadata_map
        raw = meta.get("character", "")
        self.chars = [""] + raw.split("\n")  # index 0 is CTC blank
        self.n_classes = len(self.chars)

    def _resize_norm_img(self, img: np.ndarray) -> np.ndarray:
        h, w = img.shape[:2]
        if h == 0 or w == 0:
            raise ValueError("empty crop")
        target_h = 32
        target_w = 100  # v1 CRNN uses a fixed 100px input width (T=25)
        resized = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        if resized.ndim == 2:
            resized = cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)
        normed = (resized.astype(np.float32) / 255.0 - 0.5) / 0.5
        return np.transpose(normed, (2, 0, 1))

    def probabilities(self, img: np.ndarray) -> np.ndarray:
        """CTC softmax probabilities shaped (T, C)."""
        normed = self._resize_norm_img(img)[None, :]
        out = self.session.run(None, {"x": normed.astype(np.float32)})[0][0]
        exp = np.exp(out - out.max(axis=1, keepdims=True))
        return exp / exp.sum(axis=1, keepdims=True)

    def recognize(self, img: np.ndarray) -> tuple[str, float]:
        """Best CTC decoding of one crop as (text, mean non-blank confidence)."""
        probs = self.probabilities(img)
        idxs = probs.argmax(axis=1)
        chars_out: list[str] = []
        confs: list[float] = []
        prev = 0
        for t, idx in enumerate(idxs):
            if idx == 0 or idx == prev:
                prev = idx
                continue
            chars_out.append(self.chars[idx])
            confs.append(float(probs[t][idx]))
            prev = idx
        text = "".join(chars_out).strip()
        score = float(np.mean(confs)) if confs else 0.0
        return text, score

    def topk(self, img: np.ndarray, k: int = 20) -> list[list[tuple[str, float]]]:
        """Per-timestep top-k chars with probabilities (for glyph evidence)."""
        probs = self.probabilities(img)
        rows = []
        for t in range(probs.shape[0]):
            idxs = np.argsort(probs[t])[-k:][::-1]
            rows.append(
                [(self.chars[i], float(probs[t][i])) for i in idxs]
            )
        return rows


def get_japan_recognizer() -> JapanRecognizer | None:
    """Lazy singleton; None when the model file is missing/unreadable."""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    if not JAPAN_MODEL.exists():
        return None
    with _ENGINE_LOCK:
        if _ENGINE is None:
            try:
                _ENGINE = JapanRecognizer()
            except Exception:  # noqa: BLE001
                _ENGINE = None
    return _ENGINE
