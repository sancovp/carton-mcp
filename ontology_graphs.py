# ontology_graphs.py
#
# ============================================================================
# SOMA-UNIFICATION SPLIT [done 2026-06-16 disable → 2026-06-22 P5 delete] — see journal
#   Scalable_Publishing_Giint_Architecture_Soma_Unification_Removal +
#   Soma_Validation_Architecture / Dchain_Depth_Build (P5).
# STATUS: ENACTED. The ontology TYPE-SYSTEM / _Unnamed fabrication that used to live in this
# module is REPLACED by SOMA (gnosys-vault GIINT presence d-chains, PROVEN LIVE FIX-4): the
# missing-child mereology gap is COMPUTED + surfaced as unmet_requirement in the SOMA verdict,
# never fabricated here. Per Isaac: "EVERY SINGLE THING THAT MENTIONS SYSTEM TYPE OR ONTOLOGY
# SHOULD NOT EXIST OUTSIDE OF SOMA."
#
# DELETED (P5, 2026-06-22 — replace-before-remove; zero live callers verified):
#   ONTOLOGY_SCHEMAS dict, ensure_ontology_completeness (the fabricator),
#   _parent_has_child_via_rel, _get_is_a_types. (Their dead caller block in
#   carton_utils.enforce_ontology_invariants was tombstoned in the same pass.)
#
# WHAT THIS MODULE IS NOW (all KEEP — no SOMA replacement, still live):
#   _normalize, _concept_exists                 — used by the Task-HC writer
#   _auto_create_task_hypercluster              — world-graph Task-HC writer; daemon calls it
#                                                 directly for giint_task
#   get_expanded_metagraph + format_metagraph_for_memory — MEMORY.md compiler
#                                                 (consumed by substrate_projector.py)
#   get_seed_ship_stats                         — dashboard stats
#                                                 (consumed by starlog-mcp/score_compiler.py)
# ============================================================================
"""
CartON Ontology Object Graphs — Self-Healing Type System

When a concept is created with IS_A matching a known ontology type,
CartON checks if all required structural parts exist. If they don't,
it creates them silently. Each auto-created part triggers its OWN
schema check recursively.

This is NOT YOUKNOW (general validation). This is CartON's own
structural type system: "if you say you're a Starsystem, you MUST
have Task_Collections, Done_Signal_Collections, etc."

The ontology objects don't scold — they fix.
"""

import logging
import sys
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)



# ============================================================
# ONTOLOGY TYPE SCHEMAS
# ============================================================
# Each schema defines what MUST exist when a concept of that type
# is created. "required_children" are auto-created if missing.
#
# Child format:
#   suffix: appended to parent name (Parent_Name + "_" + suffix)
#   is_a: what type the child IS
#   rel_from_parent: relationship FROM parent TO child
#   description: auto-generated description
#
# Children can themselves be ontology types, causing recursive creation.
# ============================================================

# [P5 DELETED 2026-06-22] ONTOLOGY_SCHEMAS — the Python placeholder-type dict that drove the deleted fabricator. The GIINT/collection structural type system now lives in SOMA (gnosys-vault d-chains), per 'EVERY SINGLE THING THAT MENTIONS SYSTEM TYPE OR ONTOLOGY SHOULD NOT EXIST OUTSIDE OF SOMA'.


def _normalize(name: str) -> str:
    """Normalize concept name to Title_Case_With_Underscores (matches CartON storage)."""
    return name.replace("-", "_").replace("_", " ").title().replace(" ", "_")


def _concept_exists(concept_name: str, shared_connection) -> bool:
    """Check if a concept exists in Neo4j (normalizes name first)."""
    if not shared_connection:
        return False
    normalized = _normalize(concept_name)
    try:
        result = shared_connection.execute_query(
            "MATCH (n:Wiki {n: $name}) RETURN n.n as name LIMIT 1",
            {"name": normalized}
        )
        return bool(result)
    except Exception as e:
        logger.warning(f"[ONTOLOGY] Error checking existence of {normalized}: {e}")
        return False


# [P5 DELETED 2026-06-22] _parent_has_child_via_rel + _get_is_a_types — helpers used ONLY by the deleted ensure_ontology_completeness fabricator. Their job (the mereology-presence gap) now lives in SOMA's GIINT presence d-chain premises.


