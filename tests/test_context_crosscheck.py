"""End-to-end: user-message context cross-checked against code roots."""

from __future__ import annotations

import json
from pathlib import Path


def test_inspect_image_context_code_matches(tmp_path, monkeypatch):
    import vi3ion.config as config_mod
    from vi3ion.core.engine import Vi3ionEngine

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "settings.ts").write_text(
        'export const SAVE_BUTTON = "All changes saved";\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VI3ION_CODE_ROOTS", str(tmp_path))
    config_mod.get_settings.cache_clear()
    settings = config_mod.get_settings()

    img = (
        Path(__file__).resolve().parents[1]
        / "tests" / "fixtures" / "sample_ui.png"
    )
    engine = Vi3ionEngine(settings)
    response = engine.inspect_image(
        path=str(img),
        detail="compact",
        force=True,
        context='The user says the save button shows "All changes saved".',
    )
    payload = response.model_dump(mode="json")
    ctx = payload["data"]["analysis"]["context"]
    assert ctx["echo"] == 'The user says the save button shows "All changes saved".'
    assert ctx["terms"]
    assert ctx["code_matches"], "expected at least one code match"
    assert any(m["snippet"] == "All changes saved" for m in ctx["code_matches"])
