# Project Overview — carton-mcp

## What this IS

**carton-mcp** is the persistent knowledge-graph MCP for the GNOSYS container: a stdio FastMCP server ("carton") over a **neo4j `:Wiki` SOUP store** (nodes: `n`=name, `d`=description, `c`=canonical, `t`=timestamp) plus a **ChromaDB RAG layer** (semantic search over routed collections), an **observation-queue daemon** (the single Neo4j write path), and a **wiki projection** (markdown `_itself.md` files under `$HEAVEN_DATA_DIR/wiki/concepts/`). It is the lossless store the journal CLI and the conversation timeline write into, and the graph every `get_concept`/`query_wiki_graph`/`chroma_query` call reads.

## Monorepo position

- Canonical source: `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/` (knowledge layer of the monorepo; legacy dev clone `/home/GOD/carton_mcp/` is NEVER edited).
- Installs as the flat package `carton_mcp` (`pyproject.toml`: `package-dir = {"carton_mcp" = "."}`); the RUNNING code is the installed package — deploy via `pip install --no-deps` + `reconnect_mcp carton`.
- Transport: stdio, configured in `/home/GOD/.claude.json` → `mcpServers.carton` (never SSE — see `.claude/rules/carton-mcp-transport.md`).

## The main parts (each has a 1:1 doc(m) in `docs/mirror/`)

- `server_fastmcp.py` — the MCP entrypoint; every tool/prompt; overflow-file formatting.
- `add_concept_tool.py` — the concept-creation engine: validate → queue envelope → return; also the Aho-Corasick wiki-linker with CartonObj fence-opacity.
- `observation_worker_daemon.py` — drains `$HEAVEN_DATA_DIR/carton_queue/`; ALL Neo4j writes; fence-preservation guard; wiki-file writing; linker thread.
- `carton_utils.py` — business logic between MCP layer and backends; the KV wrappers; `CartOnUtils`.
- `carton_kv.py` — the PURE CartonObj fence parser/normalizer/op-applier (innermost onion layer).
- `smart_chroma_rag.py` — ChromaDB RAG engine + concept→collection routing.
- `ontology_graphs.py` — CartON's internal structural type system / self-healing scaffolds.
- `substrate_projector.py` — CartON → substrate (file/Discord/registry/env/skill/rule) materialisation; MEMORY.md compiler.
- `concept_config.py` — the env-var config object (`wiki_config.py` is its dead legacy predecessor).
- Maintenance scripts: `backfill_wiki_files.py`, `migrate_inverse_relationships.py`.
- Lib-gate tests: `test_carton_kv.py`, `test_carton_kv_schema.py`, `test_edit_carton_obj.py`, `test_linker_fence_opacity.py` (+ the manual `test_relationship_constraints.py` harness).

## Where to go deeper

- `docs/mirror/<module>.py.md` — the 1:1 impl doc for each module (start with `server_fastmcp.py.md`).
- `context/architecture.md` — the write/read pipelines.
- `context/code-standards.md` — onion architecture + deploy/restart discipline.
