# doc(m): add_concept_tool.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/add_concept_tool.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-07-06 (re-derived — supersedes the 2026-06-10 derivation; commit `944e60d` "P0 exhaust patches (carton): Rejection_Ledger + Episode_Ledger + fired-chains parse/ledger + SOMA-availability self-heal" plus the earlier `a9555c0`/`f0b5e60` optional-domain-fields work)

## Purpose (one paragraph)
This module is the CartON concept-creation engine for the carton-mcp package. Its primary export is `add_concept_tool_func`, which validates an incoming concept (name + description + relationships) against the SOMA daemon at `:8091`, classifies the result as SOUP / CODE / SYSTEM_TYPE (and rejects Type-2 CONTRADICTION verdicts outright), serialises a `raw_concept` JSON envelope to the file-based queue at `$HEAVEN_DATA_DIR/carton_queue/`, and returns immediately. All Neo4j writes and filesystem writes are deferred to `observation_worker_daemon`. The module also owns: the `auto_link_description` / `_auto_link_core` Aho-Corasick wiki-linker with CartonObj fence-opacity masking; the `_add_observation_worker` observation-envelope processor (called by the daemon, not directly by the MCP); the `add_observation` queue-write shim; UARL compression classification; cycle and instantiation-completeness validators; concept sinking (`sink_concept_globally`) and renaming (`rename_concept_func`); the CARTON→Crystal-Ball fan-out (`_cb_place`, placing every said concept as a plane coordinate); the D2 description-coverage check (informational only, never a gate); and **three P0 exhaust-ledger additions landed 2026-07-06** (Griess-Neural-Surrogate patch): `record_soma_rejection`/`rejection_ledger_path` (oracle-labeled hard negatives to `soma_rejections.jsonl`), a `fired_chains=` verdict-block parser feeding both `queue_data["fired_chains"]` and `soma_fired_chains.jsonl`, and a SOMA-availability self-heal (`_check_soma_available` now treats a timeout as up-but-busy; `_soma_up()` re-checks per call while previously `False`). **The old `YOUKNOW`/`AddConceptTool`/`RenameConceptTool` `BaseHeavenTool` wrapper surface described in the prior (2026-06-10) doc(m) no longer exists in this file** — see Notes.

## Surface (1:1 — every public thing, in file order)

### Module-level constants / singletons

- `SOMA_URL = os.environ.get("SOMA_URL", "http://localhost:8091/event")` — `add_concept_tool.py:36`
  - POST endpoint for SOMA, env-overridable (2026-06-27) so a remote/containerized SOMA can be targeted. SOMA only exposes `POST /event`; a `GET` returns `404`, which `_check_soma_available()` treats as "daemon is up".
  - **YOUKNOW is GONE.** A comment at `add_concept_tool.py:25-28` records that the `YOUKNOW_URL`/`youknow_validate`/`_check_youknow_available`/`YOUKNOW_AVAILABLE` block was removed 2026-06-15 (zero live callers, SOMA is the validator now) — do not look for it; it is not merely dead code left in place, it is deleted.

- `CARTON_CB_STORE`, `CARTON_CB_STORE_URL`, `CARTON_CB_FLOW_URL`, `CARTON_CB_KEY_FILE` — `add_concept_tool.py:51-54`
  - The CARTON → Crystal Ball fan-out config (2026-07-02, `canon/CORE-SENTENCE-SPECTRAL-SEQUENCE.md`): carton SAYS the core sentence, SOMA ENFORCES it, CB ADDRESSES it (places it as a coordinate) — carton fans the same said sentence to both, no CB→SOMA wire. `CARTON_CB_STORE` defaults ON (`"1"`, opt-out via `"0"`/`"false"`/`"False"`).

- `SOMA_AVAILABLE: bool` — `add_concept_tool.py:136`
  - Frozen at module import by `_check_soma_available()` (`:115-134`, see below — now timeout-tolerant). Logs an error if `False` at import.

- `OBSERVATION_TAGS: set` — `add_concept_tool.py:191-197`
  - `{"insight_moment", "struggle_point", "daily_action", "implementation", "emotional_state"}`. Legal tag keys in an observation envelope; validated in `_add_observation_worker`.

