"""Step 1: brief reshaped — row pairing, uncertainty flags, omissions, spatial prose."""

from __future__ import annotations

import pytest

from vi3ion.core.summary import summarize
from vi3ion.schemas import BBox, Evidence, EvidenceKind, Provenance

W, H = 1919, 949


def text_item(
    label: str,
    *,
    bbox: list[float],
    confidence: float = 0.9,
    script: str = "latin",
    order: int = 0,
    scope: str = "image",
) -> Evidence:
    return Evidence(
        evidence_id=f"txt_{order}_{label[:8]}",
        image_id="img_test",
        kind=EvidenceKind.TEXT,
        label=label,
        bbox=BBox.from_any(bbox),
        confidence=confidence,
        attributes={"text": label, "script": script, "reading_order": order, "char_count": len(label)},
        provenance=Provenance(module="test", method="brief"),
        observed=True,
        scope=scope,
    )


def shapes(bbox=[40, 500, 120, 560]) -> list[Evidence]:
    return [
        Evidence(
            evidence_id=f"shp_1",
            image_id="img_test",
            kind=EvidenceKind.SHAPE,
            label="rectangle 1",
            bbox=BBox.from_any(bbox),
            confidence=0.8,
            attributes={"width_px": 80, "height_px": 60},
            provenance=Provenance(module="test", method="brief"),
            observed=True,
        )
    ]


RECORD = {"width": W, "height": H, "format": "PNG", "size_bytes": 1_000_000}


def test_pair_number_and_label_by_row():
    items = [
        text_item("84", bbox=[1714, 456, 1752, 470], order=1),
        text_item("DUEL DECK", bbox=[1754, 456, 1826, 470], order=2),
        text_item("HERO", bbox=[823, 43, 864, 60], order=3),
    ]
    summary = summarize(RECORD, items + shapes())
    assert '"84" (uncertain sequence; expected 00–09) "DUEL DECK" @[1754, 456, 1826, 470]' in summary
    assert 'Right column:' in summary


def test_sequence_correction_annotated_not_rewritten():
    # Right column carries a numbered list with a gap: 01,02,03,_ ,05..09.
    items = [
        text_item("01", bbox=[1700, 100, 1730, 114], order=1),
        text_item("02", bbox=[1700, 140, 1730, 154], order=2),
        text_item("03", bbox=[1700, 180, 1730, 194], order=3),
        text_item("84", bbox=[1700, 220, 1735, 234], order=4),
        text_item("LONELY LABEL", bbox=[1745, 220, 1830, 234], order=5),
        text_item("05", bbox=[1700, 260, 1730, 274], order=6),
        text_item("06", bbox=[1700, 300, 1730, 314], order=7),
        text_item("07", bbox=[1700, 340, 1730, 354], order=8),
        text_item("08", bbox=[1700, 380, 1730, 394], order=9),
        text_item("09", bbox=[1700, 420, 1730, 434], order=10),
    ]
    summary = summarize(RECORD, items + shapes())
    assert '"04" (corrected from "84", sequence inferred)' in summary
    # Never silently rewrite: raw "84" still visible in the unit.
    assert '"84"' in summary
    assert '"04"' in summary


def test_low_conf_cjk_and_short_mono_flagged():
    items = [
        text_item("天守", bbox=[1835, 528, 1873, 542], confidence=0.5, script="cjk", order=0),
        text_item("BB", bbox=[1703, 527, 1730, 542], confidence=0.4, script="latin", order=1),
        text_item("CLEAR", bbox=[100, 200, 200, 220], confidence=0.95, script="latin", order=2),
    ]
    summary = summarize(RECORD, items + shapes())
    assert "(uncertain)" in summary
    # Count flagged items: both should be flagged.
    assert summary.count("(uncertain)") >= 2


def test_omissions_reported_with_reasons_and_regions():
    low = text_item("STATUS", bbox=[100, 700, 200, 720], confidence=0.2, order=0)
    items = [low]
    for i in range(30):
        items.append(
            text_item(f"LINE{i:02d}", bbox=[100 + i, 300 + i, 200 + i, 320 + i], order=i + 1)
        )
    summary = summarize(RECORD, items + shapes())
    assert "Omitted from brief:" in summary
    assert "1 low-confidence (below 0.30)" in summary
    assert "truncated for length" in summary


def test_graph_statistics_absent_from_brief():
    scene = {"node_count": 74, "edge_count": 90, "rows": [[]], "columns": [[]]}
    summary = summarize(RECORD, [text_item("HERO", bbox=[823, 43, 864, 60])] + shapes(), scene=scene)
    assert "Layout graph" not in summary
    assert "74 nodes" not in summary


def test_spatial_names_used_not_coordinates_only():
    items = [
        text_item("HERO", bbox=[823, 43, 864, 60], order=0),          # top bar
        text_item("BUILTTO", bbox=[121, 231, 673, 325], order=1),     # left column
        text_item("SCROLL", bbox=[124, 900, 176, 913], order=2),      # bottom bar
    ]
    summary = summarize(RECORD, items + shapes())
    assert "Top bar:" in summary
    assert "Left column:" in summary
    assert "Bottom bar:" in summary
    # Boxes are retained inline for follow-up.
    assert "@[823, 43, 864, 60]" in summary


def test_no_low_conf_text_in_brief():
    low = text_item("GHOST", bbox=[300, 300, 400, 320], confidence=0.2, order=0)
    summary = summarize(RECORD, [low] + shapes())
    assert "GHOST" not in summary
    assert "Omitted from brief:" in summary
