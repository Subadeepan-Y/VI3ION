"""The `vi3ion skill` command must ship the skill with the package."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def test_skill_command_prints_the_skill():
    proc = subprocess.run(
        [sys.executable, "-m", "vi3ion.cli", "skill"],
        cwd=str(PROJECT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "VI3ION" in proc.stdout
    assert "inspect_image" in proc.stdout
    assert "verify_claim" in proc.stdout


def test_skill_file_is_packaged():
    import vi3ion

    skill = Path(vi3ion.__file__).resolve().parent / "skill" / "SKILL.md"
    assert skill.exists()
    assert skill.stat().st_size > 1000
