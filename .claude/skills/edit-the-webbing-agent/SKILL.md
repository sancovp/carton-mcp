---
name: edit-the-webbing-agent
description: "WHAT: the dev-flow for editing the WEBBING AGENT — carton's standing CONCEPT-ATOMIZATION daemon, CLONED from the proven Sophia (docmirror-cohere) architecture: CODE detects a batch of under-structured, autolinker-processed, main-agent-authored concepts (linked=true, source in CHAT_SOURCES, webbed IS NULL), serves them to a fresh SDNAC run each tick, the agent ADDS real is_a/part_of/instantiates/produces structure + child concepts, and CODE verifies + marks webbed=true. Covers webbing_agent.py, webbing_agent_worker.py, and the one-line SYSTEM_SOURCES coupling in observation_worker_daemon.py. WHEN: when editing webbing_agent.py, webbing_agent_worker.py, the eligibility predicate (_is_underdeveloped), the batch-goal builder (_build_batch_goal), the WEBBER_SYSTEM_PROMPT, the webbed/source recursion-guard, or CHAT_SOURCES/SYSTEM_SOURCES in observation_worker_daemon.py (any of)."
---

# edit-the-webbing-agent — dev-flow for carton's standing concept-atomization daemon

The webbing agent's WHOLE JOB: take a concept a real conversation just wrote as unstructured prose
(it has a real `is_a`/`part_of`, but little else) and ADD the proper multi-node graph structure the
prose implies — the graphification a human agent should have done when it first wrote the concept, per
`Daemon_Webbing_Agent_Design` (a CartON concept — read it yourself via `get_concept` before changing
this agent's behavior; this skill restates it, it is NOT the source of truth). It is a **direct clone of
Sophia's proven architecture** (`doc-mirror-system/sophia/docmirror-cohere` +
`sophia_worker.py`), retargeted from Sophia's unit (a `Doc_Mirror_Journal_Entry`, "already annotated" =
a sibling `{journal}_Momentum` node) to this agent's unit (ANY carton concept, "already atomized" = the
`webbed=true` scratch-lane property ON THE SAME NODE — atomization adds structure to the concept
itself, it does not create a side-car observation).

