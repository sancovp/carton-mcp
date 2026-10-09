"""giint_effects — STORE-SIDE release-effect handlers for the GIINT readiness cascade.

WHY THIS LIVES IN carton_mcp AND NOT IN llm_intelligence (e2e run-11, 2026-08-20):
the giint write lane is a call on CartON's SDK at the box's door — `add_concept` runs
IN the box and writes the box's own queue — so the BOX's own observation_worker_daemon
is the process that dispatches release effects for giint events. The box image is the LEAN 3-package shape BY RULING (the
2026-08-20 import-closure measurement: llm_intelligence transitively imports the
entire ecosystem — cave, sanctuary_revolution, sdna, torch — so giint can never be
installed in a tenant box). But the giint_ready stamp is not giint logic at all: it
is ONE property write on the store the daemon already owns. A store-side effect's
handler belongs in the store's own package, which every box worker has by
construction. The d-chain conclusion (gnosys_vault.giint dchain_giint_project_ready)
names THIS module; llm_intelligence.projects keeps a thin delegate under the old
name for the self-hosted topology and for existing store rows that still carry the
old handler string.

The stamp VALUE is the string 'true', one contract across backends: kuzu's :Wiki
property columns are STRING-typed by schema (a bool SET would bind-fail), and the
reader (llm_intelligence.projects._is_task_ready_in_giint) string-tests. A direct
scratch-lane 'gate' property write, NOT set_properties: set_properties on an
ontology-bearing class emits a SOMA trail, which would re-POST this concept and
re-fire this very d-chain — a stamp loop.
"""

import logging
import traceback

logger = logging.getLogger(__name__)


def stamp_giint_project_ready(concept_name: str, shared_connection=None) -> str:
    """release_effect handler for dchain_giint_project_ready (gnosys_vault.giint).

    SOMA decided this giint_project has a complete non-_Unnamed Feature->Component->
    Deliverable chain (it is dispatchable) and released this effect naming the
    project node. Stamp giint_ready='true' onto that carton node so the dispatch
    gate (_is_task_ready_in_giint) READS SOMA's verdict instead of re-deriving the
    rule. Dispatched by the observation worker daemon as
    fn(c.name, shared_connection=shared_neo4j), where shared_neo4j is the daemon's
    own GRAPH_BACKEND-aware KnowledgeGraphBuilder — USE IT (a hand-rolled bolt
    driver here once ignored the one-graph law and pointed a kuzu-tenant container
    at a dead host bolt). concept_name = the daemon's c.name (the exact Title-case
    carton node name).
    """
    query = "MATCH (p:Wiki {n: $n}) SET p.giint_ready = 'true'"
    if shared_connection is not None:
        shared_connection.execute_query(query, {"n": concept_name})
        return f"giint_ready stamped on {concept_name}"
    # Standalone fallback (no daemon handle): the env-selected store, never a raw driver.
    import os
    from heaven_base.tool_utils.graph_store import make_store
    store = make_store(
        os.environ.get("NEO4J_URI", "bolt://host.docker.internal:7687"),
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "password"),
    )
    try:
        store.execute(query, {"n": concept_name})
    except Exception:
        logger.error("giint_ready stamp failed for %s:\n%s", concept_name, traceback.format_exc())
        raise
    finally:
        store.close()
    return f"giint_ready stamped on {concept_name}"
