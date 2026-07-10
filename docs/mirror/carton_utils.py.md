# doc(m): carton_utils.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/carton_utils.py` (2249 lines)  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

Core business-logic library for CartON concept management, sitting between the MCP tool layer (`server_fastmcp.py`) and the Neo4j/Chroma backends. It owns: (1) the CANONICAL wiki-link stripping applied at the shared read primitive so no caller ever sees raw auto-linker markup; (2) the neo4j-bound CartON-KV wrappers (`edit_carton_obj`, `check_kv_refs`, `register_kv_schemas`, `validate_carton_obj`, `expand_carton_refs`) over the pure `carton_kv` library; (3) four direct-write property/relationship primitives (`RESERVED_PROPERTY_KEYS`, `_validate_property_value`, `set_concept_properties`, `query_concepts_by_properties`, `remove_concept_relationship`) that bypass the observation queue because they never touch `n.d`; and (4) the `CartOnUtils` class — bootstraps (collection/ontology/memory-ontology types), the startup ontology-invariant enforcer, the read-only Cypher facade (`query_wiki_graph`), network traversal (`get_concept_network`), missing-concept tooling, dedup analysis, retroactive autolinking, collection reads, and the `scan_carton` GPS aggregation scan.

---

## Surface (1:1 — every public thing, in file order)

### Module-level functions

- `strip_wiki_links(text) -> str` — `carton_utils.py:14`
  - CANONICAL CartON wiki-link stripper (onion: lives in the library so every caller — MCP tools, imports, CLIs — gets clean output). The auto-linker rewrites mentions into `[word](../Word/Word_itself.md)` stored RAW in `n.d`; this converts complete links to their text (loop until fixpoint, nested-safe), strips truncated/dangling links at end-of-string (the `substring(d,0,N)` truncation case), removes orphan `_itself.md` targets and residual fragments, drops empty parens, and collapses doubled spaces. Non-str input is returned unchanged.

- `deep_strip_wiki_links(obj)` — `carton_utils.py:36`
  - Recursively applies `strip_wiki_links` over any query-result structure (str / list / dict; other types pass through). Used by `_execute_neo4j_query` so the library's read primitive returns clean data.

- `edit_carton_obj(concept_name, kvobj_name, key_path, op, value=None, shared_connection=None) -> dict` — `carton_utils.py:48`
  - Neo4j-bound wrapper over the PURE `carton_kv` op-applier. Edits (or reads) one leaf of a `<CartonObj name=...>` fence in a concept's `n.d`.
  - Flow: (1) reads `n.d` RAW via direct Cypher (bypassing the strip facade) so the splice is byte-identical to stored bytes (`:86-93`); (2) applies the op:
    - `op == "remove_fence"` (`:97-106`): whole-fence deletion via `carton_kv.remove_carton_obj`; sets `removed_fences=[kvobj_name]` in the queue entry so the daemon's fence-preservation guard does NOT carry the fence back. Per the in-code comment this is the ONLY way a whole fence is deleted.
    - otherwise `carton_kv.apply_carton_obj_op(description, kvobj_name, key_path, op, value)` (`:109-113`), catching `KeyError/ValueError/IndexError/TypeError` into an error dict.
  - `op == "get"` returns the value with NO write (`:116-118`).
  - Unresolved-ref refuse (the stub-disease cure), `:120-131`: for `set`/`append` with a non-None value, extracts bare refs from the NEW value (`carton_kv.extract_refs`) and runs `check_kv_refs`; if any ref doesn't resolve, the write is REFUSED with `error: "unresolved bare ref(s) — refusing write (no stub spawned)"` plus `did_you_mean` suggestions.
  - Write path (`:133-150`): does NOT write Neo4j directly — it writes a `raw_concept: true` queue-entry JSON file into `get_observation_queue_dir()` with `desc_update_mode: "replace"`, empty `relationships` (MERGE-only, leaves rels untouched), and `removed_fences`; consumed asynchronously by the daemon's LIVE parse path `observation_worker_daemon.parse_queue_file_to_concepts` (the raw_concept branch, called from the daemon worker loop) → `batch_create_concepts_neo4j` (`process_queue_file` is DEAD CODE with zero callers — it is NOT the consumer). Filename: `{YYYYmmdd_HHMMSS}_{uuid8}_concept.json`.
  - Returns `{success, op, concept, kvobj, key_path, value?, queued?, error?, did_you_mean?}`.
  - NOTE: the docstring's Args list says `op: "get" | "set" | "append" | "remove"` but the code also accepts `"remove_fence"` (handled at `:97`); the docstring under-lists the ops (stale-by-omission).

