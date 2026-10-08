# doc(m): test_soma_critical_relay.py

**Module:** `carton-mcp/test_soma_critical_relay.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Carton_Soma_Verdict_Relay — feature boundary of `Carton_Soma_Verdict_Relay`

- **user action:** the agent calls the carton add_concept or get_concept MCP tool and must read, in the result it gets back, what SOMA graded and, last, the exact fill or drop SOMA asks of it, plus one line pointing at the soma-help skill and every CRITICAL line of the verdict
- **doc(v):** `knowledge/carton-mcp/docs/vision/add_concept_tool.py.md`
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v16, key `396a342c4030b2cf`, commit `507f1ce96`, valid from 2026-10-08T06:09:44
- **ranges in this module** (layer order):
  - `L4 prove` · `test_soma_critical_relay.py:1-266` — the relay suite, run as a script, ALL 14 PASS: CRITICAL relay, the first-line pointer, CODE and SYSTEM_TYPE with the d-chain count, MEREO and SOUP lines saying not validly the type it claims and its execution failed, SOUP with every gap (the gaps carry the clause SOMA appends) and one collapsed line per type, FILL, every DO line saying the part is important to fill next only if it is inside the meaning meant, D2 in both cases, CB region, coordinate and PROMPTER block, the SOMA error, the saved, rejected and MCP order (line 1, note, DEATH, information, help, DO last), one help line per verdict and none without SOMA, and get_concept default without the event name and d-chain counts and details with them
- **also passes through:** `server_fastmcp.py`, `add_concept_tool.py`, `base/soma-prolog/soma_prolog/core.py`, `test_cb_failure_note.py`, `.claude/skills/soma-help/SKILL.md`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
