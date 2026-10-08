# doc(m): webbing_agent_worker.py

**Module:** `carton-mcp/webbing_agent_worker.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Webbing_Agent — feature boundary (no Giint_Feature node declared)

- **user action:** the sophia daemon ensures the webbing worker at start, or an operator ticks it, and concepts the main agent left as unstructured prose get real graph structure added instead of staying as auto stubs
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['meta_sophia_audit']`
- **sealed:** v23, key `8714a1ec836b8ea4`, commit `eabb1cd06`, valid from 2026-09-29T11:56:10
- **ranges in this module** (layer order):
  - `L0 worker_cli` · `webbing_agent_worker.py:244-271` — the entry: the worker CLI dispatching daemon, catch-up, ensure, ensure-and-wait or status
  - `L1 tick_and_live_gate` · `webbing_agent_worker.py:202-218` — the PID-locked daemon loop, one catch_up_once per interval
  - `L1 tick_and_live_gate` · `webbing_agent_worker.py:147-183` — catch_up_once asks the agent how many are pending then runs DRY or LIVE
  - `L1 tick_and_live_gate` · `webbing_agent_worker.py:141-144` — the live gate: an absent live.flag file or env var means this daemon writes nothing at all
  - `L1 tick_and_live_gate` · `webbing_agent_worker.py:105-138` — _pending_concepts: the supervisor question, how many concepts are waiting. It is the ONE span of the worker the boundary never covered, which is why an edit here was refused while the rest of the file was editable. It asks webbing_agent for the count, and the whole lane died on HOW it asked: by subprocess, which is what carries a kill timer.
- **also passes through:** `webbing_agent.py`, `base/sdna/sdna/config.py`, `base/sdna/sdna/heaven_runner.py`, `add_concept_tool.py`, `webbing_write_guard.py`, `test_webbing_write_guard.py`, `test_webbing_agent.py`, `base/sdna/tests/test_heaven_runner_max_tool_calls.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
