# doc(m): carton_domain_axis.py

**Module:** `carton-mcp/carton_domain_axis.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Domain_Axis_Front_Door — feature boundary of `Giint_Feature_Domain_Axis_Front_Door`

- **user action:** a writer calls add_concept naming a domain or subdomain that is not yet a domain node and supplies domain_about, domain_part_of or subdomain_about, and that node must be written first as is_a Domain with has_about and part_of its parent, while a write without them lands as said and SOMA grades the node against that same subject
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['carton_queue_ingest']`
- **sealed:** v2, key `5d3dfdafe92d8173`, commit `b80684b69`, valid from 2026-10-01T07:39:37
- **ranges in this module** (layer order):
  - `L2 landing` · `carton_domain_axis.py:1-138` — the module: axis_targets reads the has_domain and has_subdomain names; plan_domain_axis, PURE, plans one new domain with domain_about under domain_part_of and one new subdomain with subdomain_about under the write domains, and notes a param that lands nothing, never a refusal, Isaac 2026-09-29: IT FUCKING INGESTS EVERYTHING; domain_axis_relationships; land_domain_axis reads the domain nodes once and only when a param is supplied, a failed read noted and nothing written first; domain_node_reader answers is_a Domain or Hwss_Domain
- **also passes through:** `server_fastmcp.py`, `add_concept_tool.py`, `base/soma-prolog/soma_prolog/util_deps/prolog_interop.py`, `test_carton_domain_axis.py`, `base/soma-prolog/tests/test_domain_slot_targets_are_domains.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