- `check_kv_refs(ref_names, graph, max_suggestions=3) -> dict` — `carton_utils.py:156`
  - Fuzzy did-you-mean over KV bare refs. For each name: exact `MATCH (c:Wiki {n:$n})` existence check; if missing, queries up to 300 candidates whose lowercased name CONTAINS the first underscore-token of the ref, then `difflib.get_close_matches(name, candidates, n=max_suggestions, cutoff=0.4)`. Returns `{"ok": bool, "unresolved": {ref_name: [suggestions]}}`. NEVER creates a node.

- `register_kv_schemas(concept_name, description, graph) -> dict` — `carton_utils.py:182`
  - SOUP-layer (plain KG, not SOMA/typed) auto-typing of KV schemas. For each fence found by `carton_kv.find_carton_objs(description)`:
    - `is_schema=true` fence → `MERGE` the `Carton_Kv_Schema` type node (ON CREATE sets its c/d/t) and `MERGE (concept)-[:IS_A]->(Carton_Kv_Schema)`; for fence attrs `what_for`/`how` whose value is Title_Underscore, adds `WHAT_FOR`/`HOW` edges (MATCH-both, so missing targets are skipped, not stubbed).
    - `schema=<Concept>` fence → MATCH-both `MERGE (c)-[:USES_KV_SCHEMA]->(sc)` + `MERGE (sc)-[:USED_BY_KV]->(c)` (undefined schema never stubbed).
  - Returns `{"typed_schemas": [...], "uses_schemas": [...]}`; any `find_carton_objs` exception returns empty lists.

- `validate_carton_obj(concept_name, kvobj_name, graph) -> dict` — `carton_utils.py:225`
  - Validates ONE fence: reads `n.d` raw, locates the fence via `carton_kv.get_carton_obj`; (b) ref resolution via `check_kv_refs(extract_refs(fence.obj))`; (a) if the fence has `schema=<Concept>`, loads that concept's `is_schema=true` fence and runs `carton_kv.validate_against_schema(fence.obj, sfence.obj)`, collecting `{path, message}` errors (schema-concept-missing and no-is_schema-fence are reported as `(schema)`-path errors).
  - Returns `{success, concept, kvobj, schema, valid, errors, unresolved_refs}` where `valid = no errors AND all refs resolve`.

- `expand_carton_refs(description, graph, depth=1) -> str` — `carton_utils.py:264`
  - READ-TIME ref-expansion: graph-bound wrapper over `carton_kv.expand_refs_in_description` with a `_fetch(name)` closure that pulls the referenced concept's description (wiki-link-stripped) + outgoing relationships (lowercased type, target name). RENDER-ONLY: the stored `n.d` is never mutated; `depth<=0` returns the description unchanged; cycle-guarded in the underlying lib.

- `RESERVED_PROPERTY_KEYS` — `carton_utils.py:298`
  - `frozenset` of managed Neo4j property names that `set_concept_properties` and `query_concepts_by_properties` must never overwrite via user-supplied data. Members: `"n", "d", "t", "c", "linked", "score", "source", "timeline_linked", "odyssey_linked", "system_generated", "last_modified"`. Any key in this set passed to `set_concept_properties` is collected into `refused_keys` and skipped rather than written.

- `_validate_property_value(key, value) -> None | str` — `carton_utils.py:307`
  - Pre-write scalar guard for `set_concept_properties`. Returns `None` if the value is acceptable; returns an error string otherwise. Accepts `str`, `int`, `float`, `bool`, and flat lists whose every element is one of those types. Refuses `dict` values (nested objects) and lists containing non-scalar elements — the error message tells the caller to flatten or `json.dumps` the value themselves. Called in the `mode="merge"` path before any Cypher is issued; a single bad value aborts the entire call.

