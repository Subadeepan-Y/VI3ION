"""Ingestion: validation, dedup, EXIF orientation, rejected input."""

from __future__ import annotations

import io
import struct
import zlib

import numpy as np
import pytest
from PIL import Image

from vi3ion.core.ingestion import IngestError


def _png_bytes(array: np.ndarray, fmt: str = "RGB") -> bytes:
    image = Image.fromarray(array.astype(np.uint8), fmt)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_small_png(width=64, height=48, color=(10, 20, 30)) -> bytes:
    array = np.zeros((height, width, 3), dtype=np.uint8)
    array[:, :] = color
    return _png_bytes(array)


def test_ingest_small_png(engine):
    record, deduplicated = engine.ingest_bytes(make_small_png(), filename="small.png")
    assert record["width"] == 64
    assert record["height"] == 48
    assert record["format"].lower() == "png"
    assert record["source"] == "upload"
    assert deduplicated is False


def test_ingest_dedup(engine):
    data = make_small_png()
    first, _ = engine.ingest_bytes(data, filename="a.png")
    second, deduplicated = engine.ingest_bytes(data, filename="b.png")
    assert second["image_id"] == first["image_id"]
    assert deduplicated is True


def test_reject_non_image(engine):
    with pytest.raises(IngestError):
        engine.ingest_bytes(b"not an image at all", filename="fake.png")


def test_reject_too_large(settings, engine):
    huge = b"\x00" * (settings.max_image_bytes + 1)
    with pytest.raises(IngestError):
        engine.ingest_bytes(huge, filename="huge.png")


def test_ingest_path_record(engine, sample_ui_bytes):
    # Copy into the data dir (allowed root) to test path ingestion.
    target = engine.settings.data_dir / "sample_ui.png"
    target.write_bytes(sample_ui_bytes)
    record, _ = engine.ingest_path(str(target))
    assert record["width"] == 1280
    assert record["height"] == 800


def test_ingest_path_outside_roots(engine):
    with pytest.raises(IngestError):
        engine.ingest_path("C:/Windows/System32/notepad.exe")
