"""Split lowercase words that OCR fused into one box.

``text_merge.split_merged_words`` handles wide, all-caps display lines. Body
copy fuses too (``buildwhat's``), but its boxes are proportioned differently:
letters are shorter and the fused boundary is a single wide ink gap rather
than a run of merged capitals. The cut here is taken proportionally from the
gap's x position, because glyph-run weighting under-counts lowercase letters
that touch inside a word.

The text is only separated, never rewritten; a narrow gap keeps a
``split_from`` note so the brief can show the raw read.
"""

from __future__ import annotations

import re
from typing import Iterable

import cv2
import numpy as np

from .text_merge import TextItem, _column_runs, _glyph_ink

LOWER_MIN_CHARS = 8
LOWER_MIN_ASPECT = 3.0
LOWER_MIN_GAP = 0.20
LOWER_GAP_RATIO = 2.2
LOWER_CERTAIN_GAP = 0.6


def _proportional_cut(gap_start: int, box_w: int, length: int) -> int:
    """Character index at ``gap_start``, assuming even character advance."""
    if box_w <= 0 or length < 6:
        return 3
    return max(3, min(length - 3, int(round(gap_start / box_w * length))))


def split_lowercase_words(
    bgr: np.ndarray, items: Iterable[TextItem]
) -> list[TextItem]:
    """Separate a lower-case body line at its widest internal ink gap.

    Only lines that already contain a word space are considered, so the cut can
    be checked against a known boundary: if the widest gap is the existing
    space, the cut lands on whitespace and the item is left alone. Both
    resulting words must be at least three letters, which keeps a stray gap
    inside one word from becoming a split.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    result: list[TextItem] = []
    for item in items:
        text = item.value
        x0, y0, x1, y1 = (int(round(v)) for v in item.bbox)
        box_h = max(1, y1 - y0)
        box_w = max(1, x1 - x0)
        if (
            item.uncertain
            or not text[:1].islower()
            or " " not in text
            or len(text) < LOWER_MIN_CHARS
            or not re.search(r"[a-z]{3}", text)
            or box_w / box_h < LOWER_MIN_ASPECT
        ):
            result.append(item)
            continue
        crop = gray[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0:
            result.append(item)
            continue
        h, w = crop.shape
        coverage = _glyph_ink(crop).sum(axis=0) / h
        min_run = max(1, int(round(0.02 * h)))
        glyphs = [run for run in _column_runs(coverage >= 0.08) if run[1] - run[0] >= min_run]
        gaps = [
            (glyphs[i][1], glyphs[i + 1][0])
            for i in range(len(glyphs) - 1)
            if glyphs[i + 1][0] - glyphs[i][1] > 0
        ]
        if len(glyphs) < 4 or not gaps:
            result.append(item)
            continue
        median_gap = sorted(g[1] - g[0] for g in gaps)[len(gaps) // 2]
        start, end = max(gaps, key=lambda g: g[1] - g[0])
        gap_w = end - start
        if gap_w < LOWER_MIN_GAP * h or gap_w < LOWER_GAP_RATIO * median_gap:
            result.append(item)
            continue
        cut = _proportional_cut(start, w, len(text))
        left, right = text[:cut], text[cut:]
        if (
            not left or not right
            or not left[-1].isalpha() or not right[0].isalpha()
            or len(left.split()[-1]) < 3 or len(right.split()[0]) < 3
        ):
            result.append(item)
            continue
        result.append(
            TextItem(
                value=f"{left} {right}",
                bbox=item.bbox,
                confidence=item.confidence,
                region=item.region,
                uncertain=item.uncertain,
                split_from=text if gap_w < LOWER_CERTAIN_GAP * h else None,
            )
        )
    return result
