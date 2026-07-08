# doc(m): observation_worker_daemon.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/observation_worker_daemon.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

The queue-draining background daemon that performs ALL Neo4j writes for the CartON knowledge graph. It watches `$HEAVEN_DATA_DIR/carton_queue/` for JSON queue files dropped by the MCP server (`add_concept_tool`), parses them into flat concept lists, batch-writes to Neo4j via UNWIND Cypher, applies `desc_update_mode` (append/prepend/replace/skip) with a section-level dedup pass and a fence-preservation guard, creates `REQUIRES_EVOLUTION` stubs for SOUP concepts, enforces GIINT ontology completeness, routes fully-admitted SYSTEM_TYPE concepts to substrate projectors (skill/rule crystallization), runs PBML auto-lane-move on phase-completion triggers, resolves `_Unnamed` stubs, writes wiki markdown files for ChromaDB RAG, and runs a background linker thread that rewrites `n.d` with wiki hyperlinks plus a vocabulary-coverage score and connects concepts to the active conversation timeline. It is the single write path for all CartON `:Wiki` node content; nothing else writes Neo4j node content in the normal flow.

---

## Surface (1:1 — every public thing, in file order)

- `create_wiki_files_for_concepts(concepts_data: list) -> dict`  — `observation_worker_daemon.py:38`
  - Creates `$HEAVEN_DATA_DIR/wiki/concepts/<name>/<name>_itself.md` for each concept. Builds an Overview section from `description` and a Relationships section grouping targets by type, rendered as `- name rel_type [target](../target/target_itself.md)` wiki links.
  - Produces the filesystem mirror that ChromaDB RAG indexes. Called from Phase 2.5b in the main worker loop (:1696) after a successful Neo4j batch write.
  - Returns `{files_created, files_skipped, errors}`. `files_skipped` is always 0 — the variable is initialized at :57 but never incremented anywhere in the function body (dead counter).

- `batch_create_concepts_neo4j(concepts_data: list, shared_connection) -> dict`  — `observation_worker_daemon.py:118`
  - Core write function. All Neo4j MERGE/SET for concept nodes and relationships happens here via UNWIND.
  - **Index creation** (:141-143): ensures `wiki_name` on `:Wiki(n)` and `wiki_canonical` on `:Wiki(c)` indexes exist; idempotent.
  - **Section-level dedup** (:166-226): for `append` rows, fetches current `n.d` from Neo4j, strips wiki links via a multi-pass `re.sub` loop (:194-208) using `_itself.md` as anchor, splits on `\n\n---\n\n`, compares stripped sections, and downgrades `update_mode` to `'skip'` when all incoming sections already exist. Prevents paragraph duplication on repeated daemon runs.
  - **Fence-preservation guard** (:228-246): for `replace` rows only, fetches current `n.d`, calls `carton_kv.carry_forward_fences` to re-inject any `CartonObj` fence present in the old description but absent from the incoming one — except names listed in `removed_fences`. Wrapped in broad `except` so it never blocks the write.
  - **UNWIND concept MERGE** (:252-281): `SET n.d = CASE` implements five modes: `NULL/empty → incoming`; `skip → keep old`; `replace → incoming`; `n.d == incoming or containment → no-op`; `append → old + '\n\n---\n\n' + new`; `prepend → new + '\n\n---\n\n' + old`; `else → incoming`. Sets `n.t` only when null (preserves original timestamp). Always resets `n.linked = false` and sets `n.last_modified = datetime()`.
  - **Relationship UNWIND per type** (:317-335): one UNWIND query per relationship type. **Stub-disease mechanism** (:322-328): the `MERGE (target:Wiki {n: r.target}) ON CREATE SET target.d = 'AUTO CREATED: stub node...'` clause silently creates a hollow stub for every relationship target that does not yet exist as a node. Stubs accumulate unless `target_descs` fills them or Phase 2.5d stub resolution fires.
  - **Inverse relationship generation** (:303-315): automatically generates inverse edges for `PART_OF→HAS_PART`, `HAS_PART→PART_OF`, `IS_A→HAS_INSTANCES`, `INSTANTIATES→INSTANTIATED_BY`. Doubles relationship count without caller awareness.
  - **KV schema registration** (:339-349): for any concept whose description contains `'CartonObj'`, calls `carton_utils.register_kv_schemas` to add `IS_A Carton_Kv_Schema` and `USED_BY_KV` edges. Wrapped in broad `except`.
  - **SOUP promotion trigger** (:352): calls `check_and_promote_soup_items` — which immediately returns 0 (DISABLED). The `promoted` field is always 0.
  - Returns `{concepts_created, relationships_created, errors, promoted}`.