- `set_concept_properties(concept_name, properties, mode="merge", shared_connection=None) -> dict` — `carton_utils.py:323`
  - Sets or removes NON-reserved Neo4j properties on an EXISTING concept **synchronously** (direct `MATCH` write, bypassing the observation queue). Safe to bypass the queue because properties never touch `n.d`, so no linker/fence machinery runs.
  - `mode="merge"` (default): issues `MATCH (c:Wiki {n: $n}) SET c += $props` with `$props` as a parameterized map — no value interpolation into the Cypher string. Validates all candidate values via `_validate_property_value` BEFORE writing; one bad value aborts the whole call.
  - `mode="remove"`: issues `MATCH (c:Wiki {n: $n}) REMOVE c.\`key1\`, c.\`key2\`...` — keys are backtick-quoted identifiers in the Cypher string, values ignored.
  - MATCH-not-MERGE: the concept MUST already exist; a missing concept returns `{success: False, error: "concept … not found"}` without creating anything.
  - Reserved keys in `RESERVED_PROPERTY_KEYS` are silently partitioned into `refused_keys` and never written; the rest proceed normally. If ALL supplied keys are reserved, returns `{success: True, ..., error: "only reserved keys given; nothing set/removed"}`.
  - Returns `{success, concept, updated_keys, refused_keys, removed_keys, error}`.

- `query_concepts_by_properties(where, limit=25, shared_connection=None) -> dict` — `carton_utils.py:406`
  - Finds `:Wiki` concepts whose properties **exactly match every key/value pair** in `where` (AND conjunction). Parameterized Cypher only — property values are never string-interpolated; keys are backtick-quoted identifiers. Builds: `MATCH (c:Wiki) WHERE c.\`k0\` = $w_0 AND c.\`k1\` = $w_1 ... RETURN c.n AS n, <matched props> LIMIT $lim`.
  - `limit` defaults to 25; non-integer or non-positive values are clamped to 25.
  - Returns `{success, results: [{n, <matched+requested props>}], error}`. Each result dict carries the concept name plus the value of every key in `where`.
  - `where` must be a non-empty dict; an empty or non-dict `where` returns an error without querying.

- `remove_concept_relationship(source, rel_type, target, shared_connection=None) -> dict` — `carton_utils.py:446`
  - **Synchronously** deletes exactly the directed relationship `(source)-[:REL_TYPE]->(target)` via `MATCH ... DELETE r RETURN count(r) AS deleted`. The only relationship-deletion primitive in this module; relationship creation goes through `add_concept_tool`.
  - `rel_type` is validated against `^[A-Za-z_]+$` before being interpolated as the Cypher relationship type identifier (relationship type names cannot be Cypher parameters, so strict sanitization is the injection guard). Invalid `rel_type` returns `{success: False, error: "invalid rel_type ..."}` without touching the graph.
  - `source` and `target` are passed as `$params` (never interpolated). A relationship that does not exist returns `{success: True, deleted_count: 0}` — not an error.
  - Returns `{success, source, rel_type, target, deleted_count, error}`.

### class `CartOnUtils` — `carton_utils.py:476`

Constructor `__init__(shared_connection=None)` (`:481`): stores an optional `KnowledgeGraphBuilder` to reuse (MCP context); otherwise queries go through the module singleton.

- `_get_connection() -> (graph, should_close)` — `:490`. Returns `(self._shared_conn, False)` if shared, else `(heaven_base.tool_utils.neo4j_utils.get_shared_graph(), False)`. With both branches returning `should_close=False`, the `finally: graph.close()` branches elsewhere in the class are effectively dead in current operation.

- `bootstrap_collection_types() -> bool` — `:502`
  - One-time (flag file `HEAVEN_DATA_DIR/carton/collection_types_bootstrapped.flag`) creation of `Carton_Collection`, `Global_Collection`, `Local_Collection`, `Identity_Collection` via `add_concept_tool_func`. Returns False if flag exists; flag written only on success; exceptions re-raise.

- `bootstrap_ontology_types() -> bool` — `:588`
  - One-time (flag `ontology_types_bootstrapped.flag`) creation of: `Carton_Template`; 22 `Has_*` relationship-type concepts (Has_Domain, Has_Category, Has_What, Has_When, Has_Produces, Has_Subdomain, Has_Content, Has_Reference, Has_Resources, Has_Scripts, Has_Templates, Has_Allowed_Tools, Has_Model, Has_Context_Mode, Has_Agent_Type, Has_Hook, Has_User_Invocable, Has_Disable_Model_Invocation, Has_Argument_Hint, Has_Requires, Has_Describes_Component, Has_Starsystem); the 4 skill-category types (`Skill_Category`, `_Understand`, `_Preflight`, `_Single_Turn_Process`); `Skillspec_Template` (REQUIRES_RELATIONSHIP → 9 Has_* targets); and `Skill_Template` (extends Skillspec_Template; REQUIRES_RELATIONSHIP → the full ~21-field set). All with `hide_youknow=True`.

