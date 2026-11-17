"""Measure cold and warm brief latency (p50/p95) on a real image.

Cold and warm are fundamentally different: the OCR model loads once. Reporting
them together is misleading. This script separates them and records machine
specs so numbers are never presented as universal.

    python scripts/perf_bench.py tests/fixtures/sample_ui.png --runs 8
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from full_analysis import machine_specs  # noqa: E402
from vi3ion.brief import make_brief  # noqa: E402


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--out", default="docs/perf-report.json")
    args = parser.parse_args(argv)

    image = (REPO / args.image).resolve()
    if not image.exists():
        print(f"image not found: {image}", file=sys.stderr)
        return 2
    timings: list[float] = []
    for _ in range(max(1, args.runs)):
        started = time.perf_counter()
        make_brief(image)
        timings.append(round((time.perf_counter() - started) * 1000))
    warm = timings[1:] or timings
    report = {
        "ok": True,
        "image": str(image),
        "resolution": make_brief(image).text.split("Image ", 1)[1].split(" ", 1)[0],
        "runs": len(timings),
        "cold_ms": timings[0],
        "warm_ms": {
            "p50": round(statistics.median(warm)),
            "p95": round(p95(warm)),
            "min": min(warm),
            "max": max(warm),
        },
        "machine": machine_specs(),
        "results_may_vary": "Other CPUs, resolutions and text densities will differ.",
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("cold_ms", "warm_ms", "resolution")}, indent=2))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
