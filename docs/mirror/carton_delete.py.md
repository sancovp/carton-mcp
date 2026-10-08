# doc(m): carton_delete.py

**Module:** `carton-mcp/carton_delete.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Carton_Concept_Delete — feature boundary of `Giint_Feature_Carton_Mcp_Carton_Concept_Delete`

- **user action:** an operator runs python3 -m carton_mcp.carton_delete with concept names or a names file and a backup dir, dry first, to delete concepts carton stored by mistake: every named node is backed up whole with its wiki directory, a node cited from outside the batch along an edge it does not point back along is refused, then the node, its edges and its wiki directory are removed (card 816, issue 1301)
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v2, key `bdbb5a73dbb481e4`, commit `e6d1721fa`, valid from 2026-10-08T04:07:34
- **ranges in this module** (layer order):
  - `L0 cli_entry` · `carton_delete.py:102-131` — main: python3 -m carton_mcp.carton_delete NAMES or --names-file, --backup-dir, --dry-run; sets HEAVEN_ALLOW_STDOUT, binds execute_write_statements, wiki_root/concepts and check_write wiki as the guard, prints the report as JSON
  - `L0 cli_entry` · `carton_delete.py:1-22` — module header with Isaac ruling verbatim, READ_RECORDS reads each name with its properties and every edge both ways, DELETE_NODES detach-deletes the planned names, NOT_TOUCHED names the SOMA reflection and chroma index
  - `L1 pure_plan` · `carton_delete.py:25-57` — pure plan: a name no node holds is refused; a node cited by a node outside the batch along an edge it does not point back along is refused; recomputed until no refusal changes the batch
  - `L2 executor` · `carton_delete.py:60-99` — delete_concepts, the executor: read records, plan_deletion, return the report on a dry run or an empty plan, back up records.json and copy each wiki dir under a timestamped folder, guard each dir, run DELETE_NODES, then rmtree the wiki dirs and return the report with the backup folder and how many wiki dirs it removed  ⟵ RELEASE
- **also passes through:** `carton_write_batch.py`, `carton_pathguard.py`, `test_carton_delete.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
