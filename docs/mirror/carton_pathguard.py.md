# doc(m): carton_pathguard.py

**Module:** `carton-mcp/carton_pathguard.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Carton_Concept_Delete — feature boundary of `Giint_Feature_Carton_Mcp_Carton_Concept_Delete`

- **user action:** an operator runs python3 -m carton_mcp.carton_delete with concept names or a names file and a backup dir, dry first, to delete concepts carton stored by mistake: every named node is backed up whole with its wiki directory, a node cited from outside the batch along an edge it does not point back along is refused, then the node, its edges and its wiki directory are removed (card 816, issue 1301)
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v1, key `bdbb5a73dbb481e4`, commit `123382528`, valid from 2026-10-04T14:07:48
- **ranges in this module** (layer order):
  - `L3 carton_write_and_path` · `carton_pathguard.py:83-86` — wiki_root: HEAVEN_DATA_DIR/wiki, the concepts dir sits under it
  - `L3 carton_write_and_path` · `carton_pathguard.py:121-172` — check_write wiki mode: each wiki dir removed must sit under the wiki root and carry no garbage-path artifact
- **also passes through:** `carton_delete.py`, `carton_write_batch.py`, `test_carton_delete.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
