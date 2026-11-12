"""Verification engine: parser intents + verdicts against the sample UI."""

from __future__ import annotations

from vi3ion.core.verification import parse_claim


def test_parse_alignment():
    parsed = parse_claim("The Save button is aligned with the Cancel button")
    assert parsed.intent == "alignment"
    assert parsed.subject == "Save button"
    assert parsed.object == "Cancel button"


def test_parse_distance():
    parsed = parse_claim("The Save button is 10 pixels to the right of the Cancel button")
    assert parsed.intent == "distance"
    assert parsed.value == 10.0
    assert parsed.direction == "to the right of"


def test_parse_text_present():
    parsed = parse_claim('The image contains the text "All changes saved"')
    assert parsed.intent == "text_present"
    assert parsed.text == "All changes saved"


def test_parse_color():
    parsed = parse_claim("The header bar is navy")
    assert parsed.intent == "color"
    assert parsed.color == "navy"


def test_parse_dimensions():
    parsed = parse_claim("The image is 1280x800")
    assert parsed.intent == "dimensions"
    assert (parsed.width, parsed.height) == (1280, 800)


def test_parse_unsupported():
    parsed = parse_claim("the logo looks modern and trustworthy")
    assert parsed.intent == "unsupported"


def test_verify_alignment(sample_ui_id, engine):
    response = engine.verify_claim(
        image_id=sample_ui_id, claim="The Save button is aligned with the Cancel button"
    )
    assert response.verification is not None
    assert response.verification.status.value == "verified"
    assert response.verification.method == "geometry.alignment"
    assert response.verification.confidence >= 0.5


def test_verify_distance_contradicted(sample_ui_id, engine):
    response = engine.verify_claim(
        image_id=sample_ui_id,
        claim="The Save button is 10 pixels to the right of the Cancel button",
    )
    assert response.verification is not None
    assert response.verification.status.value == "contradicted"
    assert response.verification.measurements, "expected measured evidence"


def test_verify_text_present(sample_ui_id, engine):
    response = engine.verify_claim(
        image_id=sample_ui_id, claim='The image contains the text "All changes saved"'
    )
    assert response.verification is not None
    assert response.verification.status.value == "verified"


def test_verify_dimensions(sample_ui_id, engine):
    response = engine.verify_claim(
        image_id=sample_ui_id, claim="The image is 1280x800"
    )
    assert response.verification is not None
    assert response.verification.status.value == "verified"


def test_verify_unsupported_inconclusive(sample_ui_id, engine):
    response = engine.verify_claim(
        image_id=sample_ui_id, claim="the logo looks modern and trustworthy"
    )
    assert response.verification is not None
    assert response.verification.status.value == "inconclusive"
