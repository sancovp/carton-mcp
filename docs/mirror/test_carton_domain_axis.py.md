# doc(m): test_carton_domain_axis.py

**Module:** `carton-mcp/test_carton_domain_axis.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Domain_Axis_Front_Door — feature boundary of `Giint_Feature_Domain_Axis_Front_Door`

- **user action:** a writer calls add_concept naming a domain or subdomain that is not yet a domain node and supplies domain_about, domain_part_of or subdomain_about, and that node must be written first as is_a Domain with has_about and part_of its parent, while a write without them lands as said and SOMA grades the node against that same subject
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['carton_queue_ingest']`
- **sealed:** v2, key `5d3dfdafe92d8173`, commit `b80684b69`, valid from 2026-10-01T07:39:37
- **ranges in this module** (layer order):
  - `L4 proofs` · `test_carton_domain_axis.py:1-146` — the carton suite, 8 of 8: the plan, the unused-param notes, the landing reading once, and add_concept_tool_func with SOMA, breaker, graph and queue faked queuing the new subdomain first with has_about and part_of, and writing as said with no read when no param is given
- **also passes through:** `server_fastmcp.py`, `add_concept_tool.py`, `carton_domain_axis.py`, `base/soma-prolog/soma_prolog/util_deps/prolog_interop.py`, `base/soma-prolog/tests/test_domain_slot_targets_are_domains.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
