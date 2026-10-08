# split_content_concept — status
source: doc-mirror-system/docs/vision_extracted/split_content_concept.md
sealed boundary: none (seem show split_content_concept → REFUSED: no draft 'split_content_concept')
code read: knowledge/carton-mcp/carton_split_content.py, knowledge/carton-mcp/test_split_content.py

## THE Desc_Content TYPE CARRIES A REAL DESCRIPTION
| # | requirement | cases followed | where each is decided (path:line) | what happens to each case | verdict |
|---|---|---|---|---|---|
| 1 | The `Desc_Content` universal type carries its own real description. | (a) first call when type absent: split_content_concept reaches `add_concept_tool_func(concept_name="Desc_Content", description=<6-sentence block, is_a Concept>)` at carton_split_content.py:104-117, passing a specific prose description (not empty/placeholder); (b) text survives the queue: queue_data["description"] = _caller_raw_description at add_concept_tool.py:3092, written to disk via submit_queue_entry at add_concept_tool.py:3162; (c) daemon writes it to the node: batch_create_concepts_neo4j reads `c.get('description', …)` at observation_worker_daemon.py:362 and SETs n.d; (d) later calls: re-entry check at carton_split_content.py:104 `_desc_content_type_exists` short-circuits the create branch, so the existing n.d is preserved (no clobber on subsequent splits) | carton_split_content.py:104-117 decides; add_concept_tool.py:3092 carries; observation_worker_daemon.py:362 applies; carton_split_content.py:59-67 (existence probe) + :104 guards subsequent writes | (a) real, specific prose description queued; (b) queue JSON contains it byte-identical; (c) UNWIND writes it to n.d; (d) node already exists → create branch skipped, existing n.d kept | BUILT |

counts: BUILT 1 · PARTIAL 0 · REMAINING 0 · UNKNOWN 0
<!-- map 10e03c1ce0dc -->
