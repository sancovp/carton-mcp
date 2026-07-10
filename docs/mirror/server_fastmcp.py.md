# doc(m): server_fastmcp.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/server_fastmcp.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

This is the stdio FastMCP server that exposes all CartON tools to Claude Code via the MCP protocol. It creates a single `FastMCP("carton")` instance at module load, registers every tool and prompt against it, establishes a persistent shared Neo4j connection (`KnowledgeGraphBuilder`) and a module-level `CartOnUtils` instance, bootstraps ontology types, and then runs the transport loop via `main()` → `mcp.run()`. The server owns the boundary between Claude Code tool calls and the CartON knowledge-graph backend (Neo4j + ChromaDB). It is the only MCP entry-point for CartON; all write paths queue through the observation worker daemon, not directly from tool code — except `set_properties`, `remove_relationship`, and `add_to_collection`, which write synchronously and directly to Neo4j.

---

## Surface (1:1 — every public thing, in file order)

### Module-level helpers and state

- `_get_rag(collection_name) -> SmartChromaRAG` — `server_fastmcp.py:38`
  - Returns a cached `SmartChromaRAG` instance keyed by collection name.
  - Reads `HEAVEN_DATA_DIR` env (default `/tmp/heaven_data`), appends `chroma_db/`, creates instance on first call per collection.
  - Used by `chroma_query` and `carton_management(sync_rag=True)`.

- `_strip_md(text) -> str` — `server_fastmcp.py:50`
  - Delegates to `strip_wiki_links` from `carton_utils`, then strips whitespace. Belt-and-suspenders: data from Neo4j arrives pre-stripped at the query layer; this guards any text built outside that path.

- `_dedup_desc(text) -> str` — `server_fastmcp.py:59`
  - Splits description on double newlines, removes duplicate paragraphs via seen-set. Does not truncate. Used to prevent bloat from repeated-append cycles.

- `_fmt(data) -> str` — `server_fastmcp.py:81`
  - Top-level formatter. Calls `_fmt_inner`; if result exceeds `_OVERFLOW_THRESHOLD` (10 000 chars), writes full text to `HEAVEN_DATA_DIR/query_overflow/overflow_<ts>.txt` and returns truncated prefix + file path pointer.

- `_fmt_inner(data) -> str` — `server_fastmcp.py:92`
  - Recursive inner formatter (no truncation). Handles str (dedup+strip), dict (unwraps `result` key), list (comma-join), and scalar. Called only by `_fmt`.

- `_OVERFLOW_THRESHOLD` — `server_fastmcp.py:78` — int constant `10000`.
- `_OVERFLOW_DIR` — `server_fastmcp.py:79` — `Path(HEAVEN_DATA_DIR) / "query_overflow"`.
- `_rag_cache: dict` — `server_fastmcp.py:36` — module-level dict of cached `SmartChromaRAG` instances keyed by collection name.
- `_concept_stash: dict` — `server_fastmcp.py:137` — module-level dict holding stashed payloads for failed `add_concept` or `add_observation_batch` calls; allows callers to retry with only missing fields.
- `_ALL_RAG_COLLECTIONS: list` — `server_fastmcp.py:2565` — the seven canonical collection names (`domain_knowledge`, `skillgraphs`, `flightgraphs`, `toolgraphs`, `patterns`, `conversations`, `observations`) queried in aggregate when `chroma_query` receives the default `"carton_concepts"` collection name.
- `_RESERVED_PROPERTY_KEYS` — imported from `carton_utils` at `server_fastmcp.py:28` — the set of managed neo4j property names (`n`, `d`, `t`, `c`, `linked`, `score`, `source`, `timeline_linked`, `odyssey_linked`, `system_generated`, `last_modified`) that `set_properties` refuses to touch and `get_concept` excludes from the Props block.

- `git_push_batch() -> str` — `server_fastmcp.py:183`
  - Pushes all local commits in the wiki repo to remote using `GITHUB_PAT`/`REPO_URL`/`BRANCH` env vars. Returns warning string if vars missing or push fails. Non-blocking.
  - Called only by the `with_git_push` decorator; that decorator is defined but not applied to any current `@mcp.tool()` function.

