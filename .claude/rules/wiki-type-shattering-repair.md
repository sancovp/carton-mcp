Isaac verbatim: *"there should be **ZERO DUPLICATES** because all these things **ARE THEMSELVES**"*, and
on severity: *"probably the most cirtical carton bug we have ever found because it means the entire graph
is decohered and the entire manifold system we devised with the regions with upper categories and a whole
hierarchy is impossible to make."*

`:Wiki` now carries the `wiki_name_unique` UNIQUENESS constraint on `:Wiki(n)`. An index makes lookups
fast and ENFORCES NOTHING — `CREATE INDEX wiki_name` is what let the graph shatter — so never substitute
an index for the constraint, and if you must drop it, restore it.

The repair order, if this ever recurs, is load-bearing: **1. STOP EVERY WRITER → 2. DEDUPE → 3. apply
`REQUIRE c.n IS UNIQUE`.** Deduping before the writers are stopped just lets it refill, and the
constraint cannot be applied early because neo4j REFUSES to create it while duplicates exist — that
refusal is the forcing function. A writer fix is not safe merely because it is correct: see the
amplification law below.

## States

| component | status | note |
|---|---|---|
| writer 1 — `log_system_event` | **FIXED + DEPLOYED + LIVE-VERIFIED** | `CREATE (e)-[:IS_A]->(:Wiki {n:"System_Event"})` minted a type node per call → **41,751 copies** (c9219be7f). Instance name also went second→microsecond resolution |
| writer 1 — shatter-safety | **FIXED + DEPLOYED** | every MERGE collapsed with `WITH … LIMIT 1` (46703143b). Required because the c9219be7f fix AMPLIFIED on the still-shattered graph |
| writer 2 — `Anonymous_Inline_Type_Merge_Defect` | **FIXED + PINNED** | 7 sites, `sm_gate.py` ×6 + `carton_utils.py` ×1 (d05c8a56d); pinned by `test_no_anonymous_inline_type_merge.py` (**5/5**), verified as a controlled pair that FAILS against pre-fix source. 7 EDIT SITES in the source, which the controlled-pair run reports as 8–9 OCCURRENCES because several share one statement and the detector counts per matching line. Sites and occurrences are different units; the diff of `d05c8a56d` is the arbiter |
| writer 3 — the E2E **TEST FIXTURES** | **FIXED + PINNED 2026-08-22** | **FIVE** fixtures carried shape B at **17 occurrences** — `tests/test_sm_gate_e2e.py`, `test_generate_system_prompt_e2e.py`, `test_sm_core_e2e.py`, `test_convert_skills_to_sms_e2e.py`, `test_sm_branching_live_e2e.py`. Each defaults `NEO4J_URI` to `bolt://host.docker.internal:7687` — **the identical default the live daemon uses** (`observation_worker_daemon.py:1302`) — so run bare they wrote to PRODUCTION. Every `_cleanup` deletes by a `Zztest_*` prefix, and a minted type node has no prefix, so the leak was **invisible to their own teardown** |
| writer 4 — `automation/odyssey-system/test_odyssey.py` | **FIXED 2026-08-22** (`7748f021e`) | 9 occurrences of shape A. Same production-default URI, same prefix-only teardown. The five `GIINT_*` names carry ONLY the `c`-bearing group with no un-`c`'d original at all, at exactly 3 copies each, consistent with three fixture runs and no legitimate original. Suggestive, not proof that only this fixture could have produced them. The ALL-CAPS `GIINT_` naming is deliberately left alone — renaming is graph surgery of the class-two kind |
| **TOTAL: FOUR writers** | — | 1 = `log_system_event` · 2 = the sm_gate/carton_utils inline MERGE · 3 = five carton-mcp E2E fixtures · 4 = the odyssey fixture. **Six FILES carry the production-default URI**, across **26 occurrences** (17 shape B + 9 shape A) |
| detector coverage | **WIDENED 2026-08-22** | `SKIP_DIRS` no longer excludes `tests` — that exclusion, justified as "fixtures are not the writers," is what hid writer 3. `scan()` now also RETURNS unscannable files instead of swallowing them, gated by `test_every_source_file_was_actually_scanned`, so "could not parse" can never read as "clean" |
| step 1 completion | **COMPLETE.** The basis is the **ast-scoped detector**, not a raw grep — `python3 test_no_anonymous_inline_type_merge.py` (5/5). ⚠ **A RAW MONOREPO GREP DOES NOT RETURN ZERO — it returns 40**: 36 inside the stale worktree and 4 PROSE (a `#` comment at `observation_worker_daemon.py:1474`, docstrings at `retype_buckets.py:33`, `test_log_system_event_no_duplicate_types.py:10`, `test_odyssey.py:92`). **ZERO executable live-source hits** |
| ⚠ the stale worktree | **NOT REMOVED — Isaac's call (it is a branch)** | `.claude/worktrees/agent-a276d399d25d40021/` (2026-06-27) holds **complete pre-fix copies of ALL FOUR writers**, measured at **36 occurrences**: `sm_gate.py` ×7, `carton_utils.py` ×1, `observation_worker_daemon.py` CREATE ×1, all five E2E fixtures, and `test_odyssey.py` ×9. Those fixtures default to the PRODUCTION URI, so **entering that worktree and running its tests would re-shatter the live graph** |
| step 2 — `dedupe_wiki_duplicates.py` | ✅ **DONE 2026-08-25 — 110/110 names, ZERO duplicated names remain** | `System_Event` 41,751 → 1, then the other 109. Nodes 682,459 → 639,252 (43,207 removed). **43,508 instances now converge on the ONE `System_Event`**, one `IS_A` edge each. ⚠ THE TOOL WAS BROKEN AND THAT IS WHY THIS SAT: its edge-merge loops were UNBATCHED, so the one name that mattered put ~300k MERGE+DELETE in a single transaction, killed the connection and took neo4j down. Also fixed: the "full export" exported only PLANS (1,236 bytes for a 41,750-node delete); it now dumps every doomed node's full properties, and the failure path prints the traceback rather than `str(e)` alone |
| step 3 — the constraint | ✅ **DONE 2026-08-25 — `wiki_name_unique` UNIQUENESS on `:Wiki(n)`, PROVEN ENFORCING** | It was blocked by the plain `wiki_name` RANGE index (an index enforces nothing), so that was dropped first; the constraint brings its own backing index, so no lookup cost. **Proof is a live refusal, not the success line:** `CREATE (n:Wiki {n:'System_Event'})` now returns `Neo.ClientError.Schema.ConstraintValidationFailed` and the count holds at 1. The daemon still boots: its three `CREATE INDEX ... IF NOT EXISTS` calls all succeed (they no-op against the constraint's index) and enforcement survives them |

THE TWO DEFECT SHAPES, both the same disease — an unbound type node.

SHAPE A is an inline target in a relationship `CREATE`. It mints a type node per call.

SHAPE B is an inline target in a relationship `MERGE`, and a `CREATE`-grep misses it:

```
MERGE (es:Wiki {n: $step_id}) MERGE (es)-[:IS_A]->(:Wiki {n: 'Traversal_Step'})
                                                 ^^^ ANONYMOUS + UNBOUND
```

The second MERGE matches the WHOLE PATH. For a new `es` that path never existed, so Cypher creates the
entire pattern INCLUDING a brand-new type node.

THE FIX, both shapes, always the same line: bind the type node by name FIRST, then point the edge at the
bound variable — `MERGE (t:Wiki {n:'X'})` then `MERGE (a)-[:IS_A]->(t)`.

⛔ MERGE AMPLIFICATION ON A SHATTERED GRAPH. A MERGE on a name with N duplicates MATCHES ALL N and
returns N ROWS, so every downstream clause runs ONCE PER ROW, and a `CREATE` after such a MERGE becomes N
creates. No existing check can see it: the unit test is a pure fake-connection test asserting the QUERY
TEXT merges the type, and it passes correctly, because the text IS right. The defect lives in the
interaction between correct text and a shattered store, invisible without a real graph that already
holds duplicates. Keep that test category in mind — not "is the query correct" but "is the query correct
against the damaged state we are still living in".

THE CURE: collapse every MERGE with `WITH … LIMIT 1` before any CREATE, so it yields exactly one row
whether the name has 1 node or many — correct BEFORE and AFTER a dedupe.

CLASSIFY BEFORE YOU DELETE, and never run a dedupe bare with `--apply`. The shape still matters:
- CLASS ONE, type duplicates: a universal shattered into N byte-identical copies. Keep-one plus
  MERGE-repoint is provably lossless.
- CLASS TWO, instance name collisions: GENUINELY DISTINCT records that shared a name. Keeping one DELETES
  the rest. The repair is DISAMBIGUATION by renaming, not merging.

The tool FLAGS class two by noticing the copies disagree on description; it does NOT refuse it. Treat
that flag as a prompt to LOOK, never as a verdict — on a TYPE node the heuristic is simply wrong, because
differing descriptions on a universal are POLLUTION, not distinct records.

A dedupe must MERGE edges, not merely repoint them. MERGE matched every copy, so every edge ever written
to a shattered name was written to EVERY copy, and repointing N parallel edges onto the survivor
preserves the inflation while removing the evidence of its cause. `(source, type, target)` must collapse
to one.

Export before mutating, with every doomed node's FULL PROPERTIES — not a plan. Batch the edge-merge
loops; an unbatched loop puts the whole job in one transaction, kills the connection and takes neo4j
down. Print the traceback on failure, never `str(e)` alone.

⚠ THE STALE WORKTREE `.claude/worktrees/agent-a276d399d25d40021/` holds complete PRE-FIX copies of all
four writers, and its fixtures default to the PRODUCTION URI. Entering that worktree and running its
tests would RE-SHATTER the live graph. Removing it is Isaac's call; it is a branch.

A TEST FILE IS NOT EXEMPT. The E2E fixtures default `NEO4J_URI` to `bolt://host.docker.internal:7687` —
the identical default the live daemon uses — so run bare they write to PRODUCTION, and every `_cleanup`
deletes by a `Zztest_*` prefix while a minted type node has no prefix, so the leak is invisible to their
own teardown. `tests/` is scanned for exactly that reason; never re-exclude it from the detector, and
never trust a docstring's claim that a fixture is self-cleaning.

A scanner must RETURN unscannable files rather than swallowing them, so "could not parse" can never read
as "clean".

Dev-flow, and NEVER edit one place only. Touching `dedupe_wiki_duplicates.py`, `log_system_event`, or any
writer that names a type node:
1. BIND the type node — never inline or anonymous in a relationship clause — and COLLAPSE every MERGE
   with `WITH … LIMIT 1` before any CREATE while duplicates still exist.
2. GATE: `python3 test_no_anonymous_inline_type_merge.py` 5/5 AND
   `python3 test_log_system_event_no_duplicate_types.py` 5/5, run as SCRIPTS, because the repo root IS
   the `carton_mcp` package. GREEN IS NOT THE GATE — THE CONTROLLED PAIR IS. Prove the detector still
   FAILS against the pre-fix source before trusting a pass: copy the current detector into a temp dir
   beside `git show HEAD:<the files>` and run it there. A detector that cannot fail proves nothing. Both
   gates are static and pure and NEITHER can see the amplification bug, so for anything touching a
   MERGE-on-a-duplicated-name also run a controlled pair on a THROWAWAY neo4j with a deliberately
   shattered type node — never on the live graph.
3. INSTALLED-PACKAGE LAW: a source edit reaches nothing running without `pip install --no-deps .`. Verify
   the running process START TIME against the installed file's mtime — the daemon RESPAWNS ON ITS OWN, so
   killing it is not a durable stop and a changed PID does not prove new code. The only durable way to
   stop a bad writer is to install the fix.
4. Commit and push. The monorepo is the durable record.

The BASIS for "no live writer remains" is the ast-scoped detector, never a raw grep: grep cannot tell
prose from code, so it returns hits on comments and docstrings that DOCUMENT the bad shape. If you run
the sweep anyway, exclude `/build/`, `__pycache__`, `/.git/`, the detector itself, and `\.claude/worktrees/`
— written with NO leading slash, because `grep -r .` emits paths like `.claude/worktrees/…` and a
leading-slash pattern silently excludes nothing:

```bash
grep -rEn --include='*.py' \
  '(MERGE|CREATE)[[:space:]]*\([A-Za-z_][A-Za-z0-9_]*\)[[:space:]]*-[[:space:]]*\[[^]]*\][[:space:]]*->[[:space:]]*\([[:space:]]*:Wiki[[:space:]]*\{' . \
  | grep -v '/build/' | grep -v '__pycache__' | grep -v '/\.git/' \
  | grep -v 'test_no_anonymous_inline_type_merge.py' | grep -v '\.claude/worktrees/'
```

Prove a constraint by a live REFUSAL, never by a success line: `CREATE (n:Wiki {n:'System_Event'})` must
return `Neo.ClientError.Schema.ConstraintValidationFailed` with the count unchanged.

### THE SPLIT, MEASURED 2026-08-22 (read-only dry-run) — re-measure, never quote

| class | names | nodes | removable | edges collapsed |
|---|---|---|---|---|
| **ONE — safe keep-one** | 64 | 1,298 | **1,234** | **48,698** (18.9%) |
| **TWO — keep-one DESTROYS records** | 46 | 42,021 | 41,975 | 208,882 (81.1%) |
| combined (what the tool's TOTALS line prints) | 110 | 43,319 | 43,209 | 257,580 |

**THE 64 CLASS-ONE NAMES** (safe to keep-one; `--name` takes ONE name per run, so this is a loop — and
the tool takes no class filter, which is exactly why the list must exist):

`Skillgraph_Entry` `State_Machine` `Sm_Chain` `Execution_State` `Agent_Identity` `Skill`
`Measurement_Analysis` `Learning_Decision` `Bml_Learning` `Inclusion_Map` `GIINT_Project`
`GIINT_Feature` `GIINT_Component` `GIINT_Deliverable` `GIINT_Task`
`Unified_Task_Intelligence_Architecture_v1` `Pull_Based_Task_Integration_Model_v1` `Test_Concept`
`HEAVEN_System` `Test_Full_Stack` `Test_Git_Auth_Fix` `Conversation_2026_06_04T00_52_27` `Output`
`Starsystem_Metta_Motto` `Starsystem_Mcpsquared` `Starsystem_Llm_Intelligence_Package`
`Starsystem_Heaven_Bml_Sqlite` `Starsystem_Sanctum_Builder` `Starsystem_Opera_Mcp`
`Starsystem_Paia_Builder` `Starsystem_Starsystem_Mcp` `Starsystem_Sophia_Mcp`
`Starsystem_Youknow_Kernel_Current` `Design_Yo_Mesh_Unification_Apr29` `Debug_Diary_20260429_175030`
`Debug_Diary_20260429_193505` `System_Event_2026_04_29T19_40_41_linker_batch`
`Unnamed_Conversation_At_2026_04_29T20_29_46` `Skillgraph_Skill_Omnisanc_Waypoint_State_Cleanup`
`Skillgraph_Skill_Omnisanc_End_Starlog_Gate` `Skillgraph_Skill_Cave_Script_Hook_Contract`
`Skillgraph_Skill_Stop_Hook_Zone_Sync` `Skillgraph_Skill_Session_Handshake_File` `Langgraph` `Mcp`
`Development_Roadmap` `Sdk` `Discovery` `Skillgraph_Reconnect_Mcp` `Feature`
`Claude_Code_Curriculum_v1` `Business` `Engineering` `Personal` `Insight` `Development` `Antigravity`
`Architecture` `Sanctuary_Revolution` `Integration` `Feature_Request` `Autonomous_Kg_Building`
`Sanctum` `Architecture_Overview`

**THE INVOCATION** (dry-run first, always; `--apply` is opt-in and exports before mutating):
```bash
cd knowledge/carton-mcp
python3 dedupe_wiki_duplicates.py --name '<ONE_NAME>'            # read-only preview
python3 dedupe_wiki_duplicates.py --name '<ONE_NAME>' --apply    # export, then MERGE edges + delete copies
```
⚠ **NEVER run it bare with `--apply`** — no `--name` means all 110 names, including the 46 class-two.

Two notes on the list itself: five `GIINT_*` names are in it, so deduping them first *reduces* the work
of the task-10 naming ruling rather than conflicting with it; and `Test_Full_Stack` is the malformed node
(`c` = boolean `True`, timestamp an epoch-millis integer) — deduping is fine, but it needs its own look
afterwards.

Composes with `carton-is-the-total-store-soma-is-its-reflection`, `mereo-is-part-instantiation`,
`state-what-is-vs-vision-never-encode-certainty`, `trace-bug-chain-to-exact-symptom`.
