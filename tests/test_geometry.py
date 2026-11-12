"""Geometry: shape detection on synthetic images (no OCR involved)."""

from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image


def _render(shape_fn) -> bytes:
    canvas = np.full((300, 400, 3), 250, dtype=np.uint8)  # light background
    shape_fn(canvas)
    buffer = io.BytesIO()
    Image.fromarray(canvas).save(buffer, format="PNG")
    return buffer.getvalue()


def test_detects_rectangle(engine):
    def draw(canvas):
        cv2.rectangle(canvas, (50, 50), (250, 150), (20, 20, 20), thickness=-1)

    record, _ = engine.ingest_bytes(_render(draw), filename="rect.png")
    response = engine.inspect_image(image_id=record["image_id"], tasks=["detect_layout"], detail="full")

    rectangles = [
        e for e in response.evidence if e.kind.value == "shape" and "rectangle" in e.label.lower()
    ]
    assert rectangles, f"no rectangle detected; shapes={[e.label for e in response.evidence]}"
    # Closest match to the drawn box.
    best = min(rectangles, key=lambda e: abs(e.bbox.x0 - 50) + abs(e.bbox.y0 - 50))
    assert abs(best.bbox.x0 - 50) <= 8
    assert abs(best.bbox.y0 - 50) <= 8
    assert abs(best.bbox.x1 - 250) <= 8
    assert abs(best.bbox.y1 - 150) <= 8


def test_filters_tiny_shapes(engine):
    def draw(canvas):
        # 4x4 rectangle is below the 6px minimum dimension and must be filtered.
        cv2.rectangle(canvas, (100, 100), (104, 104), (0, 0, 0), thickness=-1)
        cv2.rectangle(canvas, (200, 100), (300, 170), (0, 0, 0), thickness=-1)

    record, _ = engine.ingest_bytes(_render(draw), filename="tiny.png")
    response = engine.inspect_image(image_id=record["image_id"], tasks=["detect_layout"], detail="full")

    shapes = [e for e in response.evidence if e.kind.value == "shape"]
    big_boxes = [e.bbox for e in shapes if e.bbox and e.bbox.width >= 6 and e.bbox.height >= 6]
    small_boxes = [e.bbox for e in shapes if e.bbox and e.bbox.width < 6 and e.bbox.height < 6]
    assert small_boxes == []
    assert any(abs(box.width - 100) <= 8 for box in big_boxes)


def test_minimal_geometry_module_imports():
    from vi3ion.core.geometry import analyze_geometry  # noqa: F401
    from vi3ion.core.geometry.shapes import detect_shapes  # noqa: F401
    from vi3ion.core.geometry.contours import extract_contours  # noqa: F401