- `with_git_push(func)` — `server_fastmcp.py:219`
  - Decorator that calls `git_push_batch()` after tool execution and appends the push result. Currently unused — no tool is decorated with it.

- `ConceptRelationship(BaseModel)` — `server_fastmcp.py:238`
  - Pydantic model: `relationship: str`, `related: List[str]`. Used for optional `relationships` params.

- `_format_concept_result(concept_name, raw_result) -> str` — `server_fastmcp.py:242`
  - Formats raw string from `add_concept_tool_func` into a CartON banner with file/Neo4j status indicators. Parses `[SOUP: ...]`, `[SOMA ERROR: ...]`, `[SOMA error: ...]` patterns.

- `_check_observation_geometry(observation_data) -> str | None` — `server_fastmcp.py:281`
  - Validates that each concept in all five observation tags has `is_a`, `part_of`, `instantiates`, and at least one `has_*` relationship. Returns error string or `None`. Non-blocking warning in observation tools.

- `_ensure_identity_collection_exists(collection_name, agent_identity)` — `server_fastmcp.py:705`
  - Checks Neo4j for an existing collection node; creates it via `add_concept_tool_func` with `IS_A Identity_Collection` if absent. Swallows exceptions with a warning.

- `_ensure_daemon_running()` — `server_fastmcp.py:3049`
  - Uses `pgrep` to check if `observation_worker_daemon.py` is running; if not, spawns it via `subprocess.Popen` with required env vars, logging to `/tmp/carton_worker.log`. Called from `main()` before `mcp.run()`.

---

### MCP tools (registered with @mcp.tool())

- `add_concept(concept_name, is_a, part_of, instantiates, concept, relationships, desc_update_mode, hide_youknow, clear_stash, source, typed_values) -> str` — `server_fastmcp.py:311`
  - Creates or updates a concept. `is_a`, `part_of`, `instantiates` are REQUIRED lists; merged with optional `relationships` and passed to `add_concept_tool_func`.
  - `desc_update_mode`: `"append"` (default), `"prepend"`, `"replace"`, or `"path"` (reads file at concept path, then switches to `"replace"`).
  - `clear_stash=True` discards any prior stash for this name before processing.
  - On exception, stashes full payload under `_concept_stash[concept_name]`; next call with same name merges from stash.
  - Delegates to `add_concept_tool_func` from `.add_concept_tool`.

- `edit_carton_obj(concept_name, kvobj_name, key_path, op, value) -> str` — `server_fastmcp.py:402`
  - Reads or edits one leaf of a `<CartonObj name=...>` KV fence embedded in a concept description.
  - `op`: `"get"` | `"set"` | `"append"` | `"remove"` | `"remove_fence"` (only way to delete an entire fence).
  - For `set`/`append`: value interpreted as bare `Title_Underscore` ref -> `{"$ref": v}`, valid JSON, or plain string.
  - `get` returns value immediately; write ops queue to the daemon (applied asynchronously).
  - Delegates to `_edit_carton_obj_lib` from `carton_utils`.

- `validate_carton_obj(concept_name, kvobj_name) -> str` — `server_fastmcp.py:462`
  - Validates a KV fence: (a) body against `schema=<Concept>` JSON-schema if present; (b) all bare `Title_Underscore` refs resolve to existing concepts with fuzzy did-you-mean suggestions.
  - Returns VALID/INVALID report with per-key error details.
  - Delegates to `_validate_carton_obj_lib` from `carton_utils`.

- `set_properties(concept_name, properties, mode) -> str` — `server_fastmcp.py:503`
  - Sets or removes arbitrary neo4j node properties on an EXISTING concept node — **synchronous direct write** (not queued through the daemon). Safe because properties never touch `n.d`, so no linker/fence machinery is involved.
  - `mode="merge"` (default): sets the given key/value pairs on the node via SET. `mode="remove"`: removes the named keys (values ignored).
  - **Reserved-key refusal**: any key in `_RESERVED_PROPERTY_KEYS` (`n`, `d`, `t`, `c`, `linked`, `score`, `source`, `timeline_linked`, `odyssey_linked`, `system_generated`, `last_modified`) is refused and reported in the return value, never written.
  - Nested dict values are refused; only str/int/float/bool and flat lists of those are accepted.
  - Returns a summary of which keys were set, removed, or refused. On lib-level failure returns `❌ <error>`.
  - This never creates nodes — the concept must already exist.
  - Delegates to `_set_concept_properties_lib` (imported from `carton_utils` as `set_concept_properties` at `server_fastmcp.py:25`).

