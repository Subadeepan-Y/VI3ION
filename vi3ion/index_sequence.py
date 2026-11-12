"""Index-column reasoning: flag, never correct, a numbered list's OCR reads.

Three cues, none of which rewrite text:
1. Ordinal: five or more numbered rows ascending top to bottom form an index,
   so the row's position gives its expected number.
2. Gap: a suspicious token between valid neighbours with a single missing
   number is marked the same way.
3. Missing: a row with no digit at all is told which number its position
   implies, rather than silently presented as unnumbered.
"""

from __future__ import annotations

import logging
import re

import numpy as np

from .text_merge import TextItem

logger = logging.getLogger("vi3ion.analyzer")


def _index_model(
    entries: list[tuple[TextItem, int, float]]
) -> tuple[float, float] | None:
    """Fit (base_y, pitch) so a row's y gives its expected index number.

    A single OCR line often carries a whole index row (`84 DUEL DECK`), so
    counting rows and matching offsets is unreliable. Only values already
    below 10 are trusted as anchors; their spacing defines the pitch, and the
    fit is rejected when it disagrees with the column's typical row gap.
    """
    if len(entries) < 4:
        return None
    anchors = [(y, value) for _, value, y in entries if value < 10]
    if len(anchors) < 2:
        return None
    ys = np.array([y for y, _ in anchors], dtype=float)
    values = np.array([value for _, value in anchors], dtype=float)
    if float(ys.max() - ys.min()) <= 0:
        return None
    pitch, base_y = np.polyfit(values, ys, 1)
    if not np.isfinite(pitch) or pitch <= 0:
        return None
    all_ys = sorted(entry[2] for entry in entries)
    gaps = [b - a for a, b in zip(all_ys, all_ys[1:]) if b - a > 0]
    if not gaps:
        return None
    median_gap = float(np.median(gaps))
    if not 0.6 * median_gap <= pitch <= 1.6 * median_gap:
        return None
    residuals = np.abs(values - (ys - base_y) / pitch)
    if float(residuals.max()) > 0.34:
        return None
    return float(base_y), float(pitch)


def _merge_expected_number(item: TextItem, expected: int) -> None:
    """Set or refine the number inside an existing alternative line."""
    if item.maybe and re.match(r"^\d", item.maybe):
        item.maybe = re.sub(
            r"^\d{1,2}", f"{expected:02d}", item.maybe, count=1
        )
    elif not item.maybe:
        item.maybe = f"{expected:02d}"
    item.uncertain = True


def _flag_by_position(entries: list[tuple[TextItem, int, float]]) -> bool:
    """Ordinal cue: the row's position gives its expected index number."""
    model = _index_model(entries)
    if model is None:
        return False
    base_y, pitch = model
    for item, value, y in entries:
        expected = int(round((y - base_y) / pitch))
        if not 0 <= expected < 10 or expected == value:
            continue
        _merge_expected_number(item, expected)
        logger.debug(
            "flagged possible misread %r -> %s by index position",
            item.value, item.maybe,
        )
    return True


def _merge_full_line_alternative(item: TextItem, expected: int) -> None:
    """Keep the label text but replace its leading digit junk with the expected
    index number, as an alternative line."""
    rest = re.sub(r"^[^A-Za-z\u3040-\u30ff\u3400-\u9fff]+", "", item.value)
    rest = re.sub(r"\s+\d{1,2}\s*$", "", rest)
    if not rest:
        rest = re.sub(r"^[^\d]*\d{1,2}\s*", "", item.value)
    item.maybe = f"{expected:02d} {rest}".strip()
    item.uncertain = True


