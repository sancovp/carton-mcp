# doc(m): observation_worker_daemon.py

**Module:** `carton-mcp/observation_worker_daemon.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 8 sealed boundaries land here

## Features whose sealed boundary lands in this module

### Carton_Queue_Ingest — feature boundary (no Giint_Feature node declared)

- **user action:** a concept is written through the CartON front door, add_concept_tool_func, which POSTs it to SOMA and queues the graded node, and the observation worker must land that node in the graph and act on the verdict the payload carries
- **doc(v):** `knowledge/carton-mcp/docs/vision_extracted/add_concept.md`
- **outputs to:** `['dead_letter_lane_fires']`
- **sealed:** v5, key `d87661e7eb26a97b`, commit `37335213d`, valid from 2026-10-08T00:07:14
- **ranges in this module** (layer order):
  - `L1 parse` · `observation_worker_daemon.py:2102-2175` — phase 1 of the tick: each file is validated (observation shapes only, issue 198) and parsed; timeline merges are deferred to phase 2m; an unparseable file is dead-lettered with its reason
  - `L1 parse` · `observation_worker_daemon.py:705-888` — parse_queue_file_to_concepts: the raw_concept branch copies every verdict field OFF THE PAYLOAD, defaulting is_code, is_system_type and is_soup to False and release_effects to empty, so a payload written around the front door carries no verdict, lands ungraded and nothing downstream can fire on it. The drain grades nothing; its one SOMA call is the property trail reached at L2, carton_utils 389-511, which makes no POST while PROPERTY_TRAIL_TO_SOMA is False
  - `L2 write` · `observation_worker_daemon.py:288-702` — _compute_region and batch_create_concepts_neo4j: region from the payload verdict (None keeps the existing region, a new node defaults to soup), the edit pre-step, append dedup, fence preservation, the node UNWIND MERGE, one UNWIND per relationship type with the inverse map and auto-created stubs, timeline stub typing, then the properties applied after the node exists through carton_utils set_concept_properties, one call per concept carrying properties, which reaches the property trail; concepts_created reports the write, never the input
  - `L3 verdict` · `observation_worker_daemon.py:2180-2247` — phase 2: the batch write with retry and reconnect, then REQUIRES_EVOLUTION for every concept whose payload says is_soup
  - `L3 verdict` · `observation_worker_daemon.py:2317-2488` — THE RELEASE, where SOMA verdict becomes action: REQUIRES_EVOLUTION removed for is_code or is_system_type, each release_effect handler imported and run with the node name, gated on is_system_type except the grade-exempt effects whose d-chain premise is the gate, then the fillable requests parked, the composed triples realized as edges, the compose suggestions parked  ⟵ RELEASE
- **also passes through:** `add_concept_tool.py`, `carton_utils.py`, `test_property_trail_soma_off.py`

### Dead_Letter_Lane — feature boundary (no Giint_Feature node declared)

- **user action:** a queue batch has finished draining and the fate of every payload it parsed must be decided and RECORDED: consumed into processed, left in the queue for the next tick, or condemned to failed slash carrying the reason it was condemned for, so that a transient outage and a permanently malformed payload are never indistinguishable once they are in the directory
- **doc(v):** `docs/vision/_carton_deadletter.md`
- **outputs to:** `['dead_letter_lane_fires']`
- **sealed:** v6, key `1aa6968d7e37dc37`, commit `e5b1ae6be`, valid from 2026-09-17T07:34:15
- **ranges in this module** (layer order):
  - `L1 attempt` · `observation_worker_daemon.py:2180-2226` — THE CALL SITE that produces the attempt count, and the reason the count can be zero. Phase 2 guards the whole retry lane behind if all_concepts and shared_neo4j, so when the connection is None the guard is false and run_with_retry is never reached: no attempt, no reconnect, _write_attempts stays at its initialiser of 0 and _write_errors stays empty. _reconnect_before_retry, the one thing that could recover, lives INSIDE this branch and is therefore unreachable in exactly the case it exists for. This range is traced into this lane because the disposition below is computed from values this range either sets or leaves at zero
  - `L2 disposition` · `observation_worker_daemon.py:2630-2686` — PHASE 3, THE DISPOSITION SITE, now THREE outcomes where it had two. It calls batch_disposition with the success flag and the attempt count and branches on the answer: PROCESSED renames every parsed file into processed slash; REQUEUE leaves them exactly where they are, for the next tick to retry once _ensure_neo4j_alive re-establishes the connection at the top of the batch, and says so on stderr; DEAD_LETTER computes batch_failure_reason from the store own errors and the attempt count and extends failed_files with every parsed file, which is the unchanged behaviour for a write that was genuinely attempted and genuinely failed. BEFORE ISSUE 280 THIS ASKED ONE QUESTION, did the write succeed, so a batch that was NEVER ATTEMPTED took the identical else that a failed batch takes and was condemned under the reason batch write to the graph failed (unknown) after 0 attempt(s) -- in the same iteration in which the line one phase earlier printed that the files stay in the queue. The decision is a PURE function in carton_deadletter rather than inline here, because this block lives inside a loop that starts chroma servers and never returns, so nothing could ever drive it, which is how a two-state disposition survived unexamined
- **also passes through:** `carton_deadletter.py`, `test_carton_deadletter.py`

### Dead_Letter_Lane_Fires — AB boundary (no Giint_Feature node declared)

- **user action:** nobody does anything -- a background daemon owns the queue directory and ticks once a second, and the moment any add_concept anywhere drops a payload there the drain picks it up and settles its fate without being asked. The agent involvement ended at the write
- **doc(v):** `docs/vision/_queue_drain.md`
- **outputs to:** `['ab_chain:absorber_loop']`
- **sealed:** v7, key `6f71382ca301a3bf`, commit `5f9cff25f`, valid from 2026-10-04T06:46:07
- **ranges in this module** (layer order):
  - `L0 install` · `observation_worker_daemon.py:1932-1942` — THE REGISTRATION: the pid-file lock is what INSTALLS this drain as the one that owns the queue. acquire_pid_lock is flock-based and lives in carton_worker_control because the ORDER of open versus flock is the thing that has to be proven and cannot be proven here -- this function starts chroma servers and never returns, so no test can call it. A starter that loses the race exits 0 GRACEFULLY rather than competing, and pid_fd stays bound for the whole lifetime on purpose because closing the handle RELEASES the lock and a released lock is how two workers end up draining one queue. Without this hop the lane has no answer to what makes exactly one settler exist
  - `L1 trigger` · `observation_worker_daemon.py:2087-2100` — THE TRIGGER, and the input contract it hands the lane. The while True tick runs once a second forever; if queue_files is the branch that decides the drain fires at all, so an empty queue means nothing downstream runs and _ensure_neo4j_alive is not even called. When it DOES fire it hands the lane exactly two things, and both are what the disposition turns on: the batch of files from the glob, and the CONNECTION STATE returned by _ensure_neo4j_alive -- which may be None, because that helper returns a working connection OR NONE and its None branch is the whole of issue 280. Note the cadence consequence: today a total outage dead-letters the batch and the queue empties, so this branch stops firing and the reconnect attempts stop with it
  - `L2 release` · `observation_worker_daemon.py:2692-2697` — THE RELEASE, where the disposition stops being a decision and becomes binding on the filesystem. Every entry accumulated in failed_files is walked and dead_letter is called on it with ITS OWN reason and attempt count, so the annotation and the move happen together and a payload can never arrive in failed slash carrying nothing -- which is precisely what the bare rename this replaced used to do. failed_count is incremented only on a move that actually returned True. After this loop the batch is settled and the tick sleeps  ⟵ RELEASE

### Doc_Mirror_Ratchet_Fires — AB boundary (no Giint_Feature node declared)

- **user action:** nobody runs anything - a card LEAVES the build lane for any reason, through any verb, and the next sequenced sprint must arrive in build without anyone asking for it. The agent involvement ended when it moved the card
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['ab_chain:absorber_loop']`
- **sealed:** v8, key `d6418c74ad9b4c01`, commit `f0fa71694`, valid from 2026-10-02T08:02:23
- **ranges in this module** (layer order):
  - `L0 install` · `observation_worker_daemon.py:2367-2393` — THE GRADE EXEMPTION, which is what makes this handler dispatchable AT ALL. The dispatcher gates on is_system_type because that gate exists for PROJECTORS, where an incomplete concept must not project. A lane-change INSTANCE grades soup or code and never is_system_type, exactly like the carton_task kanban card above it, so gating it on the grade would drop it forever - the same measured GIINT cascade failure. Its d-chain premise IS its gate, so it is named here
  - `L1 trigger` · `observation_worker_daemon.py:2394-2416` — THE TRIGGER, and the branch that decides this fires at all: for every concept in the drained batch, for every release_effect SOMA surfaced on it, skip unless the concept graded is_system_type OR the handler is named in the exempt set above. A seen-set keyed on handler and arg makes it idempotent within a batch. The handler string is then split on the colon and imported - which is why a BARE handler name cannot work here and is exactly why the opera needed its own regex relay
  - `L2 release` · `observation_worker_daemon.py:2417-2425` — THE RELEASE, where the effect stops being a surfaced fact and becomes binding on the board: the handler is CALLED with the shared connection, its returned line is printed, and log_system_event records release_effect_dispatched into the graph so the dispatch is a durable record rather than only a log line. A dispatch failure is caught and printed, never raised, so one bad handler can never stop the drain. Measured live 2026-09-17: release_effect carton_mcp.doc_mirror_kanban_effects colon ratchet_on_build_freed returning sprint Doc_Mirror_Task_Leg_A_Pr_002 arrow build, 3 moved, 0 skipped  ⟵ RELEASE
