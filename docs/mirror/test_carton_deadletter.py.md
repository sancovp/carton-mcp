# doc(m): test_carton_deadletter.py

**Module:** `carton-mcp/test_carton_deadletter.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Dead_Letter_Lane — feature boundary (no Giint_Feature node declared)

- **user action:** a queue batch has finished draining and the fate of every payload it parsed must be decided and RECORDED: consumed into processed, left in the queue for the next tick, or condemned to failed slash carrying the reason it was condemned for, so that a transient outage and a permanently malformed payload are never indistinguishable once they are in the directory
- **doc(v):** `docs/vision/_carton_deadletter.md`
- **outputs to:** `['dead_letter_lane_fires']`
- **sealed:** v6, key `1aa6968d7e37dc37`, commit `e5b1ae6be`, valid from 2026-09-17T07:34:15
- **ranges in this module** (layer order):
  - `L5 gate` · `test_carton_deadletter.py:283-342` — THE STATIC WIRING PIN, and it pins a mistake that actually shipped: run_with_retry was added to the module and called from the daemon but never added to the daemon import list, and because py_compile cannot see a NameError and NO SUITE EXERCISES worker_daemon, everything was green while the live daemon raised on every drain and the queue stopped moving. _assert_module_imports_what_it_calls walks the consumer AST and requires that every symbol it imports from here EXISTS here and every function defined here that it CALLS is imported. It is ONE helper with two consumers, the daemon and the MCP server, rather than a copy each, because a second hand-written copy would be free to drift from the first -- the same class of defect one level up
  - `L5 gate` · `test_carton_deadletter.py:544-584` — THE RUNNER, in this repo script convention rather than pytest: a flat TESTS list and a main block that runs each, prints PASS or FAIL per test, and exits non-zero if any failed. Invoked as python3 test_carton_deadletter.py from the repo root, because the repo root IS the carton_mcp package and pytest-from-the-dir breaks on package inference. Every test prints its own MARKER line so a reader can tell WHICH claim held rather than only that the count was green. 24 tests as of the issue 280 fix, the last four of which are the never-attempted set
  - `L5 gate` · `test_carton_deadletter.py:401-541` — THE ISSUE 280 GATE, and the CONTROLLED PAIR that is its centre. _pre_fix_rule reproduces the two branches Phase 3 had before the fix, succeeded to processed and everything else to dead letter, with the attempt count appearing nowhere -- so the pair can differ in exactly ONE variable, the rule, while the files, the directories and the mover are literally the same code. Arm A drives the pre-fix rule over three real payloads in a real temp queue and asserts they all land in failed slash under the exact live string batch write to the graph failed (unknown) after 0 attempt(s) with zero attempts recorded. Arm B drives batch_disposition over identical inputs and asserts every file STAYS, that failed slash is never even created, and that each payload is byte-identical afterwards. A third test holds requirement 2 by proving a genuine failure after three attempts still condemns and still carries the store own text. The fourth is a STRUCTURAL PIN: it walks the daemon AST and requires worker_daemon to CALL batch_disposition and to reference REQUEUE, because a revert of Phase 3 to the two-state form would leave the import untouched and pass every other test in this file while restoring the defect, and nothing can execute worker_daemon to catch it dynamically
- **also passes through:** `carton_deadletter.py`, `observation_worker_daemon.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
