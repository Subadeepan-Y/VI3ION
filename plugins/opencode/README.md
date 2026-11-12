# @vi3ion/opencode

The OpenCode plugin for [VI3ION](https://github.com/Subadeepan-Y/VI3ION) — a
local perception engine that measures images (OCR, geometry, per-element colour,
version diffs) and hands the results to your agent.

## Install

```bash
npm i -D @vi3ion/opencode
```

The plugin needs the VI3ION engine (Python 3.11+):

```bash
pip install vi3ion
```

Then register the MCP server in `~/.config/opencode/opencode.jsonc`:

```jsonc
{
  "mcp": {
    "VI3ION": {
      "type": "local",
      "command": ["python", "-m", "vi3ion.mcp_server"],
      "environment": { "VI3ION_ALLOWED_ROOTS": "C:/path/to/your/project" }
    }
  },
  "plugin": ["@vi3ion/opencode"]
}
```

The key is the server's **display name** and becomes the tool namespace
(`VI3ION.inspect_image`). `vi3ion` works just as well.

## What it does

- **Measures every attached image** and attaches the evidence to the request —
  the agent never has to think about it
- **Introduces itself** on the first prompt and asks the agent whether it has
  native vision, so a vision-less model knows Vi3ion is its eyes
- **Re-binds on a model switch**: the new model is told the role again
- **Keeps the role across compaction**, so a summarised conversation still
  knows Vi3ion exists
- **Remembers every image** and can diff two states of the same screen
- **Self-heals**: if the MCP server dies, the plugin restarts it

Everything runs locally: no image leaves your machine.

## Documentation

- [Plugin behaviour](https://github.com/Subadeepan-Y/VI3ION/blob/main/plugins/opencode/README.md)
- [OpenCode setup guide](https://github.com/Subadeepan-Y/VI3ION/blob/main/adapters/opencode/README.md)
- [Local models (Ollama, llama.cpp, LM Studio, vLLM)](https://github.com/Subadeepan-Y/VI3ION/blob/main/LOCAL_MODELS.md)

## License

Apache-2.0

---

# Vi3ion auto-attach plugin

## Behavior guarantees

- **Blocking**: analysis runs inside prompt admission, *before* the model
  receives the image. The model stays idle until evidence is ready — it never
  half-answers while Vi3ion works.
- **Visible status**: a synthetic note ("Vi3ion is analysing…") is posted to
  the session while analysis runs, so the delay is transparent.
- **Hard timeout**: each analysis has a ceiling (`analyzeTimeoutMs`, default
  240 s). If it wedges, admission proceeds without hanging forever.
- **Blind fallback**: if analysis fails, the model is explicitly told
  *"Vi3ion analysis failed… Do not guess image contents"* — it never fabricates
  visual claims in silence.

## First-turn introduction and persistent presence

On the first prompt of every conversation, Vi3ion injects a `vi3ion-intro` block
that introduces itself to the agent and asks it to self-assess:

1. Do I have native vision?
2. Are the Vi3ion MCP tools available?
3. Is my context budget small (<32K, so compact evidence)?

The detected role is included as a hint (visionless = eyes, vision-capable =
assistant), but the agent's own answer wins. If it is visionless, the intro
instructs it to treat Vi3ion evidence as the only source of image claims. The
greeted session IDs persist in plugin storage, so reloading the plugin does not
repeat the intro inside an existing conversation.

All injections (intro, assistant note, evidence blocks, diffs) are
written as **session instruction entries** and as system-instruction blocks of
the request — they render as `<context>` blocks and never appear as visible
chat text. Evidence entries are replaced only when new evidence arrives, so a
follow-up question about the same image still has its evidence; a model switch
re-introduces the role without dropping the evidence. If the host does not
expose instruction entries, the plugin falls back to appending to the prompt
text.

The "already analysed" cache is scoped per session and keyed by content hash:
a new conversation always receives its own evidence, and the same screenshot
is never measured twice.

A compact `Vi3ion presence` line is also appended to **every model request**
and to **compaction requests**, so the role survives long conversations and
context summarisation.

## Image analysis (message level)

OpenCode delivers an attachment on the **message**, not on the prompt:

```json
{ "mime": "image/jpeg", "data": "<base64>",
  "source": { "type": "uri", "uri": "file:///C:/..." } }
{ "mime": "image/jpeg", "data": "<base64>", "source": { "type": "inline" } }
```

So the analysis runs in the **context hook** (the model request), the only
place where the mime type and the bytes exist:

- file attachments are analysed from their path,
- clipboard images (inline base64) are written to `data/inbox/` and analysed,
- the evidence is attached to the request **and** stored as a session
  instruction, so follow-up turns and compaction still know what the image was.

Every injection is recorded in `data/inbox/last-injection.json`: the exact text
the model received, with the model, the role and the reason.

## Colours in the evidence

The injected brief carries a measured colour for every element:

```
"Save" (uncertain) ink:#f8f8f8 on:#2563eb contrast:4.9 @[373, 619, 421, 640]
```

`ink:` is the element's own colour (white letters, here), `on:` the local
background (the blue button), `contrast:` the luminance ratio. Colours are
unquoted so the fidelity score is unaffected, and the shapes carry their fill
colour too (`in the centre, blue (#2868e8)`).

> Note: if the Vi3ion MCP tools look stale in an editor session (for example
> `list_images` missing), restart the editor so the MCP server re-registers its
> tool list.

## Clipboard and inline images

Attachments are detected by MIME type, by file extension and by the URI inside
`source.uri`. Inline attachments (clipboard paste: base64 `data` + `mime`) are
written to `data/inbox/` and analysed like any other image — a clipboard
screenshot is measured, never ignored. The user's chat text is never modified.

## Model switching mid-conversation

A user can switch models while chatting. The new model has never seen Vi3ion,
so the plugin:

- re-injects the intro block with the new model and its role
  (`Model changed in this conversation (was …)`),
- appends a role-change notice to the system prompt of the next request,
  naming the tools and restating eyes vs assistant.

The model named in the intro comes from the request event when present, else
from the session's selected model (`ctx.session.get`), and only then from the
configuration default. The config default is not the session model: picking a
model in the session does not change it.

Vision detection uses, in order: the model's declared input modalities
(`capabilities.input`), known vision model names, and — for local runtimes —
name heuristics (`llava`, `qwen2.5-vl`, `minicpm-v`, `gemma3`, …).

## Local runtimes (Ollama, llama.cpp, LM Studio, vLLM, Unsloth, SGLang, …)

Local models are supported explicitly:

- Local runtimes default to the **compact** evidence tier (small context).
- Local runtimes also run Vi3ion in low-resource mode: the extra Japanese
  recognizer pass is dropped, which cuts about 35% of the analysis time and
  its RAM.
- The intro states that a local model may have no image input at all and that
  Vi3ion is then the eyes; the persistent presence line repeats it per request.
- `vi3ion local` (CLI) and the `local_stack` MCP tool report which runtimes
  are reachable, which models they serve, and which of those accept images.
- `/vi3ionlocal` shows the same in the chat; `/vi3ionstatus` includes it.
- The evidence block gets a token budget (~8% of the context window) and the
  duplicate analysis pass is skipped, so local machines stay cheap.
  `/vi3ionbudget <tokens>` overrides it.
- Detection order: declared input modalities, then local model names, then
  generic names. A local server registered under a generic provider id
  (`openai`, `custom`) is **not** mistaken for a cloud vision model.
- A local GPU exposed over a tunnel (`*.unsloth.app`, `trycloudflare.com`,
  `ngrok.io`) counts as local.

See `LOCAL_MODELS.md` in the project root for the full local workflow.

## Image memory and version diff

Every analysis registers an identity signature (OCR fingerprint + coarse layout
+ perceptual hash) in Vi3ion's SQLite registry. The perceptual hash recognises
"the same screen, different wording", which an OCR fingerprint alone cannot.
The agent can then:

- `list_images` — see remembered images and their labels
- `remember_image(image_id, label)` — name one ("dashboard v1")
- `diff_images(image_id_a, image_id_b)` — observed text/layout changes

When a new image resembles a remembered one, the injected evidence includes a
`similar_images` suggestion with the label and similarity score. The plugin
tells the model to **confirm identity with the user** before treating it as the
same screen.

If exactly **two new images** are attached to one message, the plugin also runs
`vi3ion diff` automatically and injects a `vi3ion-diff` block. Diffs report the
raw OCR labels (not lowercased fingerprints), so `"System" -> "Custom"` is shown
as read. A pixel comparison is included as well, which catches changes that
carry no text (a colour, size or position change). Diff output is
evidence only: the agent must verify each change against the code or commit
diff before reporting it.

CLI equivalents:

```powershell
vi3ion images
vi3ion label old.png "dashboard v1"
vi3ion diff old.png new.png --text-only
vi3ion ingest shots\ --label run   # register a screenshot folder
vi3ion prune                        # drop images whose file is gone
```

## Two roles, chosen from the active model:

- **Visionless model** → Vi3ion is the eyes: the plugin runs Vi3ion on the
  image and injects a `vi3ion-auto` evidence block (OCR, layout, path
  candidates, code cross-check) before the model reads it.
- **Vision-capable model** (e.g. DeepSeek V4.1, GLM-5.3-Flash) → the model's
  own vision is **primary**: it is better than Vi3ion, so Vi3ion only assists.
  The plugin injects a small `vi3ion-confirm` note saying the model is the lead
  and Vi3ion is available on request for a second reading (exact OCR, pixel
  coordinates, measured colour/geometry via `verify_claim` / `inspect_region`).
  No heavy OCR block is injected; the image passes through untouched.

## On/off

Plugin is ON by default. Toggle with slash commands:

- `/vi3ionoff` — images pass through untouched (no Vi3ion involvement)
- `/vi3ionon` — re-enable auto-analysis/verification
- `/vi3ioncompact` — compact evidence tier (one line per element; for local
  models with small context)
- `/vi3ionfull` — full evidence tier (prose + layout table)
- `/vi3ionstatus` — show ON/OFF, role (eyes/assistant) and evidence tier
- `/vi3ionbudget <tokens>` — cap the evidence block per image (0 = auto)
- `/vi3ionlocal` — list local LLM runtimes and the models they serve
- `/vi3iondiff <older> <newer>` — compare two images from the chat
- `/vi3iondoctor` — self-check: OCR, RAM, registry, local runtimes, editor wiring

The state is stored per plugin and persists across sessions.

## Evidence tiers (auto)

- Model context < 32K → **compact** (lines like
  `top "SUBADEEPAN" @88,24,274,54 (top-left)`) to save tokens.
- Model context >= 32K → **full** (prose brief + markdown layout table).
- Explicit `/vi3ioncompact` / `/vi3ionfull` overrides the auto choice.

## How it works

- Hooks OpenCode's `prompt` admission.
- On the first prompt of a conversation, injects a `vi3ion-intro` self-check
  block and asks the agent whether it has native vision.
- Registers `context` and `compaction` hooks: a compact `Vi3ion presence` line
  is appended to every model request and to compaction, so the role survives
  long sessions and summaries.
- Detects image attachments (png/jpg/webp/gif/bmp/heic/avif).
- Default `mode: "auto"`: runs only when the active model looks visionless
  (unknown models are treated as visionless — safe default).
- Runs `vi3ion brief` (text/layout evidence) and, when `codeCheck` is on,
  `vi3ion analyze --context "<user text>"` for code cross-check matches.
- Appends `<context key="vi3ion-auto" ...>` to the prompt, so the model sees
  the evidence before replying.
- Dedupes repeated analysis of the same file (last 120 entries).

## Options (in `opencode.jsonc`)

```jsonc
{
  "plugin": [
    { "package": "D:\\PROJECTS\\VI3ION\\.opencode\\plugins\\vi3ion-attach",
      "options": { "mode": "auto", "codeCheck": true } }
  ]
}
```

- `mode`: `"auto"` (default) | `"always"` | `"never"`
- `codeCheck`: set `false` to skip the second (context/code) run — halves the
  per-image Python work.
- `maxEvidenceChars`: trim injected evidence (default 1400).
- `confirmOnly`: force the vision-role mode (assistant note) even for visionless
  models (default `false`).

## Environment

- Uses `%VI3ION_PYTHON%` if set, else `D:\PROJECTS\VI3ION\.venv\Scripts\python.exe`.
- Set `VI3ION_CODE_ROOTS` for code cross-check to be useful.

## Test

```powershell
node .\smoke.mjs
```

Requires `sample_ui.png` in `tests/fixtures/`.