- `bootstrap_memory_ontology_types() -> bool` — `:735`
  - One-time (flag `memory_ontology_bootstrapped.flag`) creation of memory-tier ontology: relationship types (Has_Tier, Has_Why, Has_Status, Has_Level, Has_File_Path, Has_Sequence, Has_Giint_Project); core types `HyperCluster`, `Memory_Tier`, `UltraMap`; concrete instances `Memory_Tier_0..3` (each with `has_level: Level_N` and `has_file_path` to its projection path — Tier 0 = `/home/GOD/.claude/projects/-home-GOD/memory/MEMORY.md`, Tier 1 = `~/.claude/rules/`, Tier 2/3 = faint/faintest rule files); and `HyperCluster_Template` (REQUIRES_RELATIONSHIP: Has_Giint_Project, Has_Tier, Has_Status, Has_Why).

- `enforce_ontology_invariants() -> dict` — `:863`
  - Runs EVERY startup (no flag file; `server_fastmcp.py` calls it in a background thread). Sections:
    1. Seed_Ship enforcement (`:891-956`): creates the `Seed_Ship` root node if absent; `ensure_ontology_completeness` for it; finds all `Starsystem_Collection` instances, migrates `PART_OF` from old `All_Starsystems`/`STARSYSTEM_Collection` to `Seed_Ship_Starsystems` (bidirectional PART_OF/HAS_PART), ensures each starsystem's ontology completeness. Failures logged as warnings, not raised.
    2. Ontology type materialization (`:958-973`): `materialize_ontology_types(graph)` + `ensure_instances_have_is_a(graph)` from `ontology_graphs` (bounded to ONTOLOGY_SCHEMAS keys).
    3. SKILL ENFORCEMENT (`:975-1122`) — carries an in-code BUG comment dated Apr 18 2026 declaring the section broken: nodes are flat stubs (PART_OF Skillgraph + IS_A Skillgraph_Entry only, no real relationships) and the ChromaDB entries go to a separate `skillgraphs` collection (localhost:8101) invisible to normal `chroma_query`; "Needs full rewrite". Mechanics as coded: scans `HEAVEN_DATA_DIR/skills/` dirs (skipping `_`/`Test`/`Fix`/`Live` prefixes and `.json` suffix), reads `_metadata.json` or parses WHAT:/WHEN: from SKILL.md, normalizes to `Skillgraph_Title_Case` names, maps category → pattern (`Understand_Skill_Pattern` / `Preflight_Skill_Pattern` / `Single_Turn_Skill_Pattern` / `Generic_Skill_Pattern`), MERGEs the stub node under `Skillgraph` via `HAS_INSTANCES`/`PART_OF`/`IS_A Skillgraph_Entry`, and upserts a `[SKILLGRAPH:...]` document into the chroma `skillgraphs` collection. NOTE: point (1) of the BUG comment ("SET sg.t=timestamp() overwrites timestamps every boot") does NOT match the current code, which guards with `CASE WHEN sg.t IS NULL THEN datetime() ELSE sg.t END` (`:1076`) — that claim describes a prior version; points (2) and (3) still match.
    4. Cleanup (`:1124-1166`): deletes Neo4j Skillgraph entries and chroma `skillgraph:` ids that no longer correspond to disk skills (Neo4j node deleted only if left relationship-less).
  - Returns stats dict `{skills_checked, neo4j_fixed, chroma_fixed, neo4j_removed, chroma_removed, errors, ontology_types_materialized?, instances_linked?}`.

- `get_all_concept_names(exclude_concept=None) -> List[str]` — `:1180`. All `:Wiki` names excluding sunk versions (`_v<N>$`) and concepts with an outgoing `EVOLVED_TO` (renamed-away).

- `_validate_query_safety(cypher_query) -> dict` — `:1213`. Read-only guard: word-boundary regex rejects `CREATE|MERGE|DELETE|DETACH`; requires the literal `:Wiki` in the query text.

