---
name: mcp-skill-carton
description: "WHAT: the CartON MCP — a persistent knowledge graph (Neo4j + ChromaDB) you add concepts to, query, edit, and project. WHEN: persisting knowledge, creating observations/concepts, querying concept networks, semantic search, or editing a concept's description/structured data."
---

# mcp-skill-carton

MCP shim index for CartON (Cartographic Ontology Net) — a persistent knowledge graph on Neo4j (the
`:Wiki` namespace) + ChromaDB (semantic search). Saying a concept POSTs an `add_event` to SOMA :8091,
which validates and returns the verdict; CartON stores the result as a regioned KG.

## The live tools (what you actually call)
- **`add_concept`** — say/update a concept (`is_a`/`part_of`/`instantiates`/`produces` + `has_*`,
  `typed_values`). `desc_update_mode` = append | prepend | replace | path | **edit** (surgical
  str-replace via `old_str_for_edit_case`). `stash`/`clear_stash` for retry-merge.
- **`query_wiki_graph`** — read-only Cypher over `:Wiki`. **`get_concept` / `get_concept_network`** —
  fetch one concept / its neighborhood. **`chroma_query`** — semantic search.
- **`edit_carton_obj` / `validate_carton_obj`** — edit/validate a `<CartonObj>` JSON fence inside a
  concept's `n.d` (structured-data-in-description; see `edit-carton-kv`).
- **`set_properties` / `query_by_properties` / `remove_relationship`** — the property channel
  (scratch-lane work-state; see the property-layer doctrine) + relationship deletion.
- **`add_observation_batch` / `observe_from_identity_pov`** — observation shapes (wrap `add_concept`).
- **collections**: `create_collection` / `add_to_collection` / `activate_collection` / `list_collections`.
- **`substrate_projector`** — project a concept to a substrate (file / etc).

ACCESS: via the carton MCP tools directly (`mcp__carton__*`), or through sancrev-treeshell GNOSYS nodes
(connect 'carton' first).

See `reference.md` for the full tool docs.
