# doc(m): carton_merged_labels.py

**Module:** `carton-mcp/carton_merged_labels.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Merged_Label_Redirect — feature boundary of `Giint_Feature_Merged_Label_Redirect`

- **user action:** any writer calls add_concept naming a label that was merged into another, as the concept or as a relationship target, and the write must land on the label it was merged into instead of re-minting the merged label as an auto stub
- **doc(v):** `knowledge/carton-mcp/docs/vision_extracted/add_concept.md`
- **outputs to:** `['carton_queue_ingest']`
- **sealed:** v2, key `2fe6170cc49f6898`, commit `eabb1cd06`, valid from 2026-09-29T11:55:03
- **ranges in this module** (layer order):
  - `L1 redirect` · `carton_merged_labels.py:1-13` — the rule and the cache: a merged label no longer exists, the right label records it in merged_from, and the map is cached for 60 seconds
  - `L1 redirect` · `carton_merged_labels.py:16-48` — redirect_merged, PURE: replaces each merged label with its right label as the concept name and as every relationship target, a plain name or a value dict, matching as passed and as the writer normalizer writes it, never mutating the caller list, and lists the redirects applied
  - `L1 redirect` · `carton_merged_labels.py:96-113` — merged_label_map: ONE read of merged_from over every label that recorded a merge, lowercased left to right label, cached MAP_TTL_S; a failed read answers the last map read, or None when none has been read, so the front door writes unredirected rather than failing the write while the webbing guard refuses on None
  - `L1 redirect` · `carton_merged_labels.py:51-93` — confine_hwss_domain, PURE: HWSS_ROOTS names Health, Wealth, Social and Spiritual; a write whose concept is not one of them and says is_a Hwss_Domain, a plain name or a value dict in any spelling, says is_a Domain instead, deduplicated, only on is_a and never on another relationship, never mutating the caller list - Isaac 2026-09-29: ONLY FOUR NODES CAN BE ISA HWSS_DOMAIN
- **also passes through:** `add_concept_tool.py`, `test_carton_merged_labels.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
