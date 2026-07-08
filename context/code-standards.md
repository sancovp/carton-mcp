# Code Standards — carton-mcp

## Onion architecture (the layering rule for all KV/graph code)

```
carton_kv.py            PURE lib — stdlib only, no neo4j, no I/O. New capability = lib fn + unit test FIRST.
   └── carton_utils.py  neo4j-bound WRAPPERS (edit_carton_obj, check_kv_refs, register_kv_schemas,
                        validate_carton_obj, expand_carton_refs) + CartOnUtils business logic.
        └── server_fastmcp.py   THIN MCP tools — dispatch + formatting only, no business logic.
```
Cross-cutting consumers that must stay in lockstep with the lib: `add_concept_tool.auto_link_description` (fence-opacity masking) and the daemon's TWO parse paths (`parse_queue_file_to_concepts` / `process_queue_file` → `batch_create_concepts_neo4j` fence guard). Editing any of these REQUIRES the `edit-carton-kv` dev-flow (see `context/ai-workflow-rules.md`).

## Install / deploy discipline

- The RUNNING code is the INSTALLED package, never the source tree. After ANY source edit:
  `pip install --no-deps /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp` — ALWAYS `--no-deps` (never re-resolve transitive deps; never `--force-reinstall`; never `-e`).
- Then `reconnect_mcp carton` to reload the MCP — NEVER pkill/kill MCP processes (`.claude/rules/mcp-reconnect-is-user-only.md`).
- Transport is stdio (`mcp.run()` with no arg); never SSE; never blocking queries at module import level in `server_fastmcp.py` (`.claude/rules/carton-mcp-transport.md`).

## Daemon restart needs explicit env vars — NON-NEGOTIABLE

The observation_worker_daemon is a standalone process; it does NOT inherit the MCP's `.claude.json` env. Restart ONLY with (`.claude/rules/daemon-needs-env-vars.md`):

```bash
NEO4J_URI="bolt://host.docker.internal:7687" \
NEO4J_USER="neo4j" \
NEO4J_PASSWORD="password" \
HEAVEN_DATA_DIR="/tmp/heaven_data" \
GIINT_TREEKANBAN_BOARD="poimandres_v2" \
nohup python3 -m carton_mcp.observation_worker_daemon > /tmp/carton_daemon.log 2>&1 &
```
Then check `/tmp/carton_daemon.log` for "Neo4j shared connection established".

## Config / env conventions

- All config flows through `ConceptConfig` (`concept_config.py`) with env fallbacks: `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD`, `HEAVEN_DATA_DIR` (default `/tmp/heaven_data`), `GITHUB_PAT` / `CARTON_REPO_URL`. Do not add new JSON-file config (that pattern died with `wiki_config.py`).
- Tests that import the package MUST set an isolated `HEAVEN_DATA_DIR` (tempdir) BEFORE the import, so queue writes never reach the real daemon (pattern: `test_edit_carton_obj.py:17`).

## Testing gates

- Lib gate: the 4 pure/stubbed suites green — `test_carton_kv.py`, `test_carton_kv_schema.py`, `test_edit_carton_obj.py`, `test_linker_fence_opacity.py` (each runs standalone: `python3 <file>`).
- E2E gate (KV changes): through the REAL MCP surface per the `edit-carton-kv` skill — "it imported"/"lib tests passed" is NOT the gate.
