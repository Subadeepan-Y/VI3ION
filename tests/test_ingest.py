"""Folder ingest: register a screenshot folder in the image memory."""

from __future__ import annotations

import json
from pathlib import Path

from vi3ion.cli import cmd_ingest
from vi3ion.config import get_settings


class _Args:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _workdir(name: str) -> Path:
    """A folder inside the allowed roots (the session data dir)."""
    folder = get_settings().data_dir / "ingest-tests" / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_ingest_registers_images(capsys):
    fixture = Path(__file__).parent / "fixtures" / "sample_ui.png"
    target = _workdir("shots")
    for stale in target.glob("*.png"):
        stale.unlink()
    (target / "a.png").write_bytes(fixture.read_bytes())
    (target / "b.png").write_bytes(fixture.read_bytes())

    code = cmd_ingest(
        _Args(path=str(target), recursive=False, label="run", limit=10, json=True)
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["count"] == 2
    ids = {entry["image_id"] for entry in payload["images"]}
    # Identical bytes deduplicate to one stored image.
    assert len(ids) == 1
    entry = payload["images"][0]
    assert entry["label"].startswith("run ")
    assert entry["text_count"] > 0


def test_ingest_missing_path_fails(tmp_path, capsys):
    code = cmd_ingest(
        _Args(path=str(tmp_path / "nope"), recursive=False, label=None, limit=10, json=True)
    )
    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_ingest_empty_folder(capsys):
    empty = _workdir("empty")
    for stale in empty.glob("*.png"):
        stale.unlink()
    code = cmd_ingest(
        _Args(path=str(empty), recursive=False, label=None, limit=10, json=False)
    )
    assert code == 0
    assert "no images found" in capsys.readouterr().out
