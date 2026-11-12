# Install adapters

| Harness | Guide |
|---|---|
| **OpenCode** | [opencode/README.md](opencode/README.md) — plus the optional `@vi3ion/opencode` plugin |
| **Claude Code** | [claude-code.md](claude-code.md) |
| **Cursor, Windsurf, Continue, Zed, Antigravity, Quoder** | [editors.md](editors.md) |
| **Anything else that speaks MCP** | [generic-mcp.md](generic-mcp.md) |

All of them use the same server and the same configuration block:

```json
{
  "mcpServers": {
    "vi3ion": {
      "command": "vi3ion-mcp",
      "args": [],
      "env": { "VI3ION_DATA_DIR": "~/.vi3ion" }
    }
  }
}
```

Two commands to verify any installation:

```bash
vi3ion doctor       # engine, OCR, data, local runtimes
vi3ion mcp-check    # a real MCP handshake
```

And one to give the agent the rules in harnesses that have no plugin API:

```bash
vi3ion skill --out AGENTS.md
```
