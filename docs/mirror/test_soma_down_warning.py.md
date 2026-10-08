# doc(m): test_soma_down_warning.py

**Module:** `carton-mcp/test_soma_down_warning.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Soma_Down_Warning — feature boundary of `Soma_Down_Warning`

- **user action:** any carton process imports carton_mcp.add_concept_tool while SOMA refuses the connection, and the line it logs must tell the reader the one sanctioned restart, whether to run it now, and how to confirm SOMA is back
- **doc(v):** `docs/vision/add_concept_tool.py.md`
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v5, key `0327c5474677d5de`, commit `b80684b69`, valid from 2026-10-01T07:39:38
- **ranges in this module** (layer order):
  - `L3 prove` · `test_soma_down_warning.py:1-81` — the proof, run as a script with SOMA_URL at a dead port so nothing reaches the production daemon: the three pure texts, the argv port parse including the bash wrapper, the dead-port scan finding no process, and the REAL import path, a subprocess importing the module whose stderr must carry the restart and sophia-status and must not carry the bare start; that case also imports the INSTALLED carton_mcp copy, so it fails until pip install lands the fix
- **also passes through:** `add_concept_tool.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
