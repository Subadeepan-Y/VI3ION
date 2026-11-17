"""End-to-end benchmark: text-only model with vs without VI3ION evidence.

This is the test that matters: can a blind model actually do the task? It uses
any OpenAI-compatible local endpoint (Ollama, llama.cpp, LM Studio, vLLM, ...).

    python scripts/task_benchmark.py --base-url http://127.0.0.1:11434/v1 --model qwen3-8b
    python scripts/task_benchmark.py --dry-run      # structure only, no model calls

Output is JSON with per-task accuracy, latency and token usage for both arms.
`--dry-run` never claims a model result.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from vi3ion.brief import make_brief  # noqa: E402
from vi3ion.evaluate import similarity  # noqa: E402


def call_model(base_url: str, model: str, prompt: str, api_key: str, timeout: float) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=payload, headers=headers)
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    answer = data["choices"][0]["message"]["content"]
    usage = data.get("usage") or {}
    return {
        "answer": str(answer),
        "latency_ms": elapsed_ms,
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }


def score_answer(answer: str, expected: list[str]) -> dict[str, Any]:
    """Fraction of expected facts appearing in the answer (fuzzy, case-insensitive)."""
    text = answer.lower()
    hits = [
        similarity(str(item), text) >= 0.75 or str(item).lower() in text
        for item in expected
    ]
    return {"score": round(sum(hits) / len(hits), 3) if hits else 0.0, "hits": hits}


def run(args: argparse.Namespace) -> dict[str, Any]:
    fixture_path = (REPO / args.fixture).resolve()
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    api_key = os.environ.get(args.api_key_env, "")
    rows: list[dict[str, Any]] = []

    for task in fixture["tasks"]:
        image = (REPO / task["image"]).resolve()
        evidence = make_brief(image, budget_tokens=args.budget).text if not args.dry_run else ""
        base_prompt = (
            f"Question: {task['question']}\n"
            "Answer briefly. If you cannot know, say 'I cannot know'."
        )
        with_prompt = base_prompt + "\n\nMeasured visual evidence:\n" + evidence
        if args.dry_run:
            without = {
                "answer": "DRY RUN - no model called",
                "latency_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
            with_vi3ion = dict(without)
        else:
            without = call_model(args.base_url, args.model, base_prompt, api_key, args.timeout)
            with_vi3ion = call_model(args.base_url, args.model, with_prompt, api_key, args.timeout)
        rows.append({
            "id": task["id"],
            "question": task["question"],
            "expected": task["expected"],
            "without_vi3ion": {**without, **score_answer(without["answer"], task["expected"])},
            "with_vi3ion": {**with_vi3ion, **score_answer(with_vi3ion["answer"], task["expected"])},
        })

    def summarise(arm: str) -> dict[str, Any]:
        scores = [row[arm]["score"] for row in rows]
        return {
            "accuracy": round(statistics.mean(scores), 3) if scores else 0.0,
            "latency_ms": round(statistics.mean([row[arm]["latency_ms"] for row in rows])),
            "tokens": sum(row[arm]["input_tokens"] + row[arm]["output_tokens"] for row in rows),
        }

    return {
        "ok": True,
        "mode": "dry-run (no model called)" if args.dry_run else "live",
        "model": "(none)" if args.dry_run else args.model,
        "tasks": rows,
        "summary": {
            "without_vi3ion": summarise("without_vi3ion"),
            "with_vi3ion": summarise("with_vi3ion"),
        },
        "caveat": (
            "Fuzzy string matching on short answers; not an LLM judge. "
            "Accuracy is task completion, not brief fidelity."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--model", default="qwen3-8b")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--fixture", default="tests/fixtures/task_benchmark.json")
    parser.add_argument("--budget", type=int, default=500, help="evidence token budget")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", default="docs/task-benchmark.json")
    args = parser.parse_args(argv)

    try:
        report = run(args)
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 1
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
