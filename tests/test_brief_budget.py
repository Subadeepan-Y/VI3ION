"""Token-budgeted briefs: local models need small, prioritised evidence."""

from __future__ import annotations

from pathlib import Path

from vi3ion.brief import make_brief

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ui.png"


def test_unbudgeted_brief_keeps_everything():
    result = make_brief(FIXTURE)
    assert result.budget_tokens == 0
    assert result.truncated is False
    assert result.tokens == len(result.text.split())
    assert "Dominant colour" in result.text
    assert "Note:" in result.text


def test_budgeted_brief_fits_the_budget():
    result = make_brief(FIXTURE, budget_tokens=120)
    assert result.budget_tokens == 120
    assert result.truncated is True
    assert result.tokens <= 120


def test_budget_keeps_ocr_text_first():
    result = make_brief(FIXTURE, budget_tokens=120)
    # OCR text has priority over colour/scene prose.
    assert "Settings" in result.text
    assert "Save" in result.text
    # Low-priority prose is dropped first.
    assert "Colour map" not in result.text
    assert "Scene evidence" not in result.text


def test_budget_zero_means_unlimited():
    result = make_brief(FIXTURE, budget_tokens=0)
    assert result.truncated is False
    assert result.tokens > 120
