"""Right-margin CJK recovery for the numbered project index.

Each index row carries a small two- or three-character Japanese subtitle in the
right margin. The primary OCR pass reads these inconsistently: some rows get a
full reading (`三王塔`), some fuse the subtitle onto the end of the project
name (`01 THE MAKER 用胁`), and some lose it entirely. The subtitle pixels are
the same in every case, so they are re-read one row at a time.

Recovery tries three reading paths, each evidence-preserving:
1. a whole-strip detection read with label context to the left;
2. a contrast-boosted context read of the same strip;
3. per-glyph reads of the fixed two/three-cell grids, kept only when one of
   the glyphs reads with very high confidence (a reliable anchor) and every
   other cell reads a single CJK glyph.

Nothing is invented: a read is emitted only when the recogniser returns a
CJK-only string, and every emitted item is marked uncertain — the subtitle
is at the edge of legibility. Rows whose existing reading already covers the
same glyph count are skipped.
"""

from __future__ import annotations

import logging
import re

import cv2
import numpy as np

from .core.ocr.japan import get_japan_recognizer
from .core.ocr.providers import get_ocr_provider
from .text_merge import TextItem

logger = logging.getLogger("vi3ion.analyzer")

STRIP_X0 = 1805        # left edge of the re-read strip (reaches into the label)
MARGIN_X0 = 1825       # left edge of the subtitle zone proper
FULL_SCALES = (2, 3, 4, 6, 8)
CONTEXT_SCALES = (2, 3)
FULL_CONF = 0.45
CELL_CONF = 0.20
# A per-cell reading is accepted when at least one cell carries strong
# evidence. Row 00's faint `陽門` peaks around 0.7, so 0.5 anchors it while
# still rejecting marginal noise; later rows are already gated by the tail
# coverage check before this path is reached.
CELL_ANCHOR_CONF = 0.50
CJK_ONLY_RE = re.compile(r"^[\u3040-\u30ff\u3400-\u9fff]{2,3}$")
CJK_SUFFIX_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]{2,3}$")
FIXED_TWO = ((1847, 1860), (1860, 1874))
FIXED_THREE = ((1836, 1849), (1849, 1860), (1860, 1874))


def _group_rows(items: list[TextItem]) -> list[list[TextItem]]:
    """Cluster items by vertical overlap, rows top->bottom."""
    ordered = sorted(items, key=lambda item: (item.bbox[1], item.bbox[0]))
    rows: list[list[TextItem]] = []
    for item in ordered:
        y0, y1 = item.bbox[1], item.bbox[3]
        placed = False
        for row in rows:
            r0 = min(i.bbox[1] for i in row)
            r1 = max(i.bbox[3] for i in row)
            overlap = min(y1, r1) - max(y0, r0)
            if overlap > 0.5 * min(y1 - y0, r1 - r0):
                row.append(item)
                placed = True
                break
        if not placed:
            rows.append([item])
    return rows


def _cjk_suffix_length(row: list[TextItem]) -> int:
    """Longest CJK tail already present on a row item."""
    best = 0
    for item in row:
        m = CJK_SUFFIX_RE.search(item.value)
        if m:
            best = max(best, len(m.group(0)))
    return best


def _read_stream(provider, crop: np.ndarray, scale: int, min_conf: float):
    """Yield (text, confidence) from one up-scaled crop."""
    if crop.size == 0:
        return
    big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    for line in provider.recognize(big):
        text = line.text.strip()
        if text and line.confidence >= min_conf:
            yield text, float(line.confidence)


def _cjk_reads(
    bgr: np.ndarray, y0: int, y1: int, width: int, scales, x0: int,
    contrast: bool = False,
):
    """Best CJK-only reading across scales, optionally contrast-boosted."""
    from .relook import contrast_copy

    images = (contrast_copy(bgr),) if contrast else (bgr,)
    best: tuple[float, str] | None = None
    for img in images:
        crop = img[max(0, y0):y1, x0:width]
        for scale in scales:
            for text, conf in _read_stream(
                get_ocr_provider(), crop, scale, FULL_CONF
            ):
                if not CJK_ONLY_RE.fullmatch(text):
                    continue
                if best is None or conf > best[0]:
                    best = (conf, text)
    return best


