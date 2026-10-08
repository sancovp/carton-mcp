# doc(m): test_property_trail_soma_off.py

**Module:** `carton-mcp/test_property_trail_soma_off.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Carton_Queue_Ingest — feature boundary (no Giint_Feature node declared)

- **user action:** a concept is written through the CartON front door, add_concept_tool_func, which POSTs it to SOMA and queues the graded node, and the observation worker must land that node in the graph and act on the verdict the payload carries
- **doc(v):** `knowledge/carton-mcp/docs/vision_extracted/add_concept.md`
- **outputs to:** `['dead_letter_lane_fires']`
- **sealed:** v5, key `d87661e7eb26a97b`, commit `37335213d`, valid from 2026-10-08T00:07:14
- **ranges in this module** (layer order):
  - `L2 write` · `test_property_trail_soma_off.py:1-184` — the crown, card 858: the switch reads off; off, a property write on an ontology node queries nothing, POSTs nothing and says soma-off; switched on it POSTs once within 10 s; set_properties reports soma-off; the drain lands a concept and its properties with no SOMA POST and no trail warning
- **also passes through:** `add_concept_tool.py`, `observation_worker_daemon.py`, `carton_utils.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
