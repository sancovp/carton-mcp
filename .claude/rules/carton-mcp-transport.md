# CartON MCP Transport — LESSONS LEARNED (Mar 13, 2026)

## CartON runs as STDIO, configured in .claude.json

**Config location**: `/home/GOD/.claude.json` → `mcpServers.carton`
**Transport**: stdio (command-based, Claude Code spawns the process)
**Code**: `mcp.run()` with NO transport arg (FastMCP defaults to stdio)

## What happened with SSE

1. We changed `mcp.run()` to `mcp.run(transport="sse")` thinking it would help
2. This required start_sancrev.sh to launch carton-mcp as a separate background process
3. .claude.json was changed to `{"type": "sse", "url": "http://localhost:8000/sse"}`
4. SSE connections degraded over long sessions causing Errno 32 Broken Pipe
5. We reversed ALL of this back to stdio

## What we changed to fix it

1. `server_fastmcp.py` line 2820: `mcp.run(transport="sse")` → `mcp.run()`
2. `.claude.json`: SSE config → command-based stdio config with all env vars
3. `start_sancrev.sh`: Removed the CartON SSE launcher block (lines 78-96)
4. `server_fastmcp.py` line 139-145: Moved `enforce_ontology_invariants()` to background thread — it was running at module import level and timing out the 30s MCP connection timeout

## CRITICAL: Ontology enforcement blocks startup

`enforce_ontology_invariants()` runs dozens of Neo4j queries (Seed Ship, starsystem enforcement, skill enforcement). It runs at MODULE IMPORT level in server_fastmcp.py. When it was synchronous, it exceeded Claude Code's 30-second MCP startup timeout. Fixed by wrapping in `threading.Thread(daemon=True)`.

## NEVER

- NEVER change carton transport back to SSE
- NEVER add carton-mcp launcher back to start_sancrev.sh
- NEVER add blocking queries at module import level in server_fastmcp.py
- ALL source changes go in MONOREPO: `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/`
- NEVER edit the legacy repo at `/home/GOD/carton_mcp/`
