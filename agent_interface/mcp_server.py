"""Legacy shim: the MCP server now lives in vi3ion.mcp_server.

Launchers built from older entry points (``from agent_interface.mcp_server
import main``) keep working through this module instead of failing with
ModuleNotFoundError. Running the module directly also starts the server.
"""
from vi3ion.mcp_server import main  # noqa: F401

__all__ = ["main"]

if __name__ == "__main__":  # pragma: no cover - process entry point
    main()
