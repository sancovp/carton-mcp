# doc(m): test_gnosys_status_probe.py

**Module:** `carton-mcp/test_gnosys_status_probe.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Status_Probe — feature boundary (no Giint_Feature node declared)

- **user action:** an operator or the agent runs gnosys_status_probe.py to ask whether every GNOSYS subsystem is actually up right now, rather than reading a status stamp somebody typed
- **doc(v):** `knowledge/carton-mcp/docs/vision/_status-probe.md`
- **outputs to:** `tool_dispatch_loop`
- **sealed:** v2, key `fe663892d8c33fc2`, commit `4b8fdced2`, valid from 2026-09-26T22:09:10
- **ranges in this module** (layer order):
  - `L4 proof` · `test_gnosys_status_probe.py:1-113` — the nine markers pinning that a timeout is not a diagnosis
- **also passes through:** `gnosys_status_probe.py`, `doc-mirror-system/plugin/skills/check-system-status/SKILL.md`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
