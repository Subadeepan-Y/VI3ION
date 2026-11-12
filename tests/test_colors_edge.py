"""Palette edge cases: single-colour images used to crash the palette loop."""

from __future__ import annotations

import numpy as np

from vi3ion.core.pixels.colors import dominant_colors


def test_single_colour_image_returns_one_palette_entry():
    img = np.full((24, 24, 3), (51, 34, 17), dtype=np.uint8)
    palette = dominant_colors(img)
    assert len(palette) == 1
    assert palette[0]["share"] == 1.0
    assert palette[0]["rgb"] == [17, 34, 51]


def test_black_image_is_handled():
    img = np.zeros((8, 8, 3), dtype=np.uint8)
    palette = dominant_colors(img)
    assert palette[0]["hex"] == "#000000"


def test_multi_colour_image_still_clusters():
    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, (40, 40, 3)).astype(np.uint8)
    palette = dominant_colors(img)
    assert len(palette) > 1
    for entry in palette:
        assert len(entry["rgb"]) == 3
