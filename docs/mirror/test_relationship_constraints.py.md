# doc(m): test_relationship_constraints.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_relationship_constraints.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

A LIVE-NEO4J integration check (NOT a self-asserting pytest suite) of the ontology relationship CONSTRAINTS enforced in `add_concept_tool_func`: part_of cycle rejection, instantiates-of-an-empty-pattern rejection, and part_of-to-an-already-instantiated-pattern immutability/versioning. It calls the REAL write path (`carton_mcp.add_concept_tool.add_concept_tool_func`) against `bolt://localhost:7687` and PRINTS ✓/✗ lines for a human to read — there are no `assert`s and the exit code is always 0. It is a manual smoke harness for the constraint layer, not part of the four-file lib gate.

## How to run

- `python3 test_relationship_constraints.py` — REQUIRES a running Neo4j at `bolt://localhost:7687` (note: localhost, NOT the package default `host.docker.internal`) and writes real test concepts (`ConceptA/B/C`, `InstanceOfEmpty`, `PartX/Z`, `PatternY`, `InstanceY`) into the live graph plus files under `/tmp/carton_constraint_test`.
- Env is hardcoded at import time (`:8-14`): dummy `GITHUB_PAT`/`REPO_URL`, `BASE_PATH=/tmp/carton_constraint_test`, the `NEO4J_*` trio.

## What the harness checks (the constraints it exercises)

- `test_part_of_cycle()` — `:18` — builds `ConceptA part_of ConceptB`, `ConceptB part_of ConceptC`, then attempts `ConceptC part_of ConceptA`; EXPECTS an exception whose message contains `"Cycle detected"` (the `check_part_of_cycle` constraint in `add_concept_tool`). Prints ✗ FAILED if the cycle is accepted.
- `test_instantiates_empty_pattern()` — `:63` — attempts `InstanceOfEmpty instantiates EmptyPattern` where `EmptyPattern` has no parts; EXPECTS an exception containing `"pattern has no parts"` (the `check_instantiates_completeness` constraint).
- `test_part_of_instantiated()` — `:82` — builds `PartX part_of PatternY`, then `InstanceY instantiates PatternY`, then attempts `PartZ part_of PatternY`; EXPECTS an exception containing both `"immutable"` and `"_v"` — i.e. the instantiated-pattern-is-immutable rule plus the version-suggestion (`get_next_version_number`) behavior.
- `__main__` — `:127-139` — runs the three in order with banner prints; never exits nonzero.

## Data contracts

- Encodes (as expected error-message substrings) the constraint contract of `add_concept_tool_func`: `"Cycle detected"`, `"pattern has no parts"`, `"immutable"` + `"_v"`. If the constraint code rewords its errors, this harness mis-reports ✗ unexpected-error.
- Assumes constraint violations surface as raised EXCEPTIONS from `add_concept_tool_func`. UNVERIFIED whether the current tool still raises vs. returns an error string — if it returns, every "should fail" branch prints ✗ FAILED with the returned value; run it against the live surface to find out.

## Deps

- `carton_mcp.add_concept_tool.add_concept_tool_func` (the full write path: neo4j + wiki-file machinery); a live Neo4j; stdlib `os/sys`.

## Defects / dead code

- No assertions, no nonzero exit on failure — CI-blind; results exist only as printed ✓/✗ lines a human must read.
- NOT idempotent/clean: leaves test concepts in the LIVE graph (no namespace, no teardown) and files in `/tmp/carton_constraint_test`. Running it against the production `:Wiki` graph pollutes it with `ConceptA`-style nodes.
- Hardcodes `bolt://localhost:7687`, diverging from every other module's `host.docker.internal` default; in this container it likely cannot connect unless Neo4j is local.
- `sys` imported unused (`:5`).
