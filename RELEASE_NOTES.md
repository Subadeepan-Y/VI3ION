First public release.

**Install the engine** (Python 3.11+):

    pip install https://github.com/Subadeepan-Y/VI3ION/releases/download/v0.1.0/vi3ion-0.1.0-py3-none-any.whl

**Register the MCP server** with your agent. For OpenCode, in `opencode.jsonc`:

    "mcp": {
      "VI3ION": {
        "type": "local",
        "command": ["python", "-m", "vi3ion.mcp_server"],
        "environment": { "VI3ION_ALLOWED_ROOTS": "C:/path/to/your/project" }
      }
    }

Claude Code: `claude mcp add vi3ion -- vi3ion-mcp`
Cursor / Windsurf / Continue / Zed: paste the same JSON into the MCP server list.

**Optional OpenCode plugin** - measures attached images automatically:

    npm i -D @vi3ion/opencode

**Check the install:**

    vi3ion doctor       # OCR, RAM, registry, local runtimes, MCP entry point
    vi3ion mcp-check    # a real MCP handshake
    vi3ion local        # which local LLM runtimes are serving

Apache-2.0. Nothing leaves your machine: the OCR engine is ONNX and runs locally.