def _flag_by_geometry(
    entries: list[tuple[TextItem, int, float]], area: list[TextItem]
) -> bool:
    """Ordinal fallback: evenly spaced rows imply sequential index numbers.

    Used when the fitted anchors are unreliable (digit glyphs misread as other
    digits, e.g. 04 -> 84). The row order and pitch alone give the expected
    number; the reading is flagged, never replaced. Only the right-hand index
    column qualifies — bracket hints elsewhere (e.g. `[8-9] JUMP`) must not be
    renumbered.
    """
    if not area or area[0].region != "right_column":
        return False
    if len(entries) < 6:
        return False
    ordered = sorted(entries, key=lambda e: e[2])
    ys = [y for _, _, y in ordered]
    gaps = [b - a for a, b in zip(ys, ys[1:]) if b - a > 0]
    if not gaps:
        return False
    pitch = float(np.median(gaps))
    # The ledger starts at row 00 only when a read of 00 is present among the
    # entries; otherwise the first numeric row is row 01.
    start = 0 if any(value == 0 for _, value, _ in ordered) else 1
    base = ys[0] - start * pitch
    flagged = False
    for item, value, y in ordered:
        expected = int(round((y - base) / pitch))
        if not 0 <= expected < 10 or expected == value:
            continue
        _merge_full_line_alternative(item, expected)
        flagged = True
        logger.debug("flagged possible misread %r -> %s by row geometry", item.value, item.maybe)
    return flagged


def _flag_by_gap(entries: list[tuple[TextItem, int, float]]) -> None:
    """Gap cue: one missing number between two valid neighbours."""
    valid = sorted({value for _, value, _ in entries if value < 10})
    for item, value, y in entries:
        if value < 10:
            continue
        position = sum(1 for _, _, other_y in entries if other_y < y)
        index = min(position, len(valid))
        lo = valid[index - 1] if index > 0 else None
        hi = valid[index] if index < len(valid) else None
        if lo is not None and hi is not None and hi > lo + 1:
            hole = [d for d in range(lo + 1, hi) if d not in valid]
            if len(hole) == 1:
                _merge_expected_number(item, hole[0])
                logger.debug("flagged possible misread %r -> %s", item.value, item.maybe)
                continue
        item.uncertain = True
        logger.debug("uncertain sequence token %r in %s", item.value, item.region)


def _flag_missing_numbers(
    area: list[TextItem], entries: list[tuple[TextItem, int, float]]
) -> None:
    """Rows with no digit get the number their row position implies.

    The expected number comes from the fitted pitch, not from the values of
    the neighbouring rows, because those neighbours are often misreads
    themselves (a fused `84` row may really be row 04).
    """
    model = _index_model(entries)
    if model is None:
        return
    base_y, pitch = model
    taken = [entry[2] for entry in entries]
    for item in sorted(area, key=lambda i: (i.bbox[1], -len(i.value))):
        if item.missing or item.maybe or re.match(r"^\d", item.value):
            continue
        if len(re.findall(r"[A-Za-z]", item.value)) < 2:
            continue
        y0, y1 = item.bbox[1], item.bbox[3]
        height = max(1.0, y1 - y0)
        if any(abs(y - y0) < 0.8 * height for y in taken):
            continue  # this row already has a number
        expected = int(round((y0 - base_y) / pitch))
        if not 0 <= expected < 10:
            continue
        item.missing = f"{expected:02d}"
        item.uncertain = True
        taken.append(y0)
        logger.debug("row %r implies number %s", item.value, item.missing)


def sequence_correct(area: list[TextItem]) -> None:
    """Flag likely misreads in an ascending index column. Never correct OCR."""
    entries: list[tuple[TextItem, int, float]] = []
    leading_digits = re.compile(r"^[^\dA-Za-z\u3040-\u30ff\u3400-\u9fff]*(\d{1,2})")
    for item in area:
        match = leading_digits.match(item.value)
        if match:
            entries.append((item, int(match.group(1)), item.bbox[1]))
    if len(entries) < 2:
        return
    entries.sort(key=lambda entry: entry[2])
    if not _flag_by_position(entries):
        _flag_by_gap(entries)
        _flag_by_geometry(entries, area)
    _flag_missing_numbers(area, entries)
