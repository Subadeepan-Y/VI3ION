# VI3ION — Visual Intelligence for AI Agents

Vi3ion gives AI coding agents an **independent perception engine**: it looks at
images, screenshots, and diagrams, and returns *structured evidence* — OCR text,
coordinates, shapes, colours, measured relationships, and a scene graph — that
an agent (or human) can reason over.

## Resource profile

See [PERFORMANCE.md](PERFORMANCE.md) for measured peak RAM/CPU during a run
alongside OpenCode (~0.6 GB peak, ~1 min cold per image, multi-threaded
inference burst).

## The text brief, measured

A ~530-word brief that a model with **no vision** can reason over — no model
calls, no network, ~5s on a 1919×949 screenshot:

| Component | Score | What it measures |
|---|---|---|
| **Brief fidelity** | **83.5%** | weighted mean of the four rows below |
| Text recall | 72.1% | share of real text that reached the brief (31/43 units) |
| Text precision | 91.7% | share of the brief's quoted text that is really in the image |
| Region accuracy | 83.9% | matched text filed under the right region |
| Structure | 100% | composition line, 12-cell colour map, shape sentences, honesty note |

```bash
vi3ion brief screenshot.png    # the brief itself
vi3ion score screenshot.png    # score it against hand-transcribed ground truth
```

Scores come from `tests/fixtures/*.expected.json` — hand-transcribed files of
the same images — so the claim is reproducible and every regression is visible.
The table above is the hard case; on a clean settings dialog the same pipeline
scores **98.5%**. The gap between the two is the honest story: layout and
composition hold up, and what costs points is OCR, not placement. On the
difficult image the loss is concentrated in three known defects — index digits
read as `84/85/88/89` instead of `04/05/08/09`, misread Japanese labels, and one
fused word.

### What it looks like

> Image 1919x949 (screenshot.png). Dominant colour: #080808 (32%). Colour map: row 1, col 1: black, dark; … Left column: `"00 + "PORTFOLIO"" (uncertain) @[136, 167, 288, 181]; "BUILT TO" (split from "BUILTTO") @[121, 231, 673, 325]; … Composition: 2 tall pale columns at 28% and 72% of the width split the frame; the largest colour area is a dark red horizontal band in the bottom (17% of the frame); text is concentrated in the right and left thirds. Shapes: a horizontal band (spans most of the image width) in the bottom, dark red … a rectangular area (spans most of the image width) in the centre, grey …; two pale or white columns and a red round shape sit inside it. a tall vertical column (spans most of the image height) in the left, pale or white. …

Every quoted value keeps its pixel box, so a follow-up can crop and re-read
exactly that region. Uncertain reads stay marked `(uncertain)`; a word OCR
fused is separated but recorded as `(split from "BUILTTO")`. Nothing is ever
silently corrected.

### Honest boundaries

The brief deliberately does **not** name objects — it says *"a small rectangular
area in the upper right"*, never *"a button"*. Object names are the reading
model's job, and keeping them out is what makes the evidence auditable. Large
decorative lettering too faint for OCR is not transcribed, and the brief says so
in its closing note.

## How it ships

It is packaged as an **installable agent skill/plugin**, not a standalone
product:

| Layer | What it is |
|---|---|
| **Core** | Agent-independent perception pipeline (Python). Pure computation: ingestion → pixels → geometry → OCR → spatial relations → verification → text brief. |
| **Adapter** | MCP server (stdio) exposing 11 tools. This is what the coding agent talks to. |
| **Skill** | Written instructions (`vi3ion/skill/SKILL.md`) telling the agent *when and how* to call the tools. |
| **Dashboard** | Local React dev dashboard (`dashboard/`) for testing and inspecting evidence. Never required in production. |

## Quickstart

```bash
# 1. install (OCR included; ~200 MB of dependencies)
pip install vi3ion

# ...or from a checkout
python -m venv .venv
.venv\Scripts\activate            # Windows  |  source .venv/bin/activate  # POSIX
pip install -e ".[dev]"

# 2. check the install
vi3ion doctor                      # OCR, RAM, registry, local runtimes, MCP entry point
vi3ion mcp-check                   # real MCP handshake: does the server start?

# 3. analyse an image from the CLI
vi3ion analyze screenshot.png --detail standard
vi3ion brief screenshot.png        # text-only brief for a vision-less model
vi3ion score screenshot.png        # brief fidelity vs fixtures/*.expected.json
vi3ion local                      # local LLM runtimes + the recommended Vi3ion role
vi3ion ingest shots\ --label run # register a screenshot folder in the image memory
vi3ion prune                   # drop remembered images whose file no longer exists
vi3ion health --tier              # config, OCR status, machine tier

# 4. optional: the local dashboard (not needed by agents)
vi3ion serve                       # API + dashboard on http://127.0.0.1:8765

# 5. run the test suite
pytest
```

