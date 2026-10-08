# doc(m): test_carton_merged_labels.py

**Module:** `carton-mcp/test_carton_merged_labels.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Merged_Label_Redirect — feature boundary of `Giint_Feature_Merged_Label_Redirect`

- **user action:** any writer calls add_concept naming a label that was merged into another, as the concept or as a relationship target, and the write must land on the label it was merged into instead of re-minting the merged label as an auto stub
- **doc(v):** `knowledge/carton-mcp/docs/vision_extracted/add_concept.md`
- **outputs to:** `['carton_queue_ingest']`
- **sealed:** v2, key `2fe6170cc49f6898`, commit `eabb1cd06`, valid from 2026-09-29T11:55:03
- **ranges in this module** (layer order):
  - `L2 proofs` · `test_carton_merged_labels.py:1-147` — the suite, run as a script, ALL 6 PASS: the name and every target form redirected without mutating the input, unmerged and right labels untouched and a normalized spelling caught, the map read once per TTL with a failed read keeping the last map, add_concept_tool_func with SOMA, breaker, graph and queue faked queuing Giint_Task and Domain where the write named Task and Doc_Mirror_Domain; confine_hwss_domain turning a non-root is_a Hwss_Domain into is_a Domain in both target forms while the four roots keep it and part_of is untouched; and the front door queuing Domain for Skill_Development and Hwss_Domain for Wealth
- **also passes through:** `add_concept_tool.py`, `carton_merged_labels.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
