---
name: edit-add-concept-optional-fields
description: "WHAT: the dev-flow for the OPTIONAL domain/subdomain/personal_domain/produces params on add_concept_tool_func — the internal chokepoint function every CartON concept-creation caller (Dragonbones, sm_gate.py, split_content_concept, the migration scripts) passes through, whether or not they use the add_concept MCP tool. WHEN: when editing add_concept_tool_func's domain/subdomain/personal_domain/produces params, merge_optional_domain_fields, or PERSONAL_DOMAINS in add_concept_tool.py (any of)."
---

# edit-add-concept-optional-fields — dev-flow for the optional provenance-field passthrough

Task 58 (Isaac 2026-07-04, verbatim): *"it can move into add concept tool func but as optionals
because it cant change anything about how other code uses carton as lib unless we wanna go thru
literally all the code and check for these calls and adjust them."* Context: the `add_concept` MCP
tool (`server_fastmcp.py`) already REQUIRES `domain`/`subdomain`/`personal_domain`/`produces`
(commit `e61c909`). But `add_concept_tool_func` (`add_concept_tool.py`) — the internal library
function every concept-creation call site in the monorepo actually passes through, MCP tool or not
— had no awareness of these fields at all; a caller bypassing the MCP tool (Dragonbones's
`compiler.py`, `sm_gate.py`, `carton_split_content.py`, several migration scripts — see
`Concept_Provenance_Enforcement_Gap`) had no correct, discoverable way to supply them short of
hand-building the exact relationship-type strings themselves. This build gives `add_concept_tool_func`
first-class OPTIONAL params for all four — mirroring the MCP tool's convenience-building, but
**optional, not required**, so all ~8 existing bypass callers remain completely unaffected until
each is individually migrated. It enforces nothing; it only makes correct usage possible.

## Part 1 — How you edit (read the whole function first — the ONION, pure functions first)

1. **`merge_optional_domain_fields(relationships, domain, subdomain, personal_domain, produces)`**
   — the PURE, onion-inner, unit-tested layer (no I/O), defined immediately before
   `add_concept_tool_func`. Takes the RELATIONSHIPS LIST (`[{"relationship":..., "related":...}, ...]`),
   NOT `relationship_dict` — this is load-bearing, see item 2. Returns a NEW list (never mutates the
   input) with each provided field merged in: appended as a new `{"relationship": "has_domain", ...}`-
   style entry if that type isn't already present, or deduped into the existing entry's `related` list
   if it is. `personal_domain`, if given, IS enum-validated against `PERSONAL_DOMAINS` regardless of
   the others being optional (raises `Exception` if invalid) — the enum-check is not optional, only
   the field's presence is.
2. **THE ONE THING THAT MUST NEVER REGRESS: the merge operates on `relationships` (the list), and
   `add_concept_tool_func` REASSIGNS `relationships = merge_optional_domain_fields(...)` BEFORE
   building `relationship_dict`.** `relationship_dict` is a DERIVED view built FROM the relationships
   list, used ONLY for SOMA/D2 validation (`_compute_d2_coverage`, the HAS_VALIDATOR parent-template
   check, the SOMA observation payload). The actual graph persistence — the daemon queue write,
   `queue_data["relationships"] = relationships` — serializes the LIST verbatim. **A version of this
   fix that merges only into `relationship_dict` validates correctly (SOMA/D2 both see the fields) but
   the fields NEVER reach the graph** — caught live during this build's own E2E verification 2026-07-04
   (the first draft passed all 7 unit tests and looked correct in the D2 coverage message, but
   `query_wiki_graph` after a real call showed zero `HAS_DOMAIN`/`HAS_SUBDOMAIN`/`HAS_PERSONAL_DOMAIN`/
   `PRODUCES` edges — only re-querying the live graph, not trusting the green unit tests or the D2
   message, surfaced this). If you ever refactor this function back toward dict-based merging, you
   MUST re-verify the queue write still carries the merged data — re-run Part 3's E2E gate.
3. **Ordering matters**: the empty-`relationships` validation (`if not relationships: raise
   Exception(...)`) runs BEFORE the optional-fields merge — domain/subdomain/personal_domain/produces
   alone must never satisfy "you must declare something real" (is_a/part_of/instantiates). Do not move
   the merge above that check.
4. **`add_concept_tool_func`'s new params** (`domain`, `subdomain`, `personal_domain`, `produces`, all
   `Optional`, default `None`) are appended AFTER every pre-existing param — never reorder existing
   params, since this function is called positionally in places (`server_fastmcp.py`'s `add_concept`
   MCP tool calls it with `concept_name, description, relationships_dict` positionally, then everything
   else as kwargs). Appending-only is what makes this a zero-risk, purely additive change for every
   existing caller.

## Part 2 — What you must ALSO edit (the coherence edit-set — never edit one layer only)

1. **The unit tests move in lockstep.** `test_concept_provenance_optional_fields.py` hard-asserts: the
   all-None no-op case, non-mutation of the input list, correct relationship-type mapping for all four
   fields, the `PERSONAL_DOMAINS` enum-validation (both the raise-with-full-valid-list-in-the-message
   case and the accept-every-valid-value case), dedup against a value already present via the generic
   `relationships` list, and that an empty `produces` list is a no-op (not an error). Any change to the
   merge semantics (which relationship type a field maps to, the dedup rule, the validation) must update
   these tests in the same edit.
