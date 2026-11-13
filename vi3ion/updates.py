"""Update awareness for Vi3ion: report, never install.

Design rules (explicit, no surprises):

- ``check()`` reads two public registries (PyPI for the engine, npm for the
  OpenCode plugin) and caches the result in ``<data_dir>/update-check.json``
  for 24 hours. It does not hit the network on every command or request.
- It NEVER installs anything. It only reports installed vs latest and prints
  the exact command to run. Installing is the user's (or the harness
  permission prompt's) decision.
- Auto-update consent lives in ``<data_dir>/prefs.json``
  (``{"updates_auto": bool}``), default **off**. Even when enabled, an update
  still goes through the harness permission prompt before any install runs
  (see the OpenCode plugin's ``vi3ion_update`` tool).
- Everything is offline-safe: a network failure degrades to "unavailable"
  and never raises.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PYPI_JSON_URL = "https://pypi.org/pypi/vi3ion/json"
NPM_REGISTRY_URL = "https://registry.npmjs.org/@subadeepan_y%2fvi3ion-opencode"

CACHE_TTL_S = 5 * 60  # 5 minutes
USER_AGENT = "vi3ion/update-check"


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def parse_version(value: str) -> tuple[int, ...]:
    """Split '0.1.10' into a comparable numeric tuple (best effort)."""
    out: list[int] = []
    for part in str(value).strip().lstrip("vV").replace("-", ".").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


def is_newer(latest: str | None, installed: str | None) -> bool:
    if not latest or not installed:
        return False
    try:
        return parse_version(latest) > parse_version(installed)
    except Exception:  # noqa: BLE001
        return latest != installed


def installed_engine_version() -> str:
    try:
        from vi3ion import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


# ---------------------------------------------------------------------------
# Small persistent files (prefs + cache) inside the data dir
# ---------------------------------------------------------------------------

def prefs_path(settings) -> Path:
    return settings.data_dir / "prefs.json"


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:  # noqa: BLE001
        pass
    return default


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        pass


def read_prefs(settings) -> dict[str, Any]:
    return _read_json(prefs_path(settings), {})


def auto_update_enabled(settings) -> bool:
    return bool(read_prefs(settings).get("updates_auto", False))


def set_auto_update(settings, enabled: bool) -> dict[str, Any]:
    prefs = read_prefs(settings)
    prefs["updates_auto"] = bool(enabled)
    prefs["auto_set_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_json_atomic(prefs_path(settings), prefs)
    return prefs


def cache_path(settings) -> Path:
    return settings.data_dir / "update-check.json"


def read_cache(settings) -> dict[str, Any] | None:
    data = _read_json(cache_path(settings), {})
    if not data.get("checked_at"):
        return None
    return data


def write_cache(settings, data: dict[str, Any]) -> None:
    _write_json_atomic(cache_path(settings), data)


# ---------------------------------------------------------------------------
# Network reads (small, strict timeout, never raise)
# ---------------------------------------------------------------------------

def fetch_latest_json(url: str, timeout: float = 4.0) -> dict[str, Any] | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def latest_engine_from_pypi(timeout: float = 4.0) -> str | None:
    data = fetch_latest_json(PYPI_JSON_URL, timeout)
    if data:
        version = (data.get("info") or {}).get("version")
        if isinstance(version, str) and version.strip():
            return version.strip()
    return None


def latest_plugin_from_npm(timeout: float = 4.0) -> str | None:
    data = fetch_latest_json(NPM_REGISTRY_URL, timeout)
    if data:
        latest = (data.get("dist-tags") or {}).get("latest")
        if isinstance(latest, str) and latest.strip():
            return latest.strip()
    return None


# ---------------------------------------------------------------------------
# The check itself
# ---------------------------------------------------------------------------

def _fresh_enough(cached: dict[str, Any] | None) -> bool:
    if not cached:
        return False
    try:
        checked = float(cached.get("checked_at_epoch", 0))
    except Exception:  # noqa: BLE001
        return False
    return (time.time() - checked) < CACHE_TTL_S


def check(settings, force: bool = False, timeout: float = 4.0) -> dict[str, Any]:
    """Return the update report. Uses the 24h cache unless force=True.

    Never raises. The result dict (also cached) looks like::

        {
          "checked_at": "...",
          "checked_at_epoch": 123.0,
          "offline": false,
          "engine": {"installed": "0.1.0", "latest": "0.1.1",
                     "update_available": true,
                     "command": "pip install -U vi3ion"},
          "plugin": {"installed": "0.1.2", "latest": null,
                     "update_available": false,
                     "command": "npm i -D @subadeepan_y/vi3ion-opencode@latest"}
        }
    """
    cached = read_cache(settings)
    if not force and _fresh_enough(cached):
        return cached

    engine_installed = installed_engine_version()
    result: dict[str, Any] = {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checked_at_epoch": time.time(),
        "offline": False,
        "engine": {
            "installed": engine_installed,
            "latest": None,
            "update_available": False,
            "command": "pip install -U vi3ion",
        },
        "plugin": {
            "installed": (cached or {}).get("plugin", {}).get("installed"),
            "latest": None,
            "update_available": False,
            "command": "npm i -D @subadeepan_y/vi3ion-opencode@latest",
        },
    }

    engine_latest = latest_engine_from_pypi(timeout)
    plugin_latest = latest_plugin_from_npm(timeout)

    if engine_latest is None and plugin_latest is None:
        # Offline or both registries unreachable: keep any previously known
        # values so the report still shows the last observed state.
        result["offline"] = True
        if cached:
            for key in ("engine", "plugin"):
                for field in ("latest", "update_available"):
                    if cached.get(key, {}).get(field) is not None:
                        result[key][field] = cached[key][field]
        write_cache(settings, result)
        return result

    if engine_latest:
        result["engine"]["latest"] = engine_latest
        result["engine"]["update_available"] = is_newer(engine_latest, engine_installed)
    if plugin_latest:
        result["plugin"]["latest"] = plugin_latest
        installed_plugin = result["plugin"]["installed"]
        result["plugin"]["update_available"] = is_newer(plugin_latest, installed_plugin)

    write_cache(settings, result)
    return result


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

def table_text(result: dict[str, Any]) -> str:
    lines = []
    for key, label, fallback in (
        ("engine", "engine (pip)", "pip install -U vi3ion"),
        ("plugin", "opencode plugin (npm)", "npm i -D @subadeepan_y/vi3ion-opencode@latest"),
    ):
        entry = result.get(key) or {}
        installed = entry.get("installed") or "unknown"
        latest = entry.get("latest") or "?"
        if entry.get("update_available"):
            lines.append(f"{label:<22} {installed}  ->  {latest}   update: {entry.get('command') or fallback}")
        elif installed == "unknown" and entry.get("latest"):
            # The plugin's installed version is not known here (the OpenCode
            # plugin writes it into the cache). Still print the command hint.
            lines.append(f"{label:<22} {installed}  (latest {latest})   update: {entry.get('command') or fallback}")
        else:
            lines.append(f"{label:<22} {installed}  (latest {latest})")
    if result.get("offline"):
        lines.append("update check: offline (showing last known state)")
    return "\n".join(lines)