- `PERSONAL_DOMAINS: list` — `add_concept_tool.py:200-206`
  - `["paiab", "sanctum", "cave", "misc", "personal"]`. Enum for `has_personal_domain`; enforced in `_add_observation_worker` and (as an OPTIONAL passthrough, see `merge_optional_domain_fields`) in `add_concept_tool_func`. This is the canonical source `sm_gate.py`'s `create_sm_chain` imports for its own REQUIRED `personal_domain` validation.

- `UARL_PREDICATES: set` — `add_concept_tool.py:253-263`
  - Static hardcoded set: `{"is_a", "part_of", "instantiates", "embodies", "manifests", "reifies", "programs", "validates", "invalidates"}`. A long comment block (`:208-251`) marks this as a known-wrong placeholder — the intent is a dynamic query of reified relationship concepts from Neo4j. Used only by `classify_compression_type` and the REIFIES-validation block inside the dead `create_concept_in_neo4j`.

- `_module_neo4j_conn` — `add_concept_tool.py:169`
  - Module-level lazy-initialised `KnowledgeGraphBuilder`, obtained via `_get_module_connection()`.

### Helper / utility functions

- `soma_validate(source, observations, domain="default") -> dict` — `add_concept_tool.py:38-44`
  - POSTs `{"source", "observations", "domain"}` to `SOMA_URL` with a 120-second timeout. Called by `add_concept_tool_func` when `_soma_up() and not hide_youknow`.

