# doc(m): ontology_graphs.py

**Module:** `knowledge/carton-mcp/ontology_graphs.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

CartON's internal structural type system and self-healing graph-scaffold engine. When a concept is created whose `IS_A` list matches a known type in `ONTOLOGY_SCHEMAS`, `ensure_ontology_completeness` silently auto-creates all required child concepts (recursively, up to depth 5). This is CartON's own type system — not YOUKNOW/OWL validation — and it heals by constructing rather than scolding. The module also provides `_auto_create_task_hypercluster` (special-cased for `GIINT_Task`: traces `PART_OF` upward to find the starsystem's `Task_Collections`, creates a `Hypercluster_<Name>` there), `get_expanded_metagraph` (full GIINT hierarchy traversal from a hypercluster for serialisation into `MEMORY.md`), `format_metagraph_for_memory` (text renderer of that nested dict), and `get_seed_ship_stats` (aggregate counts for the whole Seed Ship). Four large functions are dead/commented-out as of 2026-03-29.

## Surface (1:1 — every public thing, in file order)

- `ONTOLOGY_SCHEMAS: Dict[str, Dict]` — `ontology_graphs.py:40`
  - Authoritative Python dict of CartON structural type definitions. 17 type keys (in file order):
  - `Seed_Ship` (:46) — 3 required children: `_Starsystems` (IS_A `Starsystem_Registry`), `_Kardashev_Map`, `_Sanctum`; each `rel_from_parent: has_part`. Expected rels: `has_part`, `has_state`.
  - `Starsystem_Collection` (:81) — 6 required children: `_Task_Collections`, `_Done_Signal_Collections`, `_Completed_Collections`, `_Architecture_Collections`, `_Bug_Collections` (all IS_A `Collection_Category`), plus `GIINT_Project_<base>_Unnamed` (IS_A `GIINT_Project`, rel `has_giint_project`, uses `strip_prefix`/`child_prefix` naming strategy). Expected rels include `has_part`, `has_skill`, `has_agent`, `has_flight_config`, `has_persona`, `has_mcp_server`, `depends_on`, `uses`, `integrates_with`.
  - `Hypercluster` (:143) — no required children; expected rels: `has_giint_project`, `has_status`, `part_of`.
  - `Collection_Category` (:155) — no required children.
  - `GIINT_Project` (:166) — 1 required child: `GIINT_Feature_<base>_Unnamed` (rel `has_feature`); uses `strip_prefix`/`child_prefix`.
  - `GIINT_Feature` (:184) — 1 required child: `GIINT_Component_<base>_Unnamed` (rel `has_component`).
  - `GIINT_Component` (:202) — 1 required child: `GIINT_Deliverable_<base>_Unnamed` (rel `has_deliverable`).
  - `GIINT_Deliverable` (:220) — no required children; comment: "Tasks come from TreeKanban — NEVER auto-created".
  - `GIINT_Task` (:230) — no required children; sets `auto_create_hypercluster: True` which triggers `_auto_create_task_hypercluster`.
  - `Kardashev_Map` (:247) — no required children (fleets created from JSON, not auto-created).
  - `Navy_Fleet` (:253) — no required children; expected rels: `has_squadron`, `has_loose_starship`, `has_admiral`, `part_of`.
  - `Navy_Squadron` (:263) — no required children; expected rels: `has_member`, `has_leader`, `part_of`.
  - `Navy_Starship` (:273) — no required children; expected rels: `has_kardashev_level`, `part_of`.
  - `Skill` (:292) — no required children; expected rels: `part_of`, `describes`, `has_domain`, `has_category`.
  - `Flight_Config` (:302) — no required children; expected rels: `part_of`, `automates`, `has_domain`.
  - `Persona` (:311) — no required children; expected rels: `configures`, `has_skill`.
  - `MCP_Server` (:320) — no required children; expected rels: `part_of`, `provides_tools_to`.
  - UNVERIFIED: the dict is described as "a shadow of uarl.owl" in the dead-code comment at :854; a TODO notes migration to OWL-driven type materialization is pending.

- `_normalize(name: str) -> str` — `ontology_graphs.py:333`
  - Normalises concept name to `Title_Case_With_Underscores`: replaces `-` and `_` with spaces, `.title()`, replaces spaces back with `_`. Called everywhere before Neo4j lookups or child-name derivation.

- `_concept_exists(concept_name: str, shared_connection) -> bool` — `ontology_graphs.py:338`
  - Runs `MATCH (n:Wiki {n: $name}) RETURN n.n LIMIT 1`. Normalises name first. Returns `False` if `shared_connection` is `None` or on any exception. Internal helper only.

- `_get_is_a_types(concept_name: str, shared_connection) -> List[str]` — `ontology_graphs.py:354`
  - Returns all `IS_A` target names for a concept from Neo4j. Returns `[]` on exception. Currently used only by the dead `get_completeness_score`.

- `ensure_ontology_completeness(concept_name, is_a_list, relationship_dict, shared_connection=None, _depth=0) -> List[str]` — `ontology_graphs.py:370`
  - Self-healing heart of the type system. For each type in `is_a_list` with an `ONTOLOGY_SCHEMAS` entry having `required_children`: derives each child name (two strategies: `strip_prefix`/`child_prefix` for GIINT types at :430, plain suffix-append for Collection types at :443), checks `_concept_exists`, and if missing calls `add_concept_tool_func(..., _skip_ontology_healing=True)`, then fires a Neo4j `MERGE` for the parent-to-child relationship.
  - Recursion guard: `_depth > 5` returns `[]` at :395. Children named `_Unnamed` are NOT recursed into (:504). Concepts with `_Template` suffix OR `_Collections` in name are skipped entirely at :409 (load-bearing guard against infinite scaffolding).
  - `GIINT_Task` special case: calls `_auto_create_task_hypercluster` when `schema.get("auto_create_hypercluster")` is true (:524).
  - Returns list of auto-created concept names. Called by `carton_utils.py`, `observation_worker_daemon.py`.

- `_auto_create_task_hypercluster(task_name, relationship_dict, shared_connection) -> List[str]` — `ontology_graphs.py:537`
  - Creates `Hypercluster_<TaskShortName>` for a `GIINT_Task`.
  - Step 1: strips `Giint_Task_` / `GIINT_Task_` prefix to get short name (:553).
  - Step 2: traces `PART_OF*1..4` to find `Giint_Project_` ancestor (:565).
  - Step 3: traces `PART_OF*1..3` + `HAS_PART` to find node `ENDS WITH '_Task_Collections'` (:577).
  - Step 4: creates HC with rels `IS_A Hypercluster`, `PART_OF <task_collections>`, `INSTANTIATES Hypercluster_Template`, `HAS_GIINT_PROJECT <project>`, `HAS_STATUS Active`.
  - Returns `[]` silently if HC already exists, project not found, or task_collections not found. No error surfaces to caller.

- `get_expanded_metagraph(hypercluster_name: str, shared_connection) -> Dict[str, Any]` — `ontology_graphs.py:613`
  - Traces full GIINT hierarchy from a hypercluster for `MEMORY.md` serialisation. Eight sequential Neo4j queries:
    1. Starsystem via `PART_OF*1..3` to node `ENDS WITH '_Collection'` `IS_A Starsystem_Collection` (:672)
    2. Collection category via direct `PART_OF` to `IS_A Collection_Category` (:684)
    3. GIINT project via `HAS_GIINT_PROJECT|HAS_PART` to `Giint_Project_` prefix (:693)
    4. Features via `HAS_PART|HAS_FEATURE` filtered by prefix (:706)
    5. Components per feature via `HAS_PART|HAS_COMPONENT` (:721)
    6. Deliverables per component via `HAS_PART|HAS_DELIVERABLE` (:734)
    7. Tasks per deliverable + `HAS_DONE_SIGNAL` check (:748)
    8. Other concepts `PART_OF` this HC not starting with `Giint_` (:778)
  - Returns dict: `hypercluster`, `starsystem`, `collection_category`, `giint_hierarchy`, `other_concepts`. On exception appends `error` key.
  - Called by `server_fastmcp.py` for the `get_active_hypercluster_metagraph` MCP tool.

- `format_metagraph_for_memory(metagraph: Dict[str, Any]) -> str` — `ontology_graphs.py:797`
  - Renders `get_expanded_metagraph()` output as indented text for `MEMORY.md`. Produces `## Active HC:` / `### GIINT Hierarchy` / `### Concepts (N):` sections. Tasks rendered with tick/box prefix from `task["done"]` flag.

