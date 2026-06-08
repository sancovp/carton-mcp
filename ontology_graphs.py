# ontology_graphs.py
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

ONTOLOGY_SCHEMAS = {
    # ================================================================
    # SEED SHIP — Root graph node (one per user, hardcoded)
    # HAS: starsystems, kardashev map, SANCTUM
    # ================================================================

    "Seed_Ship": {
        "description": "Root graph node for user's fleet. One per user. HAS starsystems, kardashev map, and SANCTUM.",
        "required_children": [
            {
                "suffix": "Starsystems",
                "is_a": ["Starsystem_Registry"],
                "instantiates": "Starsystem_Registry_Template",
                "rel_from_parent": "has_part",
                "description": "Registry of all starsystem concepts in this Seed Ship",
            },
            {
                "suffix": "Kardashev_Map",
                "is_a": ["Kardashev_Map"],
                "instantiates": "Kardashev_Map_Template",
                "rel_from_parent": "has_part",
                "description": "Navy organization and Kardashev progression for this Seed Ship",
            },
            {
                "suffix": "Sanctum",
                "is_a": ["Sanctum"],
                "instantiates": "Sanctum_Template",
                "rel_from_parent": "has_part",
                "description": "Life architecture system for this Seed Ship's user",
            },
        ],
        "expected_relationships": [
            "has_part",     # starsystems, kardashev, sanctum
            "has_state",    # Binary: Wasteland or Sanctuary
        ],
    },

    # ================================================================
    # STARSYSTEM HIERARCHY (from starlog_mcp + llm_intelligence_mcp)
    # ================================================================

    "Starsystem_Collection": {
        "description": "A STARSYSTEM is a colonized repository with full collection hierarchy",
        "required_children": [
            {
                "suffix": "Task_Collections",
                "is_a": ["Collection_Category"],
                "instantiates": "Task_Collection_Category",
                "rel_from_parent": "has_part",
                "description": "Active task hyperclusters for this starsystem",
            },
            {
                "suffix": "Done_Signal_Collections",
                "is_a": ["Collection_Category"],
                "instantiates": "Done_Signal_Collection_Category",
                "rel_from_parent": "has_part",
                "description": "Agent-claimed done hyperclusters (unverified)",
            },
            {
                "suffix": "Completed_Collections",
                "is_a": ["Collection_Category"],
                "instantiates": "Completed_Collection_Category",
                "rel_from_parent": "has_part",
                "description": "CE-verified completed hyperclusters",
            },
            {
                "suffix": "Architecture_Collections",
                "is_a": ["Collection_Category"],
                "instantiates": "Architecture_Collection_Category",
                "rel_from_parent": "has_part",
                "description": "Architecture knowledge collections for this starsystem",
            },
            {
                "suffix": "Bug_Collections",
                "is_a": ["Collection_Category"],
                "instantiates": "Bug_Collection_Category",
                "rel_from_parent": "has_part",
                "description": "Bug tracking collections for this starsystem",
            },
            {
                "strip_prefix": "Starsystem_",
                "child_prefix": "GIINT_Project_",
                "suffix": "Unnamed",
                "is_a": ["GIINT_Project"],
                "instantiates": "GIINT_Project",
                "rel_from_parent": "has_giint_project",
                "description": "GIINT project for this starsystem — rename when scope clarifies",
            },
        ],
        # Expected relationships for scoring (not auto-created, but reward_system queries for these)
        "expected_relationships": [
            "has_part",         # collection categories (auto-created above)
            "has_skill",        # Skill concepts linked to starsystem (discovered)
            "has_agent",        # Agent concepts (discovered)
            "has_flight_config",# Flight_Config concepts (discovered)
            "has_persona",      # Persona concepts (discovered)
            "has_mcp_server",   # MCP_Server concepts (discovered)
            "depends_on",       # inter-starsystem relations
            "uses",             # inter-starsystem relations
            "integrates_with",  # inter-starsystem relations
        ],
    },

    "Hypercluster": {
        "description": "A hypercluster is created BY a GIINT task. Contains the full work graph.",
        "required_children": [],
        # Hypercluster doesn't auto-create GIINT_Project — that's specified by the creator.
        # But it MUST be part of a Task_Collections category.
        "expected_relationships": [
            "has_giint_project",  # link to the GIINT_Project
            "has_status",         # Active, Done_Signal, Completed
            "part_of",            # must be in a Collection_Category
        ],
    },

    "Collection_Category": {
        "description": "A category container within a starsystem collection.",
        "required_children": [],
        # Collection categories hold hyperclusters — no auto-children.
    },

    # ================================================================
    # GIINT HIERARCHY (from llm_intelligence_mcp/carton_sync.py)
    # PROJECT → FEATURE → COMPONENT → DELIVERABLE → TASK
    # ================================================================

    "GIINT_Project": {
        "description": "Top-level project containing full GIINT hierarchy",
        "required_children": [
            {
                "strip_prefix": "GIINT_Project_",
                "child_prefix": "GIINT_Feature_",
                "is_a": ["GIINT_Feature"],
                "instantiates": "GIINT_Feature",
                "rel_from_parent": "has_feature",
                "description": "Feature for this project — rename when scope clarifies",
            },
        ],
        "expected_relationships": [
            "has_feature",    # downward: HAS_FEATURE → GIINT_Feature
            "part_of",        # upward: PART_OF → Hypercluster
        ],
    },

    "GIINT_Feature": {
        "description": "A feature within a GIINT project.",
        "required_children": [
            {
                "strip_prefix": "GIINT_Feature_",
                "child_prefix": "GIINT_Component_",
                "is_a": ["GIINT_Component"],
                "instantiates": "GIINT_Component",
                "rel_from_parent": "has_component",
                "description": "Component for this feature — rename when scope clarifies",
            },
        ],
        "expected_relationships": [
            "has_component",  # downward: HAS_COMPONENT → GIINT_Component
            "part_of",        # upward: PART_OF → GIINT_Project
        ],
    },

    "GIINT_Component": {
        "description": "A buildable component within a feature.",
        "required_children": [
            {
                "strip_prefix": "GIINT_Component_",
                "child_prefix": "GIINT_Deliverable_",
                "is_a": ["GIINT_Deliverable"],
                "instantiates": "GIINT_Deliverable",
                "rel_from_parent": "has_deliverable",
                "description": "Deliverable for this component — rename when scope clarifies",
            },
        ],
        "expected_relationships": [
            "has_deliverable",  # downward: HAS_DELIVERABLE → GIINT_Deliverable
            "part_of",          # upward: PART_OF → GIINT_Feature
        ],
    },

    "GIINT_Deliverable": {
        "description": "A shippable deliverable within a component.",
        "required_children": [],
        # Tasks come from TreeKanban — NEVER auto-created.
        "expected_relationships": [
            "has_task",  # downward: HAS_TASK → GIINT_Task
            "part_of",   # upward: PART_OF → GIINT_Component
        ],
    },

    "GIINT_Task": {
        "description": "Atomic work item within a deliverable. Creates its own Hypercluster.",
        "required_children": [],
        # Tasks auto-create a Hypercluster in the starsystem's Task_Collections.
        # This is handled by auto_create_hypercluster (not a simple suffix child).
        "auto_create_hypercluster": True,
        "expected_relationships": [
            "part_of",     # upward: PART_OF → GIINT_Deliverable
            "has_status",  # Ready, In_Progress, Done
        ],
    },

    # ================================================================
    # NAVY HIERARCHY (from starlog_mcp/_sync_kardashev_to_carton)
    # Kardashev_Map → Fleet → Squadron → Starship
    # ================================================================

    "Kardashev_Map": {
        "description": "Top-level container for the fleet/squadron/starship organization",
        "required_children": [],
        # Fleets are dynamic — created from kardashev_map.json, not auto-created
    },

    "Navy_Fleet": {
        "description": "Fleet containing squadrons and optionally loose starships",
        "required_children": [],
        "expected_relationships": [
            "has_squadron",        # HAS_SQUADRON → Navy_Squadron
            "has_loose_starship",  # HAS_LOOSE_STARSHIP → Navy_Starship
            "has_admiral",         # whether fleet has an admiral
            "part_of",             # PART_OF → Kardashev_Map
        ],
    },

    "Navy_Squadron": {
        "description": "Squadron containing starship members",
        "required_children": [],
        "expected_relationships": [
            "has_member",   # HAS_MEMBER → Navy_Starship
            "has_leader",   # whether squadron has a leader
            "part_of",      # PART_OF → Kardashev_Map (or Fleet via HAS_SQUADRON)
        ],
    },

    "Navy_Starship": {
        "description": "Individual starship linked to a starsystem path. Kardashev level computed from state.",
        "required_children": [],
        "expected_relationships": [
            "has_kardashev_level",  # HAS_KARDASHEV_LEVEL → Kardashev_{Level}
            "part_of",              # PART_OF → Kardashev_Map + Starsystem
        ],
        # Kardashev levels (computed, not stored):
        # Unterraformed → Planetary (has .claude/) → Colonized (has starlog.hpi)
        # → Civilized (has GIINT project) → Stellar (emanation ≥ 0.6)
    },

    # ================================================================
    # REWARD SYSTEM SCORING TYPES (from starsystem-mcp/reward_system.py)
    # These are "discovered" types — not auto-created, but queried for scoring.
    # Including them here so the ontology knows they exist as types.
    # ================================================================

    "Skill": {
        "description": "A skill package that can be equipped by an agent",
        "required_children": [],
        "expected_relationships": [
            "part_of",      # linked to starsystem or domain
            "describes",    # what component this skill describes
            "has_domain",   # domain classification
            "has_category", # understand, preflight, single_turn_process
        ],
    },

    "Flight_Config": {
        "description": "Replayable workflow template for structured task execution",
        "required_children": [],
        "expected_relationships": [
            "part_of",     # linked to starsystem
            "automates",   # what it automates
            "has_domain",  # domain classification
        ],
    },

    "Persona": {
        "description": "Agent persona configuration with equipped skills and flights",
        "required_children": [],
        "expected_relationships": [
            "configures",  # what starsystem this persona configures
            "has_skill",   # skills equipped in this persona
        ],
    },

    "MCP_Server": {
        "description": "Model Context Protocol server providing tools",
        "required_children": [],
        "expected_relationships": [
            "part_of",           # linked to starsystem
            "provides_tools_to", # what it provides tools to
        ],
    },
}


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


