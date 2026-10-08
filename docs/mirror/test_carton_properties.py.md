# doc(m): test_carton_properties.py

- **Canonical path:** /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_carton_properties.py
- **Line count:** 431 (measured, post connection-API fake fix 2026-08-28)
- **Module role:** Lib-level suite for the property surface (set_concept_properties,
  query_concepts_by_properties, remove_concept_relationship from carton_utils) plus
  substrate_projector._build_template_content. Pure logic on a FakeGraph stub - no real neo4j.
  Run as a SCRIPT (python3 test_carton_properties.py), never pytest (repo pytest collection is
  broken: hyphenated dir + top-level __init__.py, pre-existing).

## Structure, with line ranges

- **FakeGraph** :27-66 - existence set (names), recorded (query, params) in calls,
  canned query_rows, and an optional edges-backed DELETE handler (edges set of
  (source, REL, target) tuples; None = the legacy always-deletes-1 stub). execute_query
  pattern-matches the existence check, SET, REMOVE, property query, and DELETE shapes.
- **set merge tests** :71-160 - parameterized SET map, reserved-key refusal (whole
  RESERVED_PROPERTY_KEYS), dict/nonscalar value refusal, not-found refusal, unknown mode,
  empty props, forced no-connection branch (monkeypatches _get_module_connection).
- **set remove tests** :163-183 - backtick-quoted REMOVE keys; reserved refused.
- **query tests** :186-221 - "c.<backtick-quoted key> = $w_i" parameterized WHERE, AND-joined,
  empty-where refused (never queried), non-int limit defaults to 25.
- **remove_rel tests** :224-260 - valid type deletes; rel_type injection/empty REFUSED
  (rel types cannot be Cypher params); forced no-connection branch.
- **Issue #201 tests** :263-352 (added by the 200+201 worktree run) - exact-first wins and
  reports matched_via exact with ONE query; normalized fallback fires on exact miss
  (matched_via normalized + normalized_source/target, TWO queries in order); honest zero
  after both; already-normalized names never re-issue the identical query; set_properties
  fallback resolves the node / exact always wins / not-found-after-fallback refuses.
- **template content test** :357-390 - _build_template_content merges node props excluding
  reserved keys; explicit concept-data keys win.
- **runner** :393-405 - sorted test_* discovery, PASS/FAIL lines, N/M passed tail, exit 1 on fail.

## Verified (2026-08-28 integration)

28/28 green against the MERGED om-is-the-base source via shadow-package PYTHONPATH (integrator
run). FakeGraph now carries the three CONNECTION-API methods (:68-92) - set_properties /
remove_properties / find_by_properties - synthesizing the same (query, params) shapes the real
neo4j backend issues, so the pre-existing Cypher-shape assertions (parameterized SET map,
backtick-quoted REMOVE keys, per-key $w_i WHERE) stay meaningful. This closed a PRE-EXISTING
drift: the connection-API change in carton_utils landed without updating the fake (HEAD's own
suite measured 12/21 vs HEAD library via git-archive before the merge; 17/28 post-merge).
CodeNose file-length + local-import smells are pre-existing deliberate shape (monkeypatch
locals), flagged not fixed.

## Boundary

Imports installed carton_mcp (so it gates the INSTALLED code post-pip-install; shadow
PYTHONPATH gates source). Sets HEAVEN_DATA_DIR to a tempdir at import. No network, no writes.
