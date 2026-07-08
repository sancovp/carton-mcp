# mcp-skill-carton — full tool reference

CartON = a persistent knowledge graph: **Neo4j** (the `:Wiki` namespace, every concept is a `:Wiki`
node with `n`=name, `d`=description, `t`=timestamp, `c`=canonical) **+ ChromaDB** (semantic search).
Saying a concept POSTs an `add_event` to **SOMA :8091**, which validates it and returns a **verdict +
region** (SOUP / CODE / SYSTEM_TYPE / ONT); CartON stores the result as a regioned KG. The region is a
**calculated SOMA verdict** — it is NEVER a settable argument (it is in `RESERVED_PROPERTY_KEYS`).

This file is the per-tool detail behind the `SKILL.md` index. Tools are grouped by capability. Every
name below is a live `mcp__carton__*` tool; functions that LEFT carton are noted at the bottom so a
future reader does not look for them here.

---

## 1. Say / edit concepts

### `add_concept(concept_name, is_a, part_of, instantiates, concept=…, relationships=…, desc_update_mode="append", old_str_for_edit_case=…, typed_values=…, clear_stash=…, hide_youknow=…)`
Say or update one concept. `is_a` / `part_of` / `instantiates` are REQUIRED lists. `concept` = the
description body (prose; mentioning other concept names auto-creates `relates_to` links). Returns the
SOMA verdict + region.
- **The one hard gate:** `is_a` must point to a KNOWN/defined type. An `is_a` to an *undefined* type is
  a `mereo_error` and is REJECTED (admitted to no region; only the timeline records it was said).
  `part_of` / `instantiates` are NOT hard-required for storage — they STRENGTHEN the concept toward
  CODE/SYSTEM_TYPE/ONT.
- `desc_update_mode` ∈ `append` (default) | `prepend` | `replace` | `path` (read the file at `concept`
  as the description) | **`edit`** (surgical str-replace WITHIN the existing `n.d`: `old_str_for_edit_case`
  is found EXACTLY ONCE and replaced by `concept`; a 0-or->1 match fails gracefully, `n.d` unchanged).
- `relationships` = extra rels beyond the required three: `[{"relationship":"has_part","related":[…]}]`.
- `typed_values` = retype relationship targets per-call (ephemeral): `[["Starsystem","Domain"]]`.
- `clear_stash` = discard any stashed retry-merge payload for this concept before processing.

### `edit_carton_obj(concept_name, kvobj_name, key_path, op, value=…)`
Read/edit ONE leaf of a `<CartonObj name=…>{ JSON-with-bare-refs }</CartonObj>` fence embedded in a
concept's `n.d`. `op` ∈ `get | set | append | remove | remove_fence`. A bare `Title_Underscore` token
in the JSON is a concept REF; a quoted string is literal. Writes go through the observation worker
(applied asynchronously). `remove_fence` is the ONLY way to delete a whole fence. (Depth: `edit-carton-kv`.)

### `validate_carton_obj(concept_name, kvobj_name)`
Validate a `<CartonObj>` fence against its `schema=<Concept>` attr (if any) AND check every bare ref
resolves to an existing concept (fuzzy did-you-mean for the ones that don't — the cure for silently
spawned stub refs).

### `add_document_concept(concept_name, description, canonical_path, template=None, relationships=…)`
Index an existing document in CartON (carton acts as the database/index). `description` = a SUMMARY (NOT
the full content); `canonical_path` = the absolute path where the real document lives; `template` = an
optional metastack template name for parsing/rendering it. Use when you want the concept to POINT AT a
file rather than hold the content.

### `rename_concept(old_concept_name, new_concept_name, reason=…)`
Proactive evolution (NOT defensive `_v1` sinking): creates the new concept, repoints ALL incoming rels,
copies ALL outgoing rels, writes bidirectional `evolved_from`/`evolved_to`, preserves the old as history.

---

## 2. The property channel (the THIRD meaning-axis, beside `n.d` and edges)

Property doctrine = **stratification, not unification** (`the-property-layer-doctrine`): two lanes —
SCRATCH (automation/work-state: `status, order, gate, *_at, active_hypercluster, commits, model, error`
— sync direct write, SOMA-free) and TRAIL (ontology-bearing classes also emit a thin `hasProperty_k`
SOMA observation). Properties are NEVER load-bearing for MEANING — an ontological fact lives in `n.d` +
relationships, never only in a property.

### `set_properties(concept_name, properties, mode="merge")`
Set (`merge`) or remove (`mode="remove"`) flat scalar/list properties on an EXISTING concept. **Direct
synchronous write** (bypasses the observation queue — that immediacy is the feature). Concept must
already exist (never creates nodes). **REFUSED keys** (`RESERVED_PROPERTY_KEYS`): `n, d, t, c, linked,
score, source, timeline_linked, odyssey_linked, system_generated, last_modified, region` — these are
managed fields; **`region` is refused because it is the calculated SOMA verdict, not a settable value**.
Nested-dict values are refused (flatten or `json.dumps`).

### `query_by_properties(where, limit=25)`
Exact-match lookup over node properties: every key/value in `where` must match (AND). Values are passed
as parameters (injection-safe). Returns each match + the value of every `where` key.

### `remove_relationship(source, rel_type, target)`
Delete exactly the edge `(source)-[:REL_TYPE]->(target)` — SYNCHRONOUS. `rel_type` is sanitized
`^[A-Za-z_]+$`; source/target are parameters. The deletion counterpart to `add_concept`'s rel creation.

---

## 3. Observations (wrap `add_concept` with the observation shape)