- `check_and_promote_soup_items(graph, new_concept_names: list) -> int`  — `observation_worker_daemon.py:364`
  - **DISABLED.** Opens with `return 0` at line 365; all code lines 366-440 are unreachable dead code. Docstring: "SOMA validates inline. No background polling needed."
  - The unreachable body contained a YOUKNOW re-validation loop deleting `REQUIRES_EVOLUTION` edges when a d-chain completes. This is entirely bypassed. SOUP→ONT promotion only happens in Phase 2.5a when `is_code=True` or `is_system_type=True` is set on the incoming concept.

- `parse_queue_file_to_concepts(queue_file: Path) -> list`  — `observation_worker_daemon.py:443`
  - Parses one queue JSON file into a flat list of concept dicts. Three format branches:
    - **`raw_concept` / `concept_name` key** (:467-501): single concept; converts relationships list-of-dicts to dict form; forwards `desc_update_mode` (:484), `removed_fences` (:485-486), `is_soup`, `soup_reason`, `is_code`, `is_system_type`, `source`, `target_descs`, `skip_ontology_healing`, `gen_target`.
    - **`concepts` list** (:502-536): batch submission format; handles Format A `{relationship, related}` and Format B `{type, target}` relationship shapes.
    - **Observation / fallback** (:540-594): constructs a timestamped `{ts}_Observation` wrapper node; each part gets `has_tag` and `part_of` pointing at the wrapper injected into its relationships.
  - Returns `[]` on JSON parse failure (logs to stderr, does not raise).

- `process_queue_file(queue_file: Path, shared_connection=None) -> bool`  — `observation_worker_daemon.py:598`
  - **DEAD CODE — zero live callers.** Verified by grep: the only references to `process_queue_file` in the repo are a comment at line 486 of this file and a docstring in `carton_utils.py:59`. The main worker loop calls `parse_queue_file_to_concepts` + `batch_create_concepts_neo4j` directly.
  - Contains a second latent bug: `queue_data` at line 695 is undefined in that scope (`observation_data` is the local name). Would raise `NameError` if ever called via the `raw_concept` branch.
  - Dead branches: `timeline_merge` (transfers `CREATED_DURING` edges from Unnamed→real Conversation), `raw_concept` (calls `batch_create_concepts_neo4j` + MEMORY tier recompile with 60s debounce), observation batch (calls `_add_observation_worker`).

- `git_commit_all_changes()`  — `observation_worker_daemon.py:771`
  - Runs `git add . && git commit` in `$HEAVEN_DATA_DIR/wiki/`. Only reached when `CARTON_GIT_AUTO=true` AND queue empties with new processed files since last push. Disabled by default (comment :1741-1743: "causes high IO load").

- `sync_rag_incremental(changed_files: list[str] | None = None)`  — `observation_worker_daemon.py:815`
  - Two paths: **targeted** (:838-859) routes each `*_itself.md` to its collection via `route_concept_to_collection` and calls `rag.ingest_path(upsert=True)`; **mtime-based fallback** (:861-879) full-glob-scans `wiki/concepts/**/*_itself.md` into `domain_knowledge`. Uses module-level `_rag_cache` dict (:35) to reuse `SmartChromaRAG` instances per collection. Full fallback commented out in idle path (:1746).

- `git_push_if_needed()`  — `observation_worker_daemon.py:886`
  - Checks unpushed commits via `git rev-list`; pushes with GitHub PAT injected into remote URL. Reads `GITHUB_PAT`, `REPO_URL`, `BRANCH` (default `main`). Only reached when `CARTON_GIT_AUTO=true`.

