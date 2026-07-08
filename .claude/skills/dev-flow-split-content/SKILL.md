---
name: dev-flow-split-content
description: "WHAT: the development-flow for the split-content capability — separating a concept whose description (n.d) holds raw CONTENT (a data dump / pasted document) from a real DESCRIPTION, by splitting the raw content into its own `{concept_name}_Desc_Content` node. Covers `carton_split_content.py` (both `build_split_spec`, the pure spec function, and `split_content_concept`, the thin neo4j-writing wrapper — self-contained, ONE module, per the one-capability-one-module law), the `Desc_Content` universal type, the `has_desc_content` relationship, and the `split_content_concept` MCP tool. WHEN: when editing `carton_split_content.py`, `split_content_concept`, the `Desc_Content` type, or the `has_desc_content` relationship; or adding a new capability that also needs the content-vs-description split (any of)."
---

# dev-flow-split-content — dev-flow for the CartON content/description split capability

> Split-content = separating a concept's description (`n.d`) into what it SHOULD be — annotation that
> traces relationships (per `carton-description-is-annotation-not-knowledge`) — from what a caller
> often actually puts there: raw CONTENT (a pasted document, a data dump, verbatim info). The capability
> computes + performs that split: the raw content moves VERBATIM into its own
> `{concept_name}_Desc_Content` node, related back via `has_desc_content`. It does NOT rewrite the
> original concept's own description, and it does NOT atomize the split-off content further — both are
> separate, judgment-driven steps for a caller/coherer agent to do afterward (Isaac's explicit 2026-07-03
> decision — do not build atomization-timing logic into this capability).
>
> Canonical source (monorepo ONLY — never `/home/GOD/carton_mcp`, never site-packages, never
> `/home/GOD/core`): `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/`. Read the whole file FULLY before
> editing (line refs below are grounded against the current code on read; re-verify — code drifts).

## Part 1 — How you edit (the ONION, but ONE self-contained module — this repo's own precedent)

Verified in code, 2026-07-03: this repo's own established layout is ONE capability = ONE dedicated library
module. `carton_kv.py` is self-contained and backs `edit_carton_obj`/`validate_carton_obj` directly;
`add_concept_tool.py` is self-contained and backs `add_concept` only; neither file imports the other;
`server_fastmcp.py` imports each directly. This is a carton-mcp-specific precedent, not a universal
MCP-architecture rule (there is no such global law — checked `understand-mcp-architecture`/`make-mcp` and
their reference docs, 2026-07-03: they cover generic FastMCP-vs-SDK and 8 abstract composition patterns,
none of which state a one-module-per-capability convention). `split_content_concept` follows this repo's
own precedent: its own capability, never routed through `add_concept_tool.py` (the backing library for the
`add_concept` tool ONLY) — exactly like `edit_carton_obj`/`validate_carton_obj` are backed by their own
`carton_kv.py`, even though both eventually call `add_concept`-style writes.

- **`carton_split_content.py`** — BOTH onion layers, together, in this ONE file:
  - `build_split_spec(concept_name, raw_content)` — the PURE core (stdlib only, no neo4j/no MCP/no I/O,
    unit-testable standalone). Computes `{content_node_name, content_node_is_a, content_node_part_of,
    relationship_name, content_node_description}`. `content_node_description` is `raw_content` passed
    through BYTE-IDENTICAL — never truncate/modify it here.
  - `_desc_content_type_exists(shared_connection)` — a thin one-query existence check (does a `Desc_Content`
    node already exist?). Note the caveat under Part 2 item 3 (an unrelated auto-created stub already
    satisfies this check).
  - `split_content_concept(concept_name, raw_content, shared_connection=None)` — the THIN neo4j-writing
    wrapper. Reuses `add_concept_tool_func` (`add_concept_tool.py`, the existing internal concept-creation
    entrypoint) — imports it, never duplicates its queueing/SOMA/daemon logic.
- **`server_fastmcp.py`** — the MCP tool `split_content_concept` (thin: one call to
  `_split_content_concept_lib`, imported at module top as
  `from .carton_split_content import split_content_concept as _split_content_concept_lib`).
- **`add_concept_tool.py`** — NOT edited for this capability. It is read-only here, for exactly one
  reason: to find and reuse `add_concept_tool_func` (the internal concept-creation entrypoint every other
  internal caller in that file also reuses — `update_concept_history`, `link_observation_to_timeline`,
  `_add_observation_worker` all call it directly, so this is the established internal reuse pattern, not
  a new one).

## Part 2 — What you must ALSO edit (the coherence edit-set)

1. **ONION DISCIPLINE, in ONE file.** A change to the split spec (new fields, a new relationship, a
   renamed universal type) starts in `build_split_spec` + its unit test (`test_split_content.py`) FIRST;
   only then update `split_content_concept` to consume the new spec shape. Never let `split_content_concept`
   diverge from what `build_split_spec` actually returns.

2. **THE REUSED ENTRYPOINT (`add_concept_tool_func`).** `split_content_concept` makes exactly THREE calls
   to it, in order: (a) create the universal `Desc_Content` type ONLY if `_desc_content_type_exists`
   returns False; (b) create `{concept_name}_Desc_Content` with `is_a=[Desc_Content]`,
   `part_of=[concept_name]`, `description=raw_content`; (c) add the relationship
   `concept_name -[has_desc_content]-> {concept_name}_Desc_Content` on the ORIGINAL concept, passing
   `description=None` DELIBERATELY. If `add_concept_tool.add_concept_tool_func`'s signature or its
   `description or ""` normalization ever changes, re-verify step (c) still leaves the original concept's
   `n.d` untouched (see item 4 below — this is the load-bearing mechanism, not incidental).

