"""Stress-test Vi3ion on a folder of images.

Runs the text brief over a deterministic sample (plus the smallest and largest
files) and writes a JSON report with failures, slowest analyses and images
where no text was found. Offline, local, and safe to rerun.

    python scripts/stress_images.py "C:\\Users\\ADMIN\\Pictures\\Screenshots"
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

from vi3ion.brief import make_brief

EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def analyse(path: Path) -> dict:
    start = time.perf_counter()
    try:
        result = make_brief(path)
        text = result.text
        return {
            "file": path.name,
            "size_kb": round(path.stat().st_size / 1024),
            "ms": round((time.perf_counter() - start) * 1000),
            "tokens": result.tokens,
            "chars": len(text),
            "has_text": '"' in text,
            "has_shapes": "Shapes:" in text,
            "truncated": result.truncated,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - a bad image must not stop the run
        return {
            "file": path.name,
            "size_kb": round(path.stat().st_size / 1024),
            "ms": round((time.perf_counter() - start) * 1000),
            "error": f"{type(exc).__name__}: {exc}"[:220],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="folder of images")
    parser.add_argument("--sample", type=int, default=18, help="random sample size")
    parser.add_argument("--seed", type=int, default=42, help="sampling seed")
    parser.add_argument("--out", type=Path, default=Path("docs/stress-report.json"))
    parser.add_argument("--all", action="store_true", help="analyse every image (slow)")
    args = parser.parse_args(argv)

    files = sorted(
        p for p in args.folder.rglob("*")
        if p.is_file() and p.suffix.lower() in EXTS and p.stat().st_size > 0
    )
    if not files:
        print("no images found", file=sys.stderr)
        return 2

    if args.all:
        sample = files
    else:
        rng = random.Random(args.seed)
        sample = set(rng.sample(files, min(args.sample, len(files))))
        by_size = sorted(files, key=lambda p: p.stat().st_size)
        sample.update(by_size[:3])
        sample.update(by_size[-3:])
        sample = sorted(sample, key=lambda p: str(p))

    rows = [analyse(path) for path in sample]
    report = {
        "folder": str(args.folder),
        "total_images": len(files),
        "sample_size": len(rows),
        "failures": [r for r in rows if r.get("error")],
        "slowest": sorted(
            [r for r in rows if not r.get("error")], key=lambda r: -r["ms"]
        )[:5],
        "no_text": [r["file"] for r in rows if not r.get("error") and not r["has_text"]],
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"analysed {len(rows)} of {len(files)} images")
    print(f"failures: {len(report['failures'])}")
    for row in report["failures"]:
        print(f"  {row['file']}: {row['error']}")
    print(f"no text detected: {len(report['no_text'])}")
    print(f"slowest: {[(r['file'], r['ms']) for r in report['slowest']]}")
    print(f"report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
