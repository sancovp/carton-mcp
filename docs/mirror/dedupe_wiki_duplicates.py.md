# doc(m): dedupe_wiki_duplicates.py

- **Canonical path:** /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/dedupe_wiki_duplicates.py
- **Line count:** 466 (measured 2026-08-28, post twins-mode)
- **Module role:** A standalone destructive CLI repair tool that operates on the live production Neo4j `:Wiki` graph. For each `n.n` value held by more than one `:Wiki` node it picks one survivor, MERGEs every edge of the other copies onto that survivor, and `DETACH DELETE`s the copies. It is dry-run by default; `--apply` is the opt-in that mutates.

## What this module IS (from the code)

The module is one file, five module-level functions plus `main()`, and no classes. It has no library
role: nothing imports it (see *What CALLS this module*), it exposes no entry point in `pyproject.toml`
(`[project.scripts]` declares only `carton-mcp = "carton_mcp.server_fastmcp:main"`), and it ends in
`raise SystemExit(main())` at `dedupe_wiki_duplicates.py:246-247`. It is run as `python3
dedupe_wiki_duplicates.py [--name X] [--limit N] [--apply]`, or in TWINS mode as
`python3 dedupe_wiki_duplicates.py --twins [--key K] [--limit N] [--apply]`.

## THE TWINS MODE (issue #201, 2026-08-28)

The same-name mode above is blind to the second duplicate class: NORMALIZATION TWINS — distinct
stored names that `normalize_concept_name(n.n)` maps to ONE name (hyphen/underscore twins, case
twins, slash-variant twins). Four functions + a flow driver:

- `find_twin_groups(g, limit)` `:203` — groups every `:Wiki` name on its normalized form
  (normalization-stability equivalence, NOT hyphen-only per the ruling); returns groups keyed by
  the normalized name.
- `inspect_twins(g, key, names)` `:227` — read-only per-group PLAN. SURVIVOR RULE (ruling 4): the
  surviving NAME is always the normalization-STABLE one (the group key); a group with NO
  stable-named node is flagged `needs_rename` and `--apply` SKIPS it (the rename_concept lane —
  never create-then-merge). `content_differs` is a prompt-to-look, never a verdict; content carry
  only onto an empty/stub survivor.
- `apply_twins(g, plan, batch=2000)` `:283` — batched edge MERGE + DETACH DELETE (the batching
  lesson from the 41,751-copy System_Event incident applied from birth).
- `twins_main(g, args)` `:341` — dry-run default; `--apply` exports every doomed node in full
  first (`/tmp/heaven_data/wiki_twins_export_*.json`); `--key` scopes to one group.

Dry-run census (2026-08-28, live): 5,340 twin groups / 10,804 distinct names / 5,464 removable /
361 rename-lane groups (supersedes the stale 4,228 hyphen-pair lower bound — re-measure, never
quote). **THE BATCH APPLY IS A SEPARATELY GATED STEP — deliberately not run.**

Integrator live check (2026-08-28): `--twins --limit 20` dry-run through the real graph — groups
found (e.g. Tmp_Sanctuary_Revolution from 4 slash-variants), content_differs flagged as prompts,
nothing modified. OBSERVED ANOMALY, recorded not fixed (skipped-scope): one group prints with an
EMPTY group key (a name that normalizes to nothing/whitespace) — `--apply` must never process it
(the stable-survivor rule cannot hold for an empty key); flagged on issue #201.

**The shape of the run.** `main()` builds a target list — either the single `--name` supplied
(`:175-176`) or every duplicated name worst-first from `find_duplicates` (`:178`) — then calls
`inspect()` per name to build a read-only PLAN, prints a per-name line and a totals block, and stops
there unless `--apply` was passed (`:205-207`). With `--apply` it writes a JSON export of every
affected node's full properties (`:209-226`) and then calls `apply_one()` per plan inside a
`try/except` (`:228-241`).

**What it deletes, exactly.** `apply_one` (`:111-161`) does three things in order, per name:

1. For every relationship type present in `plan['incoming']`, repeatedly run one batched query
   (`:127-134`): match up to `batch` (default 2000) edges of that type pointing at a NON-survivor copy,
   `MERGE` an edge of the same type from the same source onto the survivor, and `DELETE` the original
   edge. Loop until a pass moves zero.
2. The mirror of (1) for `plan['outgoing']` (`:137-148`), merging `(survivor)-[:REL]->(target)`.
3. Repeatedly `DETACH DELETE` up to `batch` copies whose `elementId` is not the survivor's, re-counting
   the remaining nodes for that name each pass, until at most one remains (`:149-157`).

So the nodes destroyed are **every `:Wiki` node sharing that name except the one survivor**. The edges
destroyed are the ORIGINAL edge instances of the doomed copies — each is deleted only after a MERGE has
placed an equivalent `(source, type, target)` edge on the survivor, which is the whole point: MERGE
collapses N parallel duplicates into one edge rather than repointing N edges (docstring `:22-26`).

