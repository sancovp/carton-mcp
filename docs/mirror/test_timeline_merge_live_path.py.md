# doc(m): test_timeline_merge_live_path.py

- **Canonical path:** /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_timeline_merge_live_path.py
- **Line count:** 138 (measured, `wc -l`)
- **Module role:** A standalone, dependency-free script that pins `observation_worker_daemon._process_timeline_merge` — the LIVE-path handler for `timeline_merge` queue files — using two hand-rolled stub graph objects and six `assert`-bearing test functions, run as `python3 test_timeline_merge_live_path.py`. It is the gate named by the repo-scoped dev-flow rule `knowledge/carton-mcp/.claude/rules/timeline-merge-live-path.md`.

## What this module IS (from the code)

It is a **script, not a pytest module**. There is no pytest import, no fixture, no `conftest.py`, no `pytest.ini`/`tox.ini` in the directory, and `pyproject.toml` carries only `[tool.setuptools]` and `[tool.mcp]` — no test-collection config. Execution happens exclusively through the `if __name__ == "__main__":` block at `test_timeline_merge_live_path.py:129-138`, which calls the six test functions by name in order and prints `ALL 6 PASS`. Failure surfaces as a bare `AssertionError` traceback and a non-zero exit; success prints one `PASS <name>` line per test.

The docstring at lines 1-8 states the run convention ("Run as a SCRIPT (repo root IS the carton_mcp package; the test_carton_kv.py flat-import convention)") and then lists the pins. Line 9 is the whole dependency surface: `import observation_worker_daemon as owd` — a **flat import off the current working directory**, not `from carton_mcp import ...`.

**The stub-graph mechanism is the core of the design.** The handler under test only ever touches its `graph` argument through `graph.execute_query(q, params)`, so the whole test suite is built on a class that implements exactly that one method and dispatches on **substrings of the Cypher text**:

`StubGraph` (`:12-29`) records `(q.strip().split("\n")[0], params)` into `self.queries` on every call — the first line only, which is what every later assertion greps. Then, in order (`:23-29`):
1. `raise_on` set and present in `q` → `raise RuntimeError("boom")` (the query is already recorded before the raise).
2. `"transferred" in q` → `[{"transferred": self.transferred}]` — the CREATED_DURING transfer query's return column.
3. `"count(r) AS n" in q` → `[{"n": 1 if self.real_exists else 0}]` — the merge-target existence probe. The comment at `:17-19` names why the flag exists: the handler refuses to `DETACH DELETE` the placeholder when the target is absent.
4. anything else → `[]`.

That fallthrough is load-bearing and easy to miss: the handler's all-relationship-types discovery queries (`MATCH ... RETURN DISTINCT type(r) AS t`, `observation_worker_daemon.py:905-907`) hit case 4 under the base stub, so the non-CREATED_DURING transfer loop is a **no-op in the first four tests**. Only `TypeAwareStubGraph` (`:67-91`) makes that loop run, by adding two branches: `"DISTINCT type(r)" in q` → `[{"t": "CREATED_DURING"}, {"t": "PART_OF"}, {"t": "lower_case_bad"}]` (`:85-86`) and `"count(x) AS n" in q` → `[{"n": 2}]` (`:87-88`), the return column of the per-type move queries. Its class docstring (`:68-77`) records the 2026-08-24 bug it exists to pin: the handler moved only `CREATED_DURING` and then ran `DETACH DELETE`, destroying every other edge on the placeholder — measured live at 95 CREATED_DURING moved plus PART_OF / HAS_PART / HAS_INSTANCES silently destroyed — and there was no test on the non-CREATED_DURING path, "which is why it survived."

The three seeded types are each doing a distinct job: `CREATED_DURING` must be skipped (already moved by the first query), `PART_OF` must be moved and must be moved *before* the delete, and `lower_case_bad` must never be interpolated into Cypher — it fails the handler's `re.fullmatch(r'[A-Z_]+', rtype)` sanitiser at `observation_worker_daemon.py:914`, which exists because relationship types cannot be Cypher parameters.

**Ordering is asserted positionally, not by mock call-order machinery.** `test_non_created_during_edges_are_transferred_before_delete` (`:94-108`) takes the index of the first PART_OF-move query and the index of the first `DETACH DELETE` in the recorded `queries` list and asserts `move_at < del_at` (`:103-105`) — the edge must be relocated while it still exists.

The runner's placement is itself documented as a fix. The comment at `:124-128` states that the `__main__` block used to sit **above** `TypeAwareStubGraph`, so the edge-loss test appended below it was never called: the gate printed `ALL 4 PASS` and the data-loss fix "sat unpinned." The comment instructs that a new test goes ABOVE the block and its call gets added to the list. `owd.log_system_event` is monkeypatched to a no-op at `:131` with the comment "log_system_event touches the graph; stub it out so tests stay pure."

**Observed behaviour (run 2026-08-24, exit 0):**

```
PASS success_transfers_and_deletes
PASS moot_merge_still_succeeds
PASS missing_fields_or_graph_fail
PASS query_explosion_returns_false
PASS non_created_during_edges_are_transferred_before_delete
PASS absent_real_target_refuses_to_delete
ALL 6 PASS
```

