# doc(m): carton_utils.py

**Module:** `carton-mcp/carton_utils.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 5 sealed boundaries land here

## Features whose sealed boundary lands in this module

### Bounded_Collection_Walk — feature boundary of `Giint_Feature_Bounded_Collection_Walk`

- **user action:** the agent calls the carton activate_collection MCP tool on a collection and must receive its members without any hub member importing its whole subtree, every stop reported ahead of the members
- **doc(v):** `knowledge/carton-mcp/docs/vision_extracted/activate_collection.md`
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v2, key `256db61ccf68e43e`, commit `21bee0c41`, valid from 2026-09-29T21:18:29
- **ranges in this module** (layer order):
  - `L1 executor` · `carton_utils.py:2261-2315` — THE THIN EXECUTOR: get_collection_concepts builds the plan with build_walk_plan, runs its ONE Cypher through _execute_neo4j_query, and classifies the rows with build_activation_result. It holds no stop logic of its own and returns a success-false dict on any exception rather than raising into the tool
- **also passes through:** `server_fastmcp.py`, `carton_bounded_walk.py`, `test_carton_bounded_walk.py`

### Carton_Queue_Ingest — feature boundary (no Giint_Feature node declared)

- **user action:** a concept is written through the CartON front door, add_concept_tool_func, which POSTs it to SOMA and queues the graded node, and the observation worker must land that node in the graph and act on the verdict the payload carries
- **doc(v):** `knowledge/carton-mcp/docs/vision_extracted/add_concept.md`
- **outputs to:** `['dead_letter_lane_fires']`
- **sealed:** v5, key `d87661e7eb26a97b`, commit `37335213d`, valid from 2026-10-08T00:07:14
- **ranges in this module** (layer order):
  - `L2 write` · `carton_utils.py:530-641` — set_concept_properties: the direct property write the drain makes for every concept carrying properties, MATCH never MERGE, exact name first then normalized, reserved keys refused, value types validated, graph.set_properties, then the property trail _emit_property_trail wrapped so a trail failure never fails the write, its status returned as trail
  - `L2 write` · `carton_utils.py:389-511` — the property trail: the scratch class set (Blog_Request, Chain_Step, Bundle_Step, Plan_Graph, Carton_Collection, Journal_Entry; CARTON_SCRATCH_PROPERTY_CLASSES replaces it), the ONE trail switch PROPERTY_TRAIL_TO_SOMA, False while Gnosys_System.soma_validator is off, read by soma_trail_on at call time, and _emit_property_trail: soma-off before any query or POST while the switch is off; switched on, scratch-lane for an untyped or scratch-typed node, else ONE POST to SOMA_URL within a 10 s bound, emitted or soma-unreachable. Card 858: on the one drain thread each POST that timed out held the next batch 10 s
- **also passes through:** `add_concept_tool.py`, `observation_worker_daemon.py`, `test_property_trail_soma_off.py`

### Carton_Read_Facade — feature boundary of `Giint_Feature_Carton_Mcp_Carton_Read_Facade`

- **user action:** an agent or a doc-mirror CLI reads the graph through carton: the query_wiki_graph MCP tool, or CartOnUtils.query_wiki_graph from python, and must receive the words, never the auto-linker wiki markup stored in n.d
- **doc(v):** `knowledge/carton-mcp/docs/vision/server_fastmcp.py.md`
- **outputs to:** `tool_dispatch_loop`
- **sealed:** v15, key `482d03b2bf6c0bb3`, commit `5fecd2b7c`, valid from 2026-10-04T03:46:22
- **ranges in this module** (layer order):
  - `L1 facade` · `carton_utils.py:1478-1493` — _validate_query_safety: refuses CREATE MERGE DELETE DETACH and any query naming no readable label
  - `L1 facade` · `carton_utils.py:1616-1637` — CartOnUtils.query_wiki_graph: validate, execute, return success plus data, or the error dict from _handle_query_errors
  - `L1 facade` · `carton_utils.py:1639-1655` — CartOnUtils.query_verbatim: the same validated read with every value as stored, never through deep_strip_wiki_links, for a reader that needs a content node exact text (card 813); a write verb is refused exactly as the facade refuses it
  - `L2 primitive` · `carton_utils.py:1576-1605` — _execute_neo4j_query: rows through the connection, serialized, and RELEASED through deep_strip_wiki_links so every caller gets clean data and a carton wiki-link such as [w](../W/W_itself.md) never renders; strip False is query_verbatim alone, the reader of a content node kept as written (card 813)  ⟵ RELEASE
  - `L2 primitive` · `carton_utils.py:49-85` — _CARTON_LINK, strip_wiki_links and deep_strip_wiki_links: the ONE canonical stripper. The auto-linker shape, the words in square brackets followed by a parenthesised target naming the concept twice, becomes its words whatever the name holds, the name matched by back-reference so doc(m) linked to the concept Doc(M) reads doc(m) (16427 nodes hold a link whose name ends in a close paren, measured 2026-10-03); any other complete, nested, orphan or truncated link form becomes its words, each removed link target taking the space before it; every other character is returned as stored, so vault() keeps its parentheses and a run of spaces stays a run (card 812)
  - `L2 primitive` · `carton_utils.py:88-115` — VERBATIM_TYPES, linker_eligible and verbatim_text (card 813): Desc_Content is kept as written; linker_eligible is the predicate the auto-linker selects nodes by, unlinked, untouched since the cutoff and is_a none of the verbatim types; verbatim_text gives a content node text as stored, or its words through strip_wiki_links when linked is true because the linker rewrote it before it skipped the verbatim types
- **also passes through:** `server_fastmcp.py`, `carton_render.py`, `base/answer-refs/answer_refs/__init__.py`, `test_carton_read_facade.py`, `base/answer-refs/tests/test_answer_refs.py`

### Doc_Mirror_File_Projection — AB boundary of `Giint_Feature_Carton_Mcp_Doc_Mirror_Projection`

- **user action:** nobody runs anything - a Doc_Mirror_Module or Doc_Mirror_Vision concept becomes complete, its projection d-chain surfaces a release effect, and the carton observation-worker daemon dispatches the named handler AFTER the d-chain phase, so the doc m or doc v file appears for the RAG without the agent asking. The agent involvement ended at the concept write.
- **doc(v):** `docs/vision/doc_mirror_projector.md`
- **outputs to:** `['ab_chain:absorber_loop']`
- **sealed:** v4, key `3e4f091136d50f5e`, commit `c862fb308`, valid from 2026-10-04T03:39:56
- **ranges in this module** (layer order):
  - `L2 read` · `carton_utils.py:1639-1655` — query_verbatim, the validated read with every value as stored, which read_concept reads the content node through (card 813)
  - `L2 read` · `carton_utils.py:88-115` — verbatim_text, the content node text as stored or its words when the linker rewrote it, and linker_eligible, which keeps the linker off Desc_Content (card 813)
- **also passes through:** `doc_mirror_projector.py`

### Docm_Projection — feature boundary of `Giint_Feature_Write_Gate_Docm_Projection`

- **user action:** the agent runs doc-mirror-commit MODULE and the doc(m) of that module is projected from its sealed HALO SEEM boundaries by seem docm instead of being written by any hand
- **doc(v):** `doc-mirror-system/docs/vision/_docm-from-seem.md`
- **outputs to:** `['docm_projection_fires']`
- **sealed:** v43, key `6ff5b2cab81d53aa`, commit `3e45f0560`, valid from 2026-10-04T17:08:30
- **ranges in this module** (layer order):
  - `L2 write_gate` · `carton_utils.py:88-115` — VERBATIM_TYPES, linker_eligible and verbatim_text in carton_utils (card 813): the doc(m) content node is Desc_Content, kept as written
  - `L2 write_gate` · `carton_utils.py:1639-1655` — CartOnUtils.query_verbatim, the read the wait and read_concept take for the content node (card 813)
- **also passes through:** `base/sanctuary-system/sanctuary_system/seem_project.py`, `doc-mirror-system/plugin/lib/docmirror_docm_concept.py`, `add_concept_tool.py`, `base/sanctuary-system/sanctuary_system/seem_cli.py`, `doc-mirror-system/plugin/hooks/docmirror_read_ledger.py`, `doc-mirror-system/plugin/bin/docmirror-docm`, `doc-mirror-system/plugin/bin/doc-mirror-commit`, `doc-mirror-system/plugin/lib/docmirror_docm_project.py`, `doc_mirror_projector.py`, `observation_worker_daemon.py`, `doc-mirror-system/plugin/hooks/docmirror_read_gate.py`, `base/sanctuary-system/tests/test_seem_cli.py`, `doc-mirror-system/tests/test_docmirror_commit_graduation.py`, `doc-mirror-system/tests/test_docmirror_drift_sweep.py`, `doc-mirror-system/tests/test_docmirror_read_ledger_graph.py`, `doc-mirror-system/tests/test_docmirror_docm_concept.py`, `doc-mirror-system/tests/test_docmirror_commit_retire.py`, `doc-mirror-system/tests/docm_fake.py`, `doc-mirror-system/tests/test_docmirror_docm_project.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
