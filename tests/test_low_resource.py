"""Low-resource mode: cheaper settings for small machines."""

from __future__ import annotations

from vi3ion.config import Settings


def test_low_resource_drops_the_japanese_model():
    assert Settings(low_resource=True).use_japan_model is False


def test_normal_mode_keeps_the_japanese_model():
    assert Settings(low_resource=False).use_japan_model is True


def test_explicit_request_wins():
    settings = Settings(low_resource=True, use_japan_model=True)
    assert settings.use_japan_model is True


def test_low_resource_caps_analysis_dimension():
    assert Settings(low_resource=True).analysis_max_dim <= 1280
