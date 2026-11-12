# Vi3ion × OpenCode

Install Vi3ion as an MCP server in OpenCode so the agent gets a visual
perception channel.

## 1. Install the package

```powershell
pip install vi3ion            # plain install: OCR included (~200 MB of deps)
```

or from a checkout:

```powershell
cd path\to\VI3ION
.venv\Scripts\activate
pip install -e .
```

Check it works:

```powershell
vi3ion doctor       # OCR, RAM, registry, local runtimes, MCP entry point
vi3ion mcp-check    # real MCP handshake: does the server start and list tools?
```

## 2. Register the MCP server

OpenCode config lives at `~/.config/opencode/` (Windows:
`C:\Users\<you>\.config\opencode\`). Add a server entry to `opencode.json`:

```json
{
  "mcp": {
    "vi3ion": {
      "type": "local",
      "command": [
        "C:\\path\\to\\python.exe",
        "-m",
        "vi3ion.mcp_server"
      ],
      "environment": {
        "VI3ION_DATA_DIR": "C:\\Users\\you\\.vi3ion",
        "VI3ION_ALLOWED_ROOTS": "C:\\path\\to\\your\\project;D:\\screenshots"
      }
    }
  }
}
```

Notes:

- The key is **`environment`**, not `env`. OpenCode ignores `env`, so those
  variables would be dropped silently — `vi3ion doctor` reports this as
  `mcp_env_key`.
- `command` is an **array** for the `local` type.
- Prefer running the module through your interpreter
  (`python -m vi3ion.mcp_server`) over the generated `vi3ion-mcp.exe`
  launcher: pip rewrites that launcher on every upgrade, and Windows refuses
  to replace a file your editor still has open ("file is being used by another
  process"), which breaks the upgrade.
- `VI3ION_ALLOWED_ROOTS` controls which directories the agent's
  `inspect_image(path=...)` calls may read. Add the folders where your
  screenshots live.
- The server is stdio: it speaks MCP on stdin/stdout. It must be running as a
  child of OpenCode — do **not** run `vi3ion serve` for this (that starts the
  HTTP API/dashboard, which is optional).

## 3. Install the skill

Copy `vi3ion/skill/SKILL.md` (shipped in the wheel) into your agent's skill
directory (e.g. `~/.config/opencode/skills/vi3ion/SKILL.md`), or reference it
from your agent instructions. The skill tells the agent when and how to call
the tools. `vi3ion skill` prints the text if you would rather paste it.

## 4. Restart & verify

1. Restart OpenCode.
2. Ask: *"List your MCP tools."* — Vi3ion's eleven tools should appear
   (`inspect_image`, `inspect_region`, `query_evidence`, `verify_claim`,
   `compare_regions`, `cross_check_text`, `list_images`, `remember_image`,
   `diff_images`, `local_stack`, `doctor`).
3. Give the agent a screenshot: *"What does this image show?"* — it should
   call `inspect_image` with the path, not guess.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "MCP server process exited with code 1" | The launcher is stale or the package is broken. Run `vi3ion mcp-check`; reinstall with `pip install -U vi3ion`. |
| "No module named 'agent_interface'" | An old launcher survived an upgrade. Reinstall the package (`pip install -U vi3ion`) — the legacy path now forwards to `vi3ion.mcp_server`. |
| "MCP server process exited with code 255" | The server was killed (restarting the editor, or an upgrade replacing it). It respawns on the next request. |
| Tools missing after restart | Check `opencode.json` is valid and `command` points at a real interpreter. Run `vi3ion mcp-check`. |
| The MCP variables seem ignored | OpenCode reads `environment`, not `env`. `vi3ion doctor` reports this as `mcp_env_key`. |
| `inspect_image` refuses a path | The path is outside allowed roots. Add the directory to `VI3ION_ALLOWED_ROOTS` (inside `environment`). |
| Slow first analysis | First run loads the ONNX OCR models (~60 MB installed). Results are cached in SQLite afterwards. |
| OCR "not available" | `vi3ion doctor` shows OCR status. Reinstall with `pip install -U vi3ion` (OCR is a core dependency). |
| `pip install -U vi3ion` fails on Windows | "file is being used by another process": the running editor holds the old launcher. Close the editor, upgrade, reopen — or register the server as `python -m vi3ion.mcp_server`. |

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