- `query_by_properties(where, limit) -> str` — `server_fastmcp.py:543`
  - Finds concepts whose neo4j node properties exactly match every key/value in `where` (AND semantics). Exact-match lookup over the structured property surface set by `set_properties`.
  - Property values are passed as Cypher parameters (never interpolated) — injection-safe.
  - `limit` defaults to 25.
  - Returns each matching concept's name plus the value of every key in `where` via `_fmt`, or the string `"(no concepts match)"`.
  - Delegates to `_query_concepts_by_properties_lib` (imported from `carton_utils` as `query_concepts_by_properties` at `server_fastmcp.py:26`).

- `remove_relationship(source, rel_type, target) -> str` — `server_fastmcp.py:566`
  - Deletes exactly the relationship `(source)-[:REL_TYPE]->(target)` — **synchronous direct write**.
  - `rel_type` is strictly sanitized against `^[A-Za-z_]+$` before use (relationship types cannot be Cypher parameters); `source` and `target` are passed as parameters.
  - Returns the count of deleted relationships (0 if that edge did not exist). On lib-level failure returns `❌ <error>`.
  - Complements `add_concept` (which creates relationships); this is the deletion counterpart introduced in commit 2d23406.
  - Delegates to `_remove_concept_relationship_lib` (imported from `carton_utils` as `remove_concept_relationship` at `server_fastmcp.py:27`).

- `add_document_concept(concept_name, description, canonical_path, template, relationships) -> str` — `server_fastmcp.py:589`
  - Indexes a document with `IS_A Document_Concept`, `has_canonical_path`, optional `uses_template`. Routes through `add_observation`; sets `hide_youknow=True`.

- `add_observation_batch(observation_data, hide_youknow) -> str` — `server_fastmcp.py:566`
  - Creates structured observation with five tags. Warns (non-blocking) on geometry errors. Merges from `_concept_stash["_observation_pending"]` if prior call failed; stashes on exception. Delegates to `add_observation`.

- `observe_from_identity_pov(observation_data, agent_identity, hide_youknow) -> str` — `server_fastmcp.py:615`
  - Same as `add_observation_batch` but resolves agent identity from `AGENT_IDENTITY` env var (priority) or param. Transforms `has_actual_domain` -> `has_domain`, strips `has_subdomain`/`has_subsubdomain`, adds `part_of -> {identity}_Collection` to all concepts. Ensures identity collection exists.

- `carton_management(...) -> str` — `server_fastmcp.py:755`
  - Multi-flag management utility. Boolean parameters activate independent operations:
    - `restart_bg_server`: kills daemon via `pkill`, spawns new one with env vars.
    - `get_git_repo_url`: returns `REPO_URL`.
    - `get_carton_dir`: returns `HEAVEN_DATA_DIR/carton_queue` path.
    - `get_carton_guide`: returns usage guide string.
    - `get_requires_evolution_list`: paginates (100/page via `page` param) concepts with `REQUIRES_EVOLUTION` relationship.
    - `sync_rag`: bulk-syncs all Neo4j `:Wiki` concepts to ChromaDB via `route_concept_to_collection`; skips noise patterns; batch size 500.
    - `check_failed_observations`: reports count in `carton_queue/failed/`.
    - `retry_failed_observations`: moves files marked `"fixed": true` back to queue dir.
    - `enable_gps` / `disable_gps` / `get_gps_status`: manages `HEAVEN_DATA_DIR/carton_gps_enabled` flag file.

- `rename_concept(old_concept_name, new_concept_name, reason) -> str` — `server_fastmcp.py:1109`
  - Renames a concept: creates new node inheriting old description, updates all incoming/outgoing rels, creates bidirectional `evolved_from`/`evolved_to` links, preserves old concept as history.
  - Delegates to `rename_concept_func` from `.add_concept_tool`.

- `observe_auto_meta_test(test_subject, fix_description) -> str` — `server_fastmcp.py:1146`
  - **STUB. Raises `NotImplementedError` unconditionally.** Registered as MCP tool but unusable.

