"""Context-driven attention relook.

When the user message supplies terms (the described bug area), only OCR lines
whose text overlaps those terms are re-read at a higher scale. This focuses
compute where the user is looking and leaves the rest of the frame untouched.
Everything produced here is still evidence: re-reads are only accepted when
the recogniser is more confident, and the updated lines keep their geometry.
"""

from __future__ import annotations

import logging
import re

import cv2

from .core.ocr.providers import OCRLine, get_ocr_provider

logger = logging.getLogger("vi3ion.analyzer")

MAX_BOXES = 8
REL_R_SCALES = (2, 3)
REL_PAD = 4


def _term_words(terms: list[str]) -> set[str]:
    words: set[str] = set()
    for term in terms:
        for w in re.findall(r"[0-9a-z\u3040-\u30ff\u3400-\u9fff]+", term.lower()):
            if len(w) >= 2:
                words.add(w)
    return words


def overlap_score(text: str, term_words: set[str]) -> float:
    if not term_words or not text:
        return 0.0
    words = {w for w in re.findall(r"[0-9a-z\u3040-\u30ff\u3400-\u9fff]+", text.lower()) if len(w) >= 2}
    if not words:
        return 0.0
    hit = len(words & term_words)
    # strong weight for exact phrase containment
    any_contain = any(tw in text.lower() for tw in term_words if len(tw) >= 4)
    return (hit / len(term_words)) + (0.6 if any_contain else 0.0)


def attention_relook(
    bgr,
    lines: list[OCRLine],
    terms: list[str],
    provider=None,
    max_boxes: int = MAX_BOXES,
) -> tuple[int, float]:
    """Re-read only lines overlapping the context terms; returns (updated, ms)."""
    if not terms or not lines:
        return 0, 0.0
    provider = provider or get_ocr_provider()
    if not provider.available:
        return 0, 0.0
    term_words = _term_words(terms)
    scored = [(overlap_score(line.text, term_words), line) for line in lines]
    scored.sort(key=lambda pair: -pair[0])
    selected = [line for score, line in scored if score > 0.0][:max_boxes]
    if not selected:
        return 0, 0.0

    import time

    started = time.perf_counter()
    updated = 0
    for line in selected:
        x0, y0, x1, y1 = (int(round(v)) for v in line.bbox)
        crop = bgr[max(0, y0 - REL_PAD):y1 + REL_PAD, max(0, x0 - REL_PAD):x1 + REL_PAD]
        if crop.size == 0:
            continue
        best: tuple[float, str] | None = None
        for scale in REL_R_SCALES:
            big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            for reread in provider.recognize(big):
                text = reread.text.strip()
                if not text:
                    continue
                if best is None or reread.confidence > best[0]:
                    best = (float(reread.confidence), text)
        if best is None or best[0] <= line.confidence:
            continue
        # keep the reading only when it overlaps/contains the original text
        old = re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", line.text.lower())
        new = re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", best[1].lower())
        if not old or not new or (old not in new and new not in old):
            continue
        line.text = best[1]
        line.confidence = best[0]
        updated += 1
        logger.debug("attention relook %r -> %r @ %.2f", old, new, best[0])
    return updated, (time.perf_counter() - started) * 1000.0
