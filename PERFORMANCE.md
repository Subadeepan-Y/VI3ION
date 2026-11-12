# Vi3ion performance profile

Measured 2026-11-02 on this machine, running a full brief generation for the
new page screenshot **while OpenCode was open and idle** in the same session
(the exact IDE-plugin usage pattern).

## Test machine

| | |
|---|---|
| OS | Windows 11 Pro 10.0.26200 |
| CPU | AMD Ryzen 5 5500GT (6 cores / 12 logical processors) |
| RAM | 15.3 GB |
| OCR | RapidOCR (ONNX Runtime, CPU) — bundled Chinese rec model |

## Results (peak values during a run)

| Process | Peak working set | Peak CPU | Avg CPU |
|---|---|---|---|
| Vi3ion brief (venv python) | **584 MB** | **63.9%** (of total CPU) | 50.7% |
| OpenCode (opencode.exe ×2) | ~340 MB each | ~3% | ~0.7% |
| Other python (system) | ~32 MB | ~1% | ~0.5% |

Timing: one brief run = **56.6 s cold** (model load + OCR + recovery passes),
single-threaded startup and multi-threaded inference burst.

## What this means for IDE integration

- **Memory floor:** Vi3ion itself needs roughly **0.6 GB** at peak while
  processing (the OCR model + frame buffers). OpenCode stays at its normal
  footprint (~0.7 GB total). A machine with ≥4 GB free RAM handles this
  comfortably.
- **CPU burst:** inference is multi-threaded and briefly uses most cores;
  the burst lasts seconds, then the process idles. Avoid running many Vi3ion
  calls in parallel on small machines.
- **Latency:** expect **~1 minute cold** per image. Once the MCP server is
  long-lived, the model stays loaded and subsequent images are faster
  (warm) — this is the recommended deployment mode for IDE plugins.
- **Disk:** model files ~13 MB; no network use during processing.

## Low-resource mode (for local models / low-end machines)

Auto-enabled when the machine has < 8 GB RAM (override with
`VI3ION_LOW_RESOURCE=0|1`). It:

- lowers the analysis cap 2048 → 1280 px (downscales images before OCR),
- skips the CJK margin-recovery pass (the most expensive extra pass),
- skips the context-driven attention relook.

Measured on this machine (1294×852 screenshot, warm runs):
- peak working set **453.9 MB** vs 562.6 MB normal (~19% less)
- run time ≈ unchanged (~4s warm)
- accuracy cost: CJK subtitles only (typical UI text unaffected)

The visual add-on also selects a **compact evidence tier** automatically for
models with < 32K context (`/vi3ioncompact`, `/vi3ionfull` to force).

## Measuring yourself

`data/debug/profile_vi3ion.ps1` samples opencode + python processes every
250 ms while running one brief and prints peaks. Run with:

```powershell
powershell -ExecutionPolicy Bypass -File data/debug/profile_vi3ion.ps1
```
