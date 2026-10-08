# doc(m): test_observation_validation_deadletter.py

- **Canonical path:** /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_observation_validation_deadletter.py
- **Line count:** 194 (measured, `wc -l`)
- **Module role:** The gate for the #198 live observation validation: a self-running script
  (`python3 test_observation_validation_deadletter.py`, the repo convention) proving the pure
  validator and the writer-side transforms (both-edges #198 + part_of merge #204), six markers.

## What this module IS (from the code)

**The six cases:**

1. `t_valid_observation_passes` — VALID_OBSERVATION_PASSES_OK: a part with all four required
   rels returns `[]`.
2. `t_missing_rels_named` — MISSING_RELS_NAMED_OK: dropping part_of + has_actual_domain yields
   ONE error naming the concept, the tag, and exactly the missing rels.
3. `t_bad_personal_domain_named` — BAD_PERSONAL_DOMAIN_NAMED_OK: a has_personal_domain value
   outside PERSONAL_DOMAINS is named in the error.
4. `t_scope_is_faithful` — SCOPE_FAITHFUL_OK: empty relationships skip (the dead validator's own
   scope); raw_concept / concepts-list / timeline_merge shapes return `[]` untouched.
5. `t_identity_pov_preserves_both_edges` — IDENTITY_POV_BOTH_EDGES_OK: calls the REAL
   `observe_from_identity_pov` with an isolated `HEAVEN_DATA_DIR` queue and `server_fastmcp.utils`
   swapped for `FakeUtils` (query_wiki_graph reports the identity collection exists, so no live
   graph is touched — the FakeGraph precedent). Asserts on the QUEUED FILE (the artifact):
   has_actual_domain PRESERVED, exactly ONE has_domain dict carrying the mirrored target
   (merge-not-append), and `observation_validation_errors(queue_json) == []` end to end.
   `AGENT_IDENTITY` is popped for the call and restored after (env priority would override the
   param).

6. `t_identity_pov_user_part_of_survives` — IDENTITY_POV_USER_PART_OF_SURVIVES_OK (#204): same
   sandbox; the queued file carries exactly ONE part_of dict whose targets include BOTH the user's
   own part_of target AND the identity collection — the merge-not-append pin (two dicts of one
   rel-name collapse to the later at the daemon's observation parse).

**What is deliberately NOT here:** the daemon's dead-letter branch itself — it lives inline in
the worker loop, and its proof is the LIVE wiring run (an invalid observation file through the
real drain → `failed/` with the named `error_message`; executed 2026-08-29), the same
wiring-proof discipline as the breaker.

## Boundary

Imports: stdlib (`json`, `os`, `tempfile`, `pathlib`) + flat `add_concept_tool` (source copy) +
installed `carton_mcp.server_fastmcp` (case 5). Writes: only its own temp dirs. Exit: 0 all
pass · 1 any failure. Runner shape identical to test_carton_breaker.py.
