# doc(m): tests/test_normalize_concept_name.py

- **Canonical path:** /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/tests/test_normalize_concept_name.py
- **Line count:** measured at commit; run as a script (python3 tests/test_normalize_concept_name.py)
- **Module role:** Suite for the issue-#200 sanitize hardening of
  `add_concept_tool.normalize_concept_name`: controlled pair per metachar class (quotes stripped
  in place; separator runs — slashes, brackets, C0 controls — to one underscore), the 200-char
  cap on transcript-blob shapes, empty-sanitize totality (returns ""), idempotence, the
  before/after WARNING content, clean names byte-identical + never warning, and a STATIC-SOURCE
  PIN that the daemon auto-stub door (observation_worker_daemon) routes concept_name and every
  relationship target through this one chokepoint.

## Verified

15/15 green 2026-08-28 (integrator run) against the installed package post-merge; the live pair
(metachar add_concept landing sanitized on the graph) is recorded in add_concept_tool.py.md.

## Boundary

Imports installed carton_mcp add_concept_tool + reads observation_worker_daemon source for the
static pin. No graph writes.
