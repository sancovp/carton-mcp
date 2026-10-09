# doc(m): observation_worker_daemon.py

- **Canonical path:** /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/observation_worker_daemon.py
- **Line count:** 2530 (measured, `wc -l`; 2026-08-29 DELTA x2: the #198 live observation-validation dead-letter branch in the worker loop (per queue file, before parse: observation_validation_errors -> annotate error_message + failed/, drain continues; parse now imports OBSERVATION_NON_TAG_KEYS from add_concept_tool as the one home) AND the #206 wiki-lane containment gate in create_wiki_files_for_concepts + the module-level carton_pathguard import — line cites below this point drift by up to +14 lines and are otherwise carried forward from the 2026-08-28 derivation)
- **Module role:** The CartON write daemon. It is a single long-lived process that watches
  `$HEAVEN_DATA_DIR/carton_queue/*.json`, parses each queue file into a flat concept list, writes the
  whole batch into the graph with UNWIND, and then runs a fixed sequence of post-write phases
  (properties, SOUP marking, release-effect dispatch, SOMA request/suggestion parking, composed-triple
  realization, PBML lane moves, stub resolution, wiki-file + Chroma indexing). It also owns three
  side jobs that only exist because this process owns the graph handle: it spawns the two Chroma
  processes, it serves the box's graph query endpoint, and it runs the background auto-linker thread.

## What this module IS (from the code)

**It is a poll loop over a directory, not a service.** `worker_daemon()` (`:1859`) is the entrypoint;
`if __name__ == "__main__": worker_daemon()` (`:2495`) is the only thing at module bottom. The loop
(`:2022`) does `sorted(queue_dir.glob('*.json'))` every second (`time.sleep(1)`, `:2477`), takes the
first `UNWIND_BATCH_SIZE` (2000) **files** (`:2038`), and processes them as one batch. Note the
constant's docstring (`:33`) describes it as a batch size "for UNWIND operations" — in the only place
it is used it caps the number of QUEUE FILES per iteration, not the number of concepts in the UNWIND.

**Startup is a fixed six-step sequence**, all inside `worker_daemon()`:

1. **PID lock** (`:1874-1887`) — `fcntl.flock(LOCK_EX|LOCK_NB)` on `/tmp/carton_worker.pid`. A second
   worker exits 0 ("gracefully"), a lock error exits 1. This is the only concurrency control; it is
   what stops two workers racing on the queue.
2. **Chroma store** (`:1898-1907`) — `Popen(["python3","-m","chromadb.cli.cli","run", --path
   $HEAVEN_DATA_DIR/chroma_db, --host localhost, --port 8101])`, then a bare `sleep(2)` and a log line
   claiming it started. Nothing checks that it did.
3. **Chroma daemon** (`:1915-1920`) — `Popen(["python3","-m","carton_mcp.chroma_daemon","--port",
   $CHROMA_DAEMON_PORT or 8190])`. The comment states this daemon is the sole importer of
   chromadb/langchain/onnxruntime, and that `:8101` is only the vector store it talks to.
4. **Env check** (`:1923-1933`) — `NEO4J_URI/USER/PASSWORD` required (missing → `sys.exit(1)`);
   `GITHUB_PAT`/`REPO_URL` optional (missing → warn, git push disabled).
5. **Graph-open preflight** (`:1953-1967`) — calls `_graph_open_preflight()`; on failure prints a
   fenced FATAL block and `sys.exit(78)`. The reason is stated in the code comment (`:1938-1952`):
   kuzu is embedded C++ and an unreplayable WAL kills the interpreter by SIGSEGV, which this process
   cannot log about itself, so the open is proven in a CHILD process first. 78 is EX_CONFIG and is
   listed in the box supervisord's `exitcodes`, so the program stays visibly EXITED instead of
   respawning.
6. **Shared connection + the SDK's door + linker thread** (`:1970-2016`) — `_create_shared_neo4j()`,
   then `carton_api.serve_in_thread(port)` **on every backend**: the worker serves CartON's SDK
   (`POST /call {operation, params}` behind `CARTON_KEY`) — with the MCP server gone from the box this
   door is the box's only service surface — then a daemon `threading.Thread(target=linker_thread)`.

**The batch write is `batch_create_concepts_neo4j` (`:307`)**, and it is where nearly all the graph
semantics live. Order inside it is load-bearing:

- Ensure `wiki_name`/`wiki_canonical` indexes (`:329-334`), errors tolerated.
- Build `concept_rows` (`:337-355`): name normalized, canonical = lowercased, `update_mode` from
  `desc_update_mode` (default `append`), plus `old_str_for_edit_case`, `removed_fences`, `source`, and
  `region = _compute_region(c)`.
- **KV edit pre-step** (`:362-366` → `_apply_carton_kv_edits`, `:142`) — runs FIRST, because it
  rewrites successful `edit` rows into `replace` rows so everything downstream sees a normal replace.
- **Append dedup** (`:371-432`) — for `append` rows only, fetch existing `n.d`, split both sides on
  `\n\n---\n\n`, compare with wiki links stripped, keep only novel sections; nothing novel → row
  becomes `skip`. The `desc` alias in that query is backticked because it is a reserved word on the
  embedded backend (`:375-378`).
- **Fence-preservation guard** (`:440-452`) — for `replace` rows only, `carry_forward_fences(old_nd,
  new, removed_fences)` so a re-derivation cannot silently drop a `CartonObj` fence.
- **The node UNWIND** (`:460-496`) — `MERGE (n:Wiki {n: c.name})`, then one big `CASE` deciding `n.d`
  by update_mode with containment short-circuits (`c.description CONTAINS n.d` → take the new one,
  and vice versa). `n.t` is set once on birth; `n.last_modified` on every write; `n.linked=false` on
  every write (this is what re-arms the linker); `n.source` set once; `n.region = coalesce(c.region,
  n.region, 'soup')`. The separator is passed as a **parameter** (`:489-496`) because kuzu 0.11.3 does
  not process backslash escapes in a Cypher string literal and would have silently written `nn---nn`.
- **Relationships** (`:505-554`) — flattened and grouped by uppercased type, with automatic inverses
  from `inverse_map` (`:521-526`: PART_OF⇄HAS_PART, IS_A→HAS_INSTANCES, INSTANTIATES→INSTANTIATED_BY).
  One UNWIND per type (Cypher cannot parameterize a relationship type). The target is `MERGE`d, so a
  missing target is **auto-created as a stub** with `d = 'AUTO CREATED: stub node referenced as
  {rel_type} target by ...'`.
- **Timeline-stub typing** (`:567-603`) — any relationship target in this batch whose name starts with
  a known timeline prefix and has no `IS_A` gets typed by prefix. `TIMELINE_PREFIXES` (`:579-587`) is
  order-sensitive: `Iteration_Summary_` must precede `Iteration_`. The prefix match is done in Python
  (`:570-578`) because a CASE-derived variable cannot be used as a pattern property on kuzu.
- **KV schema registration** (`:608-615`), **node properties** (`:627-648` via
  `set_concept_properties`, applied AFTER the MERGE so the node is guaranteed to exist), then the
  return (`:663-669`).
- `concepts_created` is `len(concept_rows) **if nodes_written else 0**` (`:664`). The comment
  (`:656-662`) records why: it used to be unconditional, so a failed UNWIND still read as success and
  the loop moved every file to `processed/` — queue consumed, nothing written, nothing dead-lettered.

**Parsing is `parse_queue_file_to_concepts` (`:672`)** and it handles exactly three shapes:
`raw_concept`/`concept_name` (single concept, and the only branch that carries the full field set —
`is_code`, `is_system_type`, `is_soup`, `release_effects`, `fillable_requests`, `composed_triples`,
`compose_suggestions`, `properties`, `target_descs`, `removed_fences`, `skip_ontology_healing`);
`{"concepts": [...]}` (accepts two relationship spellings, Format A `{relationship, related}` and
Format B `{type, target}`); and otherwise an observation batch, which becomes N+1 concepts — one
`{timestamp}_Observation` wrapper `is_a Observation` `has_parts [...]` plus every tagged part, each
given `has_tag` and `part_of` the wrapper. Anything else parses to `[]`.

**The post-write phases** run in the loop, each guarded by `all_concepts and neo4j_succeeded`:

**#198 VALIDATION DEAD-LETTER (2026-08-29), in the per-file parse loop BEFORE `parse_queue_file_to_concepts`:** each queue file is read and passed to `observation_validation_errors` (add_concept_tool — the resurrected four-required-rels validator, PURE); a non-empty return prints `[Worker] VALIDATION dead-letter <file>: <reasons>`, writes the reasons into the file as `error_message` (the key `check_failed_observations`/`retry_failed_observations` already read), appends the file to `failed_files` (the existing mover lands it in `failed/`), and CONTINUES — the drain never crashes and non-observation shapes pass through untouched. Proven live 2026-08-29.

| phase | lines | what it does |
|---|---|---|
| Task-HC | `:2148-2165` | for `is_a giint_task` only, `_auto_create_task_hypercluster`. The comment records that the old `ensure_ontology_completeness` `_Unnamed` fabrication was removed 2026-06-16 because SOMA's GIINT presence d-chains compute that gap. |
| 2.5a | `:2177-2257` | `is_code or is_system_type` → delete `REQUIRES_EVOLUTION`; then dispatch every `release_effects` entry by `handler.split(":",1)` + `import_module`. Gated on `is_system_type` **except** for `_GRADE_EXEMPT_EFFECTS` (`:2217-2231`), which holds the two giint-ready-stamp handler strings plus (2026-08-28, issue #148) `carton_mcp.substrate_projector:sync_task_kanban_card` — a carton_task INSTANCE never grades is_system_type, so the grade gate would drop the kanban-card effect forever; its d-chain's code_gap premise is the gate. The dispatch arg is `c["name"]`, not `eff["arg"]` — the comment (`:2234-2241`) says SOMA's arg is the lowercase_underscore form and would not resolve as a node name. |
| 2.5d (park) | `:2269-2279` | `soma_fillers.park_fillable_requests` |
| 2.5e | `:2291-2301` | `soma_fillers.realize_composed_triples(all_concepts, shared_neo4j.execute_query)` — MERGEs SOMA's deduced triples as real edges |
| 2.5f | `:2310-2320` | `soma_fillers.park_compose_suggestions` (parking only, no graph mutation) |
| 2.5c | `:2331-2377` | `llm_intelligence.pbml_lane.match_trigger` / `apply_pbml_move`; on trigger `done_signal` it also fires `odyssey.utils.dispatch_chain` in a background thread. `ImportError` on either is caught and logged, not fatal. |
| 2.5d (stubs) | `:2381-2418` | for each `part_of` × `is_a`, if the parent points at `{is_a_type}_Unnamed`, rewrite that edge to the real concept and MERGE `EVOLVED_TO`/`EVOLVED_FROM` |
| 2.5b (wiki) | `:2421-2434` | `create_wiki_files_for_concepts`, then `sync_rag_incremental(changed_files=...)` for the files that exist on disk |

Then **Phase 3 file disposition** (`:2437-2461`): on success every parsed file moves to `processed/`;
on failure the parsed files are appended to `failed_files`; everything in `failed_files` moves to
`failed/`. When the queue is empty (`:2465-2474`) git commit+push runs only if `CARTON_GIT_AUTO ==
'true'`; the comments state RAG sync was disabled there because it blocked 30+ minutes scanning 188k
files.

**The linker thread** (`linker_thread`, `:1691`) is a second loop on its own connection. It refreshes
a concept-name cache every 300s, then selects up to 100 nodes where `linked = false OR linked IS NULL`
AND (`last_modified IS NULL` OR `last_modified < datetime($cutoff)`), newest first. The debounce
window is `CARTON_LINKER_DEBOUNCE_S` (default 1800s); the cutoff is computed **in Python** (`:1754-1765`)
because `datetime() - duration({seconds: $s})` is neo4j-only and crashed this thread every cycle on
kuzu. For each row it runs `auto_link_description` and `compute_description_score`, writes back
`d`/`linked`/`score`, and on any exception still sets `linked = true` to avoid an infinite retry.
After each batch it calls `link_concepts_to_timeline` (`:1591`, CREATED_DURING → the active
conversation read from `/tmp/heaven_data/active_conversation.json`, LIMIT 200) and
`link_concepts_to_odyssey_timeline` (`:1647`, PART_OF → `Odyssey_Timeline` for the eight types in
`ODYSSEY_CONCEPT_TYPES`, LIMIT 100).

**`log_system_event` (`:1523`)** writes a `System_Event_{ts}_{event_type}` node directly (bypassing
the queue to avoid recursion). Its query (`:1563-1580`) carries the type-shattering repair: the type
node is `MERGE`d not `CREATE`d, the instance timestamp is microsecond resolution, and **every MERGE is
collapsed with `WITH ... LIMIT 1` before the `CREATE`**, because MERGE on a duplicated name matches all
N copies and every downstream clause then runs once per row.

## Imports

### stdlib
`os`, `re`, `sys`, `time`, `json`, `traceback`, `threading`, `pathlib.Path`, `typing.Dict/Any`
(module level, `:20-28`). Function-local: `datetime`/`timedelta`/`timezone`, `collections.defaultdict`,
`shutil`, `tempfile`, `subprocess`, `fcntl`, `signal`, `importlib`, and a second `import re` in two
functions (`:399`, `:1491`) despite the module-level one.

### third-party
None imported directly. `chromadb` is only ever launched as a subprocess (`:1899`), never imported.

### local (all lazy except one)
Module level (`:31`): `carton_mcp.add_concept_tool` → `_add_observation_worker`,
`get_observation_queue_dir`, `auto_link_description`, `normalize_concept_name`, `OBSERVATION_TAGS`
(the latter re-imported locally at `:684`).
Function-local: `heaven_base.tool_utils.neo4j_utils.KnowledgeGraphBuilder`; `heaven_base.tools.
network_edit_tool.EditHelper` + `heaven_base.baseheaventool.ToolError`; `carton_mcp.carton_kv.
carry_forward_fences`; `carton_mcp.carton_utils.register_kv_schemas` / `set_concept_properties` /
`CartOnUtils`; `carton_mcp.substrate_projector.compile_memory_tier`; `carton_mcp.chroma_client.
chroma_index` / `chroma_route`; `carton_mcp.carton_api.serve_in_thread`/`DEFAULT_PORT`/
`required_key`; `carton_mcp.ontology_graphs._auto_create_task_hypercluster`; `carton_mcp.soma_fillers.
park_fillable_requests` / `realize_composed_triples` / `park_compose_suggestions`;
`llm_intelligence.pbml_lane.apply_pbml_move`/`match_trigger`; `odyssey.utils.dispatch_chain`.

## Top-level definitions

**Constants:** `UNWIND_BATCH_SIZE = 2000` (`:34`); `_ACTIVE_HC_FILE = Path("/tmp/active_hypercluster.txt")`
(`:1400`); `_STOP_WORDS` frozenset (`:1472`); `CHAT_SOURCES = {agent, dragonbones_hook, session_start}`
(`:1515`); `SYSTEM_SOURCES` (7 entries incl. `webbing_agent`, `:1516`); `ODYSSEY_SOURCES` (`:1517`);
`ACTIVE_CONV_MARKER = Path("/tmp/heaven_data/active_conversation.json")` (`:1520`);
`ODYSSEY_CONCEPT_TYPES` (8 names, `:1643`).

**Write path**

- `create_wiki_files_for_concepts(concepts_data: list) -> dict` (`:38`) — writes
  `$HEAVEN_DATA_DIR/wiki/concepts/<Normalized>/<Normalized>_itself.md` with an Overview section and a
  Relationships section sorted by rel type, each target rendered as a relative markdown link. Returns
  `{files_created, files_skipped, errors}`. **GUARDED (#206, 2026-08-29):** per concept, BEFORE the
  `mkdir`, `check_write(str(itself_file), 'wiki')` (module-level import from
  `carton_mcp.carton_pathguard`, `:32`) asserts containment under `$HEAVEN_DATA_DIR/wiki`; a
  `CartonPathRefused` is appended to `errors` (`Refused <name>: ...`), printed to stderr, and the
  loop CONTINUES — a garbage name mints neither directory nor file, and the drain never crashes.
- `_carton_undo_dir_for_today() -> Path` (`:117`) — returns `$HEAVEN_DATA_DIR/carton_undo/<YYYY-MM-DD>/`
  and, as a side effect, `rmtree`s every other date directory. Best-effort, never raises.
- `_apply_carton_kv_edits(concept_rows: list, graph) -> None` (`:142`) — mutates rows in place. For each
  `edit` row: read current `n.d`; write a per-ATTEMPT undo file `{name}.{HHMMSS_%f}.json`; run
  `EditHelper().str_replace` on a temp file (exactly-once enforced); on success rewrite the row as
  `replace` with the edited `n.d`, on any failure set `skip` so `n.d` is untouched. `_persist_outcome`
  (`:172`) writes `kv_edit_error`/`kv_edit_error_at` onto the node and clears them on success. If
  `EditHelper` cannot be imported, every edit row fails safely (`:163-170`).
- `_compute_region(c: dict) -> str | None` (`:272`) — `cb` if any `is_a` starts with `cb_`/`crystal_ball`,
  else `system_type` / `code` / `soup` from the SOMA flags, else **None** so the UNWIND's `coalesce`
  does not clobber an already-climbed region. The docstring records that the old `is_a TreeShell_Node
  → region='treeshell'` early return was removed because it conflated two orthogonal axes.
- `batch_create_concepts_neo4j(concepts_data: list, shared_connection) -> dict` (`:307`) — described
  above. Returns `{concepts_created, relationships_created, errors, promoted, properties_set}`;
  `promoted` is hardcoded 0 (`:654`).
- `parse_queue_file_to_concepts(queue_file: Path) -> list` (`:672`) — described above.

**Timeline merge**

- `_process_timeline_merge(data: dict, graph) -> bool` (`:856`) — **this is the LIVE path.** Moves
  `CREATED_DURING` from the unnamed placeholder to the real conversation, then moves **every other
  relationship type in both directions** (types read from the DB and sanitized to `^[A-Z_]+$` before
  interpolation, `:904-936`), then **refuses to delete** if the real conversation does not exist
  (`:947-952`, returns False so the file dead-letters), then `DETACH DELETE`s the placeholder and logs
  a system event. Any move failure returns False rather than dropping an edge.

**Dead path**

- `process_queue_file(queue_file: Path, shared_connection=None) -> bool` (`:962`) — **dead code, zero
  callers.** See "Notes / discrepancies".

**Side jobs**

- `git_commit_all_changes()` (`:1135`) — `git add .` + commit in `$HEAVEN_DATA_DIR/wiki`.
- `sync_rag_incremental(changed_files=None)` (`:1179`) — with a file list, routes each path to a
  collection via `chroma_route` and indexes it; without one, falls back to an mtime scan of
  `**/*_itself.md` into `domain_knowledge`.
- `git_push_if_needed()` (`:1239`) — counts `origin/{branch}..{branch}` and pushes with the PAT
  interpolated into the URL, 30s timeout.

**Connection / health**

- `_graph_open_preflight(timeout_s=60) -> dict` (`:1290`) — runs a `KnowledgeGraphBuilder(...)
  ._ensure_connection()` probe in a subprocess. Sizes `KUZU_DB_PATH` and its `.wal` first and flags a
  WAL larger than the main file. Negative returncode → named signal death; nonzero → exit code plus
  last stderr line. A failure of the probe itself returns `openable: True` so the preflight can never
  be what takes the box down.
- `_create_shared_neo4j()` (`:1365`) — `KnowledgeGraphBuilder` from `NEO4J_URI` (default
  `bolt://host.docker.internal:7687`) / `NEO4J_USER` (`neo4j`) / `NEO4J_PASSWORD` (`password`), then
  `_ensure_connection()`. Returns None on failure.
- `_ensure_neo4j_alive(conn)` (`:1382`) — `RETURN 1` ping, reconnect on failure.

**Automation / scoring / timeline**

- `_sync_active_hypercluster(shared_connection) -> bool` (`:1403`) — reads
  `Seed_Ship.active_hypercluster`; if it differs from `/tmp/active_hypercluster.txt` AND the target is
  a node typed `IS_A Hypercluster`, writes the file and recompiles memory tier 0. Runs once per loop
  iteration, even with an empty queue.
- `compute_description_score(description, concept_cache) -> int` (`:1483`) — % of non-stop-word tokens
  in the description that appear in a flat token set built from all concept names (each name
  contributes itself lowercased plus its underscore-split parts).
- `log_system_event(neo4j_conn, event_type, description, source)` (`:1523`) — described above.
- `link_concepts_to_timeline(neo4j_conn)` (`:1591`), `link_concepts_to_odyssey_timeline(neo4j_conn)`
  (`:1647`), `linker_thread(stop_event)` (`:1691`) — described above.
- `worker_daemon()` (`:1859`) — the entrypoint and the whole loop.

## What this module CALLS

Graph: `KnowledgeGraphBuilder.execute_query` / `_ensure_connection` / `close` (heaven-framework).
CartON siblings: `add_concept_tool` (`normalize_concept_name`, `auto_link_description`,
`get_observation_queue_dir`, `_add_observation_worker`, `OBSERVATION_TAGS`), `carton_kv.
carry_forward_fences`, `carton_utils` (`register_kv_schemas`, `set_concept_properties`, `CartOnUtils.
get_all_concept_names`), `substrate_projector.compile_memory_tier`, `chroma_client` (`chroma_index`,
`chroma_route`), `carton_api` (`serve_in_thread`, `required_key`, `DEFAULT_PORT`),
`ontology_graphs._auto_create_task_hypercluster`, `soma_fillers` (three functions).
Cross-repo: `heaven_base.tools.network_edit_tool.EditHelper`, `llm_intelligence.pbml_lane`,
`odyssey.utils.dispatch_chain`, and whatever module string a SOMA `release_effect` names (imported
dynamically at `:2247-2248`).
Subprocesses: `python3 -m chromadb.cli.cli run`, `python3 -m carton_mcp.chroma_daemon`, `git`, and the
preflight probe.
Filesystem: the queue dir and its `processed/` and `failed/` subdirs, the wiki tree,
`/tmp/carton_worker.pid`, `/tmp/active_hypercluster.txt`, `/tmp/heaven_data/active_conversation.json`,
`/tmp/memory_compile_last.txt` (dead path only), `$HEAVEN_DATA_DIR/carton_undo/<date>/`,
`/tmp/chroma_server.log`, `/tmp/chroma_daemon.log`.

## What CALLS this module (grep-confirmed)

**As a process (the real invocation):**
- `knowledge/carton-mcp/server_fastmcp.py:3715` — `_ensure_daemon_running()` does
  `pgrep -f observation_worker_daemon.py`, and if absent `Popen(['python3', <this file>])` with an env
  dict, `start_new_session=True`, logging to `/tmp/carton_worker.log`. Called from `main()` at
  `server_fastmcp.py:3728` — i.e. the daemon is started by the carton MCP server's entrypoint.
- `knowledge/carton-mcp/server_fastmcp.py:1268,1295` — `carton_management(restart_bg_server=True)`
  does `pkill -f observation_worker_daemon.py` then the same `Popen`.
- `application/carton-saas/box/supervisord.conf:41` — `[program:carton-worker] command=python -m
  carton_mcp.observation_worker_daemon`, `autorestart=unexpected`, `exitcodes=78`.
- `application/sanctuary-revolution/start_sancrev.sh:174` — `pkill -f "observation_worker_daemon"`
  with the comment "carton relaunches it on MCP connect".
- `base/sdna/mcps/summarizer_mcp.py:583,610,2634,2661` and the two copies at
  `integration/summarizer-mcp/summarizer_mcp/server.py` and
  `integration/observatory-sdna/container/sdna/mcps/summarizer_mcp.py` — the same pkill/pgrep/Popen
  pair, but resolving `daemon_path = Path(__file__).parent / 'observation_worker_daemon.py'`, which in
  those packages is a path that does not contain this file.

**As an importable module (symbol callers):**
- `knowledge/carton-mcp/webbing_agent.py:146` — `compute_description_score`; `:285,313` — `CHAT_SOURCES`.
- `knowledge/carton-mcp/dedupe_wiki_duplicates.py:50-51` — `_create_shared_neo4j`.
- `starsystem/starlog-mcp/starlog_mcp/score_compiler.py:87` — `_create_shared_neo4j`.
- `knowledge/carton-mcp/test_carton_kv_schema.py:228,238` — `parse_queue_file_to_concepts`.
- `knowledge/carton-mcp/tests/test_composed_consumer.py:146-147` — `parse_queue_file_to_concepts`.
- `base/soma-prolog/tests/test_l3b_suggestion.py:187-188` — `parse_queue_file_to_concepts`.
- `knowledge/carton-mcp/test_timeline_merge_live_path.py:9,34,45,52-61,96,116` —
  `_process_timeline_merge` (and stubs out `log_system_event` at `:131`).
- `knowledge/carton-mcp/test_log_system_event_no_duplicate_types.py:43,59,128,139` — `log_system_event`.
- `base/heaven-framework/tests/test_graph_store.py:173,435,562` — reads this file's text to assert the
  daemon's UNWIND query stays engine-portable.

No grep hits call `create_wiki_files_for_concepts`, `git_commit_all_changes`, `git_push_if_needed`,
`sync_rag_incremental`, `_sync_active_hypercluster`, `_graph_open_preflight`, `linker_thread`, or
`worker_daemon` from outside this file; they are internal to the loop.

## Notes / discrepancies

**`_process_timeline_merge` is the LIVE path. `process_queue_file` is the dead one.** This is settled
by the call sites, not by the docstrings:

- `_process_timeline_merge` (`:856`) is called at `:2063`, inside the worker loop's empty-parse
  branch: a queue file that parses to `[]` is re-opened, and if it carries `timeline_merge` it is
  routed here (success → `unlink`, failure → `failed_files`). It is additionally exercised by
  `test_timeline_merge_live_path.py`.
- `process_queue_file` (`:962`) has **zero callers**. In-file, the name appears only inside comments
  and docstrings (`:717`, `:861`, `:873`, `:2054`). Across the monorepo the only hit is
  `carton_utils.py:62`, which is prose explicitly saying it is *not* the path. It cannot be reached.

The two have **diverged**, deliberately. `_process_timeline_merge`'s own docstring (`:868-874`) says so
in as many words: it used to claim identical semantics, and that sentence stayed true only until
2026-08-24. The live handler transfers every relationship type in both directions and refuses to delete
when the merge target is absent; the dead copy (`:989-1002`) still moves only `CREATED_DURING` and then
`DETACH DELETE`s unconditionally, which would destroy the placeholder's `PART_OF`/`HAS_PART` edges.
The docstring states the dead copy is not maintained in lockstep.

**The dead path also contains a latent `NameError`.** At `:1059`,
`concept_name = rel_dict.get('concept_name','') or queue_data.get('concept_name','')` references
`queue_data`, which is never defined in `process_queue_file` (the local is `observation_data`). The
first operand is also wrong on its own terms — `rel_dict` holds relationships, so it can never contain
a `concept_name` key. Reaching that line raises. This is consistent with the branch being dead.

**`_add_observation_worker` is imported at module level (`:31`) but used only at `:1093`, inside the
dead path.** The other three names from that import are live.

**Duplicated phase labels in the worker loop.** "Phase 2.5d" labels two different phases —
`:2259` (SOMA request park) and `:2379` (resolve `_Unnamed` stubs). "Phase 2.5b" also labels two —
`:2322` (a comment about a removed path) and `:2420` (wiki-file creation). The wiki phase labelled
"2.5b" executes after 2.5f. The labels do not track execution order.

**Inconsistent duplicate count inside one comment block.** `log_system_event`'s comment says the
`System_Event` universal was "shattered into 41,721 byte-identical copies" at `:1544` and "the 41,751
duplicate type nodes" at `:1554`.

**Stale line references pointing at this file from elsewhere.** `application/carton-saas/box/
supervisord.conf:25` cites "observation_worker_daemon.py:1581,1591" for the chroma spawns; they are
actually at `:1898` and `:1915`. Several test docstrings cite "observation_worker_daemon.py:1302" for
the production-default `NEO4J_URI`; the default is at `:1370` (and `:1305` in the preflight probe
string).

**Two no-op conditional expressions.** `:1632` and `:1669` both read
`[r['name'] if isinstance(r, dict) else r['name'] for r in result]` — both branches are identical, so
the `isinstance` check does nothing. The same pattern is written correctly elsewhere in the file
(e.g. `:1790-1791`, which uses `.get()` in the dict branch).

**Two paths derive the wiki file path differently.** `create_wiki_files_for_concepts` writes to
`normalize_concept_name(name)` (`:68`), but the loop's existence check at `:2429` derives the path with
`c.get('name','').replace(' ','_')`. `normalize_concept_name` also replaces hyphens and title-cases
(`add_concept_tool.py:406-413`), so these are not the same function. They agree in practice only
because `parse_queue_file_to_concepts` already normalized every name before it reaches here; a name
arriving un-normalized would be written under one path and looked up under another, and would silently
just not be indexed.

**`files_skipped` is always 0.** `create_wiki_files_for_concepts` declares it (`:57`), returns it
(`:112`), and never increments it — every file is rewritten unconditionally.

**Chroma subprocess startup is unverified by the code.** `:1906` sleeps 2 seconds and `:1907`/`:1920`
print success lines regardless of whether either `Popen` produced a working server. Failures surface
only in `/tmp/chroma_server.log` / `/tmp/chroma_daemon.log`.

**The linker marks failures as linked.** In `linker_thread`, an exception while linking a concept still
issues `SET c.linked = true` (`:1815-1822`), with two bare `except:` clauses. The stated reason is to
avoid infinite retry; the effect is that a concept that failed to link is indistinguishable afterwards
from one that linked successfully.

**Two module-level side effects at import time.** Importing this module executes the
`from carton_mcp.add_concept_tool import ...` at `:31` (which is why the symbol-importing tests get the
add_concept_tool import chain), but nothing else runs — the loop is behind `__main__`.

**Two `import re` statements are redundant** (`:399`, `:1491`) given the module-level `import re` at
`:22`.

**`promoted` is vestigial.** `batch_create_concepts_neo4j` sets `promoted = 0` (`:654`) with a comment
saying the youknow-based promotion was removed, and returns it unchanged; no caller reads it.

**Not determinable from this file:** whether the `_GRADE_EXEMPT_EFFECTS` handler modules are importable
in any given deployment (`llm_intelligence` is explicitly expected to be absent in a lean box, per the
comment at `:2333-2339`), and whether `CARTON_GIT_AUTO` is ever set anywhere. Both would be settled by
inspecting the deployment's environment, not the code.

<!-- ===VISION DELTA: id-tagged appends below = the gap (`vision diff <m>`); `doc-mirror-commit --realizes <ids>` drops them on build === -->
- [v1]  2026-09-04T03:28:13  FINDING: FINDING, 2026-09-04 03:30, second deconfabulate run (history 2026_09_04_03_26_58_deconfabulator) on why the webber never ran live, verified against git. Verdict CONFABULATED for the claim that it was deliberately parked with a plan and has run since. What is true: the webber was built and committed 2026-07-04 (4565dc5fb) and its dry-mode code was E2E-verified that night; it was NEVER wired into the observation worker daemon dispatch even though its own design spec Daemon_Webbing_Agent_Design says a worker agent living in observation_worker_daemon; no process was ever spawned; the state file is untouched since 2026-07-04 02:59; the Sophia chain about it stops 2026-07-10 and no later journal, commit or tool call touches it; there was never a follow-up decision. The one thing the deconfab got wrong: it said no reason for staying dry exists anywhere in the record, because it reads the graph and the reason is in the git commit BODY, which the graph holds only as a subject line. The body says: Still open, Isaac s call before flipping the live flag: the eligibility score/relationship-count thresholds are judgment calls, and one dry test run showed the agent can over-interpret prose into invented child concepts. So the real history is a park on Isaac with two named questions (thresholds, over-interpretation) that no one ever re-raised, which is the exact failure the P1.3 decision-check exists to catch. Both questions are still open and both are Isaac s to rule on before the live flag is set: the eligibility thresholds, and whether an over-interpreting webber is acceptable or must be constrained, which his 2026-09-04 statement of the job (conceptualize what the description refers to, reify until the web closes) partly answers by making the eligibility test description-driven rather than score-driven.  tags:[webbing_agent.py, webbing_agent_worker.py, observation_worker_daemon.py, deconfabulate]