### Connect your coding agent (MCP)

Add the stdio MCP server to your agent's config:

```json
{
  "mcpServers": {
    "VI3ION": {
      "command": "vi3ion-mcp",
      "args": [],
      "env": { "VI3ION_DATA_DIR": "~/.vi3ion" }
    }
  }
}
```

On Windows, prefer running the module through your interpreter instead of the
generated launcher:

```json
{
  "mcpServers": {
    "VI3ION": {
      "command": "C:\\path\\to\\python.exe",
      "args": ["-m", "vi3ion.mcp_server"],
      "env": { "VI3ION_DATA_DIR": "~/.vi3ion" }
    }
  }
}
```

Why: `pip install -U vi3ion` rewrites the `vi3ion-mcp.exe` launcher, and
Windows refuses to replace a file that a running editor has open — the upgrade
then fails with "file is being used by another process". `python -m
vi3ion.mcp_server` is never rewritten and picks up new code immediately.

### If your editor reports an MCP failure

```powershell
vi3ion mcp-check      # runs a real MCP handshake and prints what happened
vi3ion doctor         # OCR, RAM, registry, local runtimes, entry point
```

`vi3ion mcp-check` spawns the server exactly like the editor does and reports
the exit code and the number of tools it found. If it passes but the editor
still complains, restart the editor.

See `adapters/opencode/` for an OpenCode-specific example and install notes.

### Local models (Ollama, llama.cpp, LM Studio, vLLM, Unsloth, …)

Vi3ion detects local runtimes, reports the models they serve and tells the
agent whether it must act as the eyes or as an assistant. Local runtimes get a
compact evidence tier, a token budget and a single analysis pass. See
`LOCAL_MODELS.md`.

## The evidence contract

Everything Vi3ion returns obeys one envelope (`ToolResponse`):

- `summary` — human-readable one-liner of what was found.
- `evidence[]` — items of kind `text | shape | color | object | relationship | note | image`,
  each with `label`, `confidence`, `attributes`, and a **bounding box in
  original image pixels** (`[x0, y0, x1, y1]`).
- `evidence_total` / `truncated` — pagination awareness.
- `cached` — true when the result was served from the evidence store.

### Measured colours per element

Every text and shape item also carries its own measured colour in
`attributes`:

| Attribute | Meaning |
|---|---|
| `ink_hex`, `ink_rgb`, `ink_name` | the element's own colour (letter ink, or a shape's fill) |
| `bg_hex`, `bg_name` | the local background it sits on |
| `contrast` | WCAG-style luminance ratio between the two (1..21) |
| `ink_share` | how much of the box the ink covers |

The text brief renders the same measurement inline, unquoted so the fidelity
score is unaffected:

```
"Save" (uncertain) ink:#f8f8f8 on:#2563eb contrast:4.9 @[373, 619, 421, 640]
```

`verify_claim` uses the same measurement, so `"the text 'Save' is white"` and
`"the Save button is blue"` are answered with a verdict instead of a guess.
- `timings_ms` — per-module timing breakdown.
- `verification` — for `verify_claim`: `verified | contradicted | inconclusive`
  plus measurements, never opinions.

Coordinate space is always the **original image**, even for region crops
(`inspect_region` remaps crop coordinates back).

### Observed vs inferred

| Evidence | Marked |
|---|---|
| OCR text, shapes, colours, measured relations, geometry | `observed` |
| Semantic object labels (when a provider is enabled) | `inferred` |

Agents must preserve that distinction when reporting to users.

## MCP tools

