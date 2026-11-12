"""Prune: remembered images whose stored file vanished must be removed."""

from __future__ import annotations

from pathlib import Path

from vi3ion.config import get_settings
from vi3ion.core.engine import Vi3ionEngine


def _unique_png(folder: Path, name: str) -> Path:
    """A unique image so pruning never touches the shared fixture copy."""
    from PIL import Image

    path = folder / name
    image = Image.new("RGB", (24, 24), (17, 34, 51))
    image.save(path)
    return path


def test_prune_removes_images_without_file(engine: Vi3ionEngine):
    # Write inside the allowed roots (the session data dir).
    folder = get_settings().data_dir / "prune-tests"
    folder.mkdir(parents=True, exist_ok=True)
    fixture = _unique_png(folder, "shot.png")
    record, _ = engine.ingest_path(str(fixture))
    image_id = record["image_id"]
    engine.inspect_image(image_id=image_id, detail="compact")

    known = {item["image_id"] for item in engine.list_known_images(limit=100)}
    assert image_id in known

    # The stored copy is what the registry points at.
    stored = Path(engine.get_record(image_id)["original_path"])
    assert stored.exists()
    stored.unlink()
    pruned = engine.prune_missing()
    assert image_id in pruned

    known_after = {item["image_id"] for item in engine.list_known_images(limit=100)}
    assert image_id not in known_after


def test_prune_keeps_existing_files(engine: Vi3ionEngine, sample_ui_id):
    before = len(engine.list_known_images(limit=1000))
    engine.prune_missing()
    after = len(engine.list_known_images(limit=1000))
    assert after == before