- `_create_shared_neo4j()`  — `observation_worker_daemon.py:937`
  - Instantiates `KnowledgeGraphBuilder` from `heaven_base.tool_utils.neo4j_utils` using `NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD`; calls `_ensure_connection()`. Returns `None` on failure.

- `_ensure_neo4j_alive(conn)`  — `observation_worker_daemon.py:954`
  - Health-checks connection with `RETURN 1`; reconnects via `_create_shared_neo4j()` if stale. Returns working connection or `None`. Called at start of every non-empty-queue iteration (:1371).

- `_STOP_WORDS`  — `observation_worker_daemon.py:970`
  - Module-level frozenset of ~60 common English stop words used by `compute_description_score`.

- `compute_description_score(description: str, concept_cache: list) -> int`  — `observation_worker_daemon.py:981`
  - Returns 0-100: percentage of meaningful words in `description` appearing in CartON concept-name token set. Builds tokens by splitting concept names on `_` plus the full lowercased name. Filters stop words and single-character tokens. Returns 0 if either input is empty.
  - Called by `linker_thread` after auto-linking; result stored to `n.score` on each `:Wiki` node.

- `CHAT_SOURCES`, `SYSTEM_SOURCES`, `ODYSSEY_SOURCES`  — `observation_worker_daemon.py:1013-1015`
  - Module-level sets classifying concept `source` field values. `CHAT_SOURCES = {"agent", "dragonbones_hook", "session_start"}` is used by `link_concepts_to_timeline`. `SYSTEM_SOURCES` and `ODYSSEY_SOURCES` are defined but not referenced in live logic.

- `ACTIVE_CONV_MARKER`  — `observation_worker_daemon.py:1018`
  - `Path("/tmp/heaven_data/active_conversation.json")` — read by `link_concepts_to_timeline` for timeline linking.

- `log_system_event(neo4j_conn, event_type: str, description: str, source: str)`  — `observation_worker_daemon.py:1021`
  - Writes a `System_Event_{ts}_{event_type}` `:Wiki` node directly to Neo4j bypassing the queue. Links under `System_Timeline → Day_{YYYY_MM_DD}`. Sets `linked=true` and `timeline_linked=true` so the linker thread skips it.

- `link_concepts_to_timeline(neo4j_conn)`  — `observation_worker_daemon.py:1055`
  - Reads `ACTIVE_CONV_MARKER` for active conversation concept name (prefers `real_concept` over `concept_name`). Queries up to 200 `:Wiki` nodes with chat sources having no `CREATED_DURING` edge, not starting with `'Unnamed_Conversation'`. Batch-creates `CREATED_DURING` edges and sets `c.timeline_linked = true`. Called every linker-thread cycle.

- `ODYSSEY_CONCEPT_TYPES`  — `observation_worker_daemon.py:1107`
  - Module-level set: `{Episode, Journey, Epic, Odyssey, Executive_Summary, Iteration_Summary, Phase, Subphase, Framework_Report}`.

- `link_concepts_to_odyssey_timeline(neo4j_conn)`  — `observation_worker_daemon.py:1111`
  - Finds up to 100 concepts `IS_A` any `ODYSSEY_CONCEPT_TYPES` member not yet `PART_OF Odyssey_Timeline`. Batch-creates `PART_OF` edges, auto-creating `Odyssey_Timeline` if absent. Sets `c.odyssey_linked = true`. Called every linker-thread cycle.

- `linker_thread(stop_event: threading.Event)`  — `observation_worker_daemon.py:1155`
  - Background daemon thread started by `worker_daemon`. Runs until `stop_event` set.
  - Own dedicated Neo4j connection independent of `shared_neo4j` (:1166).
  - Cache refresh every 5 minutes via `CartOnUtils.get_all_concept_names()` (:1185-1191).
  - Per-batch: queries 100 `:Wiki` nodes `linked=false OR null`, ordered by `n.t DESC` (:1194-1199). For each: calls `auto_link_description` + `compute_description_score`; writes linked description and score to Neo4j; marks `linked=true` on any exception to prevent infinite retry (:1241-1248).
  - Calls `link_concepts_to_timeline` and `link_concepts_to_odyssey_timeline` each cycle (:1268-1270).
  - Sleeps 30s when no unlinked concepts; 1s between batches; 0.01s between individual updates.

