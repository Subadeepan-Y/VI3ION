"""Second-look OCR: a contrast pass for faint text and 2x re-reads of small-text
bands.

The primary pass runs once on the full-resolution image and loses two kinds of
text: low-contrast labels, and small dense rows where an index digit fuses with
its label. Both passes here only ever *add* readings — a line already covered
by the primary pass is never replaced — and everything they add is marked
uncertain, because a second read of the same pixels is weaker evidence.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np

from .core.ocr.providers import get_ocr_provider
from .text_merge import TextItem

logger = logging.getLogger("vi3ion.analyzer")

CONF_FLOOR = 0.30
CONF_RELOOK = 0.50
ALT_RATIO = 0.78

# Bands re-read at higher scale, as fractions of the frame: the right-hand
# index column and the three footer zones. A full-width footer strip fails
# detection, but each zone on its own is read reliably.
SMALL_TEXT_BANDS = (
    ("right column", (0.85, 0.25, 1.0, 0.75), 2),
    # The two-digit index gutter reads cleanly only when the crop excludes the
    # project names; wider crops fuse the digits into the label.
    ("index numbers", (0.88, 0.34, 0.92, 0.70), 2),
    ("footer left", (0.0, 0.85, 0.32, 1.0), 3),
    ("footer centre", (0.42, 0.90, 0.58, 1.0), 3),
    ("footer right", (0.72, 0.87, 1.0, 1.0), 2),
    ("footer right", (0.72, 0.87, 1.0, 1.0), 3),
)

CONTENT_RE = re.compile(r"[0-9A-Za-z\u3040-\u30ff\u3400-\u9fff]")
# A bracketed punctuation hint such as `[?]` is meaningful even with no letters.
BRACKET_HINT_RE = re.compile(r"^\[[^\w]{1,3}\]$")
# Any short bracket token, used to compare two readings of the same hint.
BRACKET_TOKEN_RE = re.compile(r"^\[[^\]]{1,5}\]$")


def contrast_copy(bgr: np.ndarray) -> np.ndarray:
    """Luminance-only contrast boost for the second OCR look."""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    boosted = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(lightness)
    return cv2.cvtColor(cv2.merge([boosted, a, b]), cv2.COLOR_LAB2BGR)


def box_overlap(a, b) -> float:
    """Intersection over union for two boxes."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _is_readable(text: str) -> bool:
    """Reject mojibake and punctuation-only reads."""
    if "\ufffd" in text:
        return False
    if BRACKET_HINT_RE.fullmatch(text):
        return True
    if len(CONTENT_RE.findall(text)) < 2:
        return False
    return True


def _content(text: str) -> str:
    return "".join(CONTENT_RE.findall(text)).lower()