# [P5 DELETED 2026-06-22] ensure_ontology_completeness — the _Unnamed fabricator. REPLACED by SOMA's gnosys-vault GIINT presence d-chains (the missing-child gap is COMPUTED + surfaced as unmet_requirement, not fabricated). zero live callers (its disabled body already returned []; daemon Phase 2.5 + the disabled server enforce-thread no longer reach it). The Task-HC writer _auto_create_task_hypercluster (below) STAYS.


def _auto_create_task_hypercluster(
    task_name: str,
    relationship_dict: Dict[str, List[str]],
    shared_connection,
) -> List[str]:
    """
    Auto-create a Hypercluster for a GIINT_Task.

    Traces PART_OF upward to find the GIINT_Project and Starsystem,
    then creates Hypercluster_{TaskShortName} in {Starsystem}_Task_Collections.
    """
    graph = shared_connection
    created = []

    # Derive short name (strip Giint_Task_ prefix)
    short_name = task_name
    for prefix in ("Giint_Task_", "GIINT_Task_"):
        if task_name.startswith(prefix):
            short_name = task_name[len(prefix):]
            break

    hc_name = f"Hypercluster_{short_name}"

    # Already exists? Skip.
    if _concept_exists(hc_name, graph):
        return []

    # Trace upward to find GIINT_Project (up to 4 hops: task→deliv→comp→feat→proj)
    proj_q = """
    MATCH (t:Wiki {n: $task})-[:PART_OF*1..4]->(p:Wiki)
    WHERE p.n STARTS WITH 'Giint_Project_' OR p.n STARTS WITH 'GIINT_Project_'
    RETURN p.n as project LIMIT 1
    """
    proj_result = graph.execute_query(proj_q, {"task": task_name})
    if not proj_result:
        return []

    project_name = proj_result[0]["project"] if isinstance(proj_result[0], dict) else proj_result[0]["project"]

    # Find starsystem's Task_Collections
    tc_q = """
    MATCH (p:Wiki {n: $proj})-[:PART_OF*1..3]->(ss:Wiki)-[:HAS_PART]->(tc:Wiki)
    WHERE ss.n ENDS WITH '_Collection'
    AND tc.n ENDS WITH '_Task_Collections'
    RETURN tc.n as task_collections LIMIT 1
    """
    tc_result = graph.execute_query(tc_q, {"proj": project_name})
    if not tc_result:
        return []

    task_collections = tc_result[0]["task_collections"] if isinstance(tc_result[0], dict) else tc_result[0]["task_collections"]

    # Create the Hypercluster
    from carton_mcp.add_concept_tool import add_concept_tool_func
    hc_rels = [
        {"relationship": "is_a", "related": ["Hypercluster"]},
        {"relationship": "part_of", "related": [task_collections]},
        {"relationship": "instantiates", "related": ["Hypercluster_Template"]},
        {"relationship": "has_giint_project", "related": [project_name]},
        {"relationship": "has_status", "related": ["Active"]},
    ]

    add_concept_tool_func(
        concept_name=hc_name,
        description=f"Task HC for {task_name}",
        relationships=hc_rels,
        hide_youknow=True,
        shared_connection=shared_connection,
        _skip_ontology_healing=True,
    )
    created.append(hc_name)
    print(f"[ONTOLOGY] Auto-created HC: {hc_name} for task {task_name}", file=sys.stderr)

    return created


