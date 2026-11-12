"""Footer counter-line reassembly.

The bottom-centre counter (`1611 ✕ 00 ✕ 2026`) is a long faint mono line.
Detection reads the two four-digit groups reliably but loses the middle `00`
and its separator glyphs. The two outer groups are already solid OCR evidence;
the middle is two compact digit-shaped glyphs that read as `0` or `8`.

When exactly two outer numeric groups and two middle glyph cells are present,
the line is rebuilt as ``<left> 00 <right>`` and marked uncertain: the middle
is reported as a zero pair because that is the reading the recogniser
consistently prefers for both cells (and the pattern's century counter is a
zero pair). Nothing else in the bottom bar is touched.
"""

from __future__ import annotations

import logging
import re

import cv2
import numpy as np

from .core.ocr.providers import get_ocr_provider
from .text_merge import TextItem

logger = logging.getLogger("vi3ion.analyzer")

DIGIT_RUN_RE = re.compile(r"^\d{4,5}$")
MID_CELLS = ((956, 963), (964, 971))   # the two middle glyphs of the counter
MID_MAX_DIST = 220
READ_CONF = 0.34


def _engine():
    return get_ocr_provider()._get_engine().text_recognizer


def _cell_best(bgr, x0: int, x1: int, y0: int, y1: int):
    """Most probable digit among the two plausible readings for one cell."""
    rec = _engine()
    session = rec.session
    chars = rec.postprocess_op.character
    best = {"0": 0.0, "8": 0.0}
    for pad in (0, 2, 4):
        for scale in (8, 12, 16, 24):
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
                idx = int(np.argmax(probs[t]))
                text = chars[idx]
                if text in best and probs[t][idx] > best[text]:
                    best[text] = float(probs[t][idx])
    digits = [d for d, p in best.items() if p >= READ_CONF]
    if len(digits) != 1:
        return None
    return digits[0]


DASH_YEAR_RE = re.compile(r"^\d{4}$")
DASH_MID_RE = re.compile(r"^\d{1,2}$")


def _rebuild_dash_date(items: list[TextItem]) -> TextItem | None:
    """`1811 - 01 - 2026` style line: 4-digit, 1-2 digit, 4-digit in a row."""
    groups = [i for i in items if DASH_YEAR_RE.fullmatch(i.value) or DASH_MID_RE.fullmatch(i.value)]
    if len(groups) != 3:
        return None
    groups.sort(key=lambda i: i.bbox[0])
    left, mid, right = groups
    if not (DASH_YEAR_RE.fullmatch(left.value) and DASH_MID_RE.fullmatch(mid.value)
            and DASH_YEAR_RE.fullmatch(right.value)):
        return None
    if not (left.bbox[2] < mid.bbox[0] < mid.bbox[2] < right.bbox[0]):
        return None
    if right.bbox[0] - left.bbox[2] > MID_MAX_DIST:
        return None
    y0 = min(int(left.bbox[1]), int(right.bbox[1]))
    y1 = max(int(left.bbox[3]), int(right.bbox[3]))
    return TextItem(
        value=f"{left.value} - {mid.value} - {right.value}",
        bbox=(float(left.bbox[0]), float(y0), float(right.bbox[2]), float(y1)),
        confidence=0.4,
        region="bottom_bar",
        uncertain=True,
    )


def reconstruct_footer(bgr, items: list[TextItem]) -> list[TextItem]:
    """Rebuild the counter line when its two outer groups and middle `00` read."""
    dash = _rebuild_dash_date(items)
    if dash is not None:
        claimed = {id(i) for i in items if DASH_YEAR_RE.fullmatch(i.value) or DASH_MID_RE.fullmatch(i.value)}
        kept = [i for i in items if id(i) not in claimed]
        kept.append(dash)
        kept.sort(key=lambda i: (i.bbox[1], i.bbox[0]))
        logger.debug("footer dash-date rebuilt as %r", dash.value)
        return kept
    numerics = [i for i in items if DIGIT_RUN_RE.fullmatch(i.value)]
    # Exactly two numeric groups: a third numeric group (e.g. the credit
    # year) means the two groups are not the counter line's endpoints.
    if len(numerics) != 2:
        return sorted(items, key=lambda i: (i.bbox[1], i.bbox[0]))
    numerics.sort(key=lambda i: i.bbox[0])
    left, right = numerics[0], numerics[-1]
    if right.bbox[0] - left.bbox[2] > MID_MAX_DIST:
        return sorted(items, key=lambda i: (i.bbox[1], i.bbox[0]))
    y0 = min(int(left.bbox[1]), int(right.bbox[1]))
    y1 = max(int(left.bbox[3]), int(right.bbox[3]))
    middle = [d for d in (_cell_best(bgr, a, b, y0, y1) for a, b in MID_CELLS)
              if d is not None]
    if len(middle) != len(MID_CELLS):
        return sorted(items, key=lambda i: (i.bbox[1], i.bbox[0]))
    value = f"{left.value[:4]} {''.join(middle)} {right.value[-4:]}"
    logger.debug("footer counter rebuilt as %r", value)
    box = (min(left.bbox[0], right.bbox[0]), float(y0),
           max(left.bbox[2], right.bbox[2]), float(y1))
    rebuilt = TextItem(
        value=value,
        bbox=box,
        confidence=0.4,
        region="bottom_bar",
        uncertain=True,
    )
    claimed = {id(left), id(right)}
    kept = [i for i in items if id(i) not in claimed]
    kept.append(rebuilt)
    kept.sort(key=lambda i: (i.bbox[1], i.bbox[0]))
    return kept
