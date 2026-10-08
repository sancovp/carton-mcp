# doc(m): carton_bounded_walk.py

**Module:** `carton-mcp/carton_bounded_walk.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Bounded_Collection_Walk — feature boundary of `Giint_Feature_Bounded_Collection_Walk`

- **user action:** the agent calls the carton activate_collection MCP tool on a collection and must receive its members without any hub member importing its whole subtree, every stop reported ahead of the members
- **doc(v):** `knowledge/carton-mcp/docs/vision_extracted/activate_collection.md`
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v2, key `256db61ccf68e43e`, commit `21bee0c41`, valid from 2026-09-29T21:18:29
- **ranges in this module** (layer order):
  - `L2 walk` · `carton_bounded_walk.py:1-49` — THE RULINGS of issue 203 carried at the top of the pure module: one Cypher execution, the boundary is the type list UNION the hub cap, the cap applies only to UNTYPED members so a typed conversation ladder stays whole, include-but-do-not-descend, no silent caps, and the report leads the payload because the MCP formatter truncates at 10k
  - `L2 walk` · `carton_bounded_walk.py:50-76` — THE BOUNDARY LIST AND THE KNOBS: DEFAULT_BOUNDARY_TYPES mirrors the docmirror-collect read-side list, and carton_disclose imports it as the ladder of LEVELS, so a change here changes both. Also the default depth 1, only the concepts IN the collection (Isaac 2026-09-29), the hub cap 30, the fixed probe depth 4, the depth ceiling 100, and the legacy missing-description marker
  - `L2 walk` · `carton_bounded_walk.py:79-138` — build_walk_plan: validates max_depth as a bounded int because it is the ONE interpolated value, then builds the single Cypher that prunes paths whose INTERMEDIATE nodes are a boundary, so a boundary member still arrives as a leaf. The collection name, the type list and the cap ride as parameters
  - `L2 walk` · `carton_bounded_walk.py:141-215` — classify_rows: dedupes duplicate member rows keeping the minimum depth, substitutes the legacy missing-description marker, and records WHY each stopped member stopped with the precedence boundary_type over hub_cap over depth
  - `L2 walk` · `carton_bounded_walk.py:218-241` — build_stop_report: the compact truncation line, None when nothing stopped so the formatter drops it, and its own inline elision past 40 entries is itself reported
  - `L2 walk` · `carton_bounded_walk.py:244-290` — build_activation_result: the return dict with truncation_report and stopped inserted BEFORE concepts, and the empty-collection legacy shape. The tool returns it through the formatter, which is where the walk leaves as text to the agent  ⟵ RELEASE
- **also passes through:** `server_fastmcp.py`, `carton_utils.py`, `test_carton_bounded_walk.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