def get_expanded_metagraph(
    hypercluster_name: str,
    shared_connection,
) -> Dict[str, Any]:
    """
    Trace the full expanded metagraph from a hypercluster up to its starsystem.

    Returns a nested dict of concept names (NO descriptions) following
    typed relationships: HAS_GIINT_PROJECT → HAS_FEATURE → HAS_COMPONENT →
    HAS_DELIVERABLE → HAS_TASK, plus PART_OF chain up to starsystem.

    This is what gets written to MEMORY.md for the active task HC.

    Args:
        hypercluster_name: The hypercluster to trace
        shared_connection: Neo4j connection

    Returns:
        Dict with structure:
        {
            "hypercluster": "Hypercluster_X",
            "starsystem": "Starsystem_Y_Collection",
            "collection_category": "Starsystem_Y_Task_Collections",
            "giint_hierarchy": {
                "project": "GIINT_Project_X",
                "features": [
                    {
                        "name": "GIINT_Feature_Y",
                        "components": [
                            {
                                "name": "GIINT_Component_Z",
                                "deliverables": [
                                    {
                                        "name": "GIINT_Deliverable_W",
                                        "tasks": ["GIINT_Task_V1", "GIINT_Task_V2"]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            "other_concepts": ["Bug_X", "Pattern_Y", "Inclusion_Map_Z"]
        }
    """
    if not shared_connection:
        return {"error": "No Neo4j connection"}

    graph = shared_connection
    result = {
        "hypercluster": hypercluster_name,
        "starsystem": None,
        "collection_category": None,
        "giint_hierarchy": None,
        "other_concepts": [],
    }

    try:
        # 1. Find starsystem (trace PART_OF upward)
        starsystem_q = """
        MATCH (hc:Wiki {n: $hc_name})-[:PART_OF*1..3]->(ss:Wiki)
        WHERE ss.n ENDS WITH '_Collection'
        AND (ss)-[:IS_A]->(:Wiki {n: 'Starsystem_Collection'})
        RETURN ss.n as starsystem
        LIMIT 1
        """
        ss_result = graph.execute_query(starsystem_q, {"hc_name": hypercluster_name})
        if ss_result:
            result["starsystem"] = ss_result[0]["starsystem"] if isinstance(ss_result[0], dict) else ss_result[0]["starsystem"]

        # 2. Find collection category (direct PART_OF parent)
        cat_q = """
        MATCH (hc:Wiki {n: $hc_name})-[:PART_OF]->(cat:Wiki)-[:IS_A]->(:Wiki {n: 'Collection_Category'})
        RETURN cat.n as category
        LIMIT 1
        """
        cat_result = graph.execute_query(cat_q, {"hc_name": hypercluster_name})
        if cat_result:
            result["collection_category"] = cat_result[0]["category"] if isinstance(cat_result[0], dict) else cat_result[0]["category"]

        # 3. Find GIINT project (HAS_GIINT_PROJECT or HAS_PART where child IS_A GIINT_Project)
        proj_q = """
        MATCH (hc:Wiki {n: $hc_name})-[:HAS_GIINT_PROJECT|HAS_PART]->(proj:Wiki)
        WHERE proj.n STARTS WITH 'Giint_Project_' OR proj.n STARTS WITH 'GIINT_Project_'
        RETURN proj.n as project
        LIMIT 1
        """
        proj_result = graph.execute_query(proj_q, {"hc_name": hypercluster_name})

        if proj_result:
            project_name = proj_result[0]["project"] if isinstance(proj_result[0], dict) else proj_result[0]["project"]
            hierarchy = {"project": project_name, "features": []}

            # 4. Get features (HAS_PART or HAS_FEATURE, filtered by IS_A or name prefix)
            feat_q = """
            MATCH (proj:Wiki {n: $proj})-[:HAS_PART|HAS_FEATURE]->(f:Wiki)
            WHERE f.n STARTS WITH 'Giint_Feature_' OR f.n STARTS WITH 'GIINT_Feature_'
               OR (f)-[:IS_A]->(:Wiki {n: 'Giint_Feature'})
            RETURN DISTINCT f.n as feature ORDER BY f.n
            """
            feat_result = graph.execute_query(feat_q, {"proj": project_name})

            if feat_result:
                for feat_rec in feat_result:
                    feat_name = feat_rec["feature"] if isinstance(feat_rec, dict) else feat_rec["feature"]
                    feature = {"name": feat_name, "components": []}

                    # 5. Get components
                    comp_q = """
                    MATCH (f:Wiki {n: $feat})-[:HAS_PART|HAS_COMPONENT]->(c:Wiki)
                    WHERE c.n STARTS WITH 'Giint_Component_' OR c.n STARTS WITH 'GIINT_Component_'
                       OR (c)-[:IS_A]->(:Wiki {n: 'Giint_Component'})
                    RETURN DISTINCT c.n as component ORDER BY c.n
                    """
                    comp_result = graph.execute_query(comp_q, {"feat": feat_name})

                    if comp_result:
                        for comp_rec in comp_result:
                            comp_name = comp_rec["component"] if isinstance(comp_rec, dict) else comp_rec["component"]
                            component = {"name": comp_name, "deliverables": []}

                            # 6. Get deliverables
                            del_q = """
                            MATCH (c:Wiki {n: $comp})-[:HAS_PART|HAS_DELIVERABLE]->(d:Wiki)
                            WHERE d.n STARTS WITH 'Giint_Deliverable_' OR d.n STARTS WITH 'GIINT_Deliverable_'
                               OR (d)-[:IS_A]->(:Wiki {n: 'Giint_Deliverable'})
                            RETURN DISTINCT d.n as deliverable ORDER BY d.n
                            """
                            del_result = graph.execute_query(del_q, {"comp": comp_name})

                            if del_result:
                                for del_rec in del_result:
                                    del_name = del_rec["deliverable"] if isinstance(del_rec, dict) else del_rec["deliverable"]
                                    deliverable = {"name": del_name, "tasks": []}

                                    # 7. Get tasks
                                    task_q = """
                                    MATCH (d:Wiki {n: $del})-[:HAS_PART|HAS_TASK]->(t:Wiki)
                                    WHERE t.n STARTS WITH 'Giint_Task_' OR t.n STARTS WITH 'GIINT_Task_'
                                       OR (t)-[:IS_A]->(:Wiki {n: 'Giint_Task'})
                                    RETURN DISTINCT t.n as task ORDER BY t.n
                                    """
                                    task_result = graph.execute_query(task_q, {"del": del_name})

                                    if task_result:
                                        for task_rec in task_result:
                                            task_name = task_rec["task"] if isinstance(task_rec, dict) else task_rec["task"]
                                            # Check for done signal
                                            done_q = """
                                            MATCH (t:Wiki {n: $task})-[:HAS_DONE_SIGNAL]->(s:Wiki)
                                            RETURN s.n as signal LIMIT 1
                                            """
                                            done_result = graph.execute_query(done_q, {"task": task_name})
                                            has_done = bool(done_result)
                                            deliverable["tasks"].append({"name": task_name, "done": has_done})

                                    component["deliverables"].append(deliverable)

                            feature["components"].append(component)

                    hierarchy["features"].append(feature)

            result["giint_hierarchy"] = hierarchy

        # 8. Get other concepts PART_OF this HC (bugs, patterns, solutions, etc.)
        other_q = """
        MATCH (c:Wiki)-[:PART_OF]->(hc:Wiki {n: $hc_name})
        WHERE NOT c.n STARTS WITH 'Giint_'
        AND NOT c.n STARTS WITH 'GIINT_'
        RETURN c.n as concept ORDER BY c.n
        """
        other_result = graph.execute_query(other_q, {"hc_name": hypercluster_name})
        if other_result:
            for rec in other_result:
                name = rec["concept"] if isinstance(rec, dict) else rec["concept"]
                result["other_concepts"].append(name)

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[ONTOLOGY] Error tracing metagraph for {hypercluster_name}: {e}")

    return result