with the handler's own stderr interleaved, including `moved 2 PART_OF (in)` / `moved 2 PART_OF (out)`, a `(7 relationships transferred)` total for the TypeAware success case (3 + 2 + 2), and `real conversation Conversation_Gone does NOT exist -- refusing to delete Unnamed_X`.

## Imports

### stdlib
None.

### third-party
None. (No pytest, no unittest, no mock library. Assertions are bare `assert` statements.)

### local
- `import observation_worker_daemon as owd` (`:9`) — flat, cwd-relative.

## Top-level definitions

- **`class StubGraph`** (`:12`) — the base fake graph.
  - `__init__(self, raise_on=None, transferred=3, real_exists=True)` (`:13-19`) — sets `self.queries = []` plus the three knobs.
  - `execute_query(self, q, params=None)` (`:21-29`) — records, then dispatches on query substrings as described above.
- **`def test_success_transfers_and_deletes()`** (`:32-39`) — default `StubGraph`; calls the handler with a well-formed payload; asserts `ok is True`, that some recorded query contains `CREATED_DURING`, and that some contains `DETACH DELETE`.
- **`def test_moot_merge_still_succeeds()`** (`:42-48`) — `StubGraph(transferred=0)`; the unnamed node is already gone, so the transfer matches nothing; asserts the handler still returns `True` so stale merges self-clear rather than dead-lettering forever.
- **`def test_missing_fields_or_graph_fail()`** (`:51-56`) — three one-line assertions in a row: payload missing `unnamed_concept` → `False`; missing `real_concept` → `False`; `graph=None` → `False`. Each uses a fresh `StubGraph()` (or `None`).
- **`def test_query_explosion_returns_false()`** (`:59-64`) — `StubGraph(raise_on="CREATED_DURING")`; the first transfer query raises `RuntimeError("boom")`, which the handler's outer `except` catches; asserts `False` so the caller dead-letters.
- **`class TypeAwareStubGraph(StubGraph)`** (`:67`) — subclass with the long docstring recording the 2026-08-24 edge-loss bug (`:68-77`).
  - `execute_query(self, q, params=None)` (`:79-91`) — a full override (not a `super()` delegation) that re-implements record / `raise_on` / `transferred` verbatim and adds the `DISTINCT type(r)` and `count(x) AS n` branches.
- **`def test_non_created_during_edges_are_transferred_before_delete()`** (`:94-108`) — `TypeAwareStubGraph()`; asserts `ok is True`; asserts some query contains both `PART_OF` and `MERGE` ("PART_OF was never transferred"); asserts the move index precedes the delete index ("PART_OF moved AFTER the delete -- the edge is already gone"); asserts `lower_case_bad` appears in no query ("unsanitised relationship type interpolated").
- **`def test_absent_real_target_refuses_to_delete()`** (`:111-121`) — `TypeAwareStubGraph(real_exists=False)`; asserts `ok is False` ("absent target must dead-letter, not succeed") and that **no** recorded query contains `DETACH DELETE` ("placeholder was DELETED even though the merge target does not exist -- edges lost"). Its docstring (`:112-114`) states the reasoning: every transfer `MATCH`es `real`, so with `real` absent they all matched nothing and deleting would destroy the placeholder's edges with nowhere to have moved them.
- **`if __name__ == "__main__":` block** (`:129-138`) — the placement comment (`:124-128`), the `log_system_event` no-op patch (`:131`), the six calls in file order (`:132-137`), and `print("ALL 6 PASS")` (`:138`).

## What this module CALLS

- **`owd._process_timeline_merge(data, graph) -> bool`** — defined at `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/observation_worker_daemon.py:856`. Six call sites: `:34`, `:45`, `:52`, `:53`, `:54`, `:61`, `:96`, `:116` (eight invocations total; `test_missing_fields_or_graph_fail` alone makes three). This is the entire subject of the module.
- **`owd.log_system_event`** — defined at `observation_worker_daemon.py:1523`; not called by the test, only **replaced** with `lambda *a, **k: None` at `:131`. The handler calls the real one at `observation_worker_daemon.py:955` on the success path.
- stdlib builtins only: `print`, `any`, `min`, `enumerate`, `assert`, and `RuntimeError` inside the stubs.

No filesystem, network, Neo4j, MCP, or subprocess calls anywhere in the file.

## What CALLS this module (grep-confirmed)

No Python file imports it — it is a leaf script with no importers. Two non-executing references exist:

- `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/.claude/rules/timeline-merge-live-path.md:36` — names `python3 test_timeline_merge_live_path.py` as the dev-flow gate for any edit to `_process_timeline_merge` or the empty-parse routing.
- `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_network_dialect.py:8` — a docstring citing this file (alongside `test_carton_kv.py`, `test_carton_breaker.py`) as an instance of the repo's flat-import script convention. A textual reference, not a call.

