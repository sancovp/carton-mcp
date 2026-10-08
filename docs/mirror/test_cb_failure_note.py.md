# doc(m): test_cb_failure_note.py

**Module:** `carton-mcp/test_cb_failure_note.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Carton_Soma_Verdict_Relay — feature boundary of `Carton_Soma_Verdict_Relay`

- **user action:** the agent calls the carton add_concept or get_concept MCP tool and must read, in the result it gets back, what SOMA graded and, last, the exact fill or drop SOMA asks of it, plus one line pointing at the soma-help skill and every CRITICAL line of the verdict
- **doc(v):** `knowledge/carton-mcp/docs/vision/add_concept_tool.py.md`
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v16, key `396a342c4030b2cf`, commit `507f1ce96`, valid from 2026-10-08T06:09:44
- **ranges in this module** (layer order):
  - `L4 prove` · `test_cb_failure_note.py:1-98` — card 767, run as a script, red first: three refused CB writes say CB store failed once, the pure note counts what it did not say and says it again after the window with the count, an unexpected failure is always said with its traceback, and a child process of the same answer stays quiet
- **also passes through:** `server_fastmcp.py`, `add_concept_tool.py`, `base/soma-prolog/soma_prolog/core.py`, `test_soma_critical_relay.py`, `.claude/skills/soma-help/SKILL.md`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
