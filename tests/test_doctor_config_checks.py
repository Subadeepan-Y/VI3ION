"""Doctor diagnostics for a misconfigured MCP registration.

OpenCode's MCP config uses ``environment``; the generic MCP client format uses
``env``. Using the wrong key silently drops every variable, which looks like
"Vi3ion cannot read my images".
"""

from __future__ import annotations

import json

from vi3ion.cli import _strip_jsonc


def test_strip_jsonc_handles_comments_and_trailing_commas():
    raw = """
    {
      // a line comment
      "mcp": {
        "vi3ion": {
          "type": "local",
          "command": ["python.exe", "-m", "vi3ion.mcp_server"],
        },
      },
    }
    """
    parsed = json.loads(_strip_jsonc(raw))
    assert parsed["mcp"]["vi3ion"]["command"][-1] == "vi3ion.mcp_server"


def test_strip_jsonc_keeps_urls_intact():
    raw = '{"baseURL": "http://127.0.0.1:11434/v1", "note": "// not a comment"}'
    parsed = json.loads(_strip_jsonc(raw))
    assert parsed["baseURL"] == "http://127.0.0.1:11434/v1"


def test_doctor_flags_the_wrong_env_key(tmp_path, monkeypatch, capsys):
    from vi3ion import cli

    config = tmp_path / "opencode.jsonc"
    config.write_text(
        json.dumps(
            {
                "mcp": {
                    "vi3ion": {
                        "type": "local",
                        "command": ["vi3ion-mcp"],
                        "env": {"VI3ION_DATA_DIR": "/tmp/vi3ion"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".config" / "opencode").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".config" / "opencode" / "opencode.jsonc").write_text(
        config.read_text(encoding="utf-8"), encoding="utf-8"
    )

    class Args:
        json = True

    cli.cmd_doctor(Args())
    payload = json.loads(capsys.readouterr().out)
    checks = {check["check"]: check for check in payload["checks"]}
    assert "mcp_env_key" in checks, payload["checks"]
    assert checks["mcp_env_key"]["ok"] is False
    assert "environment" in checks["mcp_env_key"]["detail"]


def _write_config(tmp_path, key: str, use_env: bool):
    entry = {"type": "local", "command": ["python.exe", "-m", "vi3ion.mcp_server"]}
    entry["env" if use_env else "environment"] = {"VI3ION_DATA_DIR": "/tmp/vi3ion"}
    (tmp_path / ".config" / "opencode").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".config" / "opencode" / "opencode.jsonc").write_text(
        json.dumps({"mcp": {key: entry}}), encoding="utf-8"
    )


def test_doctor_accepts_both_server_name_spellings(tmp_path, monkeypatch, capsys):
    """The MCP key may be 'vi3ion' or 'VI3ION' - both must be recognised."""
    from vi3ion import cli

    class Args:
        json = True

    for key in ("vi3ion", "VI3ION"):
        _write_config(tmp_path, key, use_env=False)
        monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
        cli.cmd_doctor(Args())
        payload = json.loads(capsys.readouterr().out)
        checks = {check["check"]: check for check in payload["checks"]}
        wiring = checks["editor_wiring"]
        # The test config has no plugin entry, so only the MCP half is checked.
        assert "mcp=yes" in wiring["detail"], f"{key}: MCP server not recognised ({wiring})"
        assert "mcp_env_key" not in checks, f"{key}: environment key flagged wrongly"