def _token_spans(text: str, bbox) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Split a line into tokens with proportional, approximate boxes."""
    line_width = bbox[2] - bbox[0]
    length = max(1, len(text))
    spans = []
    for match in re.finditer(r"\S+", text):
        start, end = match.span()
        spans.append(
            (
                match.group(),
                (
                    bbox[0] + line_width * start / length,
                    bbox[1],
                    bbox[0] + line_width * end / length,
                    bbox[3],
                ),
            )
        )
    return spans


def _token_covered(token: str, token_bbox, items: list[TextItem]) -> bool:
    """True when a known item already carries this token at this place.

    Containment catches a fragment inside a longer known line; the similarity
    ratio catches the same word re-read with a dropped or doubled letter.
    """
    content = _content(token)
    if not content:
        # A bracketed punctuation hint (`[?]`) carries meaning even with no
        # letters, and is only covered by an item that actually contains it.
        if BRACKET_HINT_RE.fullmatch(token):
            return any(
                token in item.value and box_overlap(token_bbox, item.bbox) > 0.05
                for item in items
            )
        return True
    for item in items:
        other = _content(item.value)
        if not other or box_overlap(token_bbox, item.bbox) <= 0.05:
            continue
        if content in other or other in content:
            return True
        if SequenceMatcher(None, content, other).ratio() >= 0.7:
            return True
    return False


def _note_alternative(token: str, token_bbox, items: list[TextItem], tag: str) -> None:
    """Keep a near-miss re-read as an item's alternative instead of dropping it.

    Only digit-bearing tokens and bracketed hint tokens qualify: those are the
    places where a second look often sees the same glyphs differently (``[0-9]``
    against a primary ``[8-9]``), and where the brief would otherwise present
    one reading as if it were certain.
    """
    content = _content(token)
    if not content:
        return
    hint = BRACKET_TOKEN_RE.fullmatch(token)
    for item in items:
        if item.maybe or box_overlap(token_bbox, item.bbox) <= 0.05:
            continue
        for known in re.findall(r"\S+", item.value):
            other = _content(known)
            if not other or other == content:
                continue
            digitish = bool(
                re.search(r"\d", token) and re.search(r"\d", known)
            )
            same_hint = bool(
                hint and BRACKET_TOKEN_RE.fullmatch(known)
                and len(token) == len(known)
                and sum(a != b for a, b in zip(token, known)) <= 1
            )
            near = (
                digitish
                and SequenceMatcher(None, content, other).ratio() >= ALT_RATIO
                and abs(len(content) - len(other)) <= 2
            )
            if not (near or same_hint):
                continue
            item.maybe = item.value.replace(known, token, 1)
            item.uncertain = True
            logger.debug("%s notes alternative %r for %r", tag, token, item.value)
            return


def _new_items(bgr, known, offset, scale, path: Path, tag: str) -> list[TextItem]:
    provider = get_ocr_provider()
    if not provider.available:
        return []
    added: list[TextItem] = []
    for line in provider.recognize(bgr):
        text = line.text.strip()
        if not text or line.confidence < CONF_RELOOK or not _is_readable(text):
            continue
        x0, y0, x1, y1 = (float(v) for v in line.bbox)
        bbox = (x0 / scale + offset[0], y0 / scale + offset[1],
                x1 / scale + offset[0], y1 / scale + offset[1])
        known_now = known + added
        uncovered = [
            (token, token_bbox)
            for token, token_bbox in _token_spans(text, bbox)
            if not _token_covered(token, token_bbox, known_now)
        ]
        if not uncovered:
            continue
        for token, token_bbox in uncovered:
            _note_alternative(token, token_bbox, known_now, tag)
        overlaps = any(box_overlap(bbox, item.bbox) > 0.3 for item in known_now)
        if overlaps and len(uncovered) < 3:
            for token, token_bbox in uncovered:
                if not re.fullmatch(r"[A-Za-z]{3,}", token):
                    continue
                logger.debug("%s adds token %r @ %.2f %s", tag, token, line.confidence, path)
                added.append(
                    TextItem(
                        value=token,
                        bbox=token_bbox,
                        confidence=float(line.confidence),
                        uncertain=True,
                    )
                )
            continue
        logger.debug("%s adds %r @ %.2f %s", tag, text, line.confidence, path)
        added.append(
            TextItem(
                value=text,
                bbox=bbox,
                confidence=float(line.confidence),
                uncertain=True,
            )
        )
    return added


def contrast_items(bgr: np.ndarray, known: list[TextItem], path: Path) -> list[TextItem]:
    """OCR the contrast-stretched frame; keep only lines the primary pass missed."""
    return _new_items(contrast_copy(bgr), known, (0, 0), 1.0, path, "contrast")


def small_text_items(bgr: np.ndarray, known: list[TextItem], path: Path) -> list[TextItem]:
    """Re-read the small-text bands at 2x and keep lines not already covered."""
    height, width = bgr.shape[:2]
    added: list[TextItem] = []
    for name, (fx0, fy0, fx1, fy1), scale in SMALL_TEXT_BANDS:
        x0, y0 = int(fx0 * width), int(fy0 * height)
        x1, y1 = int(fx1 * width), int(fy1 * height)
        crop = bgr[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        big = cv2.resize(
            crop, None, fx=scale, fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )
        added.extend(
            _new_items(big, known + added, (x0, y0), scale, path, name)
        )
    return added
