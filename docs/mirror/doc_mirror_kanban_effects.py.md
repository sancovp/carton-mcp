# doc(m): doc_mirror_kanban_effects.py

**Module:** `carton-mcp/doc_mirror_kanban_effects.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Doc_Mirror_Ratchet_Fires — AB boundary (no Giint_Feature node declared)

- **user action:** nobody runs anything - a card LEAVES the build lane for any reason, through any verb, and the next sequenced sprint must arrive in build without anyone asking for it. The agent involvement ended when it moved the card
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['ab_chain:absorber_loop']`
- **sealed:** v8, key `d6418c74ad9b4c01`, commit `f0fa71694`, valid from 2026-10-02T08:02:23
- **ranges in this module** (layer order):
  - `L2 release` · `doc_mirror_kanban_effects.py:1-109` — THE EFFECT BODY: the handler resolves the board from the transition through its card HAS_CARD edge, loads the board library by FILE LOCATION so a long-lived worker import namespace is never mutated, and calls ratchet. It NEVER RAISES - every failure is returned as a line and its traceback logged - because it runs inside the drain loop and must never be the thing that kills one
- **also passes through:** `base/soma-prolog/gnosys-vault/gnosys_vault/doc_mirror_task.py`, `observation_worker_daemon.py`, `test_doc_mirror_kanban_effects.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