**What step 3 does that steps 1-2 do not cover.** `DETACH DELETE` removes whatever relationships are
still attached to a doomed copy, with no merge. Steps 1-2 only iterate the relationship types that
`inspect()` observed at PLAN time. Any edge whose type was not in that plan — for example an edge
created between the `inspect()` read and the `apply_one()` write, since those are separate transactions
minutes or more apart on a live graph — is destroyed outright, not migrated. This is a property of the
code, not a documented one.

**Survivor choice** is made in `inspect()` by the ORDER BY at `:74`: `deg DESC, t ASC, eid ASC` — most
relationships first, then earliest timestamp, then lowest `elementId` — and `nodes[0]` is taken
(`:75`). It is deterministic. It never looks at the description: on a name whose copies disagree on
content, the surviving description is whichever copy happens to have the most edges.

**The content-agreement check** is `descs = {x['d'] for x in nodes}` at `:76`, over a `d` that the query
truncated with `substring(coalesce(n.d,''),0,4000)` at `:72`. `content_identical` therefore means "the
first 4000 characters agree". Copies differing only past character 4000 are reported as identical. The
check gates nothing — it only sets a flag that `main()` prints as `⚠ CONTENT DIFFERS` (`:195`) and
collects into a `conflicts` list printed after the totals (`:199-203`). A run with `--apply` and no
`--name` processes flagged names along with the rest.

**The edge arithmetic** (`:89-105`) predicts the repair's effect: `edges_before` sums `count(r)` per
relationship type across both directions; `edges_after` sums `count(DISTINCT s)` / `count(DISTINCT t)`,
i.e. one edge per distinct neighbour per type after the MERGE; `edges_collapsed` is the difference and
is printed as a first-class number. The prediction assumes every neighbour survives the operation; for a
name whose duplicate copies link to each other, those sources/targets are themselves deleted in step 3
and their edges vanish rather than collapse, so `edges_after` is an upper bound in that case. (Derived
from reading the queries; not measured.)

**The post-condition** is `assert final == 1` at `:160`, run after re-counting. It fires after the
deletions are already committed, so it is a report that something went wrong, not a guard that prevents
it.

**Connection.** `connect()` (`:49-51`) imports `_create_shared_neo4j` from
`carton_mcp.observation_worker_daemon` and returns its result. Verified empirically from the script's own
directory: `import carton_mcp` resolves to the INSTALLED package at
`/home/GOD/.pyenv/versions/3.11.6/lib/python3.11/site-packages/carton_mcp/__init__.py`, not to the
sibling source file — the repo-root `carton_mcp/` directory contains only `.claude/` and `__pycache__/`
and supplies no modules. So the tool runs against the installed daemon helper, and a source edit to
`observation_worker_daemon.py` does not reach this tool without a `pip install`.

`_rows(r)` (`:45-46`) normalises what `execute_query` returns: it takes element 0 if the result is a
tuple, otherwise the result itself, and coerces a falsy result to `[]`. `KnowledgeGraphBuilder.execute_query`
is annotated `-> List[Dict[str, Any]]`
(`base/heaven-framework/heaven_base/tool_utils/neo4j_utils.py:101`) but delegates to
`self._store.execute(...)` (`:112`), so the defensive unwrap covers a backend that returns a tuple.

## Imports

### stdlib
- `argparse` (`:38`) — used in `main()` (`:165-172`).
- `datetime` (`:39`) — the export filename timestamp (`:209`).
- `json` (`:40`) — the export dump (`:224`).
- `os` (`:41`) — **unused**; no `os.` reference exists in the file (grep-confirmed).
- `sys` (`:42`) — `file=sys.stderr` on the failure line (`:240`).
- `traceback` — imported locally inside the `except` block at `:239`.

### third-party
None imported directly. The Neo4j driver is reached indirectly through the daemon helper.

### local
- `carton_mcp.observation_worker_daemon._create_shared_neo4j` — imported inside `connect()` at `:50`
  (function-local, so importing this module does not touch Neo4j).

## Top-level definitions

- **`_rows(r)`** (`:45-46`) — normalise a query result to a list; unwraps a tuple's first element,
  turns falsy into `[]`.

- **`connect()`** (`:49-51`) — return a Neo4j connection by delegating to the worker daemon's
  `_create_shared_neo4j()`. That helper catches its own exceptions and returns `None` on failure
  (`observation_worker_daemon.py:1377-1379`), so `connect()` can hand back `None`.

- **`find_duplicates(g, limit=None)`** (`:54-62`) — `MATCH (n:Wiki) WITH n.n AS nm, count(*) AS c WHERE
  c > 1 RETURN ... ORDER BY c DESC`, optionally with a `LIMIT` appended by f-string with an `int()`
  cast (`:61`). Returns `[(name, copies), ...]`.