- `run_experiment(experiment_hypothesis, flight_config_name) -> str` — `server_fastmcp.py:1164`
  - **STUB. Raises `NotImplementedError` unconditionally.** Registered as MCP tool but unusable.

- `query_wiki_graph(cypher_query, parameters) -> str` — `server_fastmcp.py:1184`
  - Executes arbitrary Cypher on `:Wiki` namespace. Read-only enforced by `carton_utils._validate_query_safety` (blocks `CREATE`/`MERGE`/`DELETE`). Warns on lowercase concept names in empty results. Delegates to `utils.query_wiki_graph`.

- `get_concept_network(concept_name, depth, rel_types) -> str` — `server_fastmcp.py:1232`
  - Gets N-hop relationship neighborhood of a concept. `depth` 1-3, optional `rel_types` filter. Delegates to `utils.get_concept_network`.

- `get_concept(concept_name, refresh_code, expand_refs, depth) -> TextContent` — `server_fastmcp.py:1359`
  - Retrieves concept description + all outgoing relationships.
  - `refresh_code=True`: calls `OWLReasoner().refresh_code_reality()` before fetching.
  - `expand_refs=True, depth>0`: calls `expand_carton_refs` from `carton_utils` on the returned description — **render-only, stored `n.d` never changed** (`server_fastmcp.py:1421-1426`) — replaces bare `Title_Underscore` ref tokens with referenced concept content, recursive to `depth`, cycle-guarded.
  - **Props block** (added in commit 2d23406): the Cypher query now fetches `properties(c)` (`server_fastmcp.py:1406`). After the Description line and before the Rels block, if any user-set properties exist, a `Props:{k: v, ...}` line is rendered with keys sorted alphabetically (`server_fastmcp.py:1451-1456`). Reserved/managed fields in `_RESERVED_PROPERTY_KEYS` are excluded. The block is omitted entirely when there are no non-reserved properties.
  - Shows live SOMA status: builds observation from outgoing rels, POSTs to SOMA daemon (port 8091), parses `soup_gaps`, `failure_error`, `all_core_requirements_met`, `unmet=N` to classify as SOUP / CODE / SYSTEM_TYPE.
  - Returns `TextContent` (not plain `str`).

- `youknow_sparql(query) -> str` — `server_fastmcp.py:1450`
  - Runs SPARQL against YOUKNOW OWL ontology via `OWLReasoner().query_sparql()`. Not the Neo4j graph. Gracefully returns error if `youknow_kernel` unavailable.

- `get_history_info(info_type, id) -> str` — `server_fastmcp.py:1478`
  - Traverses typed conversation history concepts in CartON. `info_type` values:
    - `"iteration"`: all `HAS_USER_MESSAGE_N` / `HAS_AGENT_MESSAGE_N` / `HAS_TOOL_CALL_N` components sorted by sequence.
    - `"conversation"`: all `Iteration_*` nodes under a conversation, recursively calling `get_history_info("iteration", ...)`.
    - `"session"`: all `Conversation_*` nodes with iteration counts (no full recursion).
    - `"context_bundle"`: finds all Read tool calls preceding an Edit to a given file path in the same iteration.
    - `"iteration_summary"`: single `Iteration_Summary_*` node.
    - `"all_iteration_summaries"`: all iteration summaries for a conversation.
    - `"phase"`: single `Conversation_Phase_*` with `HAS_ITERATION_SUMMARY_N` children sorted.
    - `"all_phases"`: all phases for a conversation.
    - `"subphase"`: single `Conversation_Subphase_*` node.
    - `"all_subphases"`: all subphases for a phase.
    - `"executive_summary"`: finds by direct name, `Executive_Summary_` prefix, or `PART_OF` conversation.

- `list_missing_concepts() -> str` — `server_fastmcp.py:1854` — scans graph for referenced-but-absent concept names. Delegates to `utils.list_missing_concepts`.

- `create_missing_concepts(concepts_data) -> str` — `server_fastmcp.py:1875` — batch-creates missing concepts. Delegates to `utils.create_missing_concepts`.

- `get_recent_concepts(n, timeline) -> str` — `server_fastmcp.py:1899`
  - Returns up to `n` (max 100) concepts sorted by most-recent activity. `timeline` filter: `"chat"`, `"system"`, `"odyssey"`, `"overall"`, or `None`. Normalizes mixed timestamp types in Cypher. Always excludes `Skillgraph_` prefix.