- `_get_neo4j_config()` — `:1228`. Builds a `ConceptConfig` from env: `GITHUB_PAT`/`REPO_URL` (dummy defaults), `NEO4J_URI` (default `bolt://host.docker.internal:7687`), `NEO4J_USER`/`NEO4J_PASSWORD` (neo4j/password), `base_path=None` → HEAVEN_DATA_DIR default.

- Serializer helpers `_serialize_node/_serialize_relationship/_serialize_path/_serialize_collection/_serialize_dict/_serialize_neo4j_value` — `:1242-1287`. Convert neo4j driver graph types (Node/Relationship/Path) to JSON-serializable dicts; ImportError → value passthrough.

- `_create_graph_connection()` — `:1289`. Constructs a fresh `KnowledgeGraphBuilder` from `_get_neo4j_config()` and `_ensure_connection()`s it. NOT called by `_get_connection` (which uses the singleton); UNVERIFIED whether any current caller in this module or elsewhere uses it — candidate dead code.

- `_serialize_record(record) -> dict` — `:1302`. Serializes one record via `_serialize_neo4j_value` per key.

- `_execute_neo4j_query(cypher_query, parameters)` — `:1309`
  - THE shared read primitive: opens a session on `graph.driver`, runs the query, serializes each record, and — the load-bearing line — returns `deep_strip_wiki_links(serialized_results)` (`:1324`). This is the CANONICAL strip site: every read facade built on it (`query_wiki_graph`, `get_concept_network`, collections, dedup, scan) returns CLEAN data; wiki-links can never render from any caller.

- `_handle_query_errors(e) -> dict` — `:1326`. ImportError → "Neo4j driver not available"; else `{success: False, error: str(e)}`.

- `query_wiki_graph(cypher_query, parameters=None) -> dict` — `:1335`
  - The read-only Cypher facade: `_validate_query_safety` then `_execute_neo4j_query`. Returns `{success, cypher_query, parameters, data, naming_convention}` (the naming_convention string documents Title_Case_With_Underscores conventions to the calling LLM).

- `_validate_depth(depth)` — `:1358`. 1..3 only.

- `_build_network_query(depth, rel_types=None) -> str` — `:1364`
  - Builds the variable-length traversal `MATCH (source)-[r{:TYPE|TYPE}*1..depth]-(connected:Wiki)` (undirected), with WHERE exclusions for `_v<N>` versions, `*_Observation`, `UserThought_*`, `AgentMessage_*`, `Sync_*`, `*_Update_History`, and `Requires_Evolution`. Returns start_concept, relationship_path (list of types), connected name + description.

- `_clip_large_result(result, concept_name, max_items=100) -> dict` — `:1400`. If >100 items: caches the FULL list to `HEAVEN_DATA_DIR/carton_cache/{concept}_network_{ts}.json` and returns the first 100 + `cached_at` pointer.

- `get_concept_network(concept_name, depth=1, rel_types=None) -> dict` — `:1432`
  - Validates depth, runs the network query, deduplicates per unique `connected_concept` (aggregating all `relationship_paths`), clips via `_clip_large_result`. Returns `{success, concept_name, depth, network, [clipped, total_items, showing_first, cached_at, message]}`.

- `list_missing_concepts() -> dict` — `:1499`. Parses `{base_path}/missing_concepts.md` (sections `## <Name>`, `- rel: targets` lines, `**Similar existing concepts:**`) into `{name, inferred_relationships, similar_concepts}` entries. Helpers: `_get_missing_concepts_file` `:1521`, `_return_no_missing_concepts` `:1527`, `_parse_missing_concepts_content` `:1535`, `_parse_relationship_line` `:1567`, `_parse_similar_concepts_line` `:1579`, `_build_concept_data` `:1586`.

- `calculate_missing_concepts() -> dict` — `:1594`. Full scan: `setup_git_repo` (clone latest), `check_missing_concepts_and_manage_file(base_dir, "")`, and if `missing_concepts.md` changed, `commit_and_push` then re-parse the file. (GitHub-repo-backed flow from `add_concept_tool`.)

- `create_missing_concepts(concepts_data) -> dict` — `:1652`. Batch-creates concepts via `add_concept_tool_func`; missing description → `_generate_concept_description`; missing relationships → `is_a Work_In_Progress`. Returns created/failed lists.

