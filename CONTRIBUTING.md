# Contributing to Vi3ion

Thanks for helping. Keep it simple and local-first.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,ocr]"
```

## Before you open a pull request

```powershell
.venv\Scripts\python -m pytest -q          # the whole suite must pass
.venv\Scripts\python -m vi3ion.cli score --all   # fidelity must not drop
node .\.opencode\plugins\vi3ion-attach\smoke.mjs  # plugin behaviour
```

`score --all` is the release gate: the average fidelity across the bundled
fixtures must not fall below the current baseline (91.9%).

## Ground truth files

`IMAGE_ANALYSIS*.md` are the hand-written ground truths. Never edit them by
hand — they are the measuring stick. If the engine improves, regenerate them
with the documented procedure and say so in the pull request.

## Style

- Python: follow the surrounding code, type hints on public functions, no new
  dependencies without discussion.
- JavaScript (plugin): plain ESM, no build step, no runtime dependency except
  `@opencode/plugin`.
- Everything must work on Windows, macOS and Linux: no hardcoded paths, no
  machine-specific assumptions.

## Reporting perception bugs

A perception bug is "Vi3ion said X, the image shows Y". Attach the image (or
its path), what Vi3ion said, and what it should have said. Screenshots of the
wrong OCR are the fastest way to fix the OCR.
