# UI Context — carton-mcp

**N/A — there is no UI.** carton-mcp is a server-side stdio MCP; it renders no pages, serves no frontend, and has no user-facing visual surface.

The "surface" of this system is the **MCP tool set** exposed by `server_fastmcp.py` (`add_concept`, `get_concept`, `get_concept_network`, `query_wiki_graph`, `chroma_query`, `edit_carton_obj`, `validate_carton_obj`, `add_observation_batch`, collections, management, etc.), consumed by Claude Code over the stdio transport. For the complete tool-by-tool surface, see `docs/mirror/server_fastmcp.py.md`.

Secondary human-readable outputs (not a UI): the projected wiki markdown files under `$HEAVEN_DATA_DIR/wiki/concepts/`, query-overflow text files under `$HEAVEN_DATA_DIR/query_overflow/`, and substrate projections (files/skills/rules) written by `substrate_projector.py`.
