# doc(m): test_carton_write_batch.py

**Module:** `carton-mcp/test_carton_write_batch.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Carton_Write_Batch — feature boundary (no Giint_Feature node declared)

- **user action:** a doc-mirror CLI or any carton caller must apply SEVERAL graph write statements as ONE unit - a lane change with its reason and its edge replacement, a card mint with its type and session edges - and carton had no shape for it: the read facade refuses every write verb and the store exposes only one-statement auto-commit execute
- **doc(v):** `docs/vision/_carton_write_facade.md`
- **outputs to:** `doc_mirror_kanban`
- **sealed:** v2, key `a41638932df798d4`, commit `e341218ee`, valid from 2026-09-10T05:21:06
- **ranges in this module** (layer order):
  - `L3 prove` · `test_carton_write_batch.py:1-309` — the PROOF, run as a script from the carton-mcp root which IS the carton_mcp package, on SYNTHETIC FAKES only so the thing it gates can run it: a fake transaction recording every statement and whether it committed or rolled back, a driver-bearing connection and a driverless one. The two markers that matter most are M7, a failing batch ROLLS BACK and the later statements never run, and M8, an unreachable store raises WriteStoreUnavailable rather than returning an empty result - the two guarantees a careless conversion silently loses
- **also passes through:** `carton_write_batch.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
