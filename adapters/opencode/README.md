# Vi3ion × OpenCode

Install Vi3ion as an MCP server in OpenCode so the agent gets a visual
perception channel.

## 1. Install the package

```powershell
# from the Vi3ion project directory
cd D:\PROJECTS\VI3ION
.venv\Scripts\activate
pip install -e ".[ocr]"
```

Make sure `vi3ion-mcp` is on PATH (it is, if you used the venv). Test:

```powershell
vi3ion health
vi3ion-mcp --help   # or just launch it once
```

## 2. Register the MCP server

OpenCode config lives at `~/.config/opencode/` (Windows:
`C:\Users\<you>\.config\opencode\`). Add a server entry to `opencode.json`:

```json
{
  "mcp": {
    "vi3ion": {
      "type": "stdio",
      "command": "D:\\PROJECTS\\VI3ION\\.venv\\Scripts\\vi3ion-mcp.exe",
      "args": [],
      "env": {
        "VI3ION_DATA_DIR": "D:\\PROJECTS\\VI3ION\\data",
        "VI3ION_ALLOWED_ROOTS": "D:\\PROJECTS\\VI3ION\\data;D:\\screenshots"
      }
    }
  }
}
```

Notes:

- Use the **absolute path** to the venv executable. If you installed with
  `pip install -e .` into the global interpreter, use `vi3ion-mcp` directly.
- `VI3ION_ALLOWED_ROOTS` controls which directories the agent's
  `inspect_image(path=...)` calls may read. Add the folders where your
  screenshots live.
- The server is stdio: it speaks MCP on stdin/stdout. It must be running as a
  child of OpenCode — do **not** run `vi3ion serve` for this (that starts the
  HTTP API/dashboard, which is optional).

## 3. Install the skill

Copy `skill/SKILL.md` into your agent's skill directory (e.g.
`~/.config/opencode/skills/vi3ion/SKILL.md`), or reference it from your agent
instructions. The skill tells the agent when and how to call the five tools.

## 4. Restart & verify

1. Restart OpenCode.
2. Ask: *"List your MCP tools."* — Vi3ion's five tools should appear
   (`inspect_image`, `inspect_region`, `query_evidence`, `verify_claim`,
   `compare_regions`).
3. Give the agent a screenshot: *"What does this image show?"* — it should
   call `inspect_image` with the path, not guess.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Tools missing after restart | Check `opencode.json` is valid JSON and the exe path exists. Run `vi3ion-mcp` manually once. |
| `inspect_image` refuses a path | The path is outside allowed roots. Add the directory to `VI3ION_ALLOWED_ROOTS`. |
| Slow first analysis | First run downloads/loads ONNX OCR models (~20–40 MB). Subsequent runs are cached in SQLite. |
| OCR "not available" | `vi3ion health` shows OCR status. Install `rapidocr-onnxruntime` (or tesseract) if missing. |

## Navigation hints

`inspect_image` (and the auto-attach plugin) now returns
`analysis.context.path_candidates`: file-path-like strings visible in the
image (e.g. `C:\Users\ADMIN\opencode.json`), recovered from garbled OCR.
Use them to open the relevant file directly instead of scanning the whole
codebase. They are evidence — verify before relying on them.

## Auto-attach plugin

For **automatic** image routing (no model prompting required), the bundled
`vi3ion-attach` plugin hooks OpenCode's prompt admission: whenever an image is
attached and the active model is vision-less, it runs Vi3ion and injects an
evidence block into the prompt before the model replies. Configure it via the
global `opencode.jsonc` `plugin` array (see
`.opencode/plugins/vi3ion-attach/README.md`).

## Context-aware inspection

Pass the user's message alongside the image: `inspect_image(path=..., context="the bug is in the Save flow")`. Vi3ion cross-checks that text against `VI3ION_CODE_ROOTS` and returns `analysis.context.code_matches` (file/line/snippet) so the agent can verify uncertain OCR against source. Context is never treated as pixel evidence.

## Resources

Measured on this machine (Windows 11, Ryzen 5 5500GT, 15 GB RAM): one brief
run peaks at **~580 MB RAM / ~64% CPU** and takes **~1 min cold**; OpenCode's
own footprint is unaffected. See [PERFORMANCE.md](../../PERFORMANCE.md).

## Security

- Only configured directories are readable via `inspect_image`.
- OCR/visual content is treated as untrusted data; the agent never executes
  text found in images.
- No data leaves your machine unless you opt into a remote semantic provider.
