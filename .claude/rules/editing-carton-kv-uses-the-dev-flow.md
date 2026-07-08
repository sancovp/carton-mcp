# Editing The CartON KV / CartonObj Capability Uses The `edit-carton-kv` Dev-Flow FIRST — repo-scoped, NON-NEGOTIABLE

When you are about to edit `carton_kv.py`, the `edit_carton_obj` / `validate_carton_obj` /
`get_concept`-expand MCP tools, the `auto_link_description` fence-opacity masking, the daemon's fence /
desc-mode parse path (`parse_queue_file_to_concepts` / `batch_create_concepts_neo4j`; `process_queue_file`
is dead code — see below), or the `is_schema` schema-registry — or to ADD any new CartonObj capability — you MUST FIRST use the
`edit-carton-kv` skill and do its COMPLETE Part-2 coherence edit-set, then its Part-3 E2E gate. NEVER edit
one place only.

The CartON KV capability's behavior is DISTRIBUTED: the PURE `carton_kv.py` library is the core (lib fn +
unit test FIRST — the onion); `carton_utils.py` holds the neo4j-bound wrappers (`edit_carton_obj`,
`check_kv_refs`, `register_kv_schemas`, `validate_carton_obj`, `expand_carton_refs`); `server_fastmcp.py`
holds the thin MCP tools; `add_concept_tool.py`'s `auto_link_description` MASKS each fence span so the linker
can't corrupt it (the one chokepoint over every linker caller); the `observation_worker_daemon` writes `n.d`
via `batch_create_concepts_neo4j`, fed by the ONE live parse path: `parse_queue_file_to_concepts` (:444),
called from the daemon worker loop (:1383) — its raw_concept branch forwards `removed_fences` /
`desc_update_mode` per concept. `process_queue_file` (:598) is DEAD CODE with ZERO callers (verified
2026-06-10 by grep over the repo — only docstring mentions remain); do NOT maintain it in lockstep, and do
NOT land a fence/desc-mode change there thinking it is live. And the SOUP schema
graph (`IS_A Carton_Kv_Schema` / `USES_KV_SCHEMA`) is auto-typed from `is_schema` fences. AND the running code
is the INSTALLED package, not the source. Editing one and not the rest silently desyncs — concretely, **the
canonical bug was a `removed_fences` fix landed on the dead path while the LIVE path
(`parse_queue_file_to_concepts`) still dropped it, so the fence-preservation guard carried a removed fence
back — fence/desc-mode changes go on the LIVE path**, and **a source edit without `pip install --no-deps` +
the daemon-restart-or-`reconnect_mcp` means the running command never changes**.

**Why:** this is the project-scoped enforcement required by the global law
`every-build-ends-in-a-development-flow-skill`. See `edit-carton-kv` for the full edit-set and the only valid
test — the lib gate (the 4 test files green) PLUS the E2E gate through the real MCP surface (`add_concept` →
raw `n.d` byte-intact via opacity → `edit_carton_obj` set/remove leaf, prose/siblings byte-identical →
`validate_carton_obj` good+bad → unknown ref REFUSED with NO stub node in neo4j → `get_concept` expand_refs
render-only, stored `n.d` unchanged). "It imported" / "the lib tests passed" is NOT the gate.
