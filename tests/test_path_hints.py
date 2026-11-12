"""Path-hint extraction from garbled OCR."""

from __future__ import annotations

from vi3ion.path_hints import (
    _compact_spaced_letters,
    _fix_drive_split,
    path_candidates,
)


def test_compact_spaced_letters():
    assert _compact_spaced_letters("o p e n c o d e") == "opencode"
    assert _compact_spaced_letters("C : \\ Users \\ ADMIN") == "C : \\ Users \\ ADMIN"
    assert _compact_spaced_letters("normal words stay") == "normal words stay"


def test_fix_drive_split():
    assert _fix_drive_split("C : \\Users") == "C:\\Users"


def test_path_candidates_finds_windows_path():
    ocr = [
        "C : \\ Users \\ ADMIN / o p e n c o d e j so n C : / Users v A D M IN . opencode . json",
        "The parameter is incorrect.",
    ]
    cands = path_candidates(ocr, limit=10)
    assert any("opencode" in c.lower() for c in cands), cands
    assert any(":" in c for c in cands), cands


def test_path_candidates_finds_dotted_file():
    ocr = ["config was read from opencode.json at startup"]
    cands = path_candidates(ocr)
    assert any(c.lower().endswith("opencode.json") for c in cands), cands


def test_path_candidates_dedupes_and_limits():
    ocr = ["a.json a.json b.json", "c.json"] * 20
    cands = path_candidates(ocr, limit=10)
    assert len(cands) <= 10
    assert len(set(cands)) == len(cands)


def test_dot_recovery_after_missing_dot():
    from vi3ion.path_hints import _extend_dotted

    assert "opencode.json" in _extend_dotted("opencodejson")
    assert _extend_dotted("app.tsx") == ["app.tsx"]
    assert _extend_dotted("repositories") == ["repositories"]
