# doc(m): .claude/skills/soma-help/SKILL.md

**Module:** `carton-mcp/.claude/skills/soma-help/SKILL.md`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Carton_Soma_Verdict_Relay — feature boundary of `Carton_Soma_Verdict_Relay`

- **user action:** the agent calls the carton add_concept or get_concept MCP tool and must read, in the result it gets back, what SOMA graded and, last, the exact fill or drop SOMA asks of it, plus one line pointing at the soma-help skill and every CRITICAL line of the verdict
- **doc(v):** `knowledge/carton-mcp/docs/vision/add_concept_tool.py.md`
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v15, key `60e8dc465f987672`, commit `b80684b69`, valid from 2026-10-01T07:39:39
- **ranges in this module** (layer order):
  - `L5 help` · `.claude/skills/soma-help/SKILL.md:1-103` — the soma-help skill every SOMA-graded result points at once: what each result line and DO line means and what to do, MEREO and SOUP read as not validly the type and failed execution (Isaac 2026-09-29), every fill DO line meaning fill next only if it is inside the meaning you meant, the get_concept details fields, and the routing table to the nine SOMA and CartON skills; linked into ~/.claude/skills and /tmp/heaven_data/skills
- **also passes through:** `server_fastmcp.py`, `add_concept_tool.py`, `base/soma-prolog/soma_prolog/core.py`, `test_soma_critical_relay.py`, `test_cb_failure_note.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