def format_metagraph_for_memory(metagraph: Dict[str, Any]) -> str:
    """
    Format an expanded metagraph as names-only text for MEMORY.md.

    Args:
        metagraph: Output from get_expanded_metagraph()

    Returns:
        Formatted string with names only, indented hierarchy
    """
    lines = []

    if metagraph.get("error"):
        return f"Error: {metagraph['error']}"

    hc = metagraph.get("hypercluster", "Unknown")
    ss = metagraph.get("starsystem", "Unknown")
    cat = metagraph.get("collection_category", "Unknown")

    lines.append(f"## Active HC: {hc}")
    lines.append(f"Starsystem: {ss}")
    if cat:
        lines.append(f"Category: {cat}")

    hierarchy = metagraph.get("giint_hierarchy")
    if hierarchy:
        lines.append("")
        lines.append("### GIINT Hierarchy")
        lines.append(f"- {hierarchy['project']}")

        for feature in hierarchy.get("features", []):
            lines.append(f"  - {feature['name']}")
            for component in feature.get("components", []):
                lines.append(f"    - {component['name']}")
                for deliverable in component.get("deliverables", []):
                    lines.append(f"      - {deliverable['name']}")
                    for task in deliverable.get("tasks", []):
                        if isinstance(task, dict):
                            prefix = "✅" if task.get("done") else "⬜"
                            lines.append(f"        - {prefix} {task['name']}")
                        else:
                            lines.append(f"        - {task}")

    other = metagraph.get("other_concepts", [])
    if other:
        lines.append("")
        lines.append(f"### Concepts ({len(other)}):")
        for c in other:
            lines.append(f"- **{c}**")

    return "\n".join(lines)


