"""Word-splitting and geometry-based index flagging."""

from __future__ import annotations

from vi3ion.footer_fix import _rebuild_dash_date
from vi3ion.index_sequence import _merge_full_line_alternative
from vi3ion.text_merge import TextItem
from vi3ion.word_split import _respect_run, _split_run, split_body_words


def item(value: str, bbox=(0, 0, 100, 20)) -> TextItem:
    return TextItem(value=value, bbox=bbox, confidence=0.7, region="right_column")


def test_body_words_split_preserves_punctuation_and_digits():
    out = split_body_words(None, [item("6SHIPPEDPRODUCTS")])
    assert out[0].value == "6 SHIPPED PRODUCTS"
    assert out[0].split_from == "6SHIPPEDPRODUCTS"
    assert out[0].uncertain


def test_body_words_leave_short_or_spaced_items_alone():
    raw = [item("No heavy third-party black boxes. Every")]
    assert [i.value for i in split_body_words(None, raw)] == [raw[0].value]


def test_split_run_handles_hyphen_compound():
    parts = _split_run("Noheavythird-partyblackboxes.Every")
    joined = " ".join(parts)
    assert "third-party" in joined
    assert "black boxes. Every" in joined


def test_respect_run_rebuilds_fused_alpha_runs():
    assert _respect_run("Fromvisual educationplatformstobrowser") == (
        "From visual education platforms to browser"
    )


def test_full_line_alternative_replaces_leading_digit_junk():
    row = item("84 DUEL DECK 雨極殿")
    _merge_full_line_alternative(row, 4)
    assert row.maybe == "04 DUEL DECK 雨極殿"
    assert row.uncertain


def test_dash_date_rebuild():
    items = [
        item("1811", (890, 920, 950, 934)),
        item("01", (965, 920, 985, 934)),
        item("2026", (1000, 920, 1040, 934)),
    ]
    rebuilt = _rebuild_dash_date(items)
    assert rebuilt is not None
    assert rebuilt.value == "1811 - 01 - 2026"
    assert rebuilt.uncertain
