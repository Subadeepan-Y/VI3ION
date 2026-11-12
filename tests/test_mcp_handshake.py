"""MCP handshake self-test: spawn the stdio server and exercise the protocol.

Covers the exact sequence a client (OpenCode) performs: initialize ->
notifications/initialized -> tools/list -> tools/call. This locks in the
handshake so embedded Vi3ion-MCP setups don't regress (a missing `initialized`
notification is a common failure mode).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
PYTHON = PROJECT / ".venv" / "Scripts" / "python.exe"


def _spawn():
    # Inherit the full environment (stripping it breaks Winsock/asyncio on
    # Windows) and only add the roots override.
    env = os.environ.copy()
    env["VI3ION_ALLOWED_ROOTS"] = f"{PROJECT};{PROJECT / 'data'}"
    return subprocess.Popen(
        [str(PYTHON), "-m", "vi3ion.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(PROJECT),
        env=env,
    )


def _call(proc, payload):
    proc.stdin.write((json.dumps(payload) + "\n").encode())
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line.decode(errors="replace"))


def test_mcp_handshake_and_tool_call():
    proc = _spawn()
    try:
        init = _call(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "vi3ion-test", "version": "1"},
            },
        })
        assert init.get("result", {}).get("serverInfo", {}).get("name") == "vi3ion"

        # The notification is required before further requests are accepted.
        proc.stdin.write((json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }) + "\n").encode())
        proc.stdin.flush()

        tools = _call(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        names = {t["name"] for t in tools["result"]["tools"]}
        assert {"inspect_image", "inspect_region", "verify_claim",
                "cross_check_text", "compare_regions", "query_evidence",
                "list_images", "remember_image", "diff_images"} <= names

        result = _call(proc, {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "inspect_image",
                "arguments": {
                    "path": str(PROJECT / "tests" / "fixtures" / "sample_ui.png"),
                    "detail": "compact",
                },
            },
        })
        content = result["result"]["content"][0]["text"]
        payload = json.loads(content)
        assert payload["ok"] is True
        assert payload["tool"] == "inspect_image"
        assert "1280x800" in payload["summary"]
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def test_mcp_works_with_or_without_initialized_notification():
    """The installed mcp SDK accepts requests even without the initialized
    notification; the handshake test above sends it for spec compliance.
    This locks in the observed behavior so an SDK bump that *adds* strictness
    is caught."""
    proc = _spawn()
    try:
        _call(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "vi3ion-test", "version": "1"},
            },
        })
        resp = _call(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        assert "result" in resp, resp
        assert resp["result"]["tools"]
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