- `worker_daemon()`  — `observation_worker_daemon.py:1285`
  - Main entry point. Acquires `fcntl.LOCK_EX | LOCK_NB` flock on `/tmp/carton_worker.pid` (:1303-1313); exits code 0 gracefully if lock held by another worker.
  - Starts ChromaDB HTTP server subprocess on port 8101 (:1324-1332) with 2s startup wait.
  - Validates `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`; exits code 1 if any missing (:1336-1343).
  - Creates `shared_neo4j`, starts `linker_thread` as daemon thread (:1352-1358).
  - **Main poll loop** (:1364, 1s sleep): `queue_dir.glob('*.json')` sorted.
    - **Phase 1** (:1382-1389): `parse_queue_file_to_concepts` on up to 2000 files; accumulates `all_concepts`; tracks `failed_files`.
    - **Phase 2** (:1395-1438): `batch_create_concepts_neo4j(all_concepts, shared_neo4j)`. Creates `REQUIRES_EVOLUTION` for `is_soup` concepts (:1407-1421). Writes `target_descs` to stubs (:1423-1438), overwriting only null/empty/AUTO-CREATED `n.d`.
    - **Phase 2.5** (:1443-1469): GIINT ontology enforcement via `ensure_ontology_completeness` for concepts whose `is_a` intersects GIINT type set. Skips `skip_ontology_healing=True` concepts.
    - **Phase 2.5a** (:1471-1522): SYSTEM_TYPE projection. `is_code` concepts: deletes `REQUIRES_EVOLUTION` (SOUP→CODE, :1485-1492). `is_system_type` concepts: dispatches `project_to_skill` if `is_a` contains `'skill'` (:1508-1511), or `project_to_rule` if `'claude_code_rule'` (:1512-1515). **Bug at :1511 and :1515 (VERIFIED)**: `log_system_event(shared_connection, ...)` — `shared_connection` is undefined in `worker_daemon`; correct variable is `shared_neo4j`. `except Exception` at :1519 silently swallows the `NameError`; `System_Timeline` is never updated for crystallization events.
    - **Phase 2.5b comment** (:1524-1530): removal notice for legacy rule-bypass path.
    - **Phase 2.5c** (:1532-1651): PBML auto-lane-move. Detects `done_signal`, `inclusion_map`, `bml_learning`, `odyssey_learning_decision` in `is_a`. Resolves GIINT hierarchy via 5-hop path query using `shared_neo4j.driver.session()` directly (:1577-1584). Calls `update_task_status`. For `done_signal`: daemon thread calls `odyssey.utils.dispatch_chain` (:1614-1623). For `odyssey_learning_decision`: moves matching TK card from `learn` to `archive` via `HeavenBMLSQLiteClient` (:1629-1644). Reads `GIINT_TREEKANBAN_BOARD`.
    - **Phase 2.5d** (:1653-1692): `_Unnamed` stub resolution. For each concept with `part_of` + `is_a`, checks parent for edge to `{is_a_type}_Unnamed`; replaces with edge to real concept; writes `EVOLVED_TO/EVOLVED_FROM`.
    - **Phase 2.5b (live, second occurrence)** (:1694-1708): `create_wiki_files_for_concepts` + `sync_rag_incremental(changed_files=written_paths)`.
    - **Phase 3** (:1710-1735): moves parsed files to `processed/` on success; `failed/` on Neo4j failure or parse failure.
  - `KeyboardInterrupt`: sets `linker_stop_event`, breaks, joins linker 5s timeout, prints final stats.

---

## Dependencies

### stdlib
- `os`, `sys`, `time`, `json`, `traceback`, `threading`, `pathlib.Path`, `typing.Dict`, `typing.Any`, `datetime.datetime`, `collections.defaultdict`, `re`, `fcntl`, `subprocess`

