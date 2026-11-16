"""Stress harness: sampling, failure containment and report shape."""

from __future__ import annotations

import json

import scripts.stress_images as stress


class _Result:
    text = 'Top bar: "OK" @[1, 2, 3, 4]. Shapes: a circle.'
    tokens = 12
    truncated = False


def test_analyse_returns_structured_row(tmp_path, monkeypatch):
    img = tmp_path / "a.png"
    img.write_bytes(b"not really a png")
    monkeypatch.setattr(stress, "make_brief", lambda path: _Result())
    row = stress.analyse(img)
    assert row["file"] == "a.png"
    assert row["has_text"] is True
    assert row["has_shapes"] is True
    assert row["error"] is None


def test_analyse_contains_bad_images(tmp_path, monkeypatch):
    img = tmp_path / "bad.png"
    img.write_bytes(b"x")

    def boom(path):
        raise RuntimeError("cannot read")

    monkeypatch.setattr(stress, "make_brief", boom)
    row = stress.analyse(img)
    assert "cannot read" in row["error"]


def test_main_writes_report(tmp_path, monkeypatch):
    folder = tmp_path / "shots"
    folder.mkdir()
    for name in ("a.png", "b.png", "c.png"):
        (folder / name).write_bytes(b"x")
    monkeypatch.setattr(stress, "make_brief", lambda path: _Result())
    out = tmp_path / "report.json"
    rc = stress.main([str(folder), "--sample", "1", "--out", str(out)])
    report = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0
    assert report["total_images"] == 3
    assert report["sample_size"] >= 1
    assert "failures" in report and "slowest" in report