- `_generate_concept_description(concept_name, relationships) -> str` — `:1714`. Keyword-template generator (tool/system/framework, protocol/standard/format, agent/ai, integration/bridge, else "requires further definition"), appending relationship context. NOT actual AI generation despite the "AI-generated" wording in callers' docstrings — a heuristic fallback.

- `deduplicate_concepts(similarity_threshold=0.8) -> dict` — `:1744`. Loads ALL concepts (name+description), O(n²) `difflib.SequenceMatcher` name-similarity plus normalized-name equality checks; groups similar names; `_analyze_similarity` (`:1812`) labels reasons (case variations / formatting / exact duplicates / high textual similarity). Analysis only — does not merge or delete.

- `retroactive_autolink_all_concepts() -> dict` — `:1835`. Walks the git-repo `concepts/` dir, re-runs `auto_link_description` over each concept's `components/description.md` and the `## Overview` sections of `{name}.md` / `{name}_itself.md`, commits+pushes if anything changed. Operates on the FILE substrate (git concept repo), not Neo4j.

- `get_collection_concepts(collection_name, max_depth=10) -> dict` — `:1925`. Recursive `HAS_PART*1..10` traversal. NOTE: the Cypher hardcodes `*1..10`; the `max_depth` arg is accepted but NOT interpolated into the query — effectively unused. Members with NULL/empty description are flagged `[MISSING CONCEPT - NOT YET DEFINED]` and rolled into a `warning` string.

- `list_all_collections() -> dict` — `:1998`. All concepts `IS_A Carton_Collection` (excluding `_v<N>`/`*_Observation`), each with description and `concept_count` of direct `HAS_PART` members.

- `scan_carton(query, max_results=10) -> str` — `:2051`
  - Bottom-up GPS aggregation scan returning a formatted injection string. Steps: `chroma_query` (imported from `server_fastmcp` at `:2070` — deliberate late import to dodge the circular dependency) against BOTH `carton_conversations` and `carton_concepts`, parsing ranked-line results by regex; batch Cypher mapping conversations → member concepts (excluding transcript/metadata node types); merge with user concepts; batch Cypher mapping concepts → containing collections (`IS_A` one of Carton/Global/Local/Identity_Collection); categorize into collection-members vs orphaned concepts (filtered by inner `should_show_in_gps`, which excludes timestamped `*_Observation`, `Sync_N`, `Requires_Evolution`, `_vN` sunk, `Day_YYYY_MM_DD`, `Raw_Conversation_Timeline_*`, `Conversation_/UserThought_/AgentMessage_/ToolCall_` transcripts, `X_Update_History`) vs orphaned conversations; renders the "🔍 CartON Scan Results" block with 📦 collections / 📋 orphaned concepts (≤10) / 💬 orphaned conversations (≤5) + a recommendation line. Errors return a `❌ CartON scan failed: ...` string (not a dict).

---

## Internals

- **Onion layering:** pure logic in `carton_kv` (no I/O) → neo4j-bound wrappers here (module functions) → thin MCP tools in `server_fastmcp.py`. The module-level KV functions take `graph`/`shared_connection` explicitly; `CartOnUtils` methods resolve connections via `_get_connection`.
- **One description-write discipline:** `edit_carton_obj` is the only function here that mutates `n.d`, and only by queueing a `raw_concept` replace entry for the daemon — never a direct Cypher description write. `register_kv_schemas` and `enforce_ontology_invariants` DO run direct `MERGE` Cypher, but only for typed edges/stub nodes, not descriptions.
- **Sync-bypass-queue rationale:** `set_concept_properties` and `remove_concept_relationship` write directly and synchronously, bypassing the observation queue. This is safe because neither touches `n.d` — no linker, no fence-preservation guard, no daemon machinery is needed. The queue exists to serialize description writes; property-only and relationship-only mutations have no such contention.
- **Raw-read vs stripped-read split:** KV functions read `n.d` via direct `graph.execute_query` (RAW bytes, splice-safe); all general read facades go through `_execute_neo4j_query` (stripped).

## Data contracts

