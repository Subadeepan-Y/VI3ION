"""Text-only brief: merged-word splitting, colour map, tall column detection."""

from __future__ import annotations

import cv2
import numpy as np

from vi3ion.composition import colour_regions, compose_summary, containment_note
from vi3ion.describe_shapes import color_map_grid, describe_scene, describe_shapes
from vi3ion.text_merge import TextItem, split_merged_words


def item(value: str, bbox, confidence: float = 0.9) -> TextItem:
    return TextItem(value=value, bbox=tuple(float(v) for v in bbox), confidence=confidence)


def headline_canvas() -> np.ndarray:
    """Dark canvas with two words rendered far enough apart to be separate."""
    image = np.zeros((160, 760, 3), dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(image, "BUILT", (20, 120), font, 3.2, (240, 240, 240), 9)
    cv2.putText(image, "TO", (600, 120), font, 3.2, (240, 240, 240), 9)
    return image


def test_split_merged_words_at_the_word_gap():
    image = headline_canvas()
    merged = item("BUILTTO", (20, 20, 755, 150))
    result = split_merged_words(image, [merged])
    assert result[0].value == "BUILT TO"
    assert result[0].bbox == merged.bbox


def test_split_skips_a_single_word():
    image = np.zeros((80, 260, 3), dtype=np.uint8)
    cv2.putText(image, "PORTFOLIO", (10, 62), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (240, 240, 240), 2)
    result = split_merged_words(image, [item("PORTFOLIO", (10, 20, 250, 70))])
    assert [i.value for i in result] == ["PORTFOLIO"]


def test_split_leaves_lowercase_and_narrow_boxes_alone():
    image = headline_canvas()
    items = [
        item("buildwhat's", (20, 20, 300, 60)),
        item("BUILTTO", (20, 20, 60, 150)),  # aspect too tall for a split
    ]
    assert [i.value for i in split_merged_words(image, items)] == [
        "buildwhat's", "BUILTTO",
    ]


def test_colour_map_is_row_major_twelve_cells():
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    image[:40, :40] = (240, 240, 245)  # first 4x3 cell: 120/3 rows by 160/4 cols
    grid = color_map_grid(image, cols=4, rows=3)
    assert len(grid) == 12
    assert grid[0] == "row 1, col 1: pale or white, bright"
    assert grid[1].startswith("row 1, col 2: black, dark")
    assert grid[-1].startswith("row 3, col 4: black, dark")


def test_tall_column_detected_and_described():
    image = np.zeros((400, 400, 3), dtype=np.uint8)
    image[10:390, 190:210] = (235, 238, 240)  # pale vertical pillar
    sentences = describe_shapes(image, [])
    assert any("tall vertical column" in s for s in sentences)
    assert any("pale or white" in s for s in sentences)


def scene_image() -> np.ndarray:
    """Dark frame: pale central structure, two columns, a red lower band."""
    image = np.zeros((600, 900, 3), dtype=np.uint8)
    image[40:560, 200:700] = (60, 60, 62)          # central structure
    image[0:600, 180:215] = (235, 238, 240)        # left column
    image[0:600, 660:695] = (235, 238, 240)        # right column
    image[430:600, 300:900] = (30, 30, 200)        # saturated lower band
    return image


def test_colour_region_found_as_band():
    regions = colour_regions(scene_image())
    assert regions, "expected at least one large colour area"
    largest = regions[0]
    assert largest.kind == "horizontal band"
    assert largest.share > 0.1


def test_composition_names_columns_and_text_side():
    image = scene_image()
    items = [item("LEFT SIDE", (20, 200, 120, 240)), item("LEFT TOO", (20, 260, 120, 300))]
    summary = compose_summary(image, [(180, 0, 215, 600), (660, 0, 695, 600)], items, colour_regions(image))
    assert "2 tall pale columns" in summary
    assert "largest colour area" in summary
    assert "text sits only in the left third" in summary


def test_containment_note_merges_repeats():
    outer = (0.0, 0.0, 800.0, 600.0)
    siblings = [
        (outer, "grey", "rectangular area"),
        ((10.0, 0.0, 60.0, 600.0), "pale or white", "column"),
        ((200.0, 0.0, 250.0, 600.0), "pale or white", "column"),
        ((300.0, 300.0, 380.0, 380.0), "red", "round shape"),
    ]
    note = containment_note(outer, siblings)
    assert "two pale or white columns" in note
    assert "a red round shape" in note
    assert note.count("column") == 1


def test_describe_scene_reports_composition_and_shapes():
    scene = describe_scene(scene_image(), [])
    assert scene.shapes
    assert "tall pale columns" in scene.composition