def _get_is_a_types(concept_name: str, shared_connection) -> List[str]:
    """Get all IS_A types for a concept from Neo4j."""
    if not shared_connection:
        return []
    try:
        result = shared_connection.execute_query(
            "MATCH (n:Wiki {n: $name})-[:IS_A]->(t:Wiki) RETURN t.n as type_name",
            {"name": concept_name}
        )
        if result:
            return [r["type_name"] for r in result if isinstance(r, dict)]
        return []
    except Exception:
        return []


def ensure_ontology_completeness(
    concept_name: str,
    is_a_list: List[str],
    relationship_dict: Dict[str, List[str]],
    shared_connection=None,
    _depth: int = 0,
) -> List[str]:
    """
    Check if a concept's ontology type requires children, create if missing.

    This is the self-healing heart of CartON's type system. When you say
    IS_A Starsystem_Collection, you GET all the collection categories.
    No questions asked.

    Args:
        concept_name: The concept being created/checked
        is_a_list: What types this concept IS
        relationship_dict: Current relationships
        shared_connection: Neo4j connection for existence checks
        _depth: Recursion guard (max 5 levels)

    Returns:
        List of auto-created concept names (for logging)
    """
    if _depth > 5:
        logger.warning(f"[ONTOLOGY] Max recursion depth reached for {concept_name}")
        return []

    if not shared_connection:
        # Can't check existence without connection — skip silently
        return []

    # Normalize concept_name to match CartON storage (GIINT_ → Giint_)
    concept_name = _normalize(concept_name)

    # Skip _Template concepts — they are schemas, not instances.
    # ensure_instances_have_is_a already skips these, but this function
    # can be called directly. Without this guard, Starsystem_Collection_Template
    # gets treated as a Starsystem_Collection instance and spawns infinite children.
    if concept_name.endswith("_Template") or "_Collections_" in concept_name or concept_name.endswith("_Collections"):
        return []

    created = []

    for type_name in is_a_list:
        schema = ONTOLOGY_SCHEMAS.get(type_name)
        if not schema:
            continue

        required_children = schema.get("required_children", [])
        if not required_children:
            continue

        for child_spec in required_children:
            # Derive child name using one of two strategies:
            # 1. strip_prefix/child_prefix: GIINT types (GIINT_Project_X → GIINT_Feature_X_Default)
            # 2. suffix only: Collection types (Starsystem_X_Collection → Starsystem_X_Task_Collections)
            strip_prefix = child_spec.get("strip_prefix")
            child_prefix = child_spec.get("child_prefix", "")

            if strip_prefix and concept_name.upper().startswith(strip_prefix.upper()):
                # GIINT strategy: replace prefix, keep base name
                # Case-insensitive because CartON normalizes GIINT_ → Giint_
                # e.g. GIINT_Project_Memory_System → GIINT_Feature_Memory_System
                base_name = concept_name[len(strip_prefix):]
                suffix = child_spec.get("suffix", "Unnamed")
                # Strip _Collection suffix (from starsystem collection naming)
                if base_name.endswith("_Collection"):
                    base_name = base_name[:-len("_Collection")]
                # Strip existing suffix to prevent compounding (_Unnamed_Unnamed)
                if suffix and base_name.endswith(f"_{suffix}"):
                    base_name = base_name[:-len(f"_{suffix}")]
                child_name = _normalize(f"{child_prefix}{base_name}_{suffix}")
            else:
                # Collection strategy: strip _Collection suffix, append child suffix
                base_name = concept_name
                if base_name.endswith("_Collection"):
                    base_name = base_name[:-len("_Collection")]
                child_name = _normalize(f"{base_name}_{child_spec['suffix']}")

            # Already exists? Skip.
            if _concept_exists(child_name, shared_connection):
                continue
            # Also check the full-name variant (in case it was created that way)
            full_child_name = f"{concept_name}_{child_spec.get('suffix', 'Unnamed')}"
            if full_child_name != child_name and _concept_exists(full_child_name, shared_connection):
                continue

            # Build child relationships
            # Use specific instantiates from spec if provided, else derive from IS_A
            instantiates_target = child_spec.get("instantiates", f"{child_spec['is_a'][0]}_Template")
            child_rels = [
                {"relationship": "is_a", "related": child_spec["is_a"]},
                {"relationship": "part_of", "related": [concept_name]},
                {"relationship": "instantiates", "related": [instantiates_target]},
            ]

            child_desc = child_spec.get("description", f"Auto-created child for {concept_name}")

            # Queue the child concept through add_concept_tool_func
            try:
                from carton_mcp.add_concept_tool import add_concept_tool_func
                result = add_concept_tool_func(
                    concept_name=child_name,
                    description=child_desc,
                    relationships=child_rels,
                    hide_youknow=True,
                    shared_connection=shared_connection,
                    _skip_ontology_healing=True,
                )
                created.append(child_name)
                print(f"[ONTOLOGY] Auto-created: {child_name} (required by {concept_name})", file=sys.stderr)

                # Create parent→child relationship (e.g., HAS_FEATURE, HAS_COMPONENT)
                rel_from_parent = child_spec.get("rel_from_parent")
                if rel_from_parent:
                    try:
                        rel_type = rel_from_parent.upper()
                        parent_child_query = """
                        MATCH (p:Wiki {n: $parent}), (c:Wiki {n: $child})
                        MERGE (p)-[r:%s]->(c)
                        SET r.ts = datetime()
                        """ % rel_type
                        shared_connection.execute_query(parent_child_query, {
                            "parent": concept_name, "child": child_name
                        })
                        print(f"[ONTOLOGY] Linked: {concept_name} -{rel_type}-> {child_name}", file=sys.stderr)
                    except Exception as link_err:
                        print(f"[ONTOLOGY] WARN: Could not link parent→child: {link_err}", file=sys.stderr)

                # Recurse: the child might ALSO be an ontology type
                # BUT: never recurse on _Unnamed children — they are scaffolding
                # placeholders, not real concepts that need their own children.
                # Recursing on them causes infinite explosion (scaffolding scaffolding).
                if "_Unnamed" not in child_name:
                    child_is_a = child_spec["is_a"]
                    child_rel_dict = {
                        "is_a": child_spec["is_a"],
                        "part_of": [concept_name],
                    }
                    sub_created = ensure_ontology_completeness(
                        child_name,
                        child_is_a,
                        child_rel_dict,
                        shared_connection=shared_connection,
                        _depth=_depth + 1,
                    )
                    created.extend(sub_created)

            except Exception as e:
                logger.warning(f"[ONTOLOGY] Failed to auto-create {child_name}: {e}")
                print(f"[ONTOLOGY] WARN: Could not auto-create {child_name}: {e}", file=sys.stderr)

        # GIINT_Task special: auto-create Hypercluster in starsystem Task_Collections
        if schema.get("auto_create_hypercluster"):
            try:
                created.extend(
                    _auto_create_task_hypercluster(
                        concept_name, relationship_dict, shared_connection
                    )
                )
            except Exception as e:
                logger.warning(f"[ONTOLOGY] HC auto-create failed for {concept_name}: {e}")

    return created


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

    Uses ONTOLOGY_SCHEMAS to know what to count — not raw Cypher assumptions.
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
