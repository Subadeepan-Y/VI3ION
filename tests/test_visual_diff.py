"""Visual diff: pixel-level comparison of two screenshots."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from vi3ion.visual_diff import describe_visual, visual_diff


def _write(path: Path, image: Image.Image) -> str:
    image.save(path)
    return str(path)


def _base_image() -> Image.Image:
    image = Image.new("RGB", (200, 120), (250, 250, 250))
    for x in range(20, 80):
        for y in range(20, 40):
            image.putpixel((x, y), (20, 40, 120))
    return image


def test_identical_images_report_no_change(tmp_path):
    path = _write(tmp_path / "a.png", _base_image())
    result = visual_diff(path, path)
    assert result["available"] is True
    assert result["size_match"] is True
    assert result["changed_percent"] == 0.0
    assert result["changed_regions"] == []
    assert "identical" in describe_visual(result)


def test_colour_change_is_detected(tmp_path):
    old = _base_image()
    new = _base_image()
    for x in range(20, 80):
        for y in range(20, 40):
            new.putpixel((x, y), (200, 30, 30))
    older = _write(tmp_path / "old.png", old)
    newer = _write(tmp_path / "new.png", new)

    result = visual_diff(older, newer)
    assert result["changed_percent"] > 0.5
    assert result["changed_regions"]
    region = result["changed_regions"][0]
    assert region["position"] in ("top-left", "middle-left", "top-centre", "middle-centre")
    assert region["bbox"][2] > region["bbox"][0]


def test_different_size_is_handled(tmp_path):
    small = Image.new("RGB", (100, 60), (10, 10, 10))
    big = Image.new("RGB", (300, 180), (10, 10, 10))
    older = _write(tmp_path / "small.png", small)
    newer = _write(tmp_path / "big.png", big)
    result = visual_diff(older, newer)
    assert result["available"] is True
    assert result["size_match"] is False
    assert result["newer_size"] == [300, 180]


def test_missing_file_is_reported(tmp_path):
    path = _write(tmp_path / "a.png", _base_image())
    result = visual_diff(path, str(tmp_path / "nope.png"))
    assert result["available"] is False
    assert "unavailable" in describe_visual(result)
