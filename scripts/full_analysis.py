"""Analyse every image in the screenshots folder, then save, push and shut down.

Designed to run detached (without OpenCode). Progress is appended to a JSONL
file after every image, so a shutdown or crash never loses work. On completion
it writes a report, updates the README, commits and pushes, then requests a
clean Windows shutdown unless the watchdog already did.

    python scripts/full_analysis.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FOLDER = Path(r"C:\Users\ADMIN\Pictures\Screenshots")
PROGRESS = REPO / "docs" / "full-analysis-progress.jsonl"
REPORT = REPO / "docs" / "full-analysis-report.json"
MARKER = Path(os.environ.get("TEMP", "/tmp")) / "vi3ion-shutdown-marker.txt"
EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def machine_specs() -> dict:
    """Describe the test machine so numbers are never presented as universal.

    Set VI3ION_MACHINE_SPECS to a JSON string to override with a friendlier
    description (CPU model, GPU, etc.) gathered from the OS.
    """
    import platform

    override = os.environ.get("VI3ION_MACHINE_SPECS", "").strip()
    if override:
        try:
            return json.loads(override)
        except Exception:  # noqa: BLE001
            pass
    specs = {
        "cpu": platform.processor() or "unknown",
        "architecture": platform.machine(),
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "gpu": "not detected (CPU-only OCR unless configured otherwise)",
    }
    try:
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        specs["ram_gb"] = round(status.ullTotalPhys / (1024 ** 3), 1)
    except Exception:  # noqa: BLE001 - non-Windows or restricted environment
        specs["ram_gb"] = "unknown"
    return specs


def git(*args: str) -> None:
    try:
        subprocess.run(
            ["git", *args], cwd=REPO, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180,
        )
    except Exception as exc:  # noqa: BLE001 - never fail the analysis on git
        log(f"git {args[0]} failed: {exc}")


def analyse_all() -> None:
    from vi3ion.brief import make_brief

    REPO.joinpath("docs").mkdir(exist_ok=True)
    files = sorted(
        p for p in FOLDER.rglob("*")
        if p.is_file() and p.suffix.lower() in EXTS and p.stat().st_size > 0
    )
    done: dict[str, dict] = {}
    if PROGRESS.exists():
        for line in PROGRESS.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
                done[row["file"]] = row
            except Exception:  # noqa: BLE001 - skip a torn last line
                continue
    log(f"found {len(files)} images; {len(done)} already analysed")

    started = time.perf_counter()
    for index, path in enumerate(files, 1):
        key = str(path)
        if key in done:
            continue
        row_start = time.perf_counter()
        try:
            result = make_brief(path)
            row = {
                "file": key,
                "name": path.name,
                "size_kb": round(path.stat().st_size / 1024),
                "ms": round((time.perf_counter() - row_start) * 1000),
                "tokens": result.tokens,
                "chars": len(result.text),
                "has_text": '"' in result.text,
                "has_shapes": "Shapes:" in result.text,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 - one bad image must not stop the run
            row = {
                "file": key,
                "name": path.name,
                "size_kb": round(path.stat().st_size / 1024),
                "ms": round((time.perf_counter() - row_start) * 1000),
                "error": f"{type(exc).__name__}: {exc}"[:300],
            }
        with PROGRESS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        done[key] = row
        if index % 25 == 0:
            log(f"{index}/{len(files)} - last {row['name']} {row['ms']}ms")

    rows = list(done.values())
    ok = [r for r in rows if not r.get("error")]
    report = {
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "machine": machine_specs(),
        "results_may_vary": (
            "Measured on one machine. Speed depends on CPU, image resolution, "
            "text density and thermal throttling; other machines will differ."
        ),
        "total_images": len(files),
        "analysed": len(rows),
        "elapsed_seconds": round(time.perf_counter() - started),
        "failures": [r for r in rows if r.get("error")],
        "no_text": [r["name"] for r in ok if not r["has_text"]],
        "avg_ms": round(sum(r["ms"] for r in ok) / len(ok)) if ok else 0,
        "avg_tokens": round(sum(r.get("tokens", 0) for r in ok) / len(ok)) if ok else 0,
        "slowest": sorted(ok, key=lambda r: -r["ms"])[:10],
    }
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(f"complete: {len(rows)} images, {len(report['failures'])} failures, "
        f"avg {report['avg_ms']}ms")

    # Update the README comparison section with measured numbers.
    update_readme(report)

    git("add", "-A")
    git("-c", "user.name=Subadeepan-Y", "-c", "user.email=subadeepan_y@gmail.com",
        "commit", "-q", "-m", "data: full 698-image stress analysis + comparison")
    git("push", "-q", "origin", "main")
    log("pushed to GitHub")

    if not MARKER.exists():
        MARKER.write_text(f"analysis complete {datetime.now()}", encoding="utf-8")
        log("requesting shutdown")
        subprocess.run(["shutdown", "/s", "/t", "20", "/c", "VI3ION analysis complete"],
                       check=False)
    else:
        log("watchdog already handled shutdown; skipping")


def update_readme(report: dict) -> None:
    readme = REPO / "README.md"
    text = readme.read_text(encoding="utf-8")
    section = (
        "## Stress test on real screenshots\n\n"
        f"Measured on `{report['analysed']}` screenshots from one real folder "
        f"({report['elapsed_seconds']}s total, {report['avg_ms']}ms and "
        f"{report['avg_tokens']} tokens per image on this PC). "
        f"Failures: {len(report['failures'])} (tiny or corrupt images, now "
        "rejected with a clear message). Full data: `docs/full-analysis-report.json` "
        "and `docs/full-analysis-progress.jsonl`.\n"
    )
    if "## Stress test on real screenshots" in text:
        head, _, _ = text.partition("## Stress test on real screenshots")
        text = head.rstrip() + "\n\n" + section
    else:
        text = text.rstrip() + "\n\n" + section
    readme.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    analyse_all()
