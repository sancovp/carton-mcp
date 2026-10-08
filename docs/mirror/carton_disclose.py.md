# doc(m): carton_disclose.py

**Module:** `carton-mcp/carton_disclose.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Progressive_Disclosure — feature boundary (no Giint_Feature node declared)

- **user action:** the agent asks carton what the LEVELS of the graph are, or names one level and asks for its members, instead of writing freehand Cypher to navigate
- **doc(v):** `knowledge/carton-mcp/docs/vision/_progressively_disclose.md`
- **outputs to:** `tool_dispatch_loop`
- **sealed:** v4, key `f6d1644592f54ba3`, commit `28670f88e`, valid from 2026-09-29T12:56:44
- **ranges in this module** (layer order):
  - `L0 ladder` · `carton_disclose.py:36-53` — THE LADDER, and the one reason this module is safe: LEVELS is derived from carton_bounded_walk.DEFAULT_BOUNDARY_TYPES by import, never restated. That module's law is that a member whose direct IS_A hits one of the eight is a boundary, included as a leaf and never descended, which is carton declaring in code which nodes are LEVELS. A hand copy of eight names here is the issue-617 faithful-transcriber defect, so if the ladder changes there it changes here with nothing to keep in step. Also the member limit and the description slice, the slice deliberately wider than the rendered summary so the word-boundary clip has slack
  - `L1 gate` · `carton_disclose.py:56-73` — THE GATE: normalize_level resolves case, dashes and spaces onto one of LEVELS and RAISES ValueError naming the legal set on anything else. Loud on garbage is this package's own stated law in the breaker, the quota and the pathguard, and it matters more here than usual: a navigation surface that silently returns nothing for a typo is indistinguishable from a level that is genuinely empty
  - `L1 gate` · `carton_disclose.py:116-141` — THE STORE GUARD: rows_or_raise unwraps the query envelope or RAISES DiscloseStoreError, and it never returns an empty list for a FAILED query. That distinction is the whole reason it exists - on this surface an empty list renders as all eight levels at zero, which reads as THE GRAPH HAS NO LEVELS when the truth is THE STORE DID NOT ANSWER. It is the same fail-open this package already refused in the quota gate, whose rule states it directly: a meter that cannot count must never fail open into unlimited. An unrecognised envelope raises too, because a shape nobody planned for is not evidence of an empty graph either
  - `L2 plans` · `carton_disclose.py:76-87` — build_levels_plan: the ONE Cypher counting members per level, with the ladder riding as a parameter. OPTIONAL MATCH, not MATCH, so a declared level with zero members renders as 0 instead of vanishing - this level exists and is empty and this level does not exist are different facts, and a diagram that cannot tell them apart is the filtered-view-omission defect built into a tool
  - `L2 plans` · `carton_disclose.py:90-113` — build_level_plan: the ONE Cypher listing members at a chosen level. The level is resolved through the gate FIRST so an unknown level raises before any query text is built rather than producing a query that returns nothing; limit is validated as an int in 1 to 500 and rides as a parameter, never interpolated
  - `L3 render` · `carton_disclose.py:144-150` — _clip: cuts a summary to SUMMARY_CHARS on a WORD boundary with an ellipsis, which is why the query asks for a wider slice than it renders. Issue 576 is a chronology intent line sliced at 160 chars mid-word; this surface cannot do that
  - `L3 render` · `carton_disclose.py:185-210` — render_members: the members at one chosen level, summaries clipped on a word boundary. Two honesty rules live here - a full page ANNOUNCES that it stopped at the limit, because a truncated list that does not say so reads as a complete one; and zero members renders as an EMPTY level explicitly, never as a missing one, because the level is one of the eight declared axis types
  - `L3 render` · `carton_disclose.py:153-182` — render_diagram builds the diagram of the graph's categories and levels - the no-level default mode. It renders in LEVELS order rather than row order so the ladder reads identically every time, renders a level missing from the rows as 0 rather than skipping it, carries the total, and tells the reader how to descend. It is no longer the RELEASE: at v2 the effect leaves through the MCP tool, and this returns the text to it
- **also passes through:** `test_carton_disclose.py`, `server_fastmcp.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
