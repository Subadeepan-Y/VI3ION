"""Brief fidelity: parsing rendered briefs and scoring them against truth."""

from __future__ import annotations

from vi3ion.evaluate import is_supported, parse_brief, review, similarity

BRIEF = (
    'Image 100x50 (shot.png). Dominant colour: #080808 (32%). '
    'Colour map: row 1, col 1: black, dark. '
    'Top bar: "HERO" @[10, 5, 40, 15]; "ABOUT" (uncertain) @[50, 5, 90, 15]. '
    'Left column: "00 + "PORTFOLIO"" (uncertain) @[1, 20, 30, 30]; '
    '"BUILT TO" (split from "BUILTTO") @[1, 32, 90, 44]. '
    'Composition: 2 tall pale columns split the frame. '
    'Shapes: a tall vertical column in the left, pale or white. '
    'Note: this brief describes visible text. It does not name objects; fine detail is not covered.'
)

EXPECTED = {
    "_meta": {"image": "shot.png"},
    "text": [
        {"value": "HERO", "region": "top_bar"},
        {"value": "ABOUT", "region": "top_bar"},
        {"value": "00", "region": "left_column"},
        {"value": "PORTFOLIO", "region": "left_column"},
        {"value": "BUILT TO", "region": "left_column"},
    ],
}


def test_parse_brief_reads_nested_quotes_and_regions():
    values = parse_brief(BRIEF)
    parsed = dict(values)
    assert parsed["HERO"] == "top_bar"
    assert parsed["ABOUT"] == "top_bar"
    assert parsed['00 + "PORTFOLIO"'] == "left_column"
    assert parsed["BUILT TO"] == "left_column"


def test_similarity_counts_containment_but_not_lost_prefix():
    assert similarity("00", '00 + "PORTFOLIO"') == 1.0
    # A label that lost its number is a near miss, not a match.
    assert similarity("02 GRADEIFY", "GRADEIFY") < 0.75
    assert similarity("BUILT TO", "BUILT TO") == 1.0


def test_review_credits_a_faithful_brief():
    report = review(BRIEF, EXPECTED)
    assert report.recall == 1.0
    assert report.precision == 1.0
    assert report.regions == 1.0
    assert report.matched_units == report.expected_units


def test_review_reports_missing_and_spurious_values():
    brief = 'Image 1x1. Left column: "PORTFOLIO" @[1, 2, 3, 4]; "ZEBRA" @[5, 6, 7, 8].'
    report = review(brief, EXPECTED)
    assert "HERO" in report.missing
    assert "ZEBRA" in report.spurious
    assert report.recall < 1.0 and report.precision < 1.0


def test_unsupported_fragments_are_flagged():
    assert is_supported("ZEBRA CROSSING", ["build what's missing."]) is False
    # A fragment of a longer true sentence is still real text.
    assert is_supported("KYOTO", ["35°00'N 135°46'E // KYOTO VOID"]) is True
    # A one-space OCR merge is close enough to count as the same text.
    assert is_supported("buildwhat's missing.", ["build what's missing."]) is True


def test_structure_checks_track_the_brief_sections():
    checks = review(BRIEF, EXPECTED).structure_checks
    assert checks["composition line"] is True
    assert checks["honesty note"] is True
    assert checks["colour map (12 cells)"] is False  # this brief only shows one cell
    assert checks["shape sentences"] is False  # one shape, the check wants three
