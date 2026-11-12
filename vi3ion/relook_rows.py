"""Per-row re-reads for the right-hand project index.

Two failures survive the band passes: a two-digit index that OCR fused into a
name (``BB`` where the row really starts ``06``), and a label read with one
wrong glyph (``8ANCTUM``). Both are re-read one row at a time at 2x, where the
numeral and the label are still large enough to separate but not so large that
the detector merges the numeral into the name.

Nothing is replaced. A recovered digit becomes its own uncertain item, which
the normal row join may attach to the label; a differing label becomes the
row's ``maybe`` alternative, so the brief shows both readings.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

import cv2
import numpy as np

from .core.ocr.providers import get_ocr_provider
from .text_merge import TextItem

logger = logging.getLogger("vi3ion.analyzer")

DIGIT_CONF = 0.40
LABEL_CONF = 0.60
LABEL_RATIO = 0.75
LABEL_MAX_EDITS = 2
DIGIT_SCALES = (2,)
LABEL_SCALES = (2,)
DIGIT_RE = re.compile(r"^\d{2}$")
TOKEN_RE = re.compile(r"[0-9A-Za-z]{4,}")
# A label whose first character is a digit (`8ANCTUM`) is the shape a fused
# index or a digit-for-letter misread leaves behind. Other rows are skipped so
# the per-row pass stays cheap.
SUSPECT_LABEL_RE = re.compile(r"(?<!\S)\d[A-Za-z]{3,}")

def _edit_distance(left: str, right: str) -> int:
    """Levenshtein distance, used only to bound label alternatives."""
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for i, ch in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ch != other),
            ))
        previous = current
    return previous[-1]


def _contained(inner, outer) -> float:
    """Share of ``inner``'s area that falls inside ``outer``."""
    ix = min(inner[2], outer[2]) - max(inner[0], outer[0])
    iy = min(inner[3], outer[3]) - max(inner[1], outer[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    area = (inner[2] - inner[0]) * (inner[3] - inner[1])
    return ix * iy / area if area > 0 else 0.0


def _read(
    bgr: np.ndarray,
    box: tuple[int, int, int, int],
    scales: tuple[int, ...],
    min_conf: float,
):
    """Yield (text, confidence, absolute bbox) for one crop at several scales."""
    x0, y0, x1, y1 = box
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return
    provider = get_ocr_provider()
    if not provider.available:
        return
    for scale in scales:
        big = cv2.resize(
            crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
        )
        for line in provider.recognize(big):
            text = line.text.strip()
            if not text or line.confidence < min_conf:
                continue
            bbox = (
                line.bbox[0] / scale + x0,
                line.bbox[1] / scale + y0,
                line.bbox[2] / scale + x0,
                line.bbox[3] / scale + y0,
            )
            yield text, float(line.confidence), bbox


def _digit_items(
    bgr: np.ndarray, items: list[TextItem], width: int, height: int
) -> list[TextItem]:
    """Read a missing index numeral from the strip left of its label."""
    added: list[TextItem] = []
    for item in items:
        if item.region != "right_column" or re.match(r"^\d", item.value):
            continue
        if len(re.findall(r"[A-Za-z]", item.value)) < 2:
            continue
        x0, y0, x1, y1 = (int(round(v)) for v in item.bbox)
        # Reach into the label so the detector sees a full line; a crop of the
        # numeral alone is too small for the detector to find.
        box = (
            max(0, x0 - 13),
            max(0, y0 - 12),
            min(width, x0 + 75),
            min(height, y1 + 12),
        )
        best: tuple[str, float, tuple[float, float, float, float]] | None = None
        for text, conf, bbox in _read(bgr, box, DIGIT_SCALES, DIGIT_CONF):
            if DIGIT_RE.fullmatch(text) and (best is None or conf > best[1]):
                best = (text, conf, bbox)
        if best is None:
            continue
        text, conf, bbox = best
        # The numeral is often hidden inside a short misread token (`BB` for
        # `06`). Replacing that token with a new item would put two boxes on
        # the same glyphs, so record the digit as the row's alternative line.
        if _contained(bbox, item.bbox) > 0.6:
            match = re.match(r"^(\S+)(.*)$", item.value)
            if match and len(match.group(1)) <= 3:
                item.maybe = f"{text}{match.group(2)}"
                item.uncertain = True
                logger.debug(
                    "row digit %r @ %.2f replaces %r in alternative",
                    text, conf, match.group(1),
                )
                continue
        logger.debug("row digit %r @ %.2f for %r", text, conf, item.value)
        added.append(
            TextItem(
                value=text,
                bbox=bbox,
                confidence=conf,
                region="right_column",
                uncertain=True,
            )
        )
    return added


def _near_alternative(value: str, candidate: str):
    """Best (known token, re-read token) pair that differs by a small edit."""
    best = None
    for known in TOKEN_RE.findall(value):
        for token in TOKEN_RE.findall(candidate):
            if token.lower() == known.lower():
                continue
            if abs(len(known) - len(token)) == 1:
                short, long = sorted((known.lower(), token.lower()), key=len)
                if (long.startswith(short) or long.endswith(short)) and not (
                    (long[0] if long.startswith(short) else long[-1]).isdigit()
                ):
                    continue
            ratio = SequenceMatcher(None, known.lower(), token.lower()).ratio()
            edits = _edit_distance(known.lower(), token.lower())
            if ratio >= LABEL_RATIO and edits <= LABEL_MAX_EDITS:
                score = (ratio, -edits)
                if best is None or score > best[0]:
                    best = (score, known, token)
    return best


def _apply_alternative(
    item: TextItem, known: str, token: str, text: str, confidence: float
) -> None:
    """Store a full alternate line, keeping any index-number alternative."""
    line = item.value.replace(known, token, 1)
    if item.maybe and re.fullmatch(r"\d{2}", item.maybe):
        line = re.sub(r"^\d{1,2}", item.maybe, line, count=1)
    item.maybe = line
    item.uncertain = True
    logger.debug(
        "row label alternative %r -> %r (re-read %r @ %.2f)",
        item.value, token, text, confidence,
    )


def _label_alternatives(
    bgr: np.ndarray, items: list[TextItem], width: int, height: int
) -> None:
    """Re-read each index row; keep a one-glyph-different label as an alternative."""
    for item in items:
        if item.region != "right_column" or not SUSPECT_LABEL_RE.search(item.value):
            continue
        x0, y0, x1, y1 = (int(round(v)) for v in item.bbox)
        box = (
            max(0, x0 - 10),
            max(0, y0 - 10),
            min(width, x1 + 10),
            min(height, y1 + 10),
        )
        best = None
        for text, conf, _ in _read(bgr, box, LABEL_SCALES, LABEL_CONF):
            near = _near_alternative(item.value, text)
            if near is None:
                continue
            score = (near[0][0], conf)
            if best is None or score > best[0]:
                best = (score, near[1], near[2], text, conf)
        if best is not None:
            _apply_alternative(item, *best[1:])


def recover_rows(
    bgr: np.ndarray, items: list[TextItem], width: int, height: int
) -> list[TextItem]:
    """Recover index numerals and label alternatives from per-row re-reads.

    Returns new uncertain items for digits that were not in the primary read;
    label alternatives are written onto the items they qualify, so they stay
    attached to the evidence they describe.
    """
    added = _digit_items(bgr, items, width, height)
    _label_alternatives(bgr, items, width, height)
    return added
