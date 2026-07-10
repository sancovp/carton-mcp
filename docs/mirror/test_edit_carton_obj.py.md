# doc(m): test_edit_carton_obj.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_edit_carton_obj.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

The lib-level test of the `edit_carton_obj` WRAPPER in `carton_mcp.carton_utils` — the neo4j-bound glue between the pure op-applier (covered by `test_carton_kv.py`) and the daemon write path. No real neo4j, no daemon: a `FakeGraph` stub supplies `n.d` for the read query, and a temp `HEAVEN_DATA_DIR` captures the queued `raw_concept` replace entry. 7 tests prove the wrapper's read→splice→queue contract and that every error path queues NOTHING. Its docstring explicitly scopes it: the real E2E (daemon applies the replace, `n.d` actually changes) is the separate MCP-surface gate. One of the four lib-gate files of the `edit-carton-kv` dev-flow.

## How to run

- `python3 test_edit_carton_obj.py` (own runner `:142-156`) or pytest.
- Isolation: sets `HEAVEN_DATA_DIR=mkdtemp(prefix="kvtest_")` BEFORE importing the package (`:17`) so queue entries never reach the real daemon; imports the INSTALLED `carton_mcp` (relative imports require package context — `:15-18`).

## Test infrastructure

- `_DESC` — `:21-27` — a two-fence description (`Unit_Registry` with nested units/order + sibling `Other`), same shape as `test_carton_kv.py`'s.
- `class FakeGraph` — `:30` — returns the fixed `n.d` for the `RETURN c.d AS d` query, records all queries, and answers the STEP-4 ref-guard existence check (`RETURN c.n AS n LIMIT 1`) with "exists" for EVERY ref — deliberately disarming the did-you-mean guard (that guard is `test_carton_kv_schema.py`'s subject).
- `_drain_queue()` — `:47` — reads + deletes all queue `*.json` via `get_observation_queue_dir()`.

## What the suite proves (invariants asserted)

- `get` is read-only — `:56` — returns the leaf value (`2`), queues NOTHING, and issued the raw `RETURN c.d AS d` read.
- `set` queues exactly ONE entry — `:67` — with `raw_concept: True`, `concept_name`, `desc_update_mode: "replace"` (the sanctioned replace mode), `relationships: []` (existing rels untouched), and a description that is the MINIMAL-DIFF SPLICE of the live `n.d`: `"tier": 5` present, `"tier": 2` gone, leading prose byte-identical, sibling fence byte-identical, bare ref `Cave_Repo` preserved.
- Setting a `$ref` dict stores a BARE token — `:87` — `Owner_X` in the queued description, no `$ref` text.
- `remove` of a leaf queues a replace with the key gone and sibling leaves preserved — `:97`.
- `append` to a list queues a replace containing the new element — `:108`.
- Error paths queue NOTHING: missing concept (`success: False`, "not found" — `:118`), missing fence (`:126`), bad key path (`:134`).

## Data contracts

- The queue-entry shape this suite pins down: `{raw_concept, concept_name, description, relationships, desc_update_mode}` — the wire format `observation_worker_daemon` consumes for an `edit_carton_obj` write.
- Division of labor (from the module docstring): pure op logic → `test_carton_kv.py`; graph-bound guard/schema → `test_carton_kv_schema.py`; THIS file → the wrapper glue; daemon-applies-it E2E → the MCP-surface gate (not a pytest).

## Deps

- `carton_mcp.carton_utils.edit_carton_obj`, `carton_mcp.add_concept_tool.get_observation_queue_dir`; stdlib `json/os/tempfile`.

## Defects / dead code

- `FakeGraph` answers the existence check positively for ALL names, so this suite cannot catch a regression where the wrapper stops calling the ref-guard at all (it only proves the read/splice/queue path); the guard behavior itself is only covered in `test_carton_kv_schema.py`.
- Same substring-matched Cypher coupling as the schema suite's stub: a query-text rewrite silently changes stub behavior.
- The mkdtemp `HEAVEN_DATA_DIR` is never cleaned up. Cosmetic.
