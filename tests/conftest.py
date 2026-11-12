"""Shared fixtures. Settings point at a temp data dir before any vi3ion import."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

SESSION_TMP = Path(tempfile.mkdtemp(prefix="vi3ion-tests-"))
(SESSION_TMP / "data").mkdir(parents=True, exist_ok=True)
os.environ["VI3ION_DATA_DIR"] = str(SESSION_TMP / "data")
os.environ["VI3ION_ALLOWED_ROOTS"] = ";".join(
    [
        str(Path(__file__).resolve().parents[1]),  # project root (fixtures live here)
        str(SESSION_TMP / "data"),
    ]
)
os.environ["VI3ION_SEMANTIC_PROVIDER"] = "none"

from vi3ion.config import get_settings  # noqa: E402
from vi3ion.core.engine import Vi3ionEngine  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_UI = FIXTURES / "sample_ui.png"


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def engine(settings) -> Vi3ionEngine:
    return Vi3ionEngine(settings)


@pytest.fixture(scope="session")
def sample_ui_bytes() -> bytes:
    return SAMPLE_UI.read_bytes()


@pytest.fixture(scope="session")
def sample_ui_id(engine, sample_ui_bytes) -> str:
    record, deduplicated = engine.ingest_bytes(sample_ui_bytes, filename="sample_ui.png")
    return record["image_id"]