Narrative-record mentions, also grep-confirmed and also not callers: `/home/GOD/gnosys-plugin-v2/context/journal/2026-07.md:634`, `/home/GOD/gnosys-plugin-v2/context/journal/2026-08.md:2006`, `/home/GOD/gnosys-plugin-v2/context/journal/2026-08.md:2008`, `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/docs/vision/_conversation-journal-join.md:61`.

There is no CI workflow, shell script, or Makefile invoking it (grep across `*.sh`, `*.yml`, `*.yaml`, `*.toml`, `*.cfg`, `*.json` returned nothing).

## Notes / discrepancies

1. **The module's own docstring is stale.** Lines 4-7 pin four behaviours: success transfers+deletes, missing fields / no graph / query explosion return False, and the moot case still succeeds. The two tests added 2026-08-24 — the all-types transfer (`:94`) and the absent-target refusal (`:111`) — are not mentioned in it. The file has six tests; its header describes four.

2. **The dev-flow rule that names this file as its gate is stale in the same direction.** `.claude/rules/timeline-merge-live-path.md:36` says the gate is "`python3 test_timeline_merge_live_path.py` all 4 green". The measured output is `ALL 6 PASS`.

3. **That same rule directly contradicts this test.** Its "Known bounds (named, accepted)" section states: *"if `real_concept` does not exist the transfer matches nothing but the Unnamed is still deleted — the dead path's own semantics, kept unchanged."* `test_absent_real_target_refuses_to_delete` (`:111-121`) pins the exact opposite, and the handler implements the opposite at `observation_worker_daemon.py:938-952` (existence probe, then `return False` without deleting). The rule text was not updated when the behaviour changed. The code and this test agree; the rule is wrong.

4. **A stub artifact appears in the run output of test #6.** `TypeAwareStubGraph` answers `count(x) AS n` with `2` unconditionally, ignoring `real_exists`. So with `real_exists=False` the run still prints `moved 2 PART_OF (in)` / `(out)` — but the real move queries carry `MATCH (real:Wiki {n: $real})` (`observation_worker_daemon.py:917-923`), so against a live database with the target absent they would match nothing and move nothing. The stub does not model that. The test's actual assertions (returns `False`, no `DETACH DELETE`) are unaffected, but the printed line is not a claim about production behaviour.

5. **`TypeAwareStubGraph.execute_query` duplicates rather than extends.** The record, `raise_on`, `transferred`, and `count(r) AS n` branches (`:80-84`, `:89-90`) are copied verbatim from the parent instead of delegating via `super().execute_query(...)`. A change to the base dispatch will not propagate to the subclass.

6. **The `log_system_event` no-op is installed only inside `__main__` (`:131`).** Importing this module and calling a test function directly — which is what was done on 2026-08-24 to exercise the then-orphaned fifth test — leaves the real `log_system_event` in place. Reading it (`observation_worker_daemon.py:1523-1588`) shows that is benign here: it makes one `execute_query` call, ignores the result, and is wrapped in its own `try/except`. The only effect is one extra recorded tuple in `g.queries`, appended *after* the delete, whose recorded first line is `MERGE (timeline:Wiki {n: "System_Timeline"})` — containing neither `PART_OF` nor `DETACH DELETE`, so no existing assertion changes. Still, the tests are self-contained only under the script entry point.

7. **What the green result does and does not prove — measured, not inferred.** Under the flat-import convention the module under test resolves to the **source** file (`/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/observation_worker_daemon.py`), while its own dependency `carton_mcp.add_concept_tool` (imported at `observation_worker_daemon.py:31`) resolves to the **installed** copy at `/home/GOD/.pyenv/versions/3.11.6/lib/python3.11/site-packages/carton_mcp/add_concept_tool.py`. `carton_mcp.observation_worker_daemon` is a *different module object* from the one this test exercises (verified: `p is owd` → `False`). So a green run proves the source file, never the installed module the running daemon holds — which is exactly why the dev-flow rule requires `pip install --no-deps` plus a daemon restart as separate gate steps.

8. **Coverage gaps within the file's own subject.** `test_success_transfers_and_deletes` (`:32-39`) asserts that both a `CREATED_DURING` query and a `DETACH DELETE` query were issued, but not their order — ordering is asserted only for `PART_OF`, only in test #5. `test_missing_fields_or_graph_fail` (`:51-56`) never inspects `g.queries`, so it does not assert that a malformed payload issues zero queries. Nothing exercises the handler's fail-loud branch where a *move* query raises (`observation_worker_daemon.py:932-936`) — `raise_on` is only ever used with `"CREATED_DURING"`, which trips the first transfer instead.

9. **`raise_on` is a naive substring match against the whole query text**, so a future query containing the same token anywhere would also raise. Today only the first transfer query contains `CREATED_DURING` in a form that trips it.

10. **No shebang.** The file opens directly with its docstring at `:1`, unlike the sibling `test_network_dialect.py` which carries `#!/usr/bin/env python3`. It is not executable-by-path; it must be run as `python3 <file>`, which is what its own docstring and the rule both specify.

11. **The file's assertion style deliberately mixes `assert` with `print("PASS ...")`.** The trailing print is a script-mode progress marker (this repo's convention), not a substitute for an assertion — every test carries real `assert` statements above it.