2. **The docstrings on `add_concept_tool_func` and `merge_optional_domain_fields` are the ONLY place
   internal callers (Dragonbones, sm_gate.py, etc.) will ever discover these fields exist** — per
   `every-build-ends-in-a-development-flow-skill` and `state-what-is-vs-vision-never-encode-certainty`,
   keep them accurate: OPTIONAL here (unlike the MCP tool's REQUIRED), why (breaking ~8 existing callers
   is out of scope until each is individually audited), and that `personal_domain` is still enum-checked
   even though its presence is optional.
3. **DEPLOY (the running processes are the INSTALLED package, NOT the source).** After editing:
   `pip install --no-deps /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp` (per
   `pip-install-our-packages-no-deps`; NEVER `--force-reinstall`), then `reconnect_mcp carton` if the
   MCP tool's own behavior is affected (it isn't, by construction — `server_fastmcp.py`'s `add_concept`
   never passes these new kwargs, since it already folds them into `relationships_dict` itself before
   calling `add_concept_tool_func`), and confirm the standing `observation_worker_daemon` picks up the
   change on its NEXT queue-processing cycle (no daemon code changed, so no daemon restart is required
   for this specific edit — only the pip install, since the daemon imports `add_concept_tool_func`
   fresh per subprocess/module call, not a long-lived cached reference to the old bytecode... verify
   this assumption holds if you ever see stale behavior after a pip install; if so, restart the daemon
   per `skill-carton-daemon-restart`).

## Part 3 — How you test it (the E2E gate — unit tests passing is NOT sufficient alone)

**Unit gate (necessary, NOT sufficient):** `pip install --no-deps <repo>` then
`python3 test_concept_provenance_optional_fields.py` — 7 pure assertions on
`merge_optional_domain_fields` (backward-compat no-op, non-mutation, correct relationship-type mapping,
enum validation both directions, dedup, empty-list no-op).

**The REAL E2E gate — through the actual live surface (proven 2026-07-04, this build's own
verification run, TWICE — the first run caught the dict-vs-list bug in item 2 above):**
1. Call `add_concept_tool_func` DIRECTLY (not the MCP tool — the whole point is internal callers that
   bypass it) with a real `is_a`/`part_of` plus `domain=`, `subdomain=`, `personal_domain=`, `produces=`.
2. Wait for the daemon's queue-processing cycle (poll `query_wiki_graph`, typically single-digit
   seconds; confirm via `/tmp/carton_worker.log` that the batch containing your concept name shows
   `[Worker] Batch done`).
3. `query_wiki_graph` and confirm ALL FOUR relationship types actually landed:
   `HAS_DOMAIN`/`HAS_SUBDOMAIN`/`HAS_PERSONAL_DOMAIN`/`PRODUCES` edges to the exact values passed,
   alongside the caller's own `is_a`/`part_of` edges (proven 2026-07-04:
   `Test_Optional_Domain_Fields_E2E_20260704_V2` — all four edges confirmed live, `has_personal_domain`
   normalized to `Cave` title-case per CartON's naming convention).
4. **Backward-compat proof (never skip):** call `add_concept_tool_func` the OLD way — zero
   domain/subdomain/personal_domain/produces kwargs, exactly as every existing bypass caller calls it
   today — and confirm it succeeds identically to before this change (proven 2026-07-04:
   `Test_Backward_Compat_No_Optional_Fields_20260704` — succeeded with no new relationships, no error,
   no behavior change).

A green unit-test run or a correct-looking `[D2: ...]` coverage message is NOT the gate on its own —
only a live `query_wiki_graph` confirming the actual graph edges proves the fields reached the graph
(this is exactly the check that caught the dict-vs-list bug; the unit tests and the D2 message both
looked fine while the fields silently never persisted).

## Status

**IS — built + live-E2E-verified 2026-07-04** (unit tests 7/7 green; two live E2E runs against the real
neo4j graph — the first surfaced a real bug: merging into `relationship_dict` alone validates correctly
via SOMA/D2 but never reaches the graph, since the queue write persists the ORIGINAL `relationships`
list, not the derived dict; fixed by reassigning `relationships` itself before `relationship_dict` is
built; the second run confirmed all four relationship types land correctly, backward-compat for
zero-kwarg old-style calls confirmed). **Still OPEN, unchanged from `Concept_Provenance_Enforcement_Gap`
(task 58)**: this fix gives every internal caller the ABILITY to pass these fields correctly — it does
NOT migrate any of the ~8 existing bypass call sites (Dragonbones, sm_gate.py, split_content_concept,
the migration scripts) to actually pass them. That migration is separate, future work, per Isaac's
explicit framing that a full audit-and-fix pass across all of them is out of scope for now.

## Cross-refs (canonical)

`Concept_Provenance_Enforcement_Gap` (the CartON concept naming the full ~8-site audit this fix
partially addresses — read it yourself, this skill only restates the relevant slice);
`carton-concept-enforcement` vision doc; `dev-flow-split-content` /
`editing-webbing-agent-uses-the-dev-flow` (the same repo's sibling dev-flow precedents, same
onion/coherence-edit-set/E2E-gate shape); `every-build-ends-in-a-development-flow-skill`;
`pip-install-our-packages-no-deps`; `verify-via-user-surface-before-done` (why a green unit test or a
plausible-looking validation message is never the gate on its own).

(Knowledge/dev-flow skill — no subagent dispatch, so no RELIABILITY block.)
