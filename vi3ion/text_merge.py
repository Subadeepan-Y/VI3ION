"""Post-OCR text repairs: split fused words, join same-row fragments, pair
numbers with their labels across rows.

Everything here is evidence-preserving: OCR output is never corrected. A word
that was fused by OCR is only *separated* at an ink gap, and any split that is
not clearly a word boundary keeps a ``split_from`` note so the brief can say
what the raw read was.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

import cv2
import numpy as np

logger = logging.getLogger("vi3ion.analyzer")

REGION_ORDER = ["top_bar", "left_column", "centre", "right_column", "bottom_bar"]

# A merged-word split is only attempted on wide, all-caps boxes, at a gap that
# is this fraction of the box height and this many times wider than the median
# letter gap inside the same box.
SPLIT_MIN_CHARS = 6
SPLIT_MIN_ASPECT = 1.8
SPLIT_MIN_GAP = 0.20
SPLIT_GAP_RATIO = 2.2
SPLIT_CERTAIN_GAP = 0.6


@dataclass
class TextItem:
    value: str
    bbox: tuple[float, float, float, float]
    confidence: float
    region: str = "centre"
    uncertain: bool = False
    maybe: str | None = None   # flagged possible misread (never auto-corrected)
    split_from: str | None = None  # set when a merged word was split
    missing: str | None = None  # index number the row's position implies
    color: dict | None = None   # measured ink/background colours (see element_color)


def _column_runs(occupied: np.ndarray) -> list[tuple[int, int]]:
    """Half-open [start, end) runs of True columns."""
    runs: list[tuple[int, int]] = []
    start = None
    for index, flag in enumerate(occupied):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(occupied)))
    return runs


def _glyph_ink(crop: np.ndarray) -> np.ndarray:
    """Mask of glyph strokes, independent of text-on-dark vs text-on-light.

    A top-hat/black-hat pass keeps features smaller than half the box height,
    so letters register whether they are light or dark while large flat pale
    areas behind the text (a pillar, a glow) do not — which is what lets the
    space between two words show up as a real gap.
    """
    blurred = cv2.GaussianBlur(crop, (3, 3), 0)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(3, int(round(crop.shape[0] / 2))))
    )
    response = np.maximum(
        cv2.morphologyEx(blurred, cv2.MORPH_TOPHAT, kernel),
        cv2.morphologyEx(blurred, cv2.MORPH_BLACKHAT, kernel),
    )
    threshold, _ = cv2.threshold(response, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return response > max(float(threshold), 25.0)


def _split_candidates(left: str, right: str) -> bool:
    """Both halves must look like words, so '-' and '.' never start a split."""
    return (
        len(left) >= 2 and len(right) >= 2
        and left[-1].isalpha() and right[0].isalpha()
    )


def _chars_before(glyphs: list[tuple[int, int]], cut_x: int, length: int) -> int:
    """Estimate the character index sitting at ``cut_x``.

    Glyph runs are weighted by how many letters they are likely to hold, so a
    run where two letters touch still counts for two characters and the split
    falls on the right letter boundary.
    """
    widths = [end - start for start, end in glyphs]
    median_w = sorted(widths)[len(widths) // 2] or 1
    before = 0
    for (start, end), width in zip(glyphs, widths):
        if end <= cut_x:
            before += max(1, int(round(width / median_w)))
    return max(2, min(length - 2, before))


def split_merged_words(bgr: np.ndarray, items: Iterable[TextItem]) -> list[TextItem]:
    """Split two words that OCR fused into one box, at the ink gap between them.

    The box is reduced to a per-column glyph mask. Letters form narrow runs and
    the space between two words is the widest run of empty columns, at least
    ``SPLIT_MIN_GAP`` times the box height and ``SPLIT_GAP_RATIO`` times the
    median letter gap in the same box. The cut position follows the glyph runs
    to the left of that gap, so text is separated, never rewritten. A narrow
    gap still splits but is recorded as ``split_from``.
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
            or not re.fullmatch(r"[A-Z][A-Z']+", text)
            or len(text) < SPLIT_MIN_CHARS
            or box_w / box_h < SPLIT_MIN_ASPECT
        ):
            result.append(item)
            continue
        crop = gray[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0:
            result.append(item)
            continue
        h, _ = crop.shape
        coverage = _glyph_ink(crop).sum(axis=0) / h
        min_run = max(1, int(round(0.02 * h)))
        glyphs = [run for run in _column_runs(coverage >= 0.08) if run[1] - run[0] >= min_run]
        if len(glyphs) < 4:
            result.append(item)
            continue
        gaps = [
            (glyphs[i][1], glyphs[i + 1][0])
            for i in range(len(glyphs) - 1)
            if glyphs[i + 1][0] - glyphs[i][1] > 0
        ]
        if not gaps:
            result.append(item)
            continue
        gap_widths = sorted(g[1] - g[0] for g in gaps)
        median_gap = gap_widths[len(gap_widths) // 2]
        start, end = max(gaps, key=lambda g: g[1] - g[0])
        gap_w = end - start
        if gap_w < SPLIT_MIN_GAP * h or gap_w < SPLIT_GAP_RATIO * median_gap:
            result.append(item)
            continue
        cut = _chars_before(glyphs, start, len(text))
        left, right = text[:cut], text[cut:]
        if not _split_candidates(left, right):
            result.append(item)
            continue
        logger.debug("split %r -> %r %r (gap %dpx, box %dx%d)", text, left, right, gap_w, box_w, box_h)
        result.append(
            TextItem(
                value=f"{left} {right}",
                bbox=item.bbox,
                confidence=item.confidence,
                region=item.region,
                uncertain=item.uncertain,
                split_from=text if gap_w < SPLIT_CERTAIN_GAP * h else None,
            )
        )
    return result


def _letters(text: str) -> str:
    """Letters and digits only, for duplicate-content comparison."""
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u3400-\u9fff]+", "", text.lower())


def join_same_row(sections: dict[str, list[TextItem]]) -> dict[str, list[TextItem]]:
    """Join items on the same row when the horizontal gap is under one item height."""
    joined: dict[str, list[TextItem]] = {region: [] for region in REGION_ORDER}
    for region in REGION_ORDER:
        items = sections[region]
        row_items: dict[int, list[TextItem]] = {}
        for item in sorted(items, key=lambda i: (i.bbox[1], i.bbox[0])):
            placed = False
            for row in row_items.values():
                r0 = min(i.bbox[1] for i in row)
                r1 = max(i.bbox[3] for i in row)
                overlap = min(item.bbox[3], r1) - max(item.bbox[1], r0)
                if overlap > 0.5 * min(item.bbox[3] - item.bbox[1], r1 - r0):
                    row.append(item)
                    placed = True
                    break
            if not placed:
                row_items.setdefault(len(row_items), []).append(item)
        for row in row_items.values():
            row.sort(key=lambda i: i.bbox[0])
            current: TextItem | None = None
            for item in row:
                if current is None:
                    current = item
                    continue
                gap = item.bbox[0] - current.bbox[2]
                height = current.bbox[3] - current.bbox[1]
                # A re-read that contains the previous token (`[?] ALL` beside
                # `AL`) is one line, not two: keep the fuller reading.
                left, right = _letters(current.value), _letters(item.value)
                overlap_x = min(current.bbox[2], item.bbox[2]) - max(
                    current.bbox[0], item.bbox[0]
                )
                if left and right and overlap_x > 0 and (left in right or right in left):
                    if len(right) > len(left):
                        current = item
                    continue
                # A re-read of the same full line (same text, tiny differences)
                # should replace the weaker read, not join into a doubled line.
                if (
                    left and right and overlap_x > 0
                    and len(left) >= 6 and len(right) >= 6
                    and SequenceMatcher(None, left, right).ratio() >= 0.85
                ):
                    if item.confidence > current.confidence:
                        current = item
                    continue
                if gap < height:
                    current = TextItem(
                        value=f"{current.value} {item.value}",
                        bbox=(current.bbox[0], current.bbox[1], item.bbox[2], item.bbox[3]),
                        confidence=min(current.confidence, item.confidence),
                        region=region,
                        uncertain=current.uncertain or item.uncertain,
                        maybe=current.maybe or item.maybe,
                        split_from=current.split_from or item.split_from,
                        missing=current.missing or item.missing,
                    )
                else:
                    joined[region].append(current)
                    current = item
            if current is not None:
                joined[region].append(current)
    return joined


def pair_numbers_across_rows(
    sections: dict[str, list[TextItem]]
) -> dict[str, list[TextItem]]:
    """Pair a lone number with the nearest label row in the same region."""
    paired: dict[str, list[TextItem]] = {region: [] for region in REGION_ORDER}
    for region in REGION_ORDER:
        items = sorted(sections[region], key=lambda i: i.bbox[1])
        labels = [i for i in items if not re.fullmatch(r"\d{1,2}", i.value)]
        numbers = [i for i in items if re.fullmatch(r"\d{1,2}", i.value)]
        used: set[int] = set()
        for num in numbers:
            best = None
            best_dist = float("inf")
            for idx, label in enumerate(labels):
                if idx in used:
                    continue
                dist = abs(label.bbox[1] - num.bbox[1])
                if dist < best_dist:
                    best_dist = dist
                    best = idx
            if best is not None and best_dist < (label.bbox[3] - label.bbox[1]) * 3:
                label = labels[best]
                used.add(best)
                paired[region].append(
                    TextItem(
                        value=f'{num.value} + "{label.value}"',
                        bbox=(num.bbox[0], min(num.bbox[1], label.bbox[1]),
                              label.bbox[2], max(num.bbox[3], label.bbox[3])),
                        confidence=min(num.confidence, label.confidence),
                        region=region,
                        uncertain=num.uncertain or label.uncertain,
                        maybe=num.maybe or label.maybe,
                        missing=num.missing or label.missing,
                    )
                )
            else:
                paired[region].append(num)
        for idx, label in enumerate(labels):
            if idx not in used:
                paired[region].append(label)
        paired[region].sort(key=lambda i: (i.bbox[1], i.bbox[0]))
    return paired
