# doc(m): carton_write_batch.py

**Module:** `carton-mcp/carton_write_batch.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 2 sealed boundaries land here

## Features whose sealed boundary lands in this module

### Carton_Concept_Delete — feature boundary of `Giint_Feature_Carton_Mcp_Carton_Concept_Delete`

- **user action:** an operator runs python3 -m carton_mcp.carton_delete with concept names or a names file and a backup dir, dry first, to delete concepts carton stored by mistake: every named node is backed up whole with its wiki directory, a node cited from outside the batch along an edge it does not point back along is refused, then the node, its edges and its wiki directory are removed (card 816, issue 1301)
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v1, key `bdbb5a73dbb481e4`, commit `123382528`, valid from 2026-10-04T14:07:48
- **ranges in this module** (layer order):
  - `L3 carton_write_and_path` · `carton_write_batch.py:170-225` — execute_write_statements: the whole read and the whole delete each run as one transaction on the neo4j driver; WriteStoreUnavailable when the graph cannot be reached
- **also passes through:** `carton_delete.py`, `carton_pathguard.py`, `test_carton_delete.py`

### Carton_Write_Batch — feature boundary (no Giint_Feature node declared)

- **user action:** a doc-mirror CLI or any carton caller must apply SEVERAL graph write statements as ONE unit - a lane change with its reason and its edge replacement, a card mint with its type and session edges - and carton had no shape for it: the read facade refuses every write verb and the store exposes only one-statement auto-commit execute
- **doc(v):** `docs/vision/_carton_write_facade.md`
- **outputs to:** `doc_mirror_kanban`
- **sealed:** v2, key `a41638932df798d4`, commit `e341218ee`, valid from 2026-09-10T05:21:06
- **ranges in this module** (layer order):
  - `L0 entry` · `carton_write_batch.py:170-225` — execute_write_statements, the ONE public entry: validates the batch before touching any store, resolves carton own connection when none is handed in, ensures it, and REFUSES OUTRIGHT a connection that exposes neither a driver nor an execute_query, so such a caller gets this module documented WriteStoreUnavailable rather than a bare AttributeError from somewhere inside the batch - the M10 case, which the suite found before any caller did. Then it dispatches to the transaction mode or the sequential mode by what the connection can do, and returns one list of dict rows per statement in statement order, the exact shape docmirror_kanban _cypher returned, so its callers are unchanged
  - `L1 pure` · `carton_write_batch.py:67-94` — validate_statements, PURE: normalizes query and params pairs to str and dict, a None params becoming an empty dict, and raises WriteStatementsInvalid naming the offending index on a bare string, a non-pair, a non-str query or non-dict params, because a malformed batch must fail BEFORE the store rather than half way through it; an empty batch is valid and does nothing
  - `L1 pure` · `carton_write_batch.py:97-104` — atomicity_for, PURE: returns TRANSACTION when the connection exposes a driver and SEQUENTIAL when it does not, so atomicity is REPORTED rather than assumed and a caller that needs all or nothing can ask before it writes instead of discovering it afterwards
  - `L1 pure` · `carton_write_batch.py:107-132` — the unreachable classification: _unreachable_types imports the driver could-not-reach types LAZILY and TOLERANTLY, returning an empty tuple when the driver package is absent because a driverless backend raises its own errors through its own store, and logging that at DEBUG with its traceback rather than warning, since on such a backend it is the EXPECTED answer and not a fault; classify_error is PURE over those types so the executor except branch has nothing to decide and the classification is testable on synthetic exception classes with no store
  - `L1 pure` · `carton_write_batch.py:135-137` — _rows, PURE: one statement result as a list of plain dicts, with None and empty both giving an empty list
  - `L1 pure` · `carton_write_batch.py:47-64` — the two error classes and the two mode names: WriteStatementsInvalid is raised before any store is touched, WriteStoreUnavailable means the graph could not be REACHED and is never an empty result, which is the distinction docmirror_kanban StoreUnavailable carries and every one of its callers depends on; TRANSACTION and SEQUENTIAL are named so a caller can report which mode it actually got
  - `L2 modes` · `carton_write_batch.py:140-156` — _run_in_one_transaction, THE RELEASE: the whole batch commits or rolls back together, and the commit is where the effect leaves this boundary and reaches the graph. ONE explicit transaction and NO managed retry, preserved verbatim from the _cypher it replaces, because the driver managed transaction retries an unreachable store with backoff for roughly thirty seconds, longer than the CLI callers wait. A failure rolls back and re-raises, which is what keeps a block from ever landing half recorded  ⟵ RELEASE
  - `L2 modes` · `carton_write_batch.py:159-167` — _run_sequentially, the driverless branch: one execute_query per statement in order, on a backend with no driver to open a transaction on. NOT atomic and this module never claims it is - atomicity_for returns SEQUENTIAL for such a connection so a caller needing all or nothing can refuse before writing, and a part way failure leaves the earlier statements APPLIED, the honest cost of a backend without transactions
- **also passes through:** `test_carton_write_batch.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
