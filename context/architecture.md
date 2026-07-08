# Architecture — carton-mcp (write pipeline / read pipeline)

## WRITE pipeline (asynchronous, queue-mediated — the daemon is the ONLY Neo4j writer)

```
MCP tool call (add_concept / add_observation_batch / edit_carton_obj / rename_concept ...)
        │  server_fastmcp.py — thin tool layer (docs/mirror/server_fastmcp.py.md)
        ▼
add_concept_tool.add_concept_tool_func / add_observation / carton_utils.edit_carton_obj
        │  validate (SOMA :8091 when on; cycle/instantiation constraints; KV ref write-guard)
        │  then serialize a `raw_concept` JSON envelope — NO direct neo4j write
        ▼
$HEAVEN_DATA_DIR/carton_queue/*.json      (the file-based queue)
        ▼
observation_worker_daemon  (docs/mirror/observation_worker_daemon.py.md)
        │  parse_queue_file_to_concepts / process_queue_file  (TWO parse paths — change in lockstep)
        │  batch_create_concepts_neo4j: UNWIND Cypher → SET n.d with desc_update_mode
        │  (append/prepend/replace/skip) + section dedup + fence-preservation guard
        │  (carry_forward_fences honoring removed_fences)
        ├─ REQUIRES_EVOLUTION stubs for SOUP; GIINT completeness; _Unnamed resolution
        ├─ wiki markdown files → $HEAVEN_DATA_DIR/wiki/concepts/<Name>/<Name>_itself.md
        ├─ ChromaDB ingest (RAG collections, routed by smart_chroma_rag.route_concept_to_collection)
        └─ background LINKER thread: rewrites n.d with wiki hyperlinks (auto_link_description,
           fence-opacity masked — docs/mirror/add_concept_tool.py.md) + timeline connection
        ▼
neo4j :Wiki graph   (bolt://host.docker.internal:7687)
```

Key invariant: tool calls return immediately after queueing; if the daemon is down, writes pile up in the queue and the graph goes stale (check `/tmp/carton_daemon.log`, restart per `context/code-standards.md`).

## READ pipeline (synchronous, direct)

```
get_concept / get_concept_network ──► carton_utils (shared KnowledgeGraphBuilder connection)
                                       │  wiki-link stripping at the shared read primitive
                                       │  optional expand_refs: render-only CartonObj ref expansion
query_wiki_graph ────────────────────► read-only Cypher facade over :Wiki (no CREATE/MERGE)
chroma_query ────────────────────────► smart_chroma_rag (ChromaDB HTTP :8101) — semantic ranking;
                                       default "carton_concepts" fans out over the 7 routed collections
        ▼
server_fastmcp._fmt — overflow guard: >10k chars → full text to
$HEAVEN_DATA_DIR/query_overflow/overflow_<ts>.txt + truncated prefix returned
```

## The CartonObj KV sub-system (cuts across both pipelines)

`carton_kv.py` (pure lib) → `carton_utils` wrappers (`edit_carton_obj`, `validate_carton_obj`, `check_kv_refs`, `register_kv_schemas`, `expand_carton_refs`) → MCP tools; the linker masks fence spans (opacity); the daemon's guard carries fences forward across prose rewrites. Full edit-set + E2E gate: the `edit-carton-kv` dev-flow skill.

## Pointers into the doc(m) layer

- Queue/envelope shapes + daemon behavior: `docs/mirror/observation_worker_daemon.py.md`, `docs/mirror/add_concept_tool.py.md`.
- Tool surface: `docs/mirror/server_fastmcp.py.md`. Read facades: `docs/mirror/carton_utils.py.md`.
- RAG routing/budget retrieval: `docs/mirror/smart_chroma_rag.py.md`. Scaffolding: `docs/mirror/ontology_graphs.py.md`. Projection: `docs/mirror/substrate_projector.py.md`.
