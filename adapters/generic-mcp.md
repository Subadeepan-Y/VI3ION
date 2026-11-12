# Vi3ion for any MCP client

VI3ION ships as a stdio MCP server. Every MCP-capable agent can use it; the
only per-harness difference is *where* the config lives and what the key is
called.

## The configuration

```json
{
  "mcpServers": {
    "vi3ion": {
      "command": "vi3ion-mcp",
      "args": [],
      "env": {
        "VI3ION_DATA_DIR": "~/.vi3ion"
      }
    }
  }
}
```

That is the standard MCP client shape (`mcpServers` + `command` + `env`).

If your agent prefers the module form, use your interpreter directly:

```json
{
  "mcpServers": {
    "vi3ion": {
      "command": "python",
      "args": ["-m", "vi3ion.mcp_server"],
      "env": {
        "VI3ION_DATA_DIR": "~/.vi3ion"
      }
    }
  }
}
```

> The module form is the one to prefer on Windows: `pip install -U vi3ion`
> rewrites the generated `vi3ion-mcp.exe` launcher, and Windows refuses to
> replace a file that a running editor still has open. Running the module
> through your interpreter avoids that entirely.

## Environment variables

| Variable | Meaning | Default |
|---|---|---|
| `VI3ION_DATA_DIR` | Where images, the database and the thumbnails live | `~/.vi3ion` |
| `VI3ION_ALLOWED_ROOTS` | Semicolon-separated directories `inspect_image(path=...)` may read | cwd + data dir |
| `VI3ION_CODE_ROOTS` | Directories scanned to cross-check OCR readings against source code | empty |
| `VI3ION_SEMANTIC_PROVIDER` | `none` (default) or a local detector/captioner | `none` |
| `VI3ION_LOW_RESOURCE` | `1` drops the extra OCR passes for small machines | auto (RAM < 8 GB) |

## Give the agent the rules too

The MCP server ships its own instructions, but harnesses without a plugin
API can paste the skill into their instruction file:

```bash
vi3ion skill --out AGENTS.md      # or CLAUDE.md, .claude/skills/vi3ion/SKILL.md
vi3ion skill                     # just print it
```

## Check it

```bash
vi3ion doctor       # OCR, RAM, registry, local runtimes, MCP entry point
vi3ion mcp-check    # a real MCP handshake: does the server start and list tools?
vi3ion local        # which local LLM runtimes are serving, and do they see images?
```

If your editor reports an MCP failure, run `vi3ion mcp-check` first: it prints
the exit code and the number of tools the server served.
