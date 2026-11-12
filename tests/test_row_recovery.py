"""Lower-case word fusion and per-row index recovery."""

from __future__ import annotations

from pathlib import Path

import cv2

from vi3ion.fused_words import split_lowercase_words
from vi3ion.index_sequence import _merge_expected_number
from vi3ion.relook import _note_alternative
from vi3ion.relook_rows import (
    _apply_alternative,
    _contained,
    _near_alternative,
)
from vi3ion.text_merge import TextItem

FIXTURES = Path(__file__).parent / "fixtures"


def item(value: str, bbox, confidence: float = 0.9, **kwargs) -> TextItem:
    return TextItem(
        value=value, bbox=tuple(float(v) for v in bbox),
        confidence=confidence, **kwargs,
    )


def test_lowercase_fusion_splits_at_the_ink_gap():
    image = cv2.imread(str(FIXTURES / "fused_body.png"))
    merged = item("buildwhat's missing.", (7, 6, 178, 29), 0.85)
    result = split_lowercase_words(image, [merged])
    assert result[0].value == "build what's missing."
    assert result[0].split_from == "buildwhat's missing."
    assert result[0].bbox == merged.bbox


def test_lowercase_fusion_leaves_a_clean_line_alone():
    image = cv2.imread(str(FIXTURES / "fused_body.png"))
    clean = item("build what's missing.", (7, 6, 178, 29), 0.85)
    assert [i.value for i in split_lowercase_words(image, [clean])] == [clean.value]


def test_label_alternative_accepts_one_glyph_misread():
    near = _near_alternative("89 8ANCTUM 内殿", "SANCTUM")
    assert near is not None
    _, known, token = near
    assert (known, token) == ("8ANCTUM", "SANCTUM")


def test_label_alternative_rejects_quote_glyph_insertion():
    assert _near_alternative('02 + "GRADEIFY"', "IGRADEIFY") is None


def test_label_alternative_keeps_the_index_number():
    row = item("89 8ANCTUM 内殿", (0, 0, 10, 10), 0.5, maybe="09")
    _apply_alternative(row, "8ANCTUM", "SANCTUM", "SANCTUM", 0.8)
    assert row.maybe == "09 SANCTUM 内殿"
    assert row.uncertain


def test_index_flag_refines_a_full_alternative_digit():
    row = item("89 8ANCTUM", (0, 0, 10, 10), 0.5, maybe="89 SANCTUM")
    _merge_expected_number(row, 9)
    assert row.maybe == "09 SANCTUM"


def test_digit_box_inside_label_is_a_replacement_not_a_new_row():
    assert _contained((1703, 527, 1718, 538), (1703, 527, 1873, 542)) > 0.6
    assert _contained((1690, 527, 1702, 538), (1703, 527, 1873, 542)) == 0.0


def test_bracket_conflict_becomes_an_alternative():
    row = item("[8-9]   JUMP", (100, 0, 200, 12), 0.77)
    _note_alternative("[0-9]", (100, 0, 130, 12), [row], "test")
    assert row.maybe == "[0-9]   JUMP"
    assert row.uncertain
