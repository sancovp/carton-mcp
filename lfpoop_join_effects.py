"""Release-effect handlers for LFPOOP join A (card 780 / issue 1127).

write_call_graph starts the chain: the context-alignment refresh calls it with the call graph of an
edited module, and it writes the Module_Call_Graph partial. The vaulted partials in
gnosys_vault.lfpoop_join each carry a d-chain whose conclusion names one of the three handlers below as
`carton_mcp.lfpoop_join_effects:<func>`; the observation worker dispatches it with the node the chain
fired on and its graph connection. Each handler reads that node's properties, hands them to the pure
partial chain in sanctuary_system.seem_ab3, writes the result, never raises, and returns a line for the
dispatch log. The first two write the next partial through add_concept, so its own d-chain fires the
next hop; the third records the derived AB3 states on the ring set as properties, which ends the chain.
"""

import json
import logging
import os
import traceback
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DEFAULT_MONOREPO = "/home/GOD/gnosys-plugin-v2"


def node_props(concept_name, shared_connection):
    """The properties of one node, or None when the store holds no node of that name.

    Args:
        concept_name: The node name.
        shared_connection: The worker's graph connection.

    Returns:
        dict | None: The node's properties.
    """
    rows = shared_connection.execute_query(
        "MATCH (n:Wiki {n:$n}) RETURN properties(n) AS p LIMIT 1", {"n": concept_name})
    records = rows[0] if isinstance(rows, tuple) else rows
    if not records:
        return None
    rec = records[0]
    return dict(rec.get("p") if isinstance(rec, dict) else rec["p"])


def write_concept(name, is_a, properties, part_of, shared_connection=None):
    """Write one partial through CartON's front door, so SOMA grades it and its d-chain can fire.

    Args:
        name: The partial's node name.
        is_a: Its vaulted type, as a CartON name.
        properties: Its string properties; the has_ ones reach SOMA as string_value triples.
        part_of: The partial it was made from.
        shared_connection: The worker's graph connection.

    Returns:
        str: add_concept's answer.
    """
    from carton_mcp.add_concept_tool import add_concept_tool_func
    return add_concept_tool_func(
        name,
        description=f"LFPOOP join A partial {is_a} of {properties.get('has_module')}, made from {part_of}.",
        relationships=[{"relationship": "is_a", "related": [is_a]},
                       {"relationship": "part_of", "related": [part_of]},
                       {"relationship": "instantiates", "related": [is_a]}],
        desc_update_mode="replace", shared_connection=shared_connection,
        source="lfpoop_join_effects", properties=properties,
        domain="Halo_Seem", subdomain="Lfpoop_Integration", personal_domain="paiab", produces=[])


def sealed_hops():
    """Every currently valid sealed boundary's hop ranges, read from the HALO SEEM store.

    Returns:
        dict: Boundary to its hops as (file relative to the monorepo, first line, last line).
    """
    from sanctuary_system import seem_ab3, seem_cli, seem_coverage, seem_validity
    root = os.environ.get("DOCMIRROR_MONOREPO", DEFAULT_MONOREPO)
    validity = seem_validity.read_validity(seem_cli.SEEM_HOME)
    return seem_ab3.hops_of(seem_coverage.sealed_spans(validity, root))


def write_call_graph(path, repo, graph, shared_connection=None):
    """Write the Module_Call_Graph partial of one module, the call graph the CA refresh produced.

    Args:
        path: The module's absolute path.
        repo: The repository the CA refresh queued it under.
        graph: {functions, edges} from context-alignment's module_call_graph.
        shared_connection: A graph connection, when the caller holds one.

    Returns:
        str: add_concept's answer for the partial.
    """
    from sanctuary_system import seem_ab3
    root = os.environ.get("DOCMIRROR_MONOREPO", DEFAULT_MONOREPO)
    name, props = seem_ab3.call_graph_partial(path, repo, graph, root)
    return write_concept(name, "Lfpoop_Join_Module_Call_Graph", props, "Lfpoop_Join_A",
                         shared_connection=shared_connection)


def _next_partial(concept_name, shared_connection, make, is_a):
    from sanctuary_system import seem_ab3
    props = node_props(concept_name, shared_connection)
    if props is None:
        return f"{concept_name}: no node in the store; nothing written"
    name, next_props = getattr(seem_ab3, make)(concept_name, props)
    res = write_concept(name, is_a, next_props, concept_name, shared_connection=shared_connection)
    return f"{concept_name} -> {name}: {str(res).splitlines()[0] if res else res}"


def write_rollup_wiring(concept_name, shared_connection=None):
    """Write the Rollup_Wiring partial of a complete Module_Call_Graph.

    Args:
        concept_name: The Lfpoop_Join_Module_Call_Graph node the d-chain fired on.
        shared_connection: The worker's graph connection.

    Returns:
        str: What happened; a failure is returned, never raised, and its traceback logged.
    """
    try:
        return _next_partial(concept_name, shared_connection, "wiring_partial",
                             "Lfpoop_Join_Rollup_Wiring")
    except Exception as e:
        logger.error("write_rollup_wiring(%s) failed:\n%s", concept_name, traceback.format_exc())
        return f"{concept_name}: write_rollup_wiring failed, {type(e).__name__}: {e}"


def write_learned_ring_set(concept_name, shared_connection=None):
    """Write the Learned_Ring_Set partial lfpoop.rollup.learn_rollup learns from a complete Rollup_Wiring.

    Args:
        concept_name: The Lfpoop_Join_Rollup_Wiring node the d-chain fired on.
        shared_connection: The worker's graph connection.

    Returns:
        str: What happened; a failure is returned, never raised, and its traceback logged.
    """
    try:
        return _next_partial(concept_name, shared_connection, "ring_set_partial",
                             "Lfpoop_Join_Learned_Ring_Set")
    except Exception as e:
        logger.error("write_learned_ring_set(%s) failed:\n%s", concept_name, traceback.format_exc())
        return f"{concept_name}: write_learned_ring_set failed, {type(e).__name__}: {e}"


def write_ab3_states(concept_name, shared_connection=None):
    """Record on a complete Learned_Ring_Set the derived AB3 states HALO names its rings by.

    Args:
        concept_name: The Lfpoop_Join_Learned_Ring_Set node the d-chain fired on.
        shared_connection: The worker's graph connection.

    Returns:
        str: What happened; a failure is returned, never raised, and its traceback logged.
    """
    try:
        from sanctuary_system import seem_ab3
        props = node_props(concept_name, shared_connection)
        if props is None:
            return f"{concept_name}: no node in the store; nothing written"
        states = seem_ab3.ab3_states(props, sealed_hops())
        shared_connection.execute_query(
            "MATCH (n:Wiki {n:$n}) SET n.ab3_states = $ab3_states, n.ab3_states_at = $ab3_states_at "
            "RETURN n.n AS n",
            {"n": concept_name, "ab3_states": json.dumps(states),
             "ab3_states_at": datetime.now(timezone.utc).isoformat()})
        held = sum(1 for s in states if s["boundaries"])
        return f"{concept_name}: {len(states)} AB3 states recorded, {held} held by a sealed boundary"
    except Exception as e:
        logger.error("write_ab3_states(%s) failed:\n%s", concept_name, traceback.format_exc())
        return f"{concept_name}: write_ab3_states failed, {type(e).__name__}: {e}"
