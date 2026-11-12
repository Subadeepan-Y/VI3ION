"""Per-element colour measurement: ink on its local background."""

from __future__ import annotations

import numpy as np

from vi3ion.core.pixels.element_color import (
    color_suffix,
    contrast_ratio,
    measure_element,
)


def _canvas(width=300, height=100, bgr=(255, 255, 255)):
    return np.full((height, width, 3), bgr, dtype=np.uint8)


def test_light_text_on_dark_background():
    # navy background (BGR 57,35,26 = RGB #1a2339) with a white block
    img = _canvas(bgr=(57, 35, 26))
    img[40:60, 40:160] = (255, 255, 255)
    measured = measure_element(img, (40, 40, 160, 60))
    assert measured["ink_hex"].lower() in ("#f8f8f8", "#ffffff")
    assert measured["ink_name"] == "pale or white"
    assert measured["bg_hex"].lower() == "#1a2339"
    assert measured["contrast"] > 10


def test_dark_text_on_light_background():
    img = _canvas(bgr=(245, 245, 245))
    img[40:60, 40:160] = (30, 30, 30)
    measured = measure_element(img, (40, 40, 160, 60))
    assert measured["ink_name"] == "black"
    assert measured["bg_name"] == "pale or white"
    assert measured["contrast"] > 10


def test_uniform_area_reports_its_own_colour():
    # RGB #2b66e6 -> BGR 230,102,43
    img = _canvas(bgr=(230, 102, 43))
    measured = measure_element(img, (40, 40, 160, 60))
    assert measured["ink_name"] == "blue"
    assert measured["uniform"] is True


def test_contrast_ratio_bounds():
    assert contrast_ratio((255, 255, 255), (255, 255, 255)) == 1.0
    assert contrast_ratio((255, 255, 255), (0, 0, 0)) == 21.0
    value = contrast_ratio((18, 32, 64), (255, 255, 255))
    assert 1.0 < value <= 21.0


def test_color_suffix_is_unquoted_and_compact():
    colour = {
        "ink_hex": "#2b66e6",
        "bg_hex": "#ffffff",
        "contrast": 4.9,
    }
    full = color_suffix(colour)
    assert full == "ink:#2b66e6 on:#ffffff contrast:4.9"
    assert '"' not in full
    compact = color_suffix(colour, full=False)
    assert compact == "ink:#2b66e6"
    assert '"' not in compact


def test_color_suffix_empty_without_measurement():
    assert color_suffix({}) == ""
    assert color_suffix({"ink_hex": ""}) == ""
