# VI3ION × Cursor / Windsurf / Continue / Zed

All of these are standard MCP clients: the same JSON block goes into their MCP
server list, only the file path differs.

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

| Editor | Where the MCP servers are configured |
|---|---|
| Cursor | `~/.cursor/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| Continue | `~/.continue/config.json` (`experimental.modelContextProtocolServers`) or `~/.continue/mcpServers/*.yaml` |
| Zed | `~/.config/zed/settings.json` (`context_servers`) |
| Antigravity | `~/.antigravity/mcp_config.json` |
| Quoder | `~/.quoder/mcp_config.json` |

> **Verify the path for your version.** These locations are the conventional
> ones, but editors move them; the JSON shape is the stable part. Check the
> editor's own documentation if the file is not where you expect it.

For Zed the shape is slightly different:

```json
{
  "context_servers": {
    "vi3ion": {
      "command": {
        "path": "vi3ion-mcp",
        "args": [],
        "env": { "VI3ION_DATA_DIR": "~/.vi3ion" }
      }
    }
  }
}
```

## Give the agent the skill

```bash
vi3ion skill --out AGENTS.md      # or the instruction file your editor reads
```

## Check it

```bash
vi3ion mcp-check
```

If the editor shows the server as failed, this command reproduces the same
startup and prints the exit code and the tool count.
