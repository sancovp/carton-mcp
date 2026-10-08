CartON runs as STDIO, configured in `/home/GOD/.claude.json` → `mcpServers.carton`. The transport is
stdio (command-based, Claude Code spawns the process), and the code calls `mcp.run()` with NO transport
arg — FastMCP defaults to stdio.

NEVER change carton transport back to SSE.

NEVER add the carton-mcp launcher back to `start_sancrev.sh`.

NEVER add blocking queries at module import level in `server_fastmcp.py`.

Put ALL source changes in the MONOREPO: `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/`.

NEVER edit the legacy repo at `/home/GOD/carton_mcp/`.

Read the `understand-carton-mcp-rules` skill for the history behind this rule.
