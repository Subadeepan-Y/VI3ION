"""OCR providers. The rest of Vi3ion only sees `OCRLine` objects."""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass, field

import numpy as np


@dataclass
class OCRLine:
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]  # working-canvas pixels
    polygon: list[list[float]] = field(default_factory=list)
    order: int = 0
    row: int = 0


class OCRProvider:
    name = "none"
    available = False

    def recognize(self, bgr: np.ndarray) -> list[OCRLine]:  # pragma: no cover - interface
        raise NotImplementedError


class RapidOCRProvider(OCRProvider):
    name = "rapidocr_onnx"

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:  # type: ignore[override]
        try:
            import rapidocr_onnxruntime  # noqa: F401

            return True
        except Exception:
            return False

    def _get_engine(self):
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    from rapidocr_onnxruntime import RapidOCR

                    self._engine = RapidOCR()
        return self._engine

    def recognize(self, bgr: np.ndarray) -> list[OCRLine]:
        engine = self._get_engine()
        target = bgr
        if bgr is not None and bgr.size > 0:
            import cv2

            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            mean = float(np.mean(gray))
            std = float(np.std(gray))
            if mean < 60.0 or std < 45.0:
                lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
                l_chan, a_chan, b_chan = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
                boosted_l = clahe.apply(l_chan)
                target = cv2.cvtColor(cv2.merge([boosted_l, a_chan, b_chan]), cv2.COLOR_LAB2BGR)
        raw, _elapsed = engine(target)
        lines: list[OCRLine] = []
        if not raw:
            return lines
        for item in raw:
            try:
                box, text, score = item[0], item[1], item[2]
            except (IndexError, TypeError):
                continue
            text = str(text).strip()
            if not text:
                continue
            points = [[float(p[0]), float(p[1])] for p in box]
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            lines.append(
                OCRLine(
                    text=text,
                    confidence=float(score),
                    bbox=(min(xs), min(ys), max(xs), max(ys)),
                    polygon=points,
                )
            )
        return lines


class TesseractProvider(OCRProvider):
    name = "tesseract"

    @property
    def available(self) -> bool:  # type: ignore[override]
        if shutil.which("tesseract") is None:
            return False
        try:
            import pytesseract  # noqa: F401

            return True
        except Exception:
            return False

    def recognize(self, bgr: np.ndarray) -> list[OCRLine]:
        import pytesseract
        from pytesseract import Output

        rgb = bgr[:, :, ::-1]
        data = pytesseract.image_to_data(rgb, output_type=Output.DICT)
        groups: dict[tuple, list[int]] = {}
        for index, text in enumerate(data["text"]):
            if not str(text).strip():
                continue
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            groups.setdefault(key, []).append(index)
        lines: list[OCRLine] = []
        for indices in groups.values():
            words = [str(data["text"][i]).strip() for i in indices]
            lefts = [data["left"][i] for i in indices]
            tops = [data["top"][i] for i in indices]
            rights = [data["left"][i] + data["width"][i] for i in indices]
            bottoms = [data["top"][i] + data["height"][i] for i in indices]
            confidences = [float(data["conf"][i]) for i in indices if str(data["conf"][i]) != "-1"]
            confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
            lines.append(
                OCRLine(
                    text=" ".join(words),
                    confidence=confidence,
                    bbox=(float(min(lefts)), float(min(tops)), float(max(rights)), float(max(bottoms))),
                )
            )
        return lines


class NullProvider(OCRProvider):
    name = "none"
    available = False

    def recognize(self, bgr: np.ndarray) -> list[OCRLine]:
        return []


_PROVIDER: OCRProvider | None = None
_PROVIDER_LOCK = threading.Lock()


def get_ocr_provider() -> OCRProvider:
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    with _PROVIDER_LOCK:
        if _PROVIDER is None:
            for candidate in (RapidOCRProvider(), TesseractProvider()):
                if candidate.available:
                    _PROVIDER = candidate
                    break
            else:
                _PROVIDER = NullProvider()
    return _PROVIDER
