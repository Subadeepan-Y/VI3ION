"""Release gates used by CI.

1. The brief fidelity floor: `vi3ion score --all` must not fall below the
   recorded baseline. A change that quietly makes the perception worse fails
   the build instead of shipping.
2. A clean-install check: the built wheel must install into an empty venv and
   serve the MCP tools without any extra packages. This is the check that
   catches "imported an optional dependency at module level" bugs.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

FLOOR = 91.5
PROJECT = Path(__file__).resolve().parents[1]


def check_fidelity() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "vi3ion.cli", "score", "--all"],
        cwd=str(PROJECT),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    output = proc.stdout + proc.stderr
    if proc.returncode != 0:
        print("fidelity check failed to run:\n" + output[-2000:])
        return 1
    match = re.search(r"average fidelity across (\d+) images: ([0-9.]+)%", output)
    if not match:
        print("could not parse the fidelity score:\n" + output[-2000:])
        return 1
    count, average = int(match.group(1)), float(match.group(2))
    print(f"fidelity: {average}% across {count} image(s) (floor {FLOOR}%)")
    if average < FLOOR:
        print(f"FAIL: fidelity {average}% is below the {FLOOR}% floor")
        return 1
    print("PASS: fidelity floor")
    return 0


def check_clean_install(wheel: Path) -> int:
    """Install the wheel into an empty venv and make the MCP server respond."""
    import os
    import shutil
    import tempfile

    venv_dir = Path(tempfile.mkdtemp(prefix="vi3ion-clean-"))
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
            timeout=600,
        )
        python = venv_dir / ("Scripts" if os.name == "nt" else "bin") / (
            "python.exe" if os.name == "nt" else "python"
        )
        install = subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", str(wheel)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if install.returncode != 0:
            print("FAIL: clean install failed\n" + install.stdout[-1500:] + install.stderr[-1500:])
            return 1
        check = subprocess.run(
            [str(python), "-m", "vi3ion.cli", "mcp-check", "--json"],
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ, "VI3ION_DATA_DIR": str(venv_dir / "data")},
        )
        if check.returncode != 0:
            print("FAIL: the MCP server did not start from a clean install\n")
            print((check.stdout or "")[-1500:])
            print((check.stderr or "")[-1500:])
            return 1
        try:
            payload = json.loads(check.stdout)
        except json.JSONDecodeError:
            print("FAIL: unexpected mcp-check output\n" + check.stdout[-1500:])
            return 1
        attempts = payload.get("attempts") or []
        tools = max((int(a.get("tools") or 0) for a in attempts), default=0)
        print(f"clean install: MCP server started with {tools} tool(s)")
        if tools < 10:
            print("FAIL: the clean install served fewer tools than expected")
            return 1
        print("PASS: clean install")
        return 0
    finally:
        shutil.rmtree(venv_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fidelity", action="store_true")
    parser.add_argument("--clean-install", default=None, help="path to the built wheel")
    args = parser.parse_args()

    status = 0
    if args.fidelity:
        status |= check_fidelity()
    if args.clean_install:
        status |= check_clean_install(Path(args.clean_install))
    if not args.fidelity and not args.clean_install:
        parser.error("nothing to check: pass --fidelity and/or --clean-install")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