# ============================================================
# SCHEMA QUERY API (for reward_system, scoring, validation)
# ============================================================

# DEAD CODE — Commented out 2026-03-29. get_schema_for_type, get_all_ontology_types, materialize_ontology_types all read from ONTOLOGY_SCHEMAS Python dict which is a shadow of uarl.owl. The OWL + SHACL + reasoner (youknow()) now handles all type validation. Type materialization happens through ensure_ontology_completeness which still uses the dict (TODO: migrate to OWL-driven).
# def get_schema_for_type(type_name: str) -> Optional[Dict[str, Any]]:
    # """Get the ontology schema for a given type. Returns None if not a known ontology type."""
    # return ONTOLOGY_SCHEMAS.get(type_name)


# def get_all_ontology_types() -> List[str]:
    # """Return all known ontology type names."""
    # return list(ONTOLOGY_SCHEMAS.keys())


# def materialize_ontology_types(shared_connection) -> List[str]:
    # """
    # Ensure every type in ONTOLOGY_SCHEMAS exists as a concept in Neo4j.

    # Bounded: iterates ONLY the ONTOLOGY_SCHEMAS dict (finite, known list).
    # For each type, checks if it exists with a description. If not, creates it.

    # Returns:
        # List of newly created type concept names
    # """
    # if not shared_connection:
        # return []

    # created = []
    # from carton_mcp.add_concept_tool import add_concept_tool_func

    # for type_name, schema in ONTOLOGY_SCHEMAS.items():
        # normalized = _normalize(type_name)

        # # Check if exists with a description
        # try:
            # result = shared_connection.execute_query(
                # "MATCH (n:Wiki {n: $name}) WHERE n.d IS NOT NULL AND n.d <> '' RETURN n.n as name LIMIT 1",
                # {"name": normalized}
            # )
            # if result:
                # continue  # Already exists with description
        # except Exception:
            # pass

        # # Create the universal type concept
        # try:
            # add_concept_tool_func(
                # concept_name=type_name,
                # description=schema.get("description", f"Ontology type: {type_name}"),
                # relationships=[
                    # {"relationship": "is_a", "related": ["Carton_Ontology_Entity"]},
                    # {"relationship": "part_of", "related": ["CartON_System"]},
                # ],
                # hide_youknow=True,
                # shared_connection=shared_connection,
            # )
            # created.append(normalized)
        # except Exception as e:
            # print(f"[ONTOLOGY] WARN: Could not materialize {normalized}: {e}", file=sys.stderr)

    # return created


