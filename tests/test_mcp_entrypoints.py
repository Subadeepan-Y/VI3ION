"""The MCP server must start from every documented entry point.

Regression guard for the "No module named 'agent_interface'" failure: the
server moved into the package, and the legacy path is kept as a shim.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def _handshake(module: str, attempts: int = 3) -> dict:
    """Start the server and talk to it the way a client does.

    The responses are read line by line: waiting for the process to exit
    loses the tools/list answer on slow machines (macOS ARM starts the OCR
    engine lazily and the reply can arrive after the process is gone).
    """
    env = os.environ.copy()
    env["VI3ION_ALLOWED_ROOTS"] = str(PROJECT)
    messages = (
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
    last_error = ""
    for _ in range(attempts):
        proc = subprocess.Popen(
            [sys.executable, "-m", module],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(PROJECT),
            env=env,
        )
        tools = 0
        try:
            proc.stdin.write(messages)
            proc.stdin.flush()
            deadline = time.time() + 120
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("id") == 2:
                    tools = len((message.get("result") or {}).get("tools") or [])
                    break
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        finally:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()
        if tools:
            return {"tools": tools, "stderr": ""}
        time.sleep(2.0)
    raise AssertionError(f"{module} listed no tools after {attempts} attempts: {last_error}")


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