3. **THE `Desc_Content` EXISTENCE-CHECK CAVEAT (read before assuming "it exists" means "it's defined").**
   `_desc_content_type_exists` is a bare existence check (`MATCH (c:Wiki {n:'Desc_Content'}) ...`) — it
   does NOT check whether the node has a real description. CartON auto-creates SOUP stub nodes for ANY
   relationship target that doesn't yet exist (`observation_worker_daemon.py`'s relationship MERGE,
   `ON CREATE SET target.d = 'AUTO CREATED: stub node...'`), so `Desc_Content` can already exist as an
   under-defined stub from completely unrelated usage (verified live 2026-07-03: a `Desc_Content` node
   already existed from an unrelated `MENTIONS_CONCEPT` reference dated 2026-04-26, with description
   `"AUTO CREATED: stub node ... Not yet fully defined."` — so this capability's own proper description
   for `Desc_Content` was never written, because the existence check correctly found the stub and skipped
   creation per its "check first, don't duplicate" spec). This matches the brief's literal instruction
   (existence-check, not quality-check) but is a real, observed limitation — if `Desc_Content` ever needs
   a guaranteed GOOD description (not just existence), change the check to also test for a non-stub
   description, or upgrade an existing stub in place.

4. **THE EMPTY-DESCRIPTION-LEAVES-`n.d`-UNCHANGED MECHANISM (load-bearing, verify on any daemon change).**
   Step (c) above passes `description=None` for the ORIGINAL concept. `add_concept_tool_func` normalizes
   this to `description=""` before queueing (`_caller_raw_description = description or ""`). The daemon's
   `batch_create_concepts_neo4j` UNWIND write (`observation_worker_daemon.py`, the `SET n.d = CASE ... END`)
   hits the branch `WHEN n.d CONTAINS c.description THEN n.d` — an empty string is contained in EVERY
   string, so an existing non-empty `n.d` is left UNCHANGED. This is HOW `split_content_concept` satisfies
   "does not touch the original concept's description" without any special no-op mode added to
   `add_concept_tool_func`. If that daemon CASE logic is ever refactored, re-verify this branch order still
   holds (it must be checked BEFORE the `update_mode == 'append'` branch, or an empty-string append would
   instead concatenate `'\n\n---\n\n'` onto the existing description).

5. **DEPLOY (the running code is the INSTALLED package, NOT the source).** After editing the source:
   `pip install --no-deps /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp` (per
   `pip-install-our-packages-no-deps`; NEVER `--force-reinstall`). Then `reconnect_mcp carton` (per
   `mcp-reconnect-is-user-only` — never `pkill` an MCP). This capability does not touch the daemon's own
   source file, so no daemon restart is needed UNLESS you change `observation_worker_daemon.py` itself
   (e.g. investigating item 4's CASE logic) — then follow `edit-carton-kv`'s daemon-restart steps.

## Part 3 — How you test it (the ONLY valid E2E gate — "the lib test passed" is NOT the gate)

**Lib gate (necessary, NOT sufficient):** `python3 test_split_content.py` (from the repo dir; imports the
INSTALLED package, so pip-install first) — 6 pure assertions on `build_split_spec`: name derivation,
`is_a`/`part_of`, the relationship name, byte-identical content passthrough (including a `<CartonObj>`
fence + unicode), non-mutation of the input string, and empty-content preserved as empty (not defaulted).

**The REAL E2E gate — through the actual MCP tool surface (after pip-install + `reconnect_mcp carton`):**
1. `add_concept` a test concept whose description is deliberately raw CONTENT (not a real description).
2. Call the `split_content_concept` MCP tool with that same concept name + its exact current `n.d` as
   `raw_content`.
3. Wait for the daemon queue to drain (this is async — the tool returns a queued confirmation, not a
   synchronous result; see `dragonbones-compiles-after-turn`-style async carton semantics).
4. `query_wiki_graph` and confirm ALL THREE, byte-for-byte:
   - `{concept_name}_Desc_Content` exists with `c.d` EXACTLY equal to the original raw content (no
     truncation, no modification — string-compare, don't eyeball it).
   - The edge `{concept_name} -[HAS_DESC_CONTENT]-> {concept_name}_Desc_Content` exists (and the content
     node carries `IS_A Desc_Content` + `PART_OF {concept_name}`).
   - `{concept_name}`'s OWN `c.d` is EXACTLY unchanged from before the call (string-compare against a
     value captured BEFORE step 2 — this is the one most likely to silently regress if item 4 above ever
     breaks).

A `"✅ queued..."` string from the tool is NOT the gate — it only proves the write was accepted into the
queue, not that the daemon applied it correctly. The raw `n.d` compares (byte-for-byte, before vs. after)
are the gate.

## The invariant

`split_content_concept` is a SELF-CONTAINED capability in its own module (`carton_split_content.py`),
reusing `add_concept_tool.add_concept_tool_func` for all neo4j writes rather than duplicating it, and
relying on that function's `description=None → ""` normalization plus the daemon's
`n.d CONTAINS "" → unchanged` CASE branch to leave the original concept's description untouched. Never
route this capability through `add_concept_tool.py` itself, never skip the `Desc_Content` existence check
(even though it currently only proves existence, not quality — see item 3), and always verify the E2E gate
with real byte-for-byte compares, not eyeballed query output.

(Knowledge/dev-flow skill — no subagent dispatch, so no RELIABILITY block.)