# DEAD CODE — Commented out 2026-03-29. ensure_instances_have_is_a walks ONTOLOGY_SCHEMAS and injects IS_A via Neo4j queries. Dragonbones inject_giint_types() handles IS_A injection at parse time. The reasoner validates IS_A via SHACL EntityBaseShape.
# def ensure_instances_have_is_a(shared_connection) -> List[str]:
    # """
    # For each ONTOLOGY_SCHEMAS type, find concepts whose name matches
    # the type's naming convention and ensure they have IS_A that type.

    # Bounded: one query per ONTOLOGY_SCHEMAS key (finite, known list).
    # E.g. any concept named Giint_Project_% should IS_A Giint_Project.

    # Returns:
        # List of concept names that had IS_A added
    # """
    # if not shared_connection:
        # return []

    # fixed = []

    # # Map each schema type to its expected name prefix
    # # E.g. GIINT_Project -> concepts starting with Giint_Project_
    # for type_name in ONTOLOGY_SCHEMAS:
        # normalized_type = _normalize(type_name)
        # prefix = normalized_type + "_"

        # try:
            # # Find instances that match prefix but lack IS_A this type
            # query = """
            # MATCH (n:Wiki)
            # WHERE n.n STARTS WITH $prefix
            # AND NOT (n)-[:IS_A]->(:Wiki {n: $type_name})
            # AND n.n <> $type_name
            # RETURN n.n as name
            # """
            # result = shared_connection.execute_query(query, {
                # "prefix": prefix,
                # "type_name": normalized_type,
            # })

            # if not result:
                # continue

            # for rec in result:
                # instance_name = rec["name"] if isinstance(rec, dict) else rec["name"]
                # # Skip concepts that ARE ontology types themselves (exact match or _Template suffix)
                # # e.g. Starsystem_Collection_Template should NOT get IS_A Starsystem_Collection
                # bare = instance_name[len(prefix):]  # what comes after the type prefix
                # if bare in ("Template",) or instance_name in (_normalize(t) for t in ONTOLOGY_SCHEMAS):
                    # continue
                # try:
                    # # Add the missing IS_A relationship
                    # link_query = """
                    # MATCH (instance:Wiki {n: $instance}), (type:Wiki {n: $type_name})
                    # MERGE (instance)-[:IS_A]->(type)
                    # """
                    # shared_connection.execute_query(link_query, {
                        # "instance": instance_name,
                        # "type_name": normalized_type,
                    # })
                    # fixed.append(instance_name)
                # except Exception as e:
                    # print(f"[ONTOLOGY] WARN: Could not link {instance_name} IS_A {normalized_type}: {e}", file=sys.stderr)

        # except Exception as e:
            # print(f"[ONTOLOGY] WARN: IS_A check for {normalized_type} failed: {e}", file=sys.stderr)

    # return fixed


def get_seed_ship_stats(shared_connection) -> Dict[str, Any]:
    """
    Query Seed Ship stats using ontology schema knowledge.

    (Counts via direct Cypher queries below; the "Uses ONTOLOGY_SCHEMAS" claim was
    stale docstring prose — this function never referenced that dict. DISABLED 2026-06-16.)
    The ontology module knows: Seed_Ship HAS Starsystems, Kardashev_Map, Sanctum.
    Starsystems contain Starsystem_Collection types. HCs are Hypercluster types.
    GIINT_Tasks have has_status. Learnings = Pattern_ + Inclusion_Map_ prefixes.

    Returns:
        Dict with state, starsystems, active_hcs, completed_hcs,
        completed_tasks, total_concepts, learnings
    """
    stats = {
        "state": "Wasteland",
        "starsystems": 0,
        "active_hcs": 0,
        "completed_hcs": 0,
        "completed_tasks": 0,
        "total_concepts": 0,
        "learnings": 0,
    }

    if not shared_connection:
        return stats

    graph = shared_connection

    try:
        # Independent count queries — no chained OPTIONAL MATCH cross-products
        queries = {
            "total_concepts": "MATCH (c:Wiki) RETURN count(c) as v",
            "starsystems": "MATCH (ss:Wiki)-[:IS_A]->(:Wiki {n: 'Starsystem_Collection'}) RETURN count(ss) as v",
            "active_hcs": (
                "MATCH (hc:Wiki)-[:IS_A]->(:Wiki {n: 'Hypercluster'}) "
                "WHERE NOT (hc)-[:PART_OF]->(:Wiki)-[:IS_A]->(:Wiki {n: 'Completed_Collection_Category'}) "
                "RETURN count(hc) as v"
            ),
            "completed_hcs": (
                "MATCH (chc:Wiki)-[:IS_A]->(:Wiki {n: 'Hypercluster'}) "
                "WHERE (chc)-[:PART_OF]->(:Wiki)-[:IS_A]->(:Wiki {n: 'Completed_Collection_Category'}) "
                "RETURN count(chc) as v"
            ),
            "completed_tasks": (
                "MATCH (t:Wiki)-[:IS_A]->(:Wiki {n: 'GIINT_Task'}) "
                "WHERE (t)-[:HAS_STATUS]->(:Wiki {n: 'Done'}) "
                "RETURN count(t) as v"
            ),
            "learnings": (
                "MATCH (p:Wiki) "
                "WHERE p.n STARTS WITH 'Pattern_' OR p.n STARTS WITH 'Inclusion_Map_' "
                "RETURN count(p) as v"
            ),
        }

        for key, query in queries.items():
            try:
                result = graph.execute_query(query)
                if result and len(result) > 0:
                    row = result[0]
                    stats[key] = row["v"] if isinstance(row, dict) else 0
            except Exception:
                pass  # individual stat fails silently, others still work

        # Seed Ship state (binary: Wasteland or Sanctuary)
        state_result = graph.execute_query(
            "MATCH (s:Wiki {n: 'Seed_Ship'})-[:HAS_STATE]->(st:Wiki) RETURN st.n as state LIMIT 1"
        )
        if state_result and len(state_result) > 0:
            st = state_result[0]
            stats["state"] = st["state"] if isinstance(st, dict) else "Wasteland"

    except Exception as e:
        logger.warning(f"[ONTOLOGY] Seed Ship stats query failed: {e}")

    return stats