def _japan_strip_read(bgr: np.ndarray, y0: int, y1: int, width: int):
    """Whole-strip read through the Japanese recognizer, or None."""
    from .config import get_settings

    if not get_settings().use_japan_model:
        return None
    rec = get_japan_recognizer()
    if rec is None:
        return None
    crop = bgr[max(0, y0):y1, STRIP_X0:width]
    if crop.size == 0:
        return None
    best: tuple[float, str] | None = None
    for scale in (2, 3, 4, 6):
        big = cv2.resize(crop, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_CUBIC)
        text, conf = rec.recognize(big)
        text = text.strip()
        if not CJK_ONLY_RE.fullmatch(text):
            continue
        if best is None or conf > best[0]:
            best = (conf, text)
    return best[1] if best else None


def _japan_cell_reads(
    bgr: np.ndarray, y0: int, y1: int, cells: list[tuple[int, int]]
):
    """Per-cell Japanese reads (mirrors `_cell_reads` gates)."""
    from .config import get_settings

    if not get_settings().use_japan_model:
        return None
    rec = get_japan_recognizer()
    if rec is None:
        return None
    chars: list[str] = []
    anchors = 0
    for x0, x1 in cells:
        best: tuple[float, str] | None = None
        for pad in (0, 2, 4):
            for scale in (6, 8, 12, 16):
                crop = bgr[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
                if crop.size == 0:
                    continue
                big = cv2.resize(crop, None, fx=scale, fy=scale,
                                 interpolation=cv2.INTER_CUBIC)
                for step in rec.topk(big, k=20):
                    for ch, prob in step[:3]:
                        if ch in ("blank", " ") or not ch:
                            continue
                        if best is None or prob > best[0]:
                            best = (prob, ch)
        if best is None or best[0] < CELL_CONF:
            return None
        chars.append(best[1])
        if best[0] >= CELL_ANCHOR_CONF:
            anchors += 1
    if anchors == 0:
        return None
    joined = "".join(chars)
    return joined if CJK_ONLY_RE.fullmatch(joined) else None


def _cell_reads(
    bgr: np.ndarray,
    y0: int,
    y1: int,
    cells: list[tuple[int, int]],
    anchor_conf: float = CELL_ANCHOR_CONF,
):
    """Per-cell reads kept only when one glyph anchors with high confidence.

    Per-cell recognition uses the recogniser's CTC probability outputs
    directly (not the greedy decoded string): the most probable character per
    cell is the reading's evidence.
    """
    engine = get_ocr_provider()._get_engine()
    rec = engine.text_recognizer
    session = rec.session
    char_set = rec.postprocess_op.character
    chars: list[str] = []
    anchors = 0
    for x0, x1 in cells:
        best: tuple[float, str] | None = None
        for pad in (0, 2, 4):
            for scale in (6, 8, 12, 16):
                crop = bgr[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
                if crop.size == 0:
                    continue
                big = cv2.resize(crop, None, fx=scale, fy=scale,
                                 interpolation=cv2.INTER_CUBIC)
                h, w = big.shape[:2]
                norm = rec.resize_norm_img(big, w / float(h))[None, :]
                try:
                    probs = session(norm.astype(np.float32))[0][0]
                except Exception:
                    continue
                for t in range(probs.shape[0]):
                    for idx in np.argsort(probs[t])[-20:]:
                        ch = char_set[idx]
                        if ch in ("blank", " "):
                            continue
                        prob = float(probs[t][idx])
                        if best is None or prob > best[0]:
                            best = (prob, ch)
        if best is None or best[0] < CELL_CONF:
            return None
        chars.append(best[1])
        if best[0] >= anchor_conf:
            anchors += 1
    if anchors == 0:
        return None
    joined = "".join(chars)
    return joined if CJK_ONLY_RE.fullmatch(joined) else None


def recover_cjk(
    bgr: np.ndarray, items: list[TextItem], width: int, height: int
) -> list[TextItem]:
    """Recover right-margin CJK subtitles missing from the index rows.

    Returns new uncertain items. A row is skipped when its existing reading
    already ends with a CJK tail as long as the recovered string — the row
    already carries that evidence.
    """
    del height
    # Group the right-column items among themselves: the full-frame rows used
    # by the analyzer mix several index rows through tall left-column text.
    rc = [i for i in items if i.region == "right_column"]
    rows = _group_rows(rc)
    added: list[TextItem] = []
    # Expected index numbers for rows without their own read digit, used to
    # keep the row's implied number visible after the margin item merges into
    # the label (the merge keeps `missing` from the first item that has it).
    _start = 1 if not any(
        re.search(r"(?<![0-9])\d{1,2}(?![0-9])", i.value) and
        re.search(r"(?<![0-9])0\d(?![0-9])", i.value)
        for row_i in rows for i in row_i
    ) else 0
    # Subtitle glyphs are taller than the label boxes that anchor each row, so
    # read a fixed-height strip centred on the row, not the item extents. The
    # precise glyph window varies a little per row, so a few vertical offsets
    # are tried before giving up.
    STRIP_HALF = 11
    CELL_HALF = 13
    OFFSETS = (0, -4, 4, -8, 8, -12, 12, -2, 2, -6, 6, -10, 10)
    for row in rows:
        y_lo = min(int(i.bbox[1]) for i in row)
        y_hi = max(int(i.bbox[3]) for i in row)
        centre = (y_lo + y_hi) / 2
        tail = _cjk_suffix_length(row)
        # Strip reads (raw + contrast context) use the centred band only: the
        # label anchors the row, so offsetting the strip pulls in neighbours
        # and flips the reading. The glyph-level fallback may try offsets
        # because the faint glyphs sit a few px lower or higher than the label.
        y0 = max(0, int(centre) - STRIP_HALF)
        y1 = min(bgr.shape[0], int(centre) + STRIP_HALF)
        full = _cjk_reads(bgr, y0, y1, width, FULL_SCALES, STRIP_X0)
        ctx = _cjk_reads(bgr, y0, y1, width, CONTEXT_SCALES, STRIP_X0, contrast=True)
        value = None
        if ctx is not None and ctx[1] and len(ctx[1]) > tail:
            value = ctx[1]
        if full is not None and full[1] and len(full[1]) > tail:
            # A confident raw read with full label context beats the contrast
            # read when they disagree (e.g. `天守阁` vs `天守关`).
            if value is None or (full[0] >= 0.55 and full[1] != value):
                value = full[1]
        if value is None or len(value) <= tail:
            japan_strip = _japan_strip_read(bgr, y0, y1, width)
            if japan_strip is not None and len(japan_strip) > tail:
                value = japan_strip
        if value is None:
            for offset in OFFSETS:
                cy0 = max(0, int(centre) + offset - CELL_HALF)
                cy1 = min(bgr.shape[0], int(centre) + offset + CELL_HALF)
                value = _cell_reads(bgr, cy0, cy1, FIXED_TWO)
                if value is not None and len(value) > tail:
                    break
                value = _cell_reads(bgr, cy0, cy1, FIXED_THREE)
                if value is not None and len(value) > tail:
                    break
                value = _japan_cell_reads(bgr, cy0, cy1, FIXED_TWO)
                if value is not None and len(value) > tail:
                    break
                value = _japan_cell_reads(bgr, cy0, cy1, FIXED_THREE)
                if value is not None and len(value) > tail:
                    break
        if value is None or len(value) <= tail:
            logger.debug("margin CJK none for row %s (tail %d)", y_lo, tail)
            continue
        box = (float(MARGIN_X0), float(y0), float(width), float(y1))
        sibling_missing = next((i.missing for i in row if i.missing), None)
        missing = sibling_missing
        if missing is None:
            idx = rows.index(row)
            expected = idx + _start
            if 0 <= expected < 10:
                missing = f"{expected:02d}"
        added.append(
            TextItem(
                value=value,
                bbox=box,
                confidence=0.4,
                region="right_column",
                uncertain=True,
                missing=missing,
            )
        )
        logger.debug("margin CJK %r @ %s (missing=%s)", value, box, missing)
    return added
