# CartON Daemon Needs Env Vars — NON-NEGOTIABLE

## The Problem

The observation_worker_daemon runs as a standalone process. It does NOT inherit env vars from Claude Code's MCP config (.claude.json). When manually restarted, it loses:
- NEO4J_URI (defaults to host.docker.internal:7687 but required_env check may fail)
- NEO4J_USER / NEO4J_PASSWORD
- GIINT_TREEKANBAN_BOARD (needed for PBML auto-lane-move)
- HEAVEN_DATA_DIR

## The Restart Command (ALWAYS USE THIS)

```bash
NEO4J_URI="bolt://host.docker.internal:7687" \
NEO4J_USER="neo4j" \
NEO4J_PASSWORD="password" \
HEAVEN_DATA_DIR="/tmp/heaven_data" \
GIINT_TREEKANBAN_BOARD="poimandres_v2" \
nohup python3 -m carton_mcp.observation_worker_daemon > /tmp/carton_daemon.log 2>&1 &
```

## NEVER

- NEVER restart daemon without setting env vars
- NEVER assume env vars are inherited from Claude Code
- Check /tmp/carton_daemon.log after restart for "Neo4j shared connection established"