- `get_seed_ship_stats(shared_connection) -> Dict[str, Any]` — `ontology_graphs.py:981`
  - Six independent Neo4j count queries: `total_concepts`, `starsystems`, `active_hcs` (not PART_OF `Completed_Collection_Category`), `completed_hcs`, `completed_tasks` (HAS_STATUS Done), `learnings` (Pattern_ + Inclusion_Map_ prefixes). Plus `HAS_STATE` query for Seed Ship binary state.
  - Each query fails silently. Returns dict with default `"state": "Wasteland"`.

## Dead / Commented-Out Code (all commented out 2026-03-29)

Rationale at :854: "The OWL + SHACL + reasoner (youknow()) now handles all type validation."

- `get_schema_for_type(type_name)` — `:855` — returned ONTOLOGY_SCHEMAS entry. DEAD.
- `get_all_ontology_types()` — `:860` — returned dict keys. DEAD.
- `materialize_ontology_types(shared_connection)` — `:865` — created Neo4j type-concept nodes for each ONTOLOGY_SCHEMAS key. DEAD.
- `ensure_instances_have_is_a(shared_connection)` — `:914` — walked each type, found prefix-matching concepts lacking IS_A, added the link. Comment: "Dragonbones inject_giint_types() handles IS_A injection at parse time." DEAD.
- `get_completeness_score(concept_name, shared_connection)` — `:1059` — scored concept completeness vs schema. DEAD, replaced by `reward_system.py`.

## Dependencies

**stdlib:** `logging`, `sys`, `typing`

**intra-repo (called):**
- `carton_mcp.add_concept_tool.add_concept_tool_func` — lazy-imported inside `ensure_ontology_completeness` (:471) and `_auto_create_task_hypercluster` (:590) to avoid circular import

**consumers (intra-repo grep):**
- `knowledge/carton-mcp/carton_utils.py`
- `knowledge/carton-mcp/observation_worker_daemon.py`
- `knowledge/carton-mcp/substrate_projector.py`
- `starsystem/starlog-mcp/starlog_mcp/score_compiler.py`

## Notes

- `ONTOLOGY_SCHEMAS` is the single canonical definition of CartON structural types. Any new type must be added here. Migration to OWL-driven materialization is a stated TODO (:854) — NOT done.
- The `_Template` / `_Collections` skip guard at :409 is load-bearing: without it, schema templates and collection nodes recursively spawn children indefinitely.
- `_auto_create_task_hypercluster` silently returns `[]` on graph-trace failure — no error surfaces to the caller.
- `get_expanded_metagraph` queries use both `HAS_PART` and typed rels because older graph nodes were linked only via `HAS_PART`.
- `add_concept_tool_func` is lazy-imported inside the two functions to break the circular import cycle.