### `add_observation_batch(observation_data, hide_youknow=False)`
Create an observation capturing cognitive state — typed buckets (`insight_moment`, `struggle_point`,
`daily_action`, `implementation`, `emotional_state`, …), each a list of `{name, description,
relationships:[…]}`. Validates via SOMA unless `hide_youknow=True`.

### `observe_from_identity_pov(observation_data, agent_identity=None, hide_youknow=False)`
Same shape, from an agent identity: resolves `AGENT_IDENTITY` env (or the param), ensures
`{identity}_Collection` exists, adds concepts `PART_OF` it, and maps `has_actual_domain → has_domain`.

---

## 4. Query / read

### `query_wiki_graph(cypher_query, parameters=None)`
Read-only Cypher over the `:Wiki` namespace (no CREATE/MERGE). The workhorse for "what exists / what was
said". ALWAYS keep it small: `substring(n.d,0,200)`, `LIMIT`, `ORDER BY n.t`. (Timeline patterns:
`how-to-look-up-the-carton-timeline` — and check the freshness horizon FIRST.)

### `get_concept(concept_name, refresh_code=False, expand_refs=False, depth=0)`
Full concept: description + ALL relationships + the live SOMA region/verdict. `expand_refs`+`depth>0`
render-expands bare `<CartonObj>` refs inline (render-only, never mutates stored `n.d`). Leave
`refresh_code=False` (it calls a retired YOUKNOW OWL reasoner; SOMA is the authority now).

### `get_concept_network(concept_name, depth=1, rel_types=None)`
The concept + its neighborhood, following relationships `depth` hops (1–3). `rel_types` filters
(`["IS_A","PART_OF",…]`). For dependency/cluster understanding.

### `get_history_info(info_type, id)`
Typed traversal of the conversation-history structure (raw + summarizer levels): `info_type` ∈
`iteration | conversation | session | context_bundle | iteration_summary | all_iteration_summaries |
phase | subphase | executive_summary`. Use INSTEAD of raw Cypher for history reconstruction.

### `get_recent_concepts(n=20, timeline=None)`
Timeline of recent concept activity (new/mod + timestamp). `timeline` ∈ `chat | system | odyssey |
overall | None`.

---

## 5. Semantic search (ChromaDB)

### `chroma_query(query, collection_name="carton_concepts", k=10, max_tokens=20000)`
Ranked concept NAMES by semantic similarity. Use to DISCOVER which concepts are relevant, then
`get_concept` / `get_concept_network` for the structured truth. (Embedding is a candidate-finder; the
TYPED GRAPH is the actual logic — see `carton-metaprogramming-and-typing`.)

### `query_graph_from_rag_result(n=5, scopes=[0,1], max_results=100)`
Fetch full graph context for the top-N concepts from the LAST `chroma_query`. `scopes`: 0=concept only,
1=1-hop, 2=2-hop. Deduplicates across sources.

---

## 6. Collections (organize concepts for context engineering)

### `create_collection(collection_name, description, member_concepts, collection_type="local")`
Create a `Carton_Collection` with `HAS_PART` edges to its members. `collection_type` ∈ `global | local |
identity`.
### `add_to_collection(collection_name, concept_names)` — add members (`HAS_PART`/`PART_OF`).
### `activate_collection(collection_name)` — load ALL member concepts (recursively via `HAS_PART`) — the
way you pull a whole knowledge bundle into context.
### `list_collections()` — every `Carton_Collection` + member counts.

---

## 7. Projection, validation, maintenance

### `substrate_projector(substrate, target, description_only=True, template=None, get_instructions=False)`
Project a concept to a substrate (`file | discord | registry | env`). `get_instructions=True` returns
usage. `template` renders through a metastack template first.

### `youknow_sparql(query)`
SPARQL over the **SOMA OWL** (the total-runtime ontology: `soma.owl` + `uarl.owl` + `starsystem.owl`) —
the authority for typing/restrictions since YOUKNOW was retired. This queries the ONTOLOGY, not the KG
(use `query_wiki_graph` for the graph).

### `carton_management(...)`
Admin multitool (one flag per op): `restart_bg_server`, `get_git_repo_url`, `get_carton_dir`,
`get_carton_guide`, `get_requires_evolution_list` (+`page`), `sync_rag`, `check_failed_observations`,
`retry_failed_observations`, `enable_gps`/`disable_gps`/`get_gps_status`.

### `list_missing_concepts()` / `calculate_missing_concepts()` / `create_missing_concepts(concepts_data)`
Find concept names referenced-but-not-existing (gaps), recompute+commit `missing_concepts.md`, or batch-
create the missing ones with AI-generated descriptions.

### `deduplicate_concepts(similarity_threshold=0.8)`
Find duplicate/similar concepts by name similarity (for merge/rename decisions).

### `equip_frame(frame)`
Equip an observation frame/lens (e.g. `skill_development`, `meta_test`, `exercise`) that shapes
observation structure.

---

## Functions that LEFT carton (do not look for them here)
- `autobiography` — moved ENTIRELY to the **sancrev WakingDreamer autobiographer** system (Isaac,
  2026-06-20). It is NOT a carton tool.
- `stream`, `hj`, `add_user_thought`, `update_known_concept`, `observe`, `discover_patterns`,
  `scientific_method`, `deep_dive`, `krr_engineer_domain`, `add_frame` — legacy
  journaling/exploration functions left in the source with NO `@mcp.tool()` decorator (un-exposed).
- `observe_auto_meta_test`, `run_experiment`, `DetectEvent_*` — REMOVED (commented out) in the tool
  cleanup; not part of carton's surface.
