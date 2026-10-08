When you are about to edit `carton_kv.py`, the `edit_carton_obj` / `validate_carton_obj` /
`get_concept`-expand MCP tools, the `auto_link_description` fence-opacity masking, the daemon's fence and
desc-mode parse path (`parse_queue_file_to_concepts` / `batch_create_concepts_neo4j`), or the `is_schema`
schema-registry — or to ADD any new CartonObj capability — you MUST FIRST use the `edit-carton-kv` skill
and do its COMPLETE Part-2 coherence edit-set, then its Part-3 E2E gate. NEVER edit one place only.

`process_queue_file` is DEAD CODE. Do not maintain it in lockstep with the live path.

Read the `understand-carton-mcp-rules` skill for why it is distributed, the dead-code trap, the canonical
bug, and the only valid test.
