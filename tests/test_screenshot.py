"""The screenshot MCP tool: local capture, graceful headless failure.

ImageGrab and the engine are stubbed — no screen is captured and no files are
written by these tests.
"""

from __future__ import annotations

import json

import pytest

from vi3ion import mcp_server


class _Response:
    def to_json(self, detail: str) -> str:
        return json.dumps({"ok": True, "image_id": "shot1", "detail": detail})


class _Loader:
    def ingest_bytes(self, data: bytes, filename=None, source=None):
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert filename == "screenshot.png"
        assert source == "screen"
        return {"image_id": "shot1"}, False


class _Engine:
    loader = _Loader()

    def inspect_image(self, **kwargs):
        assert kwargs["image_id"] == "shot1"
        assert kwargs["agent"] == "mcp"
        return _Response()


def test_screenshot_ingests_capture_and_returns_evidence(monkeypatch):
    from PIL import Image

    frame = Image.new("RGB", (8, 8), "white")
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda *a, **k: frame)
    monkeypatch.setattr(mcp_server, "engine", lambda: _Engine())

    result = json.loads(mcp_server.screenshot(detail="compact", context="what is this?"))
    assert result["ok"] is True
    assert result["image_id"] == "shot1"
    assert result["detail"] == "compact"


def test_screenshot_headless_fails_soft(monkeypatch):
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda *a, **k: None)
    result = json.loads(mcp_server.screenshot())
    assert result["ok"] is False
    assert "screen" in result["error"]


def test_screenshot_capture_exception_fails_soft(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no display")

    monkeypatch.setattr("PIL.ImageGrab.grab", boom)
    result = json.loads(mcp_server.screenshot())
    assert result["ok"] is False
    assert "no display" in result["error"]
