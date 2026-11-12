"""The MCP server must start from every documented entry point.

Regression guard for the "No module named 'agent_interface'" failure: the
server moved into the package, and the legacy path is kept as a shim.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def _handshake(module: str) -> dict:
    env = os.environ.copy()
    env["VI3ION_ALLOWED_ROOTS"] = str(PROJECT)
    payload = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "vi3ion-test", "version": "1"},
                },
            }
        )
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        + "\n"
    )
    proc = subprocess.run(
        [sys.executable, "-m", module],
        input=payload,
        capture_output=True,
        text=True,
        timeout=90,
        cwd=str(PROJECT),
        env=env,
    )
    assert proc.returncode == 0, f"{module} exited {proc.returncode}: {proc.stderr[-400:]}"
    tools = 0
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        message = json.loads(line)
        if message.get("id") == 2:
            tools = len((message.get("result") or {}).get("tools") or [])
    return {"tools": tools, "stderr": proc.stderr}


def test_current_entry_point_serves_tools():
    result = _handshake("vi3ion.mcp_server")
    assert result["tools"] >= 10


def test_legacy_entry_point_still_works():
    """Old launchers import agent_interface.mcp_server: it must not be gone."""
    result = _handshake("agent_interface.mcp_server")
    assert result["tools"] >= 10


def test_shim_exports_main():
    import agent_interface.mcp_server as legacy

    from vi3ion.mcp_server import main as current

    assert legacy.main is current
