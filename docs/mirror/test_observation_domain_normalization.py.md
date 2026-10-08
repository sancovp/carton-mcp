# doc(m): test_observation_domain_normalization.py

- **Canonical path:** /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_observation_domain_normalization.py
- **Line count:** 62 (measured 2026-08-28, first derivation)
- **Module role:** Unit test for `server_fastmcp._normalize_observation_domain_edges` (issue #198
  data half). Script mode (`python3 test_observation_domain_normalization.py`), never pytest
  (repo pytest collection broken, pre-existing). Imports the INSTALLED `carton_mcp.server_fastmcp`
  (post-`pip install` gating, same pattern as `test_carton_properties.py`). No network, no graph —
  the helper is a pure in-place dict transform.

## Checks (6, PASS/FAIL lines + ALL_PASS tail, exit 1 on fail)

- T1a/T1b — an actual-only concept gains ONE `has_domain` dict with the same targets AND keeps
  `has_actual_domain` (both-edges, never a rewrite).
- T2a/T2b — an existing `has_domain` dict is MERGED into without duplicate targets; asserts exactly
  ONE `has_domain` dict survives (the issue #204 rel-dict-collapse guard).
- T3 — a concept without `has_actual_domain` is byte-untouched.
- T4 — `confidence`/`hide_youknow` keys, a concept missing `relationships`, a non-dict list entry,
  and an empty `related` list never raise.

## Verified

6/6 ALL_PASS 2026-08-28 against the installed copy (run by the lead).
