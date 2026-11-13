"""Update-check tests: cache TTL, offline safety, version compare, CLI surfaces.

All tests are offline: network reads are monkeypatched, so nothing here ever
touches PyPI or npm.
"""

from __future__ import annotations

import json
import time

import pytest

from vi3ion import cli
from vi3ion.updates import (
    CACHE_TTL_S,
    auto_update_enabled,
    cache_path,
    check,
    is_newer,
    parse_version,
    read_cache,
    set_auto_update,
    table_text,
)


@pytest.fixture
def fake_registries(monkeypatch):
    """Point the update check at fake latest versions."""

    def fake_engine(timeout=4.0):
        return "0.1.3"  # newer than the installed engine (0.1.2)

    def fake_plugin(timeout=4.0):
        return "0.1.5"  # newer than anything installed

    monkeypatch.setattr("vi3ion.updates.latest_engine_from_pypi", fake_engine)
    monkeypatch.setattr("vi3ion.updates.latest_plugin_from_npm", fake_plugin)


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def test_parse_version_sortable():
    assert parse_version("0.1.10") > parse_version("0.1.9")
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("0.1.0-rc1") == (0, 1, 0, 1)


def test_is_newer():
    assert is_newer("0.1.2", "0.1.1") is True
    assert is_newer("0.1.1", "0.1.2") is False
    assert is_newer("0.1.1", "0.1.1") is False
    assert is_newer(None, "0.1.0") is False
    assert is_newer("0.1.1", None) is False


# ---------------------------------------------------------------------------
# check() behaviour
# ---------------------------------------------------------------------------

def test_check_reports_updates(tmp_path, monkeypatch, fake_registries):
    class S:
        data_dir = tmp_path

    result = check(S(), force=True)
    assert result["engine"]["update_available"] is True
    assert result["engine"]["latest"] == "0.1.3"
    assert result["plugin"]["latest"] == "0.1.5"
    assert result["offline"] is False
    # The report is cached on disk.
    assert cache_path(S()).exists()


def test_check_uses_cache_without_refetch(tmp_path, monkeypatch, fake_registries):
    class S:
        data_dir = tmp_path

    calls = {"n": 0}
    real_engine = lambda timeout=4.0: calls.__setitem__("n", calls["n"] + 1) or "0.1.3"  # noqa: E731
    monkeypatch.setattr("vi3ion.updates.latest_engine_from_pypi", real_engine)

    check(S(), force=True)
    assert calls["n"] == 1
    # Second call within TTL must not hit the network again.
    check(S())
    check(S())
    assert calls["n"] == 1


def test_check_cache_expires(tmp_path, monkeypatch, fake_registries):
    class S:
        data_dir = tmp_path

    calls = {"n": 0}
    real_engine = lambda timeout=4.0: calls.__setitem__("n", calls["n"] + 1) or "0.1.3"  # noqa: E731
    monkeypatch.setattr("vi3ion.updates.latest_engine_from_pypi", real_engine)

    check(S(), force=True)
    # Rewind the cached timestamp beyond the TTL.
    cached = read_cache(S())
    cached["checked_at_epoch"] = time.time() - CACHE_TTL_S - 10
    cache_path(S()).write_text(json.dumps(cached), encoding="utf-8")

    check(S())
    assert calls["n"] == 2


def test_check_offline_keeps_last_known(tmp_path, monkeypatch):
    class S:
        data_dir = tmp_path

    # First run online.
    monkeypatch.setattr(
        "vi3ion.updates.latest_engine_from_pypi",
        lambda timeout=4.0: "0.1.3",
    )
    monkeypatch.setattr(
        "vi3ion.updates.latest_plugin_from_npm",
        lambda timeout=4.0: "0.1.5",
    )
    check(S(), force=True)

    # Second run: both registries unreachable.
    monkeypatch.setattr(
        "vi3ion.updates.latest_engine_from_pypi",
        lambda timeout=4.0: None,
    )
    monkeypatch.setattr(
        "vi3ion.updates.latest_plugin_from_npm",
        lambda timeout=4.0: None,
    )
    result = check(S(), force=True)
    assert result["offline"] is True
    assert result["engine"]["latest"] == "0.1.3"
    assert result["engine"]["update_available"] is True


def test_table_text_includes_both_artifacts(tmp_path, fake_registries):
    class S:
        data_dir = tmp_path

    result = check(S(), force=True)
    text = table_text(result)
    assert "engine (pip)" in text
    assert "opencode plugin (npm)" in text
    assert "pip install -U vi3ion" in text
    assert "npm i -D @subadeepan_y/vi3ion-opencode@latest" in text


# ---------------------------------------------------------------------------
# Auto-update consent
# ---------------------------------------------------------------------------

def test_auto_flag_defaults_off(tmp_path):
    class S:
        data_dir = tmp_path

    assert auto_update_enabled(S()) is False


def test_auto_flag_toggle(tmp_path):
    class S:
        data_dir = tmp_path

    set_auto_update(S(), True)
    assert auto_update_enabled(S()) is True
    set_auto_update(S(), False)
    assert auto_update_enabled(S()) is False


def test_auto_flag_persists_in_prefs_file(tmp_path):
    class S:
        data_dir = tmp_path

    set_auto_update(S(), True)
    prefs = json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8"))
    assert prefs["updates_auto"] is True


# ---------------------------------------------------------------------------
# CLI surfaces
# ---------------------------------------------------------------------------

def test_cli_version_reports(tmp_path, monkeypatch, capsys, fake_registries):
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    rc = cli.main(["version", "--force"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "update check" in out
    assert "engine (pip)" in out
    assert "auto-updates: off" in out


def test_cli_updates_auto_on(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    rc = cli.main(["updates", "auto", "on"])
    assert rc == 0
    assert "auto-updates: on" in capsys.readouterr().out
    assert cli.main(["updates", "auto"]) == 0


def test_cli_doctor_reports_updates_line(tmp_path, monkeypatch, capsys, fake_registries):
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    # Prime the cache with a live check first.
    cli.main(["version", "--force"])
    rc = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "updates" in out
