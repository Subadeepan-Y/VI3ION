"""One-command release helper.

    python scripts/publish.py npm          # pack + publish the OpenCode plugin
    python scripts/publish.py pypi         # build + upload the wheel to PyPI
    python scripts/publish.py pypi --test  # upload to TestPyPI instead
    python scripts/publish.py check        # build + twine check, publish nothing

The npm path asks npm for a one-time code if your account requires 2FA. The
PyPI path needs TWINE_USERNAME/TWINE_PASSWORD (or TWINE_PASSWORD with
TWINE_USERNAME=__token__) in the environment, or a ~/.pypirc.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
PLUGIN = PROJECT / "plugins" / "opencode"
DIST = PROJECT / "dist"


def run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> int:
    print(f"\n$ {' '.join(command)}")
    merged = {**os.environ, **(env or {})}
    return subprocess.call(command, cwd=str(cwd or PROJECT), env=merged)


def build_python() -> int:
    if run([sys.executable, "-m", "build"]) != 0:
        return 1
    return run([sys.executable, "-m", "twine", "check", *[str(p) for p in DIST.glob("*")]])


def publish_npm() -> int:
    if shutil.which("npm") is None:
        print("npm is not on PATH")
        return 1
    if run(["npm", "pack", "--dry-run"], cwd=PLUGIN) != 0:
        return 1
    return run(["npm", "publish", "--access", "public"], cwd=PLUGIN)


def publish_pypi(test: bool) -> int:
    if build_python() != 0:
        return 1
    command = [sys.executable, "-m", "twine", "upload"]
    if test:
        command += ["--repository", "testpypi"]
    command += ["--skip-existing", *[str(p) for p in DIST.glob("*")]]
    return run(command)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=["npm", "pypi", "check"])
    parser.add_argument("--test", action="store_true", help="use TestPyPI")
    args = parser.parse_args()

    if args.target == "npm":
        return publish_npm()
    if args.target == "pypi":
        return publish_pypi(args.test)
    return build_python()


if __name__ == "__main__":
    raise SystemExit(main())