- **also passes through:** `base/soma-prolog/gnosys-vault/gnosys_vault/doc_mirror_task.py`, `doc_mirror_kanban_effects.py`, `test_doc_mirror_kanban_effects.py`

### Docm_Projection — feature boundary of `Giint_Feature_Write_Gate_Docm_Projection`

- **user action:** the agent runs doc-mirror-commit MODULE and the doc(m) of that module is projected from its sealed HALO SEEM boundaries by seem docm instead of being written by any hand
- **doc(v):** `doc-mirror-system/docs/vision/_docm-from-seem.md`
- **outputs to:** `['docm_projection_fires']`
- **sealed:** v43, key `6ff5b2cab81d53aa`, commit `3e45f0560`, valid from 2026-10-04T17:08:30
- **ranges in this module** (layer order):
  - `L2 write_gate` · `observation_worker_daemon.py:1810-1825` — the auto-linker selection in linker_thread through carton_utils.linker_eligible: a node of a verbatim type is never selected, so the linker never rewrites a doc(m) content node (card 813); live once the observation worker restarts
- **also passes through:** `base/sanctuary-system/sanctuary_system/seem_project.py`, `doc-mirror-system/plugin/lib/docmirror_docm_concept.py`, `add_concept_tool.py`, `base/sanctuary-system/sanctuary_system/seem_cli.py`, `doc-mirror-system/plugin/hooks/docmirror_read_ledger.py`, `doc-mirror-system/plugin/bin/docmirror-docm`, `doc-mirror-system/plugin/bin/doc-mirror-commit`, `doc-mirror-system/plugin/lib/docmirror_docm_project.py`, `doc_mirror_projector.py`, `carton_utils.py`, `doc-mirror-system/plugin/hooks/docmirror_read_gate.py`, `base/sanctuary-system/tests/test_seem_cli.py`, `doc-mirror-system/tests/test_docmirror_commit_graduation.py`, `doc-mirror-system/tests/test_docmirror_drift_sweep.py`, `doc-mirror-system/tests/test_docmirror_read_ledger_graph.py`, `doc-mirror-system/tests/test_docmirror_docm_concept.py`, `doc-mirror-system/tests/test_docmirror_commit_retire.py`, `doc-mirror-system/tests/docm_fake.py`, `doc-mirror-system/tests/test_docmirror_docm_project.py`