- `calculate_missing_concepts() -> str` — `server_fastmcp.py:1982` — scans for missing refs, updates `missing_concepts.md`, commits to GitHub. Delegates to `utils.calculate_missing_concepts`.

- `deduplicate_concepts(similarity_threshold) -> str` — `server_fastmcp.py:2003` — finds duplicate concepts by name similarity (threshold 0.0-1.0, default 0.8). Delegates to `utils.deduplicate_concepts`.

- `equip_frame(frame) -> str` — `server_fastmcp.py:2027`
  - Loads observation frames from `CARTON_FRAMES_PATH` env (default `HEAVEN_DATA_DIR/carton_frames.json`). Creates with ten defaults if absent. Returns the frame's observation prompt.
  - Defaults: `skill_development`, `task_decomposition`, `meta_test`, `transfer_learning`, `exercise`, `nutrition`, `supplements`, `sleep`, `wake`, `vision_synthesis`.

- `chroma_query(query, collection_name, k, max_tokens) -> str` — `server_fastmcp.py:2575`
  - Semantic search over ChromaDB using MMR + keyword boost via `SmartChromaRAG.query`.
  - Default `"carton_concepts"` queries ALL seven `_ALL_RAG_COLLECTIONS` and merges by inverse-rank scoring.
  - Caches the ranked results to `HEAVEN_DATA_DIR/carton_last_rag_query.json` for `query_graph_from_rag_result` (the cache block defines `heaven_data_dir` locally via `os.getenv`, same pattern as the rest of the file — FIXED 2026-06-10; it formerly referenced an undefined name and the cache was never written).

