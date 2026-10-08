# doc(m): gnosys_status_probe.py

**Module:** `carton-mcp/gnosys_status_probe.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Status_Probe — feature boundary (no Giint_Feature node declared)

- **user action:** an operator or the agent runs gnosys_status_probe.py to ask whether every GNOSYS subsystem is actually up right now, rather than reading a status stamp somebody typed
- **doc(v):** `knowledge/carton-mcp/docs/vision/_status-probe.md`
- **outputs to:** `tool_dispatch_loop`
- **sealed:** v2, key `fe663892d8c33fc2`, commit `4b8fdced2`, valid from 2026-09-26T22:09:10
- **ranges in this module** (layer order):
  - `L0 transport` · `gnosys_status_probe.py:41-91` — the three transport helpers and the SOMA event budget, each keeping the failure reason rather than discarding it
  - `L1 checks` · `gnosys_status_probe.py:93-173` — the six real checks, each contacting a real surface, check_soma carrying the port-then-route three outcomes
  - `L2 registry` · `gnosys_status_probe.py:175-197` — CHECKS and UNPROBED, disjoint by construction so a check the probe cannot perform can never acquire a measured value
  - `L3 release` · `gnosys_status_probe.py:199-249` — probe, write_back onto Gnosys_System, and main where print-only is the default and the write is opt-in  ⟵ RELEASE
- **also passes through:** `test_gnosys_status_probe.py`, `doc-mirror-system/plugin/skills/check-system-status/SKILL.md`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