- **Neo4j `:Wiki` properties:** `n` (name), `d` (description — may contain raw wiki-links and `<CartonObj>` fences), `t` (timestamp), `c` (canonical; set on `Carton_Kv_Schema` create), `system_generated` (true on Skillgraph stubs).
- **Relationship types written:** `IS_A` (Carton_Kv_Schema typing; Skillgraph_Entry), `WHAT_FOR`, `HOW`, `USES_KV_SCHEMA`, `USED_BY_KV`, `PART_OF`/`HAS_PART` (starsystem migration), `HAS_INSTANCES` (Skillgraph). `remove_concept_relationship` deletes any caller-specified type matching `^[A-Za-z_]+$`. Read: `EVOLVED_TO`, `HAS_PART`, `IS_A`, `PART_OF`, plus arbitrary types in network traversal.
- **Files written:** observation queue entries (`{ts}_{uuid8}_concept.json` in `get_observation_queue_dir()`); bootstrap flag files under `HEAVEN_DATA_DIR/carton/`; network-result cache `HEAVEN_DATA_DIR/carton_cache/*.json`; concept-repo markdown (retroactive autolink).
- **Files read:** `HEAVEN_DATA_DIR/skills/*/` (`_metadata.json`, `SKILL.md`), `{base_path}/missing_concepts.md`, concept-repo `concepts/*/` markdown.
- **ChromaDB:** `skillgraphs` collection via `chromadb.HttpClient(localhost:8101)`, ids `skillgraph:<Skillgraph_Name>` (+ legacy `skillgraph:<dir-name>`), cosine space; queried collections `carton_conversations` / `carton_concepts` via `server_fastmcp.chroma_query`.
- **Env:** `HEAVEN_DATA_DIR` (default `/tmp/heaven_data`), `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`, `GITHUB_PAT`/`REPO_URL`.

## Cross-module deps

- `.carton_kv` — `apply_carton_obj_op`, `remove_carton_obj`, `extract_refs`, `find_carton_objs`, `get_carton_obj`, `validate_against_schema`, `expand_refs_in_description`, `is_title_underscore`.
- `.add_concept_tool` — `add_concept_tool_func`, `get_observation_queue_dir`, `_get_module_connection`, `auto_link_description`, `setup_git_repo`, `commit_and_push`, `check_missing_concepts_and_manage_file`.
- `.concept_config.ConceptConfig`; `.server_fastmcp.chroma_query` (late import inside `scan_carton` only — circular-dep dodge).
- `carton_mcp.ontology_graphs` — `ensure_ontology_completeness`, `materialize_ontology_types`, `ensure_instances_have_is_a`.
- `heaven_base.tool_utils.neo4j_utils` — `get_shared_graph`, `KnowledgeGraphBuilder`.
- External: `neo4j.graph` (serializers), `chromadb` (skill enforcement), `difflib`.

## Defects / dead code (grounded)

- `enforce_ontology_invariants` skill section: in-code BUG comment (`:976-980`, Apr 18 2026) declares it broken — flat stubs, separate invisible chroma collection — "Needs full rewrite". Point (1) of that comment ("SET sg.t=timestamp() overwrites timestamps every boot") does NOT match the current code, which uses `CASE WHEN sg.t IS NULL THEN datetime() ELSE sg.t END` (`:1076`) — the comment describes a prior version; points (2) and (3) still match the code.
- `edit_carton_obj` docstring omits the implemented `remove_fence` op from its Args list (`:69` vs `:97`).
- `get_collection_concepts(max_depth)` parameter is accepted but ignored — the Cypher hardcodes `HAS_PART*1..10` (`:1941`).
- `_get_connection` returns `should_close=False` in both branches (`:490-497`), so every `finally: if should_close: graph.close()` in the class is currently a no-op.
- `_create_graph_connection` (`:1289`) is not called by `_get_connection`; UNVERIFIED whether any live caller uses it — candidate dead code.
- Dead local assignments: `sg_concept_name` computed then immediately recomputed (`:1051` vs `:1053-1054`); `ss_name = ss_rec["name"] if isinstance(ss_rec, dict) else ss_rec["name"]` has identical branches (`:925`).
- `deduplicate_concepts` is O(n²) over the entire graph — analysis-only utility; runtime at current graph size UNVERIFIED.
- `_generate_concept_description` is a keyword-template stub, not actual AI generation despite "AI-generated descriptions" wording in `create_missing_concepts`' docstring (`:1653`).
