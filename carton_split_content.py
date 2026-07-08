"""
carton_split_content — CartON content/description split capability (onion arch, self-contained module).

This module holds BOTH layers of the split-content capability, per Isaac's 2026-07-03 layering
decision: `split_content_concept` is its OWN self-contained capability, matching the `carton_kv.py`
precedent (a capability's core lives in its own module, never inside `add_concept_tool.py`, which is
the backing library for the `add_concept` MCP tool specifically).

STEP 1 — `build_split_spec` (below): PURE — stdlib only, no neo4j / no MCP / no I/O — unit-testable
standalone (test_split_content.py).

STEP 2 — `split_content_concept` (below): THIN neo4j-writing wrapper. It reuses the existing internal
concept-creation entrypoint (`add_concept_tool_func` in `add_concept_tool.py`) rather than duplicating
any neo4j/queueing logic — it imports that function, it does not re-implement it.

THE PROBLEM (Isaac, verbatim, 2026-07-03): a concept is often entered with its description (n.d) being
raw CONTENT (a data dump, a pasted document, verbatim info) rather than an actual DESCRIPTION that
names/traces the concept's relationships. `carton-description-is-annotation-not-knowledge` already
states description = annotation for embedding, ALL knowledge goes in typed relationships — this module
computes + performs the SPLIT that a coherer agent uses to separate the two: the raw content moves to
its own `{concept_name}_Desc_Content` node (preserved verbatim, never truncated/modified), related back
to the original concept via a `has_desc_content` relationship.

IS-vs-VISION: both functions in this file are CODE. `build_split_spec` is unit-tested at the library
level (test_split_content.py); `split_content_concept` is a thin wrapper verified via the real MCP
surface (the dev-flow's E2E gate), not a unit test — it does I/O (queues a carton write; the
observation-worker daemon applies it asynchronously). Whether/when to further ATOMIZE the split-off
content into sub-concepts is explicitly OUT OF SCOPE for this module (a future coherer agent's own
judgment call, per Isaac's 2026-07-03 decision) — this module only computes + performs the split,
never any atomization timing/logic.
"""
from typing import Dict


def build_split_spec(concept_name: str, raw_content: str) -> Dict[str, object]:
    """Pure. Computes the node name, relationship name, and node payload for a content split.

    Does NOT touch neo4j. Returns a dict:
        {content_node_name, content_node_is_a, content_node_part_of,
         relationship_name, content_node_description}

    - content_node_name = "{concept_name}_Desc_Content"
    - content_node_is_a = ["Desc_Content"] (the universal type the content node instantiates)
    - content_node_part_of = [concept_name] (the content node belongs to the concept it split from)
    - relationship_name = "has_desc_content" (the forward edge concept_name -> content_node_name)
    - content_node_description = raw_content, passed through BYTE-IDENTICAL — this function never
      truncates, modifies, or re-derives the content; verbatim preservation is the whole point.
    """
    content_node_name = f"{concept_name}_Desc_Content"
    return {
        "content_node_name": content_node_name,
        "content_node_is_a": ["Desc_Content"],
        "content_node_part_of": [concept_name],
        "relationship_name": "has_desc_content",
        "content_node_description": raw_content,
    }


def _desc_content_type_exists(shared_connection=None) -> bool:
    """Query neo4j for the universal `Desc_Content` type concept. Thin — one query, no writes."""
    from carton_mcp.carton_utils import CartOnUtils

    utils = CartOnUtils(shared_connection=shared_connection)
    result = utils.query_wiki_graph(
        "MATCH (c:Wiki {n: $name}) RETURN c.n as name", {"name": "Desc_Content"}
    )
    return bool(result.get("success") and result.get("data"))


def split_content_concept(concept_name: str, raw_content: str, shared_connection=None) -> str:
    """Split `concept_name`'s raw CONTENT off into its own `{concept_name}_Desc_Content` node.

    Thin wrapper over `build_split_spec` (STEP 1, pure) + `add_concept_tool_func` (the existing
    internal concept-creation entrypoint, `carton_mcp.add_concept_tool.add_concept_tool_func` —
    reused here, not duplicated). Three neo4j-facing actions, in order:

    1. Ensure the universal `Desc_Content` type concept exists (checked via `query_wiki_graph`
       first; only created once, via `add_concept_tool_func`, if missing — per
       `universal-concepts-must-exist`).
    2. Create `{concept_name}_Desc_Content` with `is_a=[Desc_Content]`, `part_of=[concept_name]`,
       and `description=raw_content` passed through byte-identical (never modified).
    3. Add the relationship `concept_name -[has_desc_content]-> {concept_name}_Desc_Content` on
       the ORIGINAL concept. This call passes `description=None` deliberately: `add_concept_tool_func`
       queues `description=""` in that case, and the daemon's UNWIND write
       (`observation_worker_daemon.batch_create_concepts_neo4j`) CASEs `WHEN n.d CONTAINS
       c.description THEN n.d` — an empty string is contained in every string, so an existing,
       non-empty `n.d` is left UNCHANGED. This is how the tool satisfies "does NOT touch the
       original concept's description" without a special no-op mode in the reused function.

    All three writes go through the SAME async carton queue as every other `add_concept` call — this
    function does not wait for the daemon to drain, so the queued writes land asynchronously (per
    `dragonbones-compiles-after-turn`-style async carton semantics: verify in a LATER query, not the
    same turn's return value).

    Rewriting `{concept_name}`'s OWN description into an actual DESCRIPTION that traces its
    relationships (including the new `has_desc_content` edge) — and any further ATOMIZATION of the
    split-off content into sub-concepts — is OUT OF SCOPE here; both are separate, judgment-driven
    steps for the caller/coherer agent, never done by this function.
    """
    from carton_mcp.add_concept_tool import add_concept_tool_func

    spec = build_split_spec(concept_name, raw_content)

    if not _desc_content_type_exists(shared_connection=shared_connection):
        add_concept_tool_func(
            concept_name="Desc_Content",
            description=(
                "Universal type for a concept's split-off raw content node. Created by "
                "split_content_concept when a concept's description (n.d) was judged to be raw "
                "CONTENT (a data dump, a pasted document, verbatim info) rather than an actual "
                "DESCRIPTION that names/traces the concept's relationships. Each instance "
                "(`{Concept}_Desc_Content`) holds that original raw content verbatim, related back "
                "to the concept it split from via `part_of` and `has_desc_content`."
            ),
            relationships=[{"relationship": "is_a", "related": ["Concept"]}],
            shared_connection=shared_connection,
        )

    add_concept_tool_func(
        concept_name=spec["content_node_name"],
        description=spec["content_node_description"],
        relationships=[
            {"relationship": "is_a", "related": spec["content_node_is_a"]},
            {"relationship": "part_of", "related": spec["content_node_part_of"]},
        ],
        shared_connection=shared_connection,
    )

    add_concept_tool_func(
        concept_name=concept_name,
        description=None,
        relationships=[
            {"relationship": spec["relationship_name"], "related": [spec["content_node_name"]]},
        ],
        shared_connection=shared_connection,
    )

    return (
        f"✅ queued split of {concept_name} -> {spec['content_node_name']} "
        f"(relationship: {spec['relationship_name']}); the daemon applies the writes asynchronously."
    )