# DEAD CODE — Commented out 2026-03-29. get_completeness_score reads from ONTOLOGY_SCHEMAS to score completeness. reward_system.py now handles starsystem scoring via CartON queries, and the reasoner validates completeness via SHACL.
# def get_completeness_score(
    # concept_name: str,
    # shared_connection,
# ) -> Dict[str, Any]:
    # """
    # Score how complete a concept is relative to its ontology schema.

    # Checks which expected_relationships exist vs which are missing.
    # Used by reward_system to compute hierarchy completeness from a single
    # canonical source instead of ad-hoc Cypher queries.

    # Returns:
        # {
            # "concept": concept_name,
            # "type": "Starsystem_Collection",
            # "score": 0.75,  # fraction of expected rels present
            # "present": ["has_part", "depends_on"],
            # "missing": ["has_skill"],
            # "required_children_present": 5,
            # "required_children_total": 5,
        # }
    # """
    # if not shared_connection:
        # return {"concept": concept_name, "score": 0.0, "error": "No connection"}

    # graph = shared_connection

    # # Find what types this concept IS
    # is_a_types = _get_is_a_types(concept_name, graph)
    # if not is_a_types:
        # return {"concept": concept_name, "score": 0.0, "error": "No IS_A types found"}

    # # Find matching schema
    # matched_schema = None
    # matched_type = None
    # for t in is_a_types:
        # if t in ONTOLOGY_SCHEMAS:
            # matched_schema = ONTOLOGY_SCHEMAS[t]
            # matched_type = t
            # break

    # if not matched_schema:
        # return {"concept": concept_name, "score": 1.0, "type": None, "note": "Not an ontology type"}

    # result = {
        # "concept": concept_name,
        # "type": matched_type,
        # "present": [],
        # "missing": [],
        # "required_children_present": 0,
        # "required_children_total": 0,
    # }

    # # Check required children
    # required_children = matched_schema.get("required_children", [])
    # result["required_children_total"] = len(required_children)
    # for child_spec in required_children:
        # child_name = f"{concept_name}_{child_spec['suffix']}"
        # if _concept_exists(child_name, graph):
            # result["required_children_present"] += 1

    # # Check expected relationships
    # expected_rels = matched_schema.get("expected_relationships", [])
    # if expected_rels:
        # # Query all outgoing relationships for this concept
        # rel_q = """
        # MATCH (n:Wiki {n: $name})-[r]->(target:Wiki)
        # RETURN DISTINCT toLower(type(r)) as rel_type
        # """
        # try:
            # rel_result = graph.execute_query(rel_q, {"name": concept_name})
            # existing_rels = set()
            # if rel_result:
                # for rec in rel_result:
                    # rt = rec["rel_type"] if isinstance(rec, dict) else rec["rel_type"]
                    # existing_rels.add(rt)

            # for expected in expected_rels:
                # if expected.lower() in existing_rels:
                    # result["present"].append(expected)
                # else:
                    # result["missing"].append(expected)
        # except Exception:
            # result["missing"] = expected_rels

    # # Compute score
    # total_checks = len(required_children) + len(expected_rels)
    # if total_checks == 0:
        # result["score"] = 1.0
    # else:
        # passed = result["required_children_present"] + len(result["present"])
        # result["score"] = round(passed / total_checks, 2)

    # return result
