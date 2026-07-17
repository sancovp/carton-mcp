# CartON MCP Transport

## CartON runs as STDIO, configured in .claude.json

**Config location**: `/home/GOD/.claude.json` → `mcpServers.carton`
**Transport**: stdio (command-based, Claude Code spawns the process)
**Code**: `mcp.run()` with NO transport arg (FastMCP defaults to stdio)

## NEVER

- NEVER change carton transport back to SSE
- NEVER add carton-mcp launcher back to start_sancrev.sh
- NEVER add blocking queries at module import level in server_fastmcp.py
- ALL source changes go in MONOREPO: `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/`
- NEVER edit the legacy repo at `/home/GOD/carton_mcp/`

→ What happened with SSE / what fixed it / why ontology enforcement blocks startup: read the `understand-carton-mcp-rules` skill.
