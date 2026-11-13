"""Text-only brief: merged-word splitting, colour map, tall column detection."""

from __future__ import annotations

import cv2
import numpy as np

from vi3ion.composition import colour_regions, compose_summary, containment_note
from vi3ion.describe_shapes import color_map_grid, describe_scene, describe_shapes
from vi3ion.text_merge import TextItem, join_same_row, split_merged_words


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


def _make_sections(items: list[TextItem], region: str = "centre") -> dict[str, list[TextItem]]:
    sections = {r: [] for r in ["top_bar", "left_column", "centre", "right_column", "bottom_bar"]}
    sections[region] = items
    return sections


def test_vertical_gutter_strip_remains_isolated_from_adjacent_code_line():
    """A vertical line-number gutter (aspect ratio h > 1.8 * w and h > 25) must remain isolated rather than merging horizontally into adjacent code lines."""
    # Gutter strip: width=18, height=120 -> aspect ratio h/w = 6.67 > 1.8, h=120 > 25
    gutter = item("1\n2\n3\n4\n5", (10, 50, 28, 170))
    # Code line right next to it with horizontal gap = 4px (< max(h, 12))
    code_line = item("def process_image(img):", (32, 50, 220, 68))

    sections = _make_sections([gutter, code_line])
    result = join_same_row(sections)["centre"]

    values = [i.value for i in result]
    assert len(result) == 2
    assert "1\n2\n3\n4\n5" in values
    assert "def process_image(img):" in values


def test_vertical_gutter_spanning_multiple_code_lines():
    """A line-number gutter strip spanning multiple rows must not merge into any adjacent code lines."""
    gutter = item("10\n11\n12", (10, 100, 26, 190))  # w=16, h=90 -> ratio=5.625 > 1.8, h > 25
    line1 = item("x = 42", (30, 100, 90, 120))
    line2 = item("y = x * 2", (30, 135, 110, 155))
    line3 = item("return y", (30, 170, 105, 190))

    sections = _make_sections([gutter, line1, line2, line3])
    result = join_same_row(sections)["centre"]

    values = [i.value for i in result]
    assert len(result) == 4
    assert values == ["10\n11\n12", "x = 42", "y = x * 2", "return y"]


def test_multiple_vertical_gutters_remain_isolated():
    """Multiple tall strips (e.g. diff gutter and line-number gutter) each remain isolated in separate rows."""
    diff_marker = item("+ + +", (5, 50, 15, 150))   # w=10, h=100 -> ratio=10.0 > 1.8
    line_nums = item("1 2 3", (20, 50, 35, 150))     # w=15, h=100 -> ratio=6.67 > 1.8
    code = item("added_function()", (40, 50, 160, 70))

    sections = _make_sections([diff_marker, line_nums, code])
    result = join_same_row(sections)["centre"]

    assert len(result) == 3
    values = [i.value for i in result]
    assert "+ + +" in values
    assert "1 2 3" in values
    assert "added_function()" in values


def test_narrow_item_below_height_threshold_merges_normally():
    """An item with h > 1.8 * w but h <= 25 px is not isolated by the gutter rule and can merge."""
    # w=8, h=16 -> ratio=2.0 > 1.8, but h=16 <= 25
    part1 = item("I", (10, 50, 18, 66))
    part2 = item("O", (22, 50, 34, 66))  # gap = 4px < max(16, 12)

    sections = _make_sections([part1, part2])
    result = join_same_row(sections)["centre"]

    assert len(result) == 1
    assert result[0].value == "I O"


def test_height_incompatibility_prevents_row_collapse():
    """Items with vastly different heights (ratio min/max < 0.4) do not collapse into the same row."""
    # Large header: h=80 (y: 100 to 180)
    title = item("SECTION HEADER", (20, 100, 200, 180))
    # Small label/badge overlapping vertically: h=16 (y: 110 to 126), gap=6px
    # Height ratio: 16 / 80 = 0.20 < 0.4
    badge = item("NEW", (206, 110, 240, 126))

    sections = _make_sections([title, badge])
    result = join_same_row(sections)["centre"]

    # Must not collapse into a single merged row "SECTION HEADER NEW"
    assert len(result) == 2
    values = [i.value for i in result]
    assert "SECTION HEADER" in values
    assert "NEW" in values


def test_height_compatibility_boundary_ratio():
    """Height ratio check: items below 0.4 ratio stay separate, items at or above 0.4 merge."""
    # Base item: h=50 (y: 100 to 150)
    base = item("BASE", (10, 100, 60, 150))
    # Below threshold: h=18 -> 18/50 = 0.36 < 0.4. Vertical overlap: 18px. Gap: 5px
    below = item("BELOW", (65, 110, 120, 128))

    res_below = join_same_row(_make_sections([base, below]))["centre"]
    assert len(res_below) == 2
    assert [i.value for i in res_below] == ["BASE", "BELOW"]

    # Compatible item: h=25 -> 25/50 = 0.50 >= 0.4. Vertical overlap: 25px. Gap: 5px
    compat_base = item("BASE", (10, 100, 60, 150))
    compat = item("COMPAT", (65, 110, 130, 135))
    res_compat = join_same_row(_make_sections([compat_base, compat]))["centre"]
    assert len(res_compat) == 1
    assert res_compat[0].value == "BASE COMPAT"


def test_superscript_or_tiny_note_does_not_collapse_into_heading():
    """Superscript / tiny annotation (h=10) next to large heading (h=40) does not collapse into the same row."""
    # Heading: h=40 (y: 200 to 240)
    heading = item("HEADING", (50, 200, 150, 240))
    # Tiny superscript: h=10 (y: 200 to 210), gap=4px, ratio = 10/40 = 0.25 < 0.4
    superscript = item("1", (154, 200, 164, 210))

    sections = _make_sections([heading, superscript])
    result = join_same_row(sections)["centre"]

    assert len(result) == 2
    assert [i.value for i in result] == ["HEADING", "1"]


def test_same_height_items_on_row_merge_properly():
    """Regression check: items with compatible heights and overlapping y merge horizontally as expected."""
    word1 = item("Hello", (10, 100, 60, 120))  # h=20
    word2 = item("World", (68, 100, 120, 120))  # h=20, gap=8px < max(20, 12)

    sections = _make_sections([word1, word2])
    result = join_same_row(sections)["centre"]

    assert len(result) == 1
    assert result[0].value == "Hello World"
    assert result[0].bbox == (10.0, 100.0, 120.0, 120.0)

