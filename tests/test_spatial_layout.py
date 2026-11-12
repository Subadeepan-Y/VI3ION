"""Spatial layout table: region/box/relative-position rendering."""

from __future__ import annotations

from vi3ion.brief import _x_band, _y_band, spatial_layout
from vi3ion.text_merge import REGION_ORDER, TextItem


def _item(value, bbox):
    return TextItem(value=value, bbox=bbox, confidence=0.9, region="centre")


def test_bands():
    assert _x_band(10, 100) == "left"
    assert _x_band(30, 100) == "left-center"
    assert _x_band(60, 100) == "right-center"
    assert _x_band(90, 100) == "right"
    assert _y_band(10, 100) == "top"
    assert _y_band(50, 100) == "middle"
    assert _y_band(90, 100) == "bottom"


def test_spatial_layout_table_shape():
    sections = {r: [] for r in REGION_ORDER}
    sections["centre"] = [_item("Save", (10, 20, 40, 50))]
    sections["top_bar"] = [_item("Settings", (0, 0, 100, 10))]
    table = spatial_layout(sections, 100, 100)
    lines = table.splitlines()
    assert lines[0].startswith("| Region |")
    assert "Settings" in table
    assert "Save" in table
    assert "(10, 20, 40, 50)" in table
    assert "top-full-width" in table
    assert "middle-left-center" in table


def test_spatial_layout_escapes_pipes():
    sections = {r: [] for r in REGION_ORDER}
    sections["centre"] = [_item("a | b", (0, 0, 10, 10))]
    table = spatial_layout(sections, 100, 100)
    assert "a / b" in table
    assert "a | b" not in table