> ⚠️ **PATH CORRECTION (2026-07-04, this skill's own build session):** the original design brief said
> the source files live at `knowledge/carton-mcp/carton_mcp/webbing_agent.py`. That path is WRONG for
> this repo — `pyproject.toml` declares `packages = ["carton_mcp"]` with
> `package-dir = {"carton_mcp" = "."}`, meaning the **repo ROOT** (`knowledge/carton-mcp/`) IS the
> `carton_mcp` package (exactly where `observation_worker_daemon.py`/`carton_utils.py`/`soma_fillers.py`
> already live, as siblings, not nested under a `carton_mcp/` subdirectory). A stray `carton_mcp/`
> subdirectory DOES exist in this repo (only a `.claude/` copy + two orphaned `.pyc` files, no real
> source) — do NOT be misled by it into thinking it is the package. The REAL files are:

- **`knowledge/carton-mcp/webbing_agent.py`** — the SDNAC primitive + CODE detection + verify.
- **`knowledge/carton-mcp/webbing_agent_worker.py`** — the thin PID-locked driver daemon.
- **`knowledge/carton-mcp/test_webbing_agent.py`** — the pure-function unit tests.

## Part 1 — How you edit (read the whole file first — the ONION, pure functions first)

1. **`webbing_agent.py`** — READ IN FULL first (per `read-entire-file-before-any-change`). Structure,
   top to bottom:
   - **PURE, onion-inner, unit-tested layer (no I/O):**
     - `_is_underdeveloped(description, concept_cache, other_rel_count, score_threshold, min_rel_count)`
       — the eligibility predicate. Fires (returns True = "needs atomization") when EITHER
       `compute_description_score(...) < score_threshold` (imported lazily from
       `observation_worker_daemon.py` — reused, never reinvented) OR
       `other_rel_count < min_rel_count` (relationships beyond `BASE_RELS_EXCLUDED`
       `{IS_A, PART_OF, CREATED_DURING, HAS_TAG, TIMELINE_LINKED, ODYSSEY_LINKED}` — deliberately
       EXCLUDES `INSTANTIATES`/`PRODUCES`, which DO count as real structure).
     - `_format_rels(rels)` / `_build_batch_goal(batch, rels_by_concept)` — the goal-text builder that
       SERVES the batch (names + description + existing relationships) so the SDNAC agent never has to
       hunt for what to atomize.
   - **The two-function primitive pattern (mirrors Sophia's "call_sophia() and
     call_sophia_with_this_prompt() — that is it"):**
     - `call_webber_with_this_prompt(prompt, model)` — runs ONE SDNAC to completion on an arbitrary
       goal. Copied near-verbatim from `docmirror-cohere.call_sophia_with_this_prompt` (same
       `HeavenInputs`/`HermesConfig` shape, same `_get_mcp()` carton MCP wiring). `history_id=None` —
       UNLIKE Sophia, there is no cross-run momentum web to rehydrate (each run is a fresh, bounded,
       self-contained batch), so a fresh history every run is correct here, not a gap.
     - `call_webber(model, dry_run, cap, concept_names=None)` — detect → build goal → run → verify →
       mark webbed. `concept_names` is the **TEST/DEBUG direct-invocation escape hatch** (via
       `_batch_for_names`, wired to the CLI `--concept NAME` flag) — mirrors Sophia's
       `--prompt-file`/`--journal` — lets you atomize ONE named concept without waiting for it to
       surface from a real, potentially enormous, oldest-first backlog. NEVER used by the normal
       `--loop`/`--once` production path.
   - **CODE detection (no LLM):** `_next_batch(carton, cap)` — the eligibility Cypher (`linked=true AND
     source IN CHAT_SOURCES AND webbed IS NULL`, plus the housekeeping-relationship count), over-fetches
     `cap * FETCH_MULTIPLIER` candidates (oldest-linked first) because the description-score signal
     needs the full `concept_cache` computed in Python and cannot be pushed into Cypher, then
     Python-filters via `_is_underdeveloped` and truncates to `cap`. `_pending_count(carton)` is an
     honest UPPER BOUND (the coarse Cypher filter only — documented in its own docstring as such, never
     silently treated as exact).
   - **Verify (CODE, not the agent):** `_verify_and_mark_webbed(carton, batch)` — re-checks each served
     concept's CURRENT description/rel-count against the SAME `_is_underdeveloped` predicate; only a
     concept that NOW passes (is no longer under-structured) gets `webbed=true` via
     `set_concept_properties`. A concept the agent failed to improve stays un-webbed (eligible again
     next tick) — no silent partial credit.
   - **`loop(model, limit, dry_run, cap)`** — ratchets batch-by-batch until caught up (or `limit`
     batches), with the SAME no-progress spin-guard as Sophia's `loop()` (2 no-progress batches in a row
     → abort with an explicit error, never spins forever).
   - **`main(argv)`** — `--loop`/`--once`/`--concept NAME`/`--dry-run`/`--cap`/`--model`/`--limit`, with
     the SAME fd-1 stdout guard as `docmirror-cohere.main()` (carton's query layer leaks fd 1 → stderr
     after the first query; the caller — `webbing_agent_worker.py` — reads our stdout for the result
     JSON, so the real fd is `os.dup(1)`'d BEFORE any carton work).
2. **`webbing_agent_worker.py`** — READ IN FULL first. The THIN stream driver, copied near-verbatim
   from `sophia_worker.py`: PID-file lifecycle (`_alive`/`_running_pid`/`daemon`/`ensure_running`/
   `wait_caught_up`), the `--daemon`/`--catch-up`/`--ensure`/`--ensure-and-wait`/`--status` flags, the
   FAIL-LOUD empty/unparseable-stdout handling in `_pending_concepts` (empty stdout is a FAILURE
   returning `-1`, NEVER silently "0 pending"), and the `_live()` DRY-by-default gate (`live.flag` file
   OR `WEBBING_AGENT_LIVE=1` env var — **ships DRY; Isaac flips it live explicitly, never the build**).
   ONE structural difference from `sophia_worker.py`: `webbing_agent.py` lives INSIDE the `carton_mcp`
   package (not a `plugin/bin/` installed console script like `docmirror-cohere`), so the worker invokes
   it via `python3 -m carton_mcp.webbing_agent` (module invocation), never a bare command name.
3. **`observation_worker_daemon.py`** — the ONE line this build touches: `SYSTEM_SOURCES` (~line 1270)
   now includes `"webbing_agent"`. This is the WHOLE recursion-guard mechanism — see Part 2 item 2.
   Nothing else in that file changes for this capability; the webbing agent runs OUT OF PROCESS via its
   own worker, exactly like Sophia does not live inside the summarizer's daemon either.

## Part 2 — What you must ALSO edit (the coherence edit-set — never edit one layer only)

1. **The eligibility predicate + its unit tests move together.** Change `_is_underdeveloped`'s
   thresholds, signals, or the excluded-relationship set (`BASE_RELS_EXCLUDED`) → update
   `test_webbing_agent.py`'s assertions in lockstep (it hard-asserts the strict `<` boundary, the OR
   semantics between the two signals, and that `INSTANTIATES`/`PRODUCES` are NEVER excluded). The
   thresholds (`DEFAULT_SCORE_THRESHOLD=50`, `DEFAULT_MIN_REL_COUNT=2`) are **JUDGMENT CALLS**, not a
   derived spec — env-overridable (`WEBBING_AGENT_SCORE_THRESHOLD`/`WEBBING_AGENT_MIN_REL_COUNT`); flag
   any change to Isaac explicitly rather than silently re-tuning.

2. **THE RECURSION GUARD (the one safety property Isaac was explicit about — never weaken this).**
   `_next_batch` ONLY ever queries `c.source IN CHAT_SOURCES` (imported from
   `observation_worker_daemon.py`, never redefined locally — a second copy WILL drift). `WEBBER_SYSTEM_PROMPT`
   + `_build_batch_goal` instruct the agent to pass `source='webbing_agent'` on EVERY `add_concept` call
   it makes. `'webbing_agent'` lives in `SYSTEM_SOURCES`, NEVER in `CHAT_SOURCES` — so any concept this
   agent touches or creates is STRUCTURALLY excluded from ever being re-served to it, with zero extra
   bookkeeping. **If you ever add `'webbing_agent'` to `CHAT_SOURCES` (even by accident, e.g. a future
   merge of the two sets), this agent will start recursively re-processing its own output — this is the
   ONE thing this dev-flow exists to protect.** If a real agent later re-engages a webbing-agent-authored
   concept and re-queues it with `source='agent'`, it becomes eligible again automatically — this is NOT
   special-cased anywhere; it falls straight out of the eligibility query being source-based (Isaac's
   design: "unless they become involved in the main agent's context and re-enter through the queue").

3. **THE NEVER-TOUCH-DESCRIPTION MECHANISM (load-bearing, same as `dev-flow-split-content`'s item 4 —
   verify on any daemon change).** `WEBBER_SYSTEM_PROMPT` instructs the agent to OMIT the `concept`
   (description) argument when amending an EXISTING served concept. This relies on the SAME mechanism
   `dev-flow-split-content` documents: an absent/omitted description normalizes to `""`
   (`add_concept_tool_func`), and `observation_worker_daemon.batch_create_concepts_neo4j`'s UNWIND
   write-CASE branch `WHEN n.d CONTAINS c.description THEN n.d` leaves an existing non-empty `n.d`
   COMPLETELY UNCHANGED (an empty string is contained in every string). If that CASE's branch ORDER is
   ever refactored, re-verify this still holds BEFORE the `update_mode == 'append'` branch — proven live
   2026-07-04 (see Part 3's E2E run: a byte-for-byte sha256 compare of the test concept's description,
   before vs. after a real atomization run, matched exactly).

4. **DEPLOY (the running daemon is the INSTALLED package, NOT the source).** After editing:
   `pip install --no-deps /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp` (per
   `pip-install-our-packages-no-deps`; NEVER `--force-reinstall`). The webbing-agent worker is a
   SEPARATE process from `observation_worker_daemon` — if you only changed `webbing_agent.py`/
   `webbing_agent_worker.py`, no daemon restart is needed (the worker's `--catch-up`/`--daemon` always
   subprocess-invokes the freshly-pip-installed module by path, so a fresh subprocess call always picks
   up the new code — UNLESS a `--daemon` process is already running its own long-lived Python
   interpreter, in which case restart it: find the PID via `webbing_agent_worker.py --status` or the
   PID file at `$HEAVEN_DATA_DIR/webbing_agent/worker.pid`, kill it, `ensure_running` again). If you
   changed the ONE `SYSTEM_SOURCES` line in `observation_worker_daemon.py`, that daemon (a genuinely
   long-running process) DOES need a restart — follow `skill-carton-daemon-restart`.

## Part 3 — How you test it (the E2E gate — "the unit tests passed" is NOT sufficient alone)

**Unit gate (necessary, NOT sufficient):** `pip install --no-deps <repo>` then
`python3 test_webbing_agent.py` — 10 pure assertions on `_is_underdeveloped`/`_format_rels`/
`_build_batch_goal` (the strict `<` threshold boundary, the OR semantics, the never-touch-description +
additive-only + source-tag laws literally present in the built goal text, and that
`BASE_RELS_EXCLUDED` never excludes `INSTANTIATES`/`PRODUCES`).

**The REAL E2E gate — through the actual live surface (proven 2026-07-04, this build's own verification
run):**
1. `add_concept` (the real MCP tool) a test concept with a real `is_a`/`part_of` but genuinely
   under-structured prose, `source='agent'`.
2. Wait for the autolinker (`linker_thread` in `observation_worker_daemon.py`) to set `linked=true`
   (poll `query_wiki_graph`; takes seconds to tens of seconds depending on queue depth).
3. Run the agent against that ONE concept via the direct-invocation escape hatch (`--concept NAME`) —
   NOT `--loop`/`--once` against the live backlog, which is FIFO oldest-first and can be tens of
   thousands deep (measured live: ~44,000 pending under `CHAT_SOURCES`), so a brand-new test concept
   would never surface in a bounded test run.
4. `query_wiki_graph` and confirm ALL of:
   - Real `is_a`/`part_of`/`instantiates`/`produces`/`has_part` structure now exists, derived from the
     prose (NOT a placeholder — genuinely reflects what the description described).
   - `webbed=true` is set on the served concept.
   - The served concept's `n.d` is BYTE-FOR-BYTE identical to a sha256 snapshot taken BEFORE the run
     (string-compare, never eyeball).
   - Any NEW child concept the agent created carries `source='webbing_agent'`.
   - Re-running `_next_batch` (a fresh call, no `--concept` override) does NOT surface the now-webbed
     concept.
5. **Recursion-guard proof (the one safety property Isaac was explicit about — never skip):** confirm,
   via a direct query, that every `source='webbing_agent'` concept has `source IN CHAT_SOURCES` = FALSE,
   and that none of them appear in a fresh `_next_batch()` call. (Proven live 2026-07-04: both new child
   concepts confirmed `in_chat_sources: False`; neither ever appeared across a 50-concept fresh batch.)

A queued-write confirmation string is NOT the gate (per `verify-via-user-surface-before-done`) — only
the byte-for-byte `n.d` compare + the live recursion-guard query prove the capability actually works.

## Status

**IS — built + live-E2E-verified 2026-07-04** (unit tests 10/10 green; live run against the real neo4j
graph atomized a real test concept, added real `instantiates`/`produces`/`has_part` structure, left the
original description byte-identical, tagged both new children `source='webbing_agent'`, and confirmed
the recursion guard holds). Ships DRY (`webbing_agent_worker.py`'s `_live()` gate defaults off, same as
Sophia's) — **NOT yet flipped `--live` for the standing daemon** (Isaac's call, per Part 2 item 4's
design and this build's own report). The eligibility thresholds
(`DEFAULT_SCORE_THRESHOLD=50`/`DEFAULT_MIN_REL_COUNT=2`) are UNVERIFIED-AS-TUNED judgment calls this
build chose — flag them for Isaac's review before relying on them at scale (see item 1 above).

## Cross-refs (canonical)

`edit-the-sophia-coherer` (the architecture this clones — read it for the general Sophia-shape
dev-flow discipline); `dev-flow-split-content` (the same repo's own precedent for the
empty-description-leaves-`n.d`-unchanged mechanism, item 3 above); `Daemon_Webbing_Agent_Design` +
`Provenance_Tracking_Main_Vs_Daemon_Origin` + `Carton_Schema_Always_List_Requirement` (the CartON design
concepts this build realizes — read them yourself, this skill only restates them);
`the-property-layer-doctrine` (`webbed` is a SCRATCH-lane property, never ontology);
`every-build-ends-in-a-development-flow-skill`; `pip-install-our-packages-no-deps`;
`skill-carton-daemon-restart`.

(Knowledge/dev-flow skill — no subagent dispatch, so no RELIABILITY block.)
