# Editing The CartON KV / CartonObj Capability Uses The `edit-carton-kv` Dev-Flow FIRST — repo-scoped

When you are about to edit `carton_kv.py`, the `edit_carton_obj` / `validate_carton_obj` /
`get_concept`-expand MCP tools, the `auto_link_description` fence-opacity masking, the daemon's fence /
desc-mode parse path (`parse_queue_file_to_concepts` / `batch_create_concepts_neo4j`; `process_queue_file`
is dead code — see below), or the `is_schema` schema-registry — or to ADD any new CartonObj capability — you MUST FIRST use the
`edit-carton-kv` skill and do its COMPLETE Part-2 coherence edit-set, then its Part-3 E2E gate. NEVER edit
one place only.

→ Why it's distributed / the dead-code trap / the canonical bug / the only-valid-test: read the `understand-carton-mcp-rules` skill.