- **`inspect(g, name)`** (`:65-108`) — read-only. Three queries: the node list with degree, timestamp
  and truncated description ordered for survivor choice (`:67-74`); incoming edges grouped by type with
  `count(r)` and `count(DISTINCT s)` (`:79-83`); outgoing likewise (`:84-88`). Returns `None` if the
  name has no nodes. Otherwise returns a plan dict: `name`, `copies`, `survivor_eid`,
  `survivor_degree`, `survivor_t`, `content_identical`, `distinct_descriptions`, `edges_before`,
  `edges_after`, `edges_collapsed`, `incoming`, `outgoing`. Note the function name shadows the stdlib
  `inspect` module; that module is not imported here, so nothing breaks.

- **`apply_one(g, plan, batch=2000)`** (`:111-161`) — the mutating half, described above. Returns the
  final node count for the name (always `1` on the non-raising path, because of the assert).
  Relationship types are interpolated into the query text with an f-string (`:129`, `:141`, and the
  `MERGE` lines) because Cypher cannot parameterise a relationship type; the values come from `type(r)`
  read back from the database, and are not quoted or backticked.

- **`main()`** (`:164-243`) — argument parsing (`--apply`, `--limit`, `--name`), plan building and
  reporting, the dry-run early return (`:205-207`), the export (`:209-226`), the apply loop with
  per-name `try/except` and traceback (`:228-241`), and the final `done/len(plans)` line. Always
  returns `0`.

## What this module CALLS

