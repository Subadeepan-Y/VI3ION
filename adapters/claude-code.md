# VI3ION × Claude Code

## Install

```bash
pip install vi3ion
claude mcp add vi3ion -- vi3ion-mcp
```

`claude mcp add` writes the registration into your user scope. For a project
that everyone on the team should share, add a `.mcp.json` in the repository
root instead:

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

## Give Claude the skill

```bash
mkdir -p ~/.claude/skills/vi3ion
vi3ion skill --out ~/.claude/skills/vi3ion/SKILL.md
```

## Notes

- The server is stdio: Claude Code starts it as a child process. Do not run
  `vi3ion serve` for this — that starts the optional HTTP API and dashboard.
- `vi3ion mcp-check` reproduces exactly what Claude Code does, so it is the
  fastest way to diagnose "MCP failed" in the editor.
- Claude Code asks for approval the first time a server runs; approve the
  `vi3ion` entry and it is remembered.