### third-party
- `chromadb` — CLI subprocess for HTTP server on port 8101

### intra-repo
- `carton_mcp.add_concept_tool`: `_add_observation_worker`, `get_observation_queue_dir`, `auto_link_description`, `normalize_concept_name`, `OBSERVATION_TAGS`
- `carton_mcp.carton_kv`: `carry_forward_fences`
- `carton_mcp.carton_utils`: `register_kv_schemas`, `CartOnUtils`
- `carton_mcp.substrate_projector`: `project_to_skill`, `SkillSubstrate`, `project_to_rule`, `RuleSubstrate`, `compile_memory_tier`
- `carton_mcp.ontology_graphs`: `ensure_ontology_completeness`
- `carton_mcp.smart_chroma_rag`: `SmartChromaRAG`, `route_concept_to_collection`
- `heaven_base.tool_utils.neo4j_utils`: `KnowledgeGraphBuilder`
- `llm_intelligence.projects`: `update_task_status`
- `odyssey.utils`: `dispatch_chain` (optional; PBML done_signal only)
- `youknow_kernel.compiler`: `youknow` (dead code in `check_and_promote_soup_items` only)
- `heaven_bml_sqlite.heaven_bml_sqlite_client`: `HeavenBMLSQLiteClient`

### filesystem / external state
- `$HEAVEN_DATA_DIR/carton_queue/*.json` — input queue (read + rename to processed/failed)
- `$HEAVEN_DATA_DIR/carton_queue/processed/` — successfully consumed files
- `$HEAVEN_DATA_DIR/carton_queue/failed/` — parse-failed or Neo4j-failed files
- `$HEAVEN_DATA_DIR/wiki/concepts/` — wiki markdown files written by `create_wiki_files_for_concepts`
- `$HEAVEN_DATA_DIR/chroma_db/` — ChromaDB persistence directory
- `$HEAVEN_DATA_DIR/active_conversation.json` — read by `link_concepts_to_timeline`
- `/tmp/carton_worker.pid` — exclusive flock PID file
- `/tmp/chroma_server.log` — ChromaDB subprocess stdout/stderr
- `/tmp/memory_compile_last.txt` — debounce timestamp (dead code only)

### consumers
- `carton_mcp.server_fastmcp` — launches this daemon as a background process on MCP startup
- No other module imports this file; it is a standalone daemon script

---

## Notes

1. **`process_queue_file` (:598) is entirely dead code.** No live caller exists in `carton-mcp/`. Main loop bypasses it. Contains latent `NameError`: `queue_data` at line 695 is undefined (`observation_data` is the local name). Do not add callers without fixing this first.

2. **`NameError` bug at :1511 and :1515 (VERIFIED)**: `log_system_event(shared_connection, ...)` — `shared_connection` is undefined in `worker_daemon` scope; correct variable is `shared_neo4j`. Inner `except Exception` at :1519 silently swallows it. Effect: `System_Timeline` is never updated for Skill or Rule crystallization events.

3. **`check_and_promote_soup_items` (:364) is disabled** via `return 0` at line 365. Lines 366-440 unreachable. Background SOUP→ONT promotion via YOUKNOW polling does not occur.

4. **Stub-disease mechanism** (:322-328): every relationship write to an unknown target auto-creates a hollow `'AUTO CREATED'` stub node. Stubs accumulate unless filled by `target_descs` (:1423-1438) or Phase 2.5d resolution (:1653-1692).

5. **Inverse relationships silently generated** for `PART_OF`, `HAS_PART`, `IS_A`, `INSTANTIATES` (:303-315). Relationship count doubles without caller awareness.

6. **Phase label collision**: two blocks labeled "Phase 2.5b" in `worker_daemon` — removal notice at :1524 and live wiki-file-creation at :1694. The live block is the second one.

7. **`files_skipped`** in `create_wiki_files_for_concepts` always 0: initialized at :57, never incremented.

8. **Required env vars**: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` (exits code 1 if absent); `HEAVEN_DATA_DIR` (default `/tmp/heaven_data`); `GIINT_TREEKANBAN_BOARD` (PBML archive move — silently skipped if unset, :1630).