- `carton_mcp.observation_worker_daemon._create_shared_neo4j()` — via `connect()`, `:50`.
- `g.execute_query(query, params)` on the returned `KnowledgeGraphBuilder` — every read and every
  write. Ten distinct query sites: `:57` (`find_duplicates`), `:67`/`:79`/`:84` (`inspect`), `:127`
  and `:139` (the batched edge merges), `:150` and `:154` (the delete loop's count and DETACH DELETE),
  `:158` (the final count), `:219` (the export read).
- `json.dump(...)`, `open(path, 'w')` — `:224-225`.
- `traceback.print_exc()` — `:241`.

## What CALLS this module (grep-confirmed)

**No Python caller exists.** A monorepo-wide grep for `import dedupe_wiki_duplicates` /
`from dedupe_wiki_duplicates` returns nothing. It is invoked only as a command line, and the invocation
is documented in the repo rule:

- `knowledge/carton-mcp/.claude/rules/wiki-type-shattering-repair.md:221-222` — the sanctioned
  invocation (`python3 dedupe_wiki_duplicates.py --name '<ONE_NAME>'`, then the same with `--apply`).
- `knowledge/carton-mcp/.claude/rules/wiki-type-shattering-repair.md:35` and `:149` — the rule's status
  row for the tool and its dev-flow trigger.
- `knowledge/carton-mcp/docs/mirror/observation_worker_daemon.py.md:274` — lists this module at
  `:50-51` as a consumer of `_create_shared_neo4j`.
- Journal and vision references (`knowledge/carton-mcp/context/journal/2026-08.md:93`,
  `docs/vision/_dedupe_tool.md`, `_type_shattering.md`, `_data_loss_risk.md`, root
  `context/journal/2026-08.md:849`) — prose, not callers.

## Notes / discrepancies

**Test coverage is ZERO.** There is no `test_dedupe*.py` anywhere in the repo. The three files that
match a `dedupe` grep are unrelated: `test_concept_provenance_optional_fields.py:72` tests list
de-duplication of `produces` targets, and `test_log_system_event_no_duplicate_types.py:37,84` plus
`tests/test_sm_gate_e2e.py:81` mention the dedupe only in prose. Nothing exercises `inspect`,
`apply_one`, the survivor rule, the batching loop, the export, or the post-condition. Every safety
property of this tool is asserted by its docstring and by manual runs, not by a test.

**`apply_one` is NOT atomic, and a mid-run failure leaves committed partial state.** Each
`g.execute_query` call is its own transaction. One call to `apply_one` issues many: at minimum one per
relationship type per direction, plus one more per type to observe the zero-move that ends its loop,
plus the count/delete pairs, plus the final count — for a large name, hundreds of separate
transactions. Only an individual batch is atomic (that per-batch rollback is exactly what saved the
graph in the 2026-08-25 incident described at `:114-124`). Consequences a reader of a failed run must
assume: relationship types processed before the failure are already merged onto the survivor AND their
originals already deleted; types after it are untouched; the doomed copies may still exist, may be
partly deleted, or may be fully deleted with the assert having fired. The `except` in `main()`
(`:233-241`) catches this and moves on to the next name, so a failed name is left in that partial state
while the run continues.

**A `--apply` run always exits 0.** `main()` returns `0` on every path, including the one where
`apply_one` raised for some or all names (`:242-243`). The only signal of failure is the stderr text
and the `done/len(plans)` line. Nothing calling this from a script or a scheduler can detect failure
from the exit code.

**The export makes node properties recoverable, and nothing else.** After the 2026-08-25 fix
(`:211-216`) the export writes every node of every affected name with `properties(n)` in full, plus a
`survivor` boolean, plus the plans (`:217-225`). It does NOT export relationships. So a rollback can
recreate the deleted nodes with their stored properties, but cannot restore the graph topology: the
original edges of the doomed copies are gone and the merged edges on the survivor cannot be
distinguished from pre-existing ones. The docstring word "reversible" (`:216`) should be read as
"node content is recoverable", not "the operation can be undone".

**The export path is hardcoded and unchecked.** `/tmp/heaven_data/wiki_dedupe_export_{stamp}.json`
(`:210`). If that directory does not exist, `open(path, 'w')` at `:225` raises `FileNotFoundError`
BEFORE `apply_one` is ever reached — so this failure mode is fail-closed, which is the safe direction.
The file handle from `open()` is never explicitly closed; CPython closes it when the reference drops
after `json.dump` returns.

**Docstring claims versus what the code does.**
- "full export of every affected name BEFORE any mutation" (`:34`) — true for node properties as of the
  fix; silent about relationships, which are not exported.
- "the tool VERIFIES that assumption per name and flags any name whose copies differ in description"
  (`:29-31`) — true, but only over the first 4000 characters (`:72`), and the flag is advisory: nothing
  refuses to process a flagged name.
- "SURVIVOR CHOICE is deterministic and content-preferring" (`:27`) — deterministic, yes. "Content-
  preferring" is not what the code does: the ordering key is degree, then timestamp, then elementId
  (`:74`), and description content is never compared for the purpose of choosing.
- "per-name exception safety" (`:35`) — true in the sense that one name's failure does not abort the
  run (`:233`); it does not mean a failed name is rolled back. See the atomicity note above.
- "batched deletes" (`:35`) — the delete loop was always batched; the edge-merge loops are batched as
  of 2026-08-25 (`:114-124`).
- "a post-condition assert that each processed name ends at exactly 1 node" (`:35`) — present at `:160`,
  but it runs after the deletions commit. Note also that Python run with `-O` strips asserts, removing
  this check entirely.

**The census numbers in the header are a 2026-08-22 measurement stated in present tense.** `:6-7`
("111 names across 43,716 nodes, worst System_Event at 41,751") and the fan-out figures at `:18-20`.
The repo rule `knowledge/carton-mcp/.claude/rules/wiki-type-shattering-repair.md:35` records the dedupe
as applied on 2026-08-25 with zero duplicated names remaining, and `:12-13` of this module still frames
step 3 (the uniqueness constraint) as pending while that rule records it as done. I did not query the
live graph, so the current state is UNVERIFIED here; what IS is that the module's header carries a
census that the repo's own rule says is superseded.

**If the survivor node disappears between plan and apply, every copy is deleted.** The delete loop
(`:149-157`) matches `elementId(dup) <> $keep`. If `$keep` no longer identifies an existing node, every
remaining node for that name matches and is deleted; `left` then reaches 0, the loop exits on
`left <= 1`, and the assert at `:160` fails on `final == 0` — after the deletions are committed. This
is reachable because inspect and apply are separated by an unbounded amount of wall time and other
writers are live. (Derived from the loop conditions; not reproduced.)

**Relationship types are interpolated into Cypher without quoting.** `f"...[r:{rel}]..."` (`:129`,
`:141`) and the corresponding `MERGE` lines. The values are read back from the database via `type(r)`
rather than supplied by the user, so this is not an injection surface from the CLI; but a relationship
type containing a backtick, a space, or other characters that need escaping in Cypher would produce a
syntax error at apply time, i.e. a failure in the middle of a non-atomic operation.

**Report lines truncate names.** `name[:52]` in the plan table (`:192`) and `p['name'][:60]` in the OK
and FAILED lines (`:232`, `:240`). Two long names sharing a prefix are indistinguishable in the output
of a destructive run.

**`--name` bypasses duplicate detection entirely.** `targets = [(args.name, 0)]` at `:176` — the name
is not required to be duplicated. `inspect` is still called and `copies < 2` is skipped at `:184`, so
the effect is a no-op report rather than damage.

**`connect()` can return `None`.** `_create_shared_neo4j` catches its own exceptions and returns `None`
(`observation_worker_daemon.py:1377-1379`). The tool does not check, so a connection failure surfaces
as `AttributeError: 'NoneType' object has no attribute 'execute_query'` from inside `find_duplicates`
rather than as a stated connection error.

**`os` is imported and never used** (`:41`), grep-confirmed.