- `_cb_place(concept_name, relationship_dict, soma_region, want_guidance=False) -> (cb_x, cb_y, cb_encoded, guidance_block_or_None)` — `add_concept_tool.py:56-113`
  - Best-effort fan-out to Crystal Ball: places the said core sentence as a 2-D PLANE POINT (`cb_x` = kernel's global/column id, `cb_y` = plane position, `cb_encoded` decodes back to `(kernelId, localCoord)`). NEVER raises — a CB failure is logged loud and returns `(None, None, "", None)`. Default path: POST `/api/cb/store` (no-auth). When `want_guidance=True`: POSTs the `store` verb over the authed `/api/cb/flow`, which places AND returns the four-layer PROMPTER guidance block.

- `_check_soma_available() -> bool` — `add_concept_tool.py:115-134` **(CHANGED, 2026-07-06)**
  - Issues a `GET` to `localhost:8091/event`. `HTTPError` (including 404) → `True`. **NEW:** any OTHER exception is inspected — if `"timed out" in str(e).lower()` or `isinstance(e, TimeoutError)` → returns `True` (up-but-busy), because SOMA serializes events and a 2-second GET loses the race whenever any event is in flight (most of the time under the observation daemon's continuous drain). Only a genuinely fast failure (connection refused / unreachable) returns `False`. **Why this matters:** before this fix, a fresh carton process importing during any in-flight event froze `SOMA_AVAILABLE=False` for the process lifetime and silently skipped validation FOREVER.

- `_soma_up() -> bool` — `add_concept_tool.py:144-160` **(NEW, 2026-07-06)**
  - Call-time SOMA availability check: memoized-UPGRADE. If the module-level `SOMA_AVAILABLE` is already `True`, returns `True` immediately (cheap). If `False`, re-checks via `_check_soma_available()` on EVERY call (never re-freezes `False`); once it flips `True` it stays `True` for the rest of the process. This is the call now guarding the SOMA gate inside `add_concept_tool_func` (replacing the old bare `SOMA_AVAILABLE` read) — fixes the "frozen False forever" bug the import-time snapshot had.

- `_get_module_connection() -> KnowledgeGraphBuilder | None` — `add_concept_tool.py:171-188`
  - Lazy-initialises `_module_neo4j_conn`. Returns `None` on connection failure (non-fatal; callers fall back to per-call connections).

- `get_uarl_predicates(config) -> set` — `add_concept_tool.py:265-320`
  - Always returns `{"is_a", "part_of", "instantiates"}` (bootstrap primitives only). The dynamic Neo4j query for reified relationship concepts is implemented but commented out (`:289-320`) to avoid 100+ redundant queries per observation.

- `classify_compression_type(rel_type, config, is_composite=False) -> str` — `add_concept_tool.py:323-344`
  - Returns `"weak_compression"` / `"simple_strong"` / `"composite_strong"`. Called only inside the dead `create_concept_in_neo4j`.

- `get_observation_queue_dir() -> Path` — `add_concept_tool.py:348-353`
  - Returns `$HEAVEN_DATA_DIR/carton_queue/`, creating it with `mkdir -p`. Used by `add_concept_tool_func` and `add_observation`.

- `rejection_ledger_path() -> str` — `add_concept_tool.py:367-371` **(NEW, 2026-07-06)**
  - The SOMA-rejection ledger file: `$HEAVEN_DATA_DIR/soma_rejections.jsonl` (dir created if absent). Part of the "Griess-Neural-Surrogate exhaust patch #1" comment block (`:356-366`).

- `record_soma_rejection(concept_name, relationships, verdict_kind, reason) -> None` — `add_concept_tool.py:374-396` **(NEW, 2026-07-06)**
  - Appends ONE oracle-labeled hard negative to the rejection ledger: `{concept, relationships, verdict_kind, reason, timestamp}`. `verdict_kind` is `"contradiction"` (Type-2 geometric reject — the node is NEVER saved) or `"mereo_error"` (Type-1 undefined-is_a fill-signal — the node IS saved as soup by carton, but the record is still a negative example of a well-formed claim). Called at BOTH branch points in `add_concept_tool_func`: the contradiction-reject path (`:2514`) and the mereo_error fall-through path (`:2553`). NEVER raises — any exception is logged and swallowed (recording a rejection must never affect the add_concept verdict path).

- `normalize_concept_name(name: str) -> str` — `add_concept_tool.py:403-428`
  - Canonical Title_Case_With_Underscores normaliser. Single source of truth used throughout the module.

- `run_git_command(cmd, cwd) -> Dict[str, str]` — `add_concept_tool.py:431-447`
  - Runs a git subprocess; returns `{"output": ...}` or `{"error": ...}`. Used by `setup_git_repo`, `sync_with_remote`, `commit_and_push`, `rename_concept_func`.

- `setup_git_repo(config, base_path) -> Dict[str, str]` — `add_concept_tool.py:449-491`
  - Clones the private wiki repo into `base_path` if absent; re-uses existing if present.

- `sync_with_remote(config, base_path) -> Dict[str, str]` — `add_concept_tool.py:493-509`
  - Fetches and pulls `config.private_wiki_branch` from origin.

- `auto_link_description(description, base_path, current_concept, concept_cache=None, _automaton_cache={}) -> str` — `add_concept_tool.py:512-546`
  - **Public auto-linker with CartonObj fence-opacity masking.** Locates all `<CartonObj name=..>{...}</CartonObj>` fence spans via `carton_kv.find_carton_objs`, masks each with a private-use Unicode char (`chr(0xE000+i)`) so the linker's bracket-strip regexes and Aho-Corasick automaton cannot touch them, calls `_auto_link_core`, then restores each fence VERBATIM. Degrades to plain linking if `carton_kv` is unavailable.

- `_auto_link_core(description, base_path, current_concept, concept_cache=None, _automaton_cache={}) -> str` — `add_concept_tool.py:549-698`
  - Converts concept-name mentions to `[text](../Concept/Concept_itself.md)` markdown links via a cached Aho-Corasick automaton over 7 case/underscore variations per concept. **Danger (unchanged):** after stripping well-formed wiki links, it strips ANY bare `[`/`]` (`:592-593`) — any caller bypassing `auto_link_description`'s fence masking will have JSON-array brackets silently eaten.

- `find_auto_relationships(content, base_path, current_concept, concept_cache=None) -> List[str]` — `add_concept_tool.py:700-735`
  - Same variation set as `_auto_link_core` but via `re.search`. No live caller (only referenced from the commented-out dead-code block near the end of the file).

- `infer_relationships_for_missing_concept` / `check_missing_concepts_and_manage_file` — `add_concept_tool.py:738-786` / `789-871`
  - Filesystem-scan helpers for `missing_concepts.md`. No live caller (referenced only from dead code).

- `commit_and_push(config, base_path, commit_msg) -> Dict[str, str]` — `add_concept_tool.py:873-885`
  - `git add . && git commit && git push`. No live caller in the MCP path (git moved to the background daemon), EXCEPT it is reused directly by `rename_concept_func`'s own inline git calls (which call `run_git_command` directly, not this wrapper — see below).

- `check_part_of_cycle` / `check_is_a_cycle` / `is_concept_instantiated` / `check_instantiates_completeness` / `get_next_version_number` — `add_concept_tool.py:888-918` / `921-951` / `954-977` / `980-1048` / `1051-1095`
  - Unchanged cycle/completeness/versioning validators. `check_part_of_cycle` and `check_is_a_cycle` are called by `validate_observation_background`; `check_instantiates_completeness` likewise; `is_concept_instantiated` and `get_next_version_number` have no live caller outside the commented-out dead-code block.

- `create_concept_in_neo4j(config, concept_name, description, relationships, shared_connection=None) -> str` — `add_concept_tool.py:1098-1328`
  - **Dead — zero live callers.** Formerly performed synchronous Neo4j MERGE + relationship writes + REQUIRES_EVOLUTION tagging + REIFIES-validation-and-promotion. Replaced by the daemon's `batch_create_concepts_neo4j`. Contains the only live-in-code REIFIES-validation logic (`:1255-1315`): if a concept supplies `reifies` and all its relationships are strong-compression, auto-adds `PROGRAMS → Carton_Ontology_Entity` and `IS_A → Carton_Ontology_Entity`; if any relationship is weak, removes the `REIFIES` edge. This logic is NOT reachable from any live path.

- `get_update_history_symbol(concept_name) -> str` — `add_concept_tool.py:1331-1341`
  - First uppercase char of the normalised name (A-Z or 0-9), for bucketed `{Symbol}_Update_History` concepts.

- `update_concept_history(concept_name, observation_name, confidence, timestamp) -> None` — `add_concept_tool.py:1344-1387`
  - Appends a mention entry to `{Symbol}_Update_History` via `add_concept_tool_func`. Called from `_add_observation_worker` per part concept.

- `link_observation_to_timeline(observation_name, timestamp, concept_cache=None) -> None` — `add_concept_tool.py:1390-1457`
  - Creates `{year}_Year`/`{Month}_{year}_Month`/`Day_{Y}_{m}_{d}` concepts (each `part_of` the next) via `add_concept_tool_func`. Called from `_add_observation_worker`.

- `sink_concept_globally(concept_name, config, reason) -> Dict[str, Any]` — `add_concept_tool.py:1460-1531`
  - Renames concept → `{concept_name}_v1` in Neo4j, creates a `REQUIRES_EVOLUTION` edge, renames the filesystem dir. Called by `validate_observation_background` on cycle/completeness failures.

- `validate_observation_background(observation_name, all_concept_names) -> None` — `add_concept_tool.py:1534-1690`
  - Post-creation validator run SYNCHRONOUSLY (not actually backgrounded) from `_add_observation_worker`. Steps: intra-observation auto-linking of part concepts' on-disk description files; IS_A cycle check + sink per part; PART_OF cycle check + sink per part; INSTANTIATES completeness check + sink per part.

- `_add_observation_worker(observation_data, shared_connection=None) -> str` — `add_concept_tool.py:1693-1880`
  - Internal worker called by `observation_worker_daemon`, never by MCP tools directly. Queries Neo4j once for all concept names (query-once cache), generates `{timestamp}_Observation`, links to Timeline hierarchy, creates the observation wrapper + each tagged part concept (enforcing `is_a`/`part_of`/`has_personal_domain`/`has_actual_domain` on each), calls `update_concept_history` per part, then `validate_observation_background` synchronously.

- `add_observation(observation_data: Dict[str, Any]) -> str` — `add_concept_tool.py:1883-1920`
  - **Queue-write shim exposed as MCP tool.** Writes `observation_data` verbatim to `$HEAVEN_DATA_DIR/carton_queue/{timestamp}_{uuid8}.json` and returns immediately; does NOT call `_add_observation_worker` (the daemon does).

- `validate_giint_hierarchy` — `add_concept_tool.py:1923-2019`
  - **Fully commented-out dead code** since 2026-03-29 (unchanged — the reasoner inside `youknow()`/SOMA does this now, not a bypassing Python check).

- `ADMIN_ROLLUP_KEYS`, `_rollup_sentence_isa_partof`, `_rollup_sentence_has_instantiates`, `_rollup_sentence_produces`, `_compute_description_rollup` — `add_concept_tool.py:2033-2114`
  - The D2 REVERSE-rendering machinery (render the supplied relationship graph back into Isaac's natural-paragraph template: `"{X} {is_a}, {part_of} in the {subdomain} subdomain of {domain} domain. X has {has-part list}, which instantiates {instantiates}. {X} instantiating that graph produces {produces}."`). `_compute_description_rollup` is **dead — zero callers**; the module comment at `:2022-2031` explains the archaeology (D1 = preserve raw prose separately, the `raw_staging` queue field; D2 = this never-wired reverse-render).

- `_compute_d2_coverage(description, relationship_dict) -> (coverage_pct, unmatched_targets)` — `add_concept_tool.py:2117-2152`
  - **Read-only coverage check, never a gate.** Never modifies/truncates/rejects the caller's description. Checks each relationship TARGET name (underscored→spaced, case-folded) for a literal substring hit in the description; a heuristic, not full semantic coverage. Called by `add_concept_tool_func` (`:2598`) to append an informational `[D2: ...]` tag to the response.

- `merge_optional_domain_fields(relationships, domain, subdomain, personal_domain, produces) -> List[Dict[str, Any]]` — `add_concept_tool.py:2155-2210`
  - **Task 58 (2026-07-04).** Pure helper giving `add_concept_tool_func` OPTIONAL `domain`/`subdomain`/`personal_domain`/`produces` params, mirroring `add_concept`'s MCP-level has_domain/has_subdomain/has_personal_domain/produces convenience-building but every field here is OPTIONAL (unlike `sm_gate.py`'s `create_sm_chain`, which REQUIRES them — see that module's doc(m) for why the two differ: this internal function is the one chokepoint every EXISTING caller across the monorepo already passes through, so making the fields required here would break ~8 callers that have not been individually audited). `personal_domain` IS enum-validated regardless (raises if invalid). Operates on the `relationships` LIST (not `relationship_dict` — the derived, validation-only view), returning a NEW list with each provided field merged in (appended if the relationship type is absent, deduped into the existing entry if present).

### Primary public functions

- `add_concept_tool_func(concept_name, description=None, relationships=None, concept_cache=None, desc_update_mode="append", hide_youknow=False, shared_connection=None, _skip_ontology_healing=False, source="agent", target_descs=None, typed_values=None, old_str_for_edit_case=None, properties=None, cb_guidance=False, domain=None, subdomain=None, personal_domain=None, produces=None) -> str` — `add_concept_tool.py:2213-2992` **(the core entry point — CHANGED)**
  - Processing steps, in order:
    1. Validates `relationships` non-empty (`:2300-2301`).
    2. **`merge_optional_domain_fields`** (`:2312`) merges the optional domain/subdomain/personal_domain/produces params into `relationships` BEFORE `relationship_dict` is built, so the merge lands both in SOMA/D2 validation AND the actual queue-write persistence.
    3. Builds `relationship_dict`.
    4. Accumulates existing CartON relationships from Neo4j via `query_wiki_graph` so SOMA validates the full accumulated state (`:2321-2342`).
    5. **SOMA gate** (`:2376`, `if _soma_up() and not hide_youknow:` — **now gated on `_soma_up()`, not the frozen `SOMA_AVAILABLE`**): builds a typed observation (each relationship target gets `string_value` by default, overridable via `typed_values`), calls `soma_validate`, and parses the result for: `soup_gaps=` lines, `failure_error`, per-concept `status=<name>:<level>` (doc-27 authoritative status line, matched underscore-insensitively against `concept_name` — SOMA and CartON canonicalize names DIFFERENTLY), `unmet=N`, `fillable_requests` (via `soma_sdk.SomaResponse.from_verdict`), and **`fired_chains=` (NEW, `:2637-2675`)** — parses each `  - chain: <name>` line into `_fired_chains`, and if non-empty, best-effort appends `{concept, fired_chains, status, timestamp}` to `$HEAVEN_DATA_DIR/soma_fired_chains.jsonl` (the Chain_Prioritizer training substrate; a ledger fault is logged and swallowed).
    6. **TYPE-2 CONTRADICTION reject** (`:2502-2520`): if `_soma_concept_status == "contradiction"`, extracts the reason from the `contradictions=` block, **calls `record_soma_rejection(concept_name, relationships, "contradiction", reason)`** (NEW — captures the oracle-labeled hard negative before the early `return`), and returns a `❌ ... REJECTED` message WITHOUT writing to the queue — CartON does not save a geometric contradiction even as soup.
    7. **MEREO_ERROR fill-signal** (`:2533-2560`): if `_soma_concept_status == "mereo_error"`, extracts the reason from the `mereo_errors=` block, **calls `record_soma_rejection(concept_name, relationships, "mereo_error", reason)`** (NEW), sets an informational `youknow_msg`, and FALLS THROUGH to the queue write — CartON still saves the node as soup.
    8. HAS_VALIDATOR template check (`:2562-2583`): for each `part_of` parent, queries `REQUIRES_RELATIONSHIP`; raises if the child is missing required rel types.
    9. D2 coverage check (`:2597-2598`) — informational only.
    10. **Three-level status classification** (`:2606-2803`): derives `_is_soup` / `_is_code` / `_is_system_type` — authoritative from the `status=` line when present, else falls back to `soup_items`/`all_core_requirements_met`/`unmet` inference.
    11. Parses `release_effects=` (`:2677-2701`), `composed=` (`:2703-2734`), `compose_suggestions=` (`:2736-2765`) verdict sections into `queue_data` fields, exactly as before.
    12. **CB fan-out + join** (`:2815-2846`): derives `soma_region` from the just-computed three-level status (`system_type`/`code`/`mereo_error`/`soup`/`unvalidated` — no second SOMA call), calls `_cb_place` best-effort, and merges `{soma_region, cb_x, cb_y, cb_encoded}` into `_merged_properties` alongside any caller-supplied `properties`.
    13. **Queue write** (`:2921-2922`): serialises `queue_data` to `{timestamp}_{uuid8}_concept.json`.
    14. D2 tag + CB tag appended to the response message (`:2966-2985`).
    15. Returns `"✅ {concept_name}{youknow_msg}"` (or the `❌` reject message from step 6, which returns early).

  **Queue payload fields** (written to `{timestamp}_{uuid8}_concept.json`, `add_concept_tool.py:2848-2919`):
  - `raw_concept: True`, `concept_name`, `description` (caller's raw prose, verbatim), `raw_staging` (same, D1 remnant), `relationships` (list form, POST-merge), `desc_update_mode`, `old_str_for_edit_case`, `hide_youknow`
  - `is_soup`, `soup_reason`, `is_code`, `is_system_type` (mutually exclusive)
  - `unmet_dchains: int`
  - **`fired_chains: List[str]`** (NEW) — which chains fired this event, from the `fired_chains=` block
  - `gen_target: None` (always — SOMA does not emit a projection target)
  - `release_effects`, `fillable_requests`, `composed_triples`, `compose_suggestions` — the RELEASE-LAW / authorization / carton-bundle-back / L3b channels, each `[]` when SOMA emitted none
  - `skip_ontology_healing`, `source`, `target_descs`
  - `properties: _merged_properties` — the caller's `properties` dict merged with `{soma_region, cb_x, cb_y, cb_encoded}` from the CB fan-out.

- `rename_concept_func(old_concept_name, new_concept_name, reason="Conceptual refinement") -> str` — `add_concept_tool.py:3278-3523`
  - Proactive concept evolution (not sinking). Verifies old exists and new does not; `CREATE`s new node copying old description (direct Cypher, bypasses queue and SOMA); redirects all incoming edges from old to new; copies all outgoing edges; creates `EVOLVED_TO`/`EVOLVED_FROM` bidirectional links; optionally copies the filesystem `_itself.md` with an evolution note; runs `git add . && git commit` directly via `run_git_command` (not `commit_and_push`). Old concept preserved as historical record.

## Dependencies

### Stdlib
- `subprocess`, `shutil`, `json`, `re`, `os`, `sys`, `traceback`, `logging`
- `pathlib.Path`, `typing` (Optional, Dict, Any, List)
- `difflib.get_close_matches`, `urllib.request`, `datetime`, `uuid`

### Third-party
- `ahocorasick` (pyahocorasick) — imported lazily inside `_auto_link_core`; degrades gracefully if absent
- `heaven_base` — `KnowledgeGraphBuilder` via `heaven_base.tool_utils.neo4j_utils` (the heavy `BaseHeavenTool`/`ToolArgsSchema`/`ToolResult` import was REMOVED 2026-06-25, see Notes)
- `soma_sdk` — `SomaResponse.from_verdict` (parses `soma_requests=` into typed `FillableRequest` objects), imported inline inside the SOMA-gate try block

### Intra-repo (carton-mcp package)
- `carton_mcp.concept_config.ConceptConfig` — config dataclass
- `carton_mcp.carton_utils.CartOnUtils` — `get_all_concept_names`, `query_wiki_graph`
- `carton_mcp.carton_kv.find_carton_objs` — locates `<CartonObj>` fence spans for opacity masking

### Consumers (files that import from this module)
- `carton_mcp/__init__.py` — package-level re-export
- `server_fastmcp.py` — registers `add_concept`, `add_observation` as MCP tool handlers (calling `add_concept_tool_func`/`add_observation` DIRECTLY — no `BaseHeavenTool` wrapper layer, see Notes)
- `observation_worker_daemon.py` — calls `_add_observation_worker`, `auto_link_description`, `normalize_concept_name`
- `sm_gate.py` — imports `PERSONAL_DOMAINS` (its own `create_sm_chain`'s enum validation reads this canonical source, never a duplicate)
- `ontology_graphs.py` — imports `add_concept_tool_func` for ontology bootstrapping
- `carton_utils.py` — imports `normalize_concept_name`
- Test files exercising this module's various capabilities (fence opacity, split-content, relationship constraints, etc.)

## Notes

1. **`create_concept_in_neo4j` (:1098) is dead code — zero live callers.** All Neo4j writes happen inside `observation_worker_daemon.batch_create_concepts_neo4j`. Contains the only live-in-code REIFIES-validation-and-auto-promotion logic; unreachable from any live path.

2. **`_compute_description_rollup` (:2083) is dead code — zero callers.** The D2 reverse-render design; `raw_staging` in queue payloads is its D1 sibling, written but UNVERIFIED whether consumed downstream.

3. **The `_soma_up()` gate replaces the old frozen-`SOMA_AVAILABLE` gate (2026-07-06).** Before this fix, a process that imported this module while SOMA was mid-event (a 2-second timeout race under continuous daemon load) froze `SOMA_AVAILABLE=False` for the rest of that process's life, silently skipping ALL validation. `_soma_up()` re-checks per call while `False` and treats a timeout as "up but busy," never as "down."

4. **YOUKNOW is fully deleted, not merely dead.** The 2026-06-10 doc(m) documented `YOUKNOW_URL`/`youknow_validate`/`_check_youknow_available`/`YOUKNOW_AVAILABLE` as present-but-uncalled; as of this file, all four are GONE (removed 2026-06-15 per the inline comment at `:25-28`). Do not look for them.

5. **The `AddConceptTool`/`RenameConceptTool` `BaseHeavenTool` wrapper classes documented in the 2026-06-10 doc(m) are GONE (removed 2026-06-25).** A trailing comment (`:3526-3535`) confirms: nothing in the monorepo imported them; their only real effect was forcing `from heaven_base import BaseHeavenTool, ToolArgsSchema, ToolResult` at module top, which pulled `langchain_core` (~53MB) into every carton process. `server_fastmcp.py` calls `add_concept_tool_func`/`rename_concept_func`/`add_observation` directly via FastMCP, and always did.

6. **Bracket-strip danger in `_auto_link_core`** (`:592-593`, unchanged). Any caller passing text with JSON arrays or markdown tables directly — without going through `auto_link_description`'s fence-opacity masking — will have those brackets silently deleted.

7. **`_automaton_cache` is a mutable default argument** (unchanged) — persists for the process lifetime; cache invalidation is by concept-count only, so a delete-then-re-add-to-the-same-count can reuse a stale automaton.

8. **`record_soma_rejection` and the `fired_chains`/`soma_fired_chains.jsonl` ledger are BEST-EFFORT exhaust capture, never gates.** Both wrap their file I/O in try/except and log-and-swallow on failure — a ledger fault must never affect the add_concept verdict path itself. These are two of the three P0 Griess-Neural-Surrogate exhaust patches landed 2026-07-06 (the third, `sm_gate.py`'s episode ledger, lives in that module).

9. **`rename_concept_func` bypasses the queue** (direct `CREATE` Cypher). SOMA validation is skipped and no queue file is written for the new node.

10. **`_add_observation_worker` runs synchronously** within the daemon despite being named "worker"; `validate_observation_background` runs inline, not in a thread.

11. **`merge_optional_domain_fields`'s fields are OPTIONAL here, unlike the same fields on `sm_gate.py`'s `create_sm_chain`, which are REQUIRED** — this is a deliberate, documented asymmetry (see that function's own docstring at `:2162-2210`): this internal function is the one chokepoint every EXISTING caller across the monorepo (Dragonbones, `sm_gate.py`, `split_content_concept`, migration scripts) already passes through, so requiring the fields here would break all of them until individually audited; `create_sm_chain` is a brand-new capability with exactly 4 known callers, all updated in the same change, so it can require them from day one.