| Tool | Purpose |
|---|---|
| `inspect_image` | Ingest + analyse an image (by `path` or `image_id`). |
| `inspect_region` | Deep-dive on `[x0,y0,x1,y1]`; coordinates mapped back to original. |
| `query_evidence` | Query stored evidence by kind/text/region/confidence without re-analysis. |
| `verify_claim` | Check a claim ("Save is aligned with Cancel") against measurements. |
| `compare_regions` | Measure differences between two regions. |
| `cross_check_text` | Verify an OCR reading against project source string literals. |
| `list_images` | List remembered images (labels + identity metadata, including the perceptual hash). |
| `remember_image` | Attach a persistent label to an image. |
| `diff_images` | Compare two versions of a screen (observed text/layout changes **and** a pixel-level comparison). |
| `local_stack` | Detect local LLM runtimes (Ollama, llama.cpp, LM Studio, vLLM, …), their models, and the recommended Vi3ion role. |
| `doctor` | Self-check the setup: OCR, RAM/tier, registry, local runtimes, editor wiring. |

All results are returned as JSON strings over the MCP transport.

The **text brief** (`vi3ion brief` / `vi3ion score`) is currently a CLI entry
point rather than an MCP tool; wiring it into the adapter is a small, tracked
gap rather than an implied capability.

## Architecture

```
vi3ion/
  config.py            pydantic settings (VI3ION_* env vars)
  brief.py             the text-only brief: compose every section into one page
  image_memory.py      identity signatures, similarity, version diffs
  visual_diff.py       pixel-level comparison of two screenshots
  core/pixels/element_color.py  per-element colour measurement (ink + background)
  local_stack.py       local LLM runtime detection (Ollama, llama.cpp, LM Studio, vLLM, …)
  analyzer.py          OCR -> rows -> spatial regions -> per-region budget
  text_merge.py        split fused words, join fragments, pair numbers
  describe_shapes.py   region sentences: contours, pale columns, colour areas
  composition.py       large colour areas + "how the frame is divided"
  evaluate.py          brief-fidelity scorer against hand-transcribed truth
  colors.py            named colour set (Lab nearest-name)
  schemas/             evidence contract: BBox, Evidence, ToolResponse, claims
  storage/             SQLite schema, image store, repositories
  core/
    ingestion/         validation, EXIF orientation, dedup, thumbnails
    pixels/            CIELAB palette, statistics, colour regions
    geometry/          adaptive Canny, contours, shapes, measurements
    ocr/               rapidocr-onnxruntime (with tesseract fallback)
    semantics/         optional semantic provider (mock/remote/OpenAI-compatible)
    spatial/           scene graph, rows/columns, relationships
    verification/      claim parser + verifier
    engine.py          orchestrator (single entry to everything)
  server/              FastAPI app (dev dashboard API + static mount)
  mcp_server.py        MCP stdio server (11 tools) — the portable interface
  agent_interface/      legacy shim → vi3ion.mcp_server (kept for old launchers)
dashboard/              React + Vite dev dashboard
skill/                  the agent skill instructions
tests/                  82 tests: schema, ingestion, geometry, verification,
                        API, text merging, composition, brief fidelity
```

## Security model

- Server binds loopback by default (`127.0.0.1`).
- Agent-supplied filesystem paths are restricted to `VI3ION_ALLOWED_ROOTS`
  (default: cwd + data dir). Anything outside is refused.
- Images are validated at ingestion (magic bytes, format whitelist, size and
  pixel limits). **Image content is never executed**; OCR/semantics output is
  treated as untrusted data.
- The MCP server never prints to stdout (that is the protocol channel).

### Semantic providers (local, opt-in)

All perception beyond OCR/geometry is **inferred** and tagged as such.
Enable providers via `VI3ION_SEMANTIC_PROVIDER` (comma-separated):

| Value | Provider | Notes |
|---|---|---|
| `mock` | deterministic JSON fixtures keyed by image hash | default for tests; no model loaded |
| `florence` | Florence-2 base (object detection + region captions) | input capped at 768px, boxes mapped back |
| `owlvit` | OWL-ViT open-vocabulary detector | vocabulary in `core/semantics/vocabulary.json` (extend without code changes) |
| `clip` | CLIP zero-shot scene tags | top 3, marked `suggested` |
| `remote` | OpenAI-compatible API | **image leaves the machine** — opt-in only |

Heavy models require `pip install -e ".[semantic]"` (torch + transformers). If a
provider is enabled but its dependencies/weights are missing, it reports an
error and the analysis continues with the remaining providers.

```bash
# run with all local semantic layers
VI3ION_SEMANTIC_PROVIDER=florence,owlvit,clip vi3ion analyze shot.png
```

## Development

```bash
npm --prefix dashboard install
npm --prefix dashboard run build     # TS + Vite; dist/ mounts at server root
pytest                                # full suite
```

The dashboard proxies `/api` to the server and is only mounted when
`dashboard/dist` exists.