- `query_graph_from_rag_result(n, scopes, max_results) -> str` — `server_fastmcp.py:2688`
  - Reads `carton_last_rag_query.json` (written by `chroma_query`'s cache block). For each of top `n` cached concepts, fetches scope-0 (concept + direct rels) and/or scope-1/2 (N-hop network) with global deduplication. Returns merged result via `_fmt`.

- `create_collection(collection_name, description, member_concepts, collection_type) -> str` — `server_fastmcp.py:2839`
  - Creates a `Carton_Collection` node (`IS_A Global_Collection | Local_Collection | Identity_Collection`) with `HAS_PART` rels to members and inverse `PART_OF` links. Bootstraps collection type hierarchy first.

- `activate_collection(collection_name) -> str` — `server_fastmcp.py:2918` — recursively traverses `HAS_PART` to retrieve all member concepts. Delegates to `utils.get_collection_concepts`.

- `add_to_collection(collection_name, concept_names) -> str` — `server_fastmcp.py:2943`
  - Adds concepts via `MERGE` of both `HAS_PART` and `PART_OF`. Uses `_neo4j_conn.execute_query` directly (bypasses `query_wiki_graph` read-only guard) — the only tool to do so.

- `list_collections() -> str` — `server_fastmcp.py:2992` — lists all `Carton_Collection` nodes with member counts. Delegates to `utils.list_all_collections`.

- `substrate_projector(substrate, target, description_only, template, get_instructions) -> str` — `server_fastmcp.py:3014`
  - Projects a CartON concept to an external substrate (file, discord, registry, env). `get_instructions=True` returns usage guide. Delegates to `carton_mcp.substrate_projector.substrate_project`.

---

### MCP prompts (registered with @mcp.prompt())

- `add_user_thought(user_quote, topic) -> str` — `server_fastmcp.py:2077` — instructs caller to call `add_concept` with verbatim quote.
- `update_known_concept(concept_name, current_description, new_info) -> str` — `server_fastmcp.py:2090` — instructs caller to merge old + new description via `add_concept`.
- `update_user_thought_train_emergently(original_concept_name, original_description, later_concept, how_it_led_to) -> str` — `server_fastmcp.py:2104` — adds `led_to` relationship tracking thought evolution.
- `sync_after_update_known_concept(concept_list, change_summary, sync_number) -> str` — `server_fastmcp.py:2124` — creates `Sync{N}` concept for version control documentation.
- `observe(description) -> str` — `server_fastmcp.py:2142` — triggers `[OBSERVATION MODE]` LLM analysis.
- `add_frame(frame_name, description) -> str` — `server_fastmcp.py:2155` — instructs caller to update `carton_frames.json`.
- `discover_patterns(n) -> str` — `server_fastmcp.py:2183` — retrospective interaction-pattern discovery for last `n` turns.
- `scientific_method(hypothesis) -> str` — `server_fastmcp.py:2210` — systematic hypothesis-testing protocol referencing CartON.
- `deep_dive(description) -> str` — `server_fastmcp.py:2242` — knowledge-gap exploration protocol.
- `krr_engineer_domain(description) -> str` — `server_fastmcp.py:2274` — KRR domain-ontology engineering protocol.
- `autobiography() -> str` — `server_fastmcp.py:2312` — guided memory-capture using Timeline hierarchy (Year/Month/Day).
- `stream() -> str` — `server_fastmcp.py:2360` — stream-of-consciousness capture with recursive imagination->reality grounding.
- `hj(story) -> str` — `server_fastmcp.py:2420` — Vogler 12-stage Hero's Journey mapping protocol.

---

### Commented-out functions (not registered as MCP tools)

- `DetectEvent_user_thought(trigger)` — `server_fastmcp.py:2517` — returns add_concept prompt chain trigger.
- `DetectEvent_concept_update(trigger)` — `server_fastmcp.py:2532` — returns file-path-based concept update instructions.
- `DetectEvent_thought_evolution(trigger)` — `server_fastmcp.py:2548` — delegates to `DetectEvent_concept_update`.
- `DetectEvent_sync_needed(trigger)` — `server_fastmcp.py:2823` — generates `Sync_{timestamp}` concept creation prompt.

---

### Entry point

- `main()` — `server_fastmcp.py:3095`
  - Console script entry point (declared in `pyproject.toml` as `carton-mcp`).
  - Calls `_ensure_daemon_running()`, then `mcp.run(transport=os.environ.get("CARTON_TRANSPORT", "stdio"))`.
  - Default transport is stdio. Repo rule forbids `CARTON_TRANSPORT=sse`.

---

## Import-time side effects and threads

All of the following execute at module import time (when Claude Code connects):

1. `mcp = FastMCP("carton")` — `server_fastmcp.py:111`.
2. `_neo4j_conn = _create_shared_neo4j()` — `server_fastmcp.py:131` — creates `KnowledgeGraphBuilder` + `_ensure_connection()`. Failure is non-fatal (returns `None`).
3. `utils = CartOnUtils(shared_connection=_neo4j_conn)` — `server_fastmcp.py:134`.
4. `utils.bootstrap_ontology_types()` — `server_fastmcp.py:141` — flag-file-guarded; runs once per installation; non-fatal on failure.
5. `utils.bootstrap_memory_ontology_types()` — `server_fastmcp.py:146` — same pattern.
6. **Background enforcement thread — DISABLED AND COMMENTED OUT** at `server_fastmcp.py:160-161`:
   `# threading.Thread(target=_deferred_enforcement, daemon=True).start()`
   Comment explains: was pegging CPU at 99% because `enforce_ontology_invariants` creates a `chromadb.PersistentClient` that never finishes. `_deferred_enforcement` (lines 153-159) is defined but never launched — dead code.

---

## Known defects (verified in code)

1. **FIXED 2026-06-10 — `chroma_query` cache write no longer fails**: the cache block now defines `heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')` locally (`server_fastmcp.py:2782`) before writing `carton_last_rag_query.json`, so the `chroma_query` → `query_graph_from_rag_result` two-tool RAG flow works. (Historical defect: the block referenced an undefined `heaven_data_dir`, the `NameError` was swallowed by the `except Exception as cache_error` warning-only handler, and the cache file was never written.)

2. **`observe_auto_meta_test` and `run_experiment` are registered tools that always raise** — `server_fastmcp.py:1161, 1182`
   - Both decorated with `@mcp.tool()` and visible to callers, but unconditionally raise `NotImplementedError`. The exception propagates unhandled.

3. **`with_git_push` decorator is defined but never applied** — `server_fastmcp.py:219`
   - No `@mcp.tool()` function uses it; git pushes never happen automatically.

---

## Dependencies

### Stdlib
- `json`, `logging`, `traceback`, `subprocess`, `os`, `re`, `threading`
- `datetime.datetime`, `pathlib.Path`, `typing.List`, `typing.Optional`, `functools.wraps`

### Third-party
- `pydantic.BaseModel`
- `mcp.server.fastmcp.FastMCP`
- `mcp.types.TextContent`

### Intra-repo
- `carton_mcp.carton_utils` — `CartOnUtils`, `strip_wiki_links`, `edit_carton_obj` (as `_edit_carton_obj_lib`), `validate_carton_obj` (as `_validate_carton_obj_lib`), `set_concept_properties` (as `_set_concept_properties_lib`), `query_concepts_by_properties` (as `_query_concepts_by_properties_lib`), `remove_concept_relationship` (as `_remove_concept_relationship_lib`), `RESERVED_PROPERTY_KEYS` (as `_RESERVED_PROPERTY_KEYS`); `expand_carton_refs` imported lazily inside `get_concept`
- `carton_mcp.add_concept_tool` — `add_concept_tool_func`, `add_observation`, `rename_concept_func`, `get_observation_queue_dir`; `normalize_concept_name` lazy inside `observe_from_identity_pov`; `soma_validate`, `SOMA_AVAILABLE` lazy inside `get_concept`
- `carton_mcp.concept_config` — `ConceptConfig`
- `carton_mcp.smart_chroma_rag` — `SmartChromaRAG`, `route_concept_to_collection`
- `carton_mcp.carton_kv` — imported lazily inside `edit_carton_obj` (`is_title_underscore`)
- `carton_mcp.substrate_projector` — `build_instructions`, `substrate_project` lazy inside `substrate_projector` tool
- `heaven_base.tool_utils.neo4j_utils.KnowledgeGraphBuilder` — imported inside `_create_shared_neo4j`
- `youknow_kernel.owl_reasoner.OWLReasoner` — lazy inside `get_concept` (refresh_code path) and `youknow_sparql`

### Consumers (who references this module in the repo)
- `pyproject.toml` — declares `carton-mcp = "carton_mcp.server_fastmcp:main"` as the console script entry point.
- `carton_utils.py` — references `server_fastmcp` (exact usage UNVERIFIED from grep).
- `observation_worker_daemon.py` — references `server_fastmcp` (exact usage UNVERIFIED from grep).
- `substrate_projector.py` — references `server_fastmcp` (exact usage UNVERIFIED from grep).

---

## Notes

- **Transport is stdio-only.** Repo rule (`.claude/rules/carton-mcp-transport.md`) forbids SSE. `main()` reads `CARTON_TRANSPORT` env (default `"stdio"`).
- **`enforce_ontology_invariants` startup thread is permanently disabled** (lines 160-161 commented out). `_deferred_enforcement` is dead code.
- **The daemon is a separate process.** All write paths queue to `HEAVEN_DATA_DIR/carton_queue/` and return immediately; the daemon applies writes and commits asynchronously. **Exceptions: `set_properties`, `remove_relationship`, and `add_to_collection` write synchronously and directly to Neo4j** — they bypass the queue because they do not touch `n.d` or the linker/fence machinery.
- **`query_wiki_graph` is read-only enforced** via `carton_utils._validate_query_safety`. `add_to_collection` is the only tool that bypasses this by calling `_neo4j_conn.execute_query` directly. `set_properties` and `remove_relationship` also write directly but through their own lib functions imported from `carton_utils`.
- **`_concept_stash` is module-level** and shared across all tool calls in the same process lifetime. A stash entry survives until the next successful `add_concept` for that name or explicit `clear_stash=True`.
- **SOMA status in `get_concept`** uses `string_value` for all relationship target types (no `typed_values` available at read time); SOMA validation is less precise than at `add_concept` time.
- **UARL/ontology status** (lines 163-180 block comment): soup layer implemented; formal axiom extraction, semantic pattern matching, and description composition from origination stacks are not yet implemented.
- **`_RESERVED_PROPERTY_KEYS`** is imported from `carton_utils` at line 28 and shared between `set_properties` (refusal guard on write) and `get_concept` (exclusion filter for the Props block on read) — both sides use the same constant; if it changes in `carton_utils` both behaviors change together.
