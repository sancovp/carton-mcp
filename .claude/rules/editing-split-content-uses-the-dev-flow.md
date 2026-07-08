# Editing The CartON Split-Content Capability Uses The `dev-flow-split-content` Dev-Flow FIRST — repo-scoped, NON-NEGOTIABLE

When you are about to edit `carton_split_content.py` (`build_split_spec`, `split_content_concept`,
`_desc_content_type_exists`), the `split_content_concept` MCP tool in `server_fastmcp.py`, the
`Desc_Content` universal type, or the `has_desc_content` relationship — or to ADD any new
content/description-split capability — you MUST FIRST use the `dev-flow-split-content` skill and do its
COMPLETE Part-2 coherence edit-set, then its Part-3 E2E gate. NEVER edit one place only.

The split-content capability is SELF-CONTAINED in its own module, matching this repo's own established
precedent (verified in code, 2026-07-03: `carton_kv.py` is self-contained and backs `edit_carton_obj`/
`validate_carton_obj` directly; `add_concept_tool.py` is self-contained and backs `add_concept` only;
neither imports the other; `server_fastmcp.py` imports each directly). `carton_split_content.py` holds BOTH
the pure `build_split_spec` core AND the thin neo4j-writing `split_content_concept` wrapper together;
`server_fastmcp.py` imports `split_content_concept` from it directly. It is NEVER routed through
`add_concept_tool.py` — that file is the backing library for the `add_concept` tool ONLY. (Note: this is a
carton-mcp-REPO-SPECIFIC convention, not a universal MCP-architecture law — it lives here as a local rule,
not in `system/rules/`, precisely because it is this repo's own established layout, not a global truth
about every MCP.) The ONE thing
this capability reads from `add_concept_tool.py` (never edits) is `add_concept_tool_func`, the existing
internal concept-creation entrypoint every other internal caller in that file also reuses.

**Why:** this is the project-scoped enforcement required by the global law
`every-build-ends-in-a-development-flow-skill`. See `dev-flow-split-content` for the full edit-set and the
only valid test — the lib gate (`test_split_content.py` green) PLUS the E2E gate through the real MCP
surface (`add_concept` a content-as-description test concept → `split_content_concept` → `query_wiki_graph`
byte-for-byte confirms: the new `{X}_Desc_Content` node holds the content verbatim, the `HAS_DESC_CONTENT`
edge exists, and the original concept's `n.d` is UNCHANGED). "It imported" / "the lib test passed" is NOT
the gate.

Two load-bearing mechanisms this dev-flow documents that are easy to break silently if you touch adjacent
code without reading it first: (1) the `Desc_Content` existence-check is existence-only, NOT a quality
check — an unrelated auto-created SOUP stub already satisfies it, so this capability's own proper
description for `Desc_Content` may never get written (observed live 2026-07-03); (2) leaving the original
concept's description untouched relies on `add_concept_tool_func`'s `description=None → ""` normalization
plus the daemon's `n.d CONTAINS "" → n.d unchanged` CASE branch in
`observation_worker_daemon.batch_create_concepts_neo4j` — if that CASE ordering is ever refactored, this
capability's core guarantee ("does not touch the original concept's description") silently breaks.
