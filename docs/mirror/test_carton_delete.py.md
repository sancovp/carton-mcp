# doc(m): test_carton_delete.py

**Module:** `carton-mcp/test_carton_delete.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Carton_Concept_Delete — feature boundary of `Giint_Feature_Carton_Mcp_Carton_Concept_Delete`

- **user action:** an operator runs python3 -m carton_mcp.carton_delete with concept names or a names file and a backup dir, dry first, to delete concepts carton stored by mistake: every named node is backed up whole with its wiki directory, a node cited from outside the batch along an edge it does not point back along is refused, then the node, its edges and its wiki directory are removed (card 816, issue 1301)
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v2, key `bdbb5a73dbb481e4`, commit `e6d1721fa`, valid from 2026-10-08T04:07:34
- **ranges in this module** (layer order):
  - `L4 proof` · `test_carton_delete.py:1-151` — crown: python3 test_carton_delete.py from the repo root, 6 markers on synthetic records and a fake runner
- **also passes through:** `carton_delete.py`, `carton_write_batch.py`, `carton_pathguard.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
