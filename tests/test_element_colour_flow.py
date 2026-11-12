"""Element colours reach the brief and the evidence store."""

from __future__ import annotations

from pathlib import Path

from vi3ion.brief import make_brief
from vi3ion.config import get_settings
from vi3ion.core.engine import Vi3ionEngine

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ui.png"


def test_brief_carries_element_colours():
    result = make_brief(FIXTURE)
    assert "ink:#" in result.text
    # Colours are unquoted: the fidelity scorer only reads quoted values.
    assert '"#' not in result.text
    # The blue Save button is measured as white ink on a blue surface.
    assert "ink:#f8f8f8" in result.text
    assert "on:#2563eb" in result.text


def test_brief_budget_still_respected():
    result = make_brief(FIXTURE, budget_tokens=120)
    assert result.tokens <= 120
    assert result.truncated is True


def test_engine_attaches_colour_attributes(sample_ui_id, engine: Vi3ionEngine):
    engine.inspect_image(image_id=sample_ui_id, detail="compact", force=True)
    response = engine.query_evidence(image_id=sample_ui_id, kind="text", limit=50)
    coloured = [
        item
        for item in response.evidence
        if (item.attributes or {}).get("ink_hex")
    ]
    assert coloured, "no text evidence carries a measured colour"
    attributes = coloured[0].attributes
    assert attributes["ink_hex"].startswith("#")
    assert len(attributes["ink_rgb"]) == 3
    assert isinstance(attributes["contrast"], (int, float))
    assert attributes["bg_hex"].startswith("#")


def test_element_colour_claim_uses_measured_ink(sample_ui_id, engine: Vi3ionEngine):
    engine.inspect_image(image_id=sample_ui_id, detail="compact", force=True)
    white = engine.verify_claim(
        image_id=sample_ui_id, claim="the text 'Settings' is white", agent="test"
    )
    assert white.data["status"] == "verified"

    black = engine.verify_claim(
        image_id=sample_ui_id, claim="the text 'Settings' is black", agent="test"
    )
    assert black.data["status"] == "contradicted"

    button = engine.verify_claim(
        image_id=sample_ui_id, claim="the Save button is blue", agent="test"
    )
    assert button.data["status"] == "verified"


def test_measured_colour_survives_a_fresh_analysis(sample_ui_id, engine: Vi3ionEngine):
    settings = get_settings()
    assert settings.data_dir.exists()
    response = engine.inspect_image(
        image_id=sample_ui_id, detail="full", force=True
    )
    texts = [item for item in response.evidence if item.kind.value == "text"]
    assert texts
    assert any((item.attributes or {}).get("ink_hex") for item in texts)
