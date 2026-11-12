"""Small images: OCR must still read the text and keep original coordinates."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from vi3ion.analyzer import analyze_image
from vi3ion.config import get_settings


def _small_ui(folder: Path) -> Path:
    path = folder / "small_ui.png"
    image = Image.new("RGB", (480, 260), (245, 246, 250))
    draw = ImageDraw.Draw(image)
    draw.text((30, 30), "Settings", fill=(20, 30, 60))
    draw.text((30, 150), "Save", fill=(20, 60, 160))
    image.save(path)
    return path


def test_small_image_is_upscaled_and_text_is_found():
    folder = get_settings().data_dir / "small-image-tests"
    folder.mkdir(parents=True, exist_ok=True)
    path = _small_ui(folder)

    result = analyze_image(path)
    texts = [item.value for items in result.sections.values() for item in items]
    assert any("Settings" in value for value in texts), texts

    # Coordinates must be in original pixels, not the upscaled canvas.
    boxes = [
        item.bbox for items in result.sections.values() for item in items if "Settings" in item.value
    ]
    assert boxes, "Settings box missing"
    x0, y0, x1, y1 = boxes[0]
    assert 0 <= x0 <= 60 and 0 <= y0 <= 60
    assert x1 <= 480 and y1 <= 260


def test_large_image_is_not_upscaled():
    fixture = Path(__file__).parent / "fixtures" / "sample_ui.png"
    result = analyze_image(fixture)
    texts = [item.value for items in result.sections.values() for item in items]
    assert any("Settings" in value for value in texts)
    boxes = [
        item.bbox for items in result.sections.values() for item in items if "Settings" in item.value
    ]
    assert boxes[0][0] < 60