### Lfpoop_Join_A_Fires — AB boundary (no Giint_Feature node declared)

- **user action:** nobody runs anything - the agent edits a Python module, the codenose PostToolUse hook queues it for the CA refresh, and once the refresh flushes, CA writes the module call graph as the first partial and each partial d-chain releases the carton handler that writes the next, through the rollup wiring and the learned ring set, until the derived AB3 states, which sealed boundaries run together, are recorded on the ring set. The agent involvement ended at the edit
- **AB tier:** `ab1` — SPECIALIZATION, not composition: this boundary IS the tier below it used more specifically, so it carries the whole chain up to `ab1`. The tier never says what receives control; `outputs to` says that.
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['ab_chain:absorber_loop']`
- **sealed:** v1, key `6151338b9136d38b`, commit `e0e55f087`, valid from 2026-10-02T03:58:45
- **ranges in this module** (layer order):
  - `L5 dispatch` · `observation_worker_daemon.py:2367-2425` — the dispatch: the observation worker imports each release_effect handler of a drained concept and calls it with the concept node name and its shared connection when the concept is a system type or the handler is in _GRADE_EXEMPT_EFFECTS, where the three join A handlers sit because a partial instance grades code and never is_system_type
- **also passes through:** `automation/codenose/hooks/codenose_posttool.py`, `knowledge/context-alignment/neo4j_codebase_mcp/pattern_detector.py`, `knowledge/context-alignment/neo4j_codebase_mcp/module_call_graph.py`, `lfpoop_join_effects.py`, `base/sanctuary-system/sanctuary_system/seem_ab3.py`, `add_concept_tool.py`, `base/soma-prolog/gnosys-vault/gnosys_vault/lfpoop_join.py`, `knowledge/context-alignment/tests/test_module_call_graph.py`, `base/sanctuary-system/tests/test_lfpoop_join_ab3.py`, `test_lfpoop_join_effects.py`

### Timeline_Merge — feature boundary (no Giint_Feature node declared)

- **user action:** the session compacts, and the conversation that just ended must become a retrievable record with the journal entries written inside it attached to it rather than to the placeholder node session_start minted before the real name existed
- **doc(v):** `docs/vision/_timeline_merge.md`
- **outputs to:** `['read_layer']`
- **sealed:** v6, key `556ea49c2346ab8e`, commit `e5b1ae6be`, valid from 2026-09-17T07:34:26
- **ranges in this module** (layer order):
  - `L2 worker_drain` · `observation_worker_daemon.py:891-1007` — the CONSUMER, _process_timeline_merge: transfer every relationship type in BOTH directions from the placeholder onto the real conversation, reading the types from the database and sanitising them because a relationship type cannot be parameterised in Cypher, then REFUSE the delete outright when the merge target does not exist so the placeholder edges are never destroyed with nowhere to have moved them. Returns True and the caller consumes the file, False and the caller dead-letters it
  - `L2 worker_drain` · `observation_worker_daemon.py:2145-2173` — THE DISPATCH SITE, and the defect this boundary was extended to name: a queue file whose parse returns no concepts is peeked, and a timeline_merge payload is executed HERE, inside the parse phase. Every ordinary concept in the same batch is only ACCUMULATED here and is not written until the batch write below, so a merge whose target conversation is created by that same batch can never find it and dead-letters on a race that its own error text calls retryable. Measured three times, 2026-09-14, 2026-09-15 and 2026-09-16, each stranding a whole window of journal entries on the placeholder while the message ladder landed on the real node
  - `L2 worker_drain` · `observation_worker_daemon.py:2180-2226` — THE BATCH WRITE that creates the merge target: batch_create_concepts_neo4j under run_with_retry, which is where the Conversation node queued by precompact actually lands in the graph. This range is traced into this boundary because it is the ORDERING CONSTRAINT the merge depends on and nothing previously recorded that dependency: the merge must run after this, never beside it
  - `L2 worker_drain` · `observation_worker_daemon.py:2604-2628` — PHASE 2m, THE ORDERING FIX, added 2026-09-16: every timeline_merge collected during the parse phase is dispatched HERE, after the batch write that creates its target conversation, and never beside it. Deliberately NOT gated on neo4j_succeeded, because a batch holding only merge files parses no concepts at all, so that flag is false while the targets landed in an earlier batch and the merges are perfectly runnable. Success unlinks the queue file, failure dead-letters it with the unchanged reason string, which should now be reached only by a target whose own concept dead-lettered or by a retry of a merge older than its conversation
- **also passes through:** `hooks/carton_precompact.py`

### Worker_Restart — feature boundary of `Giint_Feature_Carton_Mcp_Worker_Restart`

- **user action:** the agent calls the carton carton_management MCP tool with restart_bg_server, because a pip install changes no running observation worker, and one call must end with a live worker running the installed code, or a named survivor, and say which
- **doc(v):** `docs/vision/_carton_worker_control.md`
- **outputs to:** `['dead_letter_lane_fires']`
- **sealed:** v3, key `e610c45b7e4265a1`, commit `65b574104`, valid from 2026-10-04T07:21:03
- **ranges in this module** (layer order):
  - `L3 spawned_worker` · `observation_worker_daemon.py:1932-1942` — the spawned worker takes WORKER_PID_FILE, imported from carton_worker_control, through acquire_pid_lock; a starter that finds it held prints Another worker already running and exits 0
- **also passes through:** `server_fastmcp.py`, `carton_worker_control.py`, `test_carton_worker_control.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
