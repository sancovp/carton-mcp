"""
CartOn Utils - Core business logic for concept management
"""
import logging
import os
from typing import Dict, List, Optional
from pathlib import Path

# Setup logging
logger = logging.getLogger(__name__)

class CartOnUtils:
    """
    CartOn utilities for concept management
    """

    def __init__(self, shared_connection=None):
        """Initialize with optional shared Neo4j connection.

        Args:
            shared_connection: KnowledgeGraphBuilder instance to reuse (for MCP context).
                              If None, creates temp connections per query (for external callers).
        """
        self._shared_conn = shared_connection

    def _get_connection(self):
        """Get Neo4j connection - reuse shared or module singleton.

        Returns:
            Tuple of (connection, should_close). Never closes singleton.
        """
        if self._shared_conn:
            return self._shared_conn, False  # MCP context - don't close
        # Use module-level singleton instead of creating new connection per query
        from heaven_base.tool_utils.neo4j_utils import get_shared_graph
        return get_shared_graph(), False  # Singleton - never close

    def bootstrap_collection_types(self) -> bool:
        """Bootstrap collection type system if not already done.

        Creates base collection type concepts:
        - Carton_Collection (root type)
        - Global_Collection (IS_A Carton_Collection)
        - Local_Collection (IS_A Carton_Collection)
        - Identity_Collection (IS_A Carton_Collection)

        Uses filesystem flag to avoid repeated bootstrapping.
        Uses shared_connection if available to avoid connection overhead.

        Returns:
            True if bootstrap was performed, False if already bootstrapped
        """
        # Get carton directory from env
        base_path = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        carton_dir = Path(base_path) / 'carton'
        carton_dir.mkdir(parents=True, exist_ok=True)

        flag_file = carton_dir / 'collection_types_bootstrapped.flag'

        # Check if already bootstrapped
        if flag_file.exists():
            logger.info("Collection types already bootstrapped (flag file exists)")
            return False

        logger.info("Bootstrapping collection type system...")

        from .add_concept_tool import add_concept_tool_func

        try:
            # Create root Carton_Collection concept
            add_concept_tool_func(
                concept_name="Carton_Collection",
                description="Root type for all CartON collections. Collections organize related concepts for context engineering and memory management.",
                relationships=[
                    {"relationship": "is_a", "related": ["Concept"]},
                    {"relationship": "part_of", "related": ["CartON_System"]}
                ],
                shared_connection=self._shared_conn
            )

            # Create Global_Collection type
            add_concept_tool_func(
                concept_name="Global_Collection",
                description="Collection type for universal baseline knowledge loaded in every conversation. Only one global collection should exist.",
                relationships=[
                    {"relationship": "is_a", "related": ["Carton_Collection"]},
                    {"relationship": "part_of", "related": ["Collection_Type_System"]}
                ],
                shared_connection=self._shared_conn
            )

            # Create Local_Collection type
            add_concept_tool_func(
                concept_name="Local_Collection",
                description="Collection type for domain-specific, purposive knowledge bundles. Examples: OAuth_Implementation_Collection, Discord_Setup_Collection. Activated on-demand when working on specific domains.",
                relationships=[
                    {"relationship": "is_a", "related": ["Carton_Collection"]},
                    {"relationship": "part_of", "related": ["Collection_Type_System"]}
                ],
                shared_connection=self._shared_conn
            )

            # Create Identity_Collection type
            add_concept_tool_func(
                concept_name="Identity_Collection",
                description="Collection type for agent-specific knowledge domains. Defines what an agent knows and can access. Can contain individual concepts and references to local collections (retrieval maps).",
                relationships=[
                    {"relationship": "is_a", "related": ["Carton_Collection"]},
                    {"relationship": "part_of", "related": ["Collection_Type_System"]}
                ],
                shared_connection=self._shared_conn
            )

            # Write bootstrap flag
            flag_file.write_text("Collection type system bootstrapped successfully.\n")
            logger.info("✅ Collection type system bootstrapped successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to bootstrap collection types: {e}")
            # Don't write flag if bootstrap failed
            raise

    def bootstrap_ontology_types(self) -> bool:
        """Bootstrap ontology template types if not already done.

        Creates foundation ontology concepts that HAS_VALIDATOR depends on:
        - Carton_Template (root template type)
        - Skillspec_Template (template for typed skills, with REQUIRES_RELATIONSHIP)
        - Relationship type concepts: Has_Domain, Has_Category, Has_What, Has_When

        Uses filesystem flag to avoid repeated bootstrapping.

        Returns:
            True if bootstrap was performed, False if already bootstrapped
        """
        base_path = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        carton_dir = Path(base_path) / 'carton'
        carton_dir.mkdir(parents=True, exist_ok=True)

        flag_file = carton_dir / 'ontology_types_bootstrapped.flag'

        if flag_file.exists():
            logger.info("Ontology types already bootstrapped (flag file exists)")
            return False

        logger.info("Bootstrapping ontology type system...")

        from .add_concept_tool import add_concept_tool_func

        try:
            # Create Carton_Template root type
            add_concept_tool_func(
                concept_name="Carton_Template",
                description="Root type for CartON templates. Templates define required relationships that child concepts must provide (via REQUIRES_RELATIONSHIP edges). HAS_VALIDATOR checks these at add_concept time.",
                relationships=[
                    {"relationship": "is_a", "related": ["Concept"]},
                    {"relationship": "part_of", "related": ["CartON_System"]}
                ],
                hide_youknow=True,
                shared_connection=self._shared_conn
            )

            # Create relationship type concepts
            for rel_name, rel_desc in [
                ("Has_Domain", "Relationship type indicating domain membership (e.g., Paiab, Sanctum, Cave)"),
                ("Has_Category", "Relationship type indicating skill category (understand, preflight, single_turn_process)"),
                ("Has_What", "Relationship type describing what a skill does"),
                ("Has_When", "Relationship type describing when to use a skill"),
                ("Has_Produces", "Relationship type declaring what a skill produces/instantiates (the output artifact, NOT the pattern type)"),
                # Skill structure and content
                ("Has_Subdomain", "Relationship type indicating subdomain within a domain"),
                ("Has_Content", "Relationship type linking to skill body content (truncated hash reference)"),
                ("Has_Reference", "Relationship type linking to reference.md table of contents"),
                ("Has_Resources", "Relationship type linking to resource files listing"),
                ("Has_Scripts", "Relationship type linking to executable scripts listing"),
                ("Has_Templates", "Relationship type linking to template files listing"),
                # Claude Code integration fields
                ("Has_Allowed_Tools", "Relationship type for Claude allowed-tools field (comma-separated tool names)"),
                ("Has_Model", "Relationship type for Claude model field (which model to use)"),
                ("Has_Context_Mode", "Relationship type for Claude context field (fork/inline execution mode)"),
                ("Has_Agent_Type", "Relationship type for Claude agent field (subagent type when context=fork)"),
                ("Has_Hook", "Relationship type for Claude hooks field (PreToolUse/PostToolUse)"),
                ("Has_User_Invocable", "Relationship type for Claude user-invocable field (show in / menu)"),
                ("Has_Disable_Model_Invocation", "Relationship type for Claude disable-model-invocation field"),
                ("Has_Argument_Hint", "Relationship type for Claude argument-hint field (autocomplete hint)"),
                # System links
                ("Has_Requires", "Relationship type linking to understand skill dependencies"),
                ("Has_Describes_Component", "Relationship type linking to GIINT component path"),
                ("Has_Starsystem", "Relationship type linking to project/starsystem"),
            ]:
                add_concept_tool_func(
                    concept_name=rel_name,
                    description=rel_desc,
                    relationships=[
                        {"relationship": "is_a", "related": ["Relationship_Type"]},
                        {"relationship": "part_of", "related": ["CartON_System"]}
                    ],
                    hide_youknow=True,
                    shared_connection=self._shared_conn
                )

            # Create canonical skill category types
            for cat_name, cat_desc in [
                ("Skill_Category", "Root type for skill categories. Claude Code has one native type (skill). Categories are our typed layer on top."),
                ("Skill_Category_Understand", "Skills for discussion/recall of domain knowledge. Equip to talk about or remember a domain."),
                ("Skill_Category_Preflight", "Skills that prime for work and point to flight configs. Equip before starting a workflow."),
                ("Skill_Category_Single_Turn_Process", "Skills with context + immediate action. Equip and do in one turn."),
            ]:
                add_concept_tool_func(
                    concept_name=cat_name,
                    description=cat_desc,
                    relationships=[
                        {"relationship": "is_a", "related": ["Skill_Category"] if cat_name != "Skill_Category" else ["Concept"]},
                        {"relationship": "part_of", "related": ["CartON_System"]}
                    ],
                    hide_youknow=True,
                    shared_connection=self._shared_conn
                )

            # Create Skillspec_Template with REQUIRES_RELATIONSHIP edges
            add_concept_tool_func(
                concept_name="Skillspec_Template",
                description="Template for skill metadata envelope (SkillSpec). Enforces required relationships for skill discovery: domain, category, what, when, produces. Extended fields: subdomain, requires, describes_component, starsystem.",
                relationships=[
                    {"relationship": "is_a", "related": ["Carton_Template"]},
                    {"relationship": "part_of", "related": ["Skill_Projection_Pipeline_Feb8"]},
                    {"relationship": "instantiates", "related": ["Template_Pattern"]},
                    {"relationship": "REQUIRES_RELATIONSHIP", "related": [
                        "Has_Domain", "Has_Category", "Has_What", "Has_When", "Has_Produces",
                        "Has_Subdomain", "Has_Requires", "Has_Describes_Component", "Has_Starsystem"
                    ]}
                ],
                hide_youknow=True,
                shared_connection=self._shared_conn
            )

            # Create Skill_Template extending Skillspec_Template with content + Claude fields
            add_concept_tool_func(
                concept_name="Skill_Template",
                description="Template for COMPLETE skill concepts. Extends Skillspec_Template with content, file structure, and Claude Code integration fields. A Skill is a SkillSpec PLUS the actual content body, reference docs, resources, scripts, templates, and Claude frontmatter fields.",
                relationships=[
                    {"relationship": "is_a", "related": ["Carton_Template"]},
                    {"relationship": "extends", "related": ["Skillspec_Template"]},
                    {"relationship": "part_of", "related": ["Skill_Projection_Pipeline_Feb8"]},
                    {"relationship": "instantiates", "related": ["Template_Pattern"]},
                    {"relationship": "REQUIRES_RELATIONSHIP", "related": [
                        # SkillSpec fields (inherited)
                        "Has_Domain", "Has_Category", "Has_What", "Has_When", "Has_Produces",
                        # Content + structure
                        "Has_Content", "Has_Reference", "Has_Resources", "Has_Scripts", "Has_Templates",
                        # Claude Code integration
                        "Has_Allowed_Tools", "Has_Model", "Has_Context_Mode", "Has_Agent_Type",
                        "Has_Hook", "Has_User_Invocable", "Has_Disable_Model_Invocation", "Has_Argument_Hint",
                        # System links
                        "Has_Subdomain", "Has_Requires", "Has_Describes_Component", "Has_Starsystem",
                    ]}
                ],
                hide_youknow=True,
                shared_connection=self._shared_conn
            )

            flag_file.write_text("Ontology type system bootstrapped successfully.\n")
            logger.info("✅ Ontology type system bootstrapped successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to bootstrap ontology types: {e}")
            raise

    def bootstrap_memory_ontology_types(self) -> bool:
        """Bootstrap memory architecture ontology types.

        Creates types for the fractal memory tier system:
        - HyperCluster: Groups of concepts tracking a GIINT_Project in memory
        - Memory_Tier: Tier 0-3 placement (active → archived → faint → faintest)
        - UltraMap: Sequencing/dependency relationships between clusters
        - Relationship types: Has_Tier, Has_Why, Has_Status, Has_Level, Has_File_Path, etc.
        - Concrete tier instances: Memory_Tier_0 through Memory_Tier_3

        Uses filesystem flag to avoid repeated bootstrapping.
        """
        base_path = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        carton_dir = Path(base_path) / 'carton'
        carton_dir.mkdir(parents=True, exist_ok=True)

        flag_file = carton_dir / 'memory_ontology_bootstrapped.flag'

        if flag_file.exists():
            logger.info("Memory ontology types already bootstrapped (flag file exists)")
            return False

        logger.info("Bootstrapping memory ontology type system...")

        from .add_concept_tool import add_concept_tool_func

        try:
            # --- Relationship types for memory architecture ---
            for rel_name, rel_desc in [
                ("Has_Tier", "Relationship linking a HyperCluster to its Memory_Tier placement"),
                ("Has_Why", "Relationship storing the one-line reason a HyperCluster matters"),
                ("Has_Status", "Relationship indicating HyperCluster status: active, done, or archived"),
                ("Has_Level", "Relationship storing numeric tier level (0, 1, 2, 3)"),
                ("Has_File_Path", "Relationship linking a Memory_Tier to its filesystem projection path"),
                ("Has_Sequence", "Relationship storing ordered sequence of HyperClusters in an UltraMap"),
                ("Has_Giint_Project", "Relationship linking a HyperCluster to the GIINT_Project it tracks"),
            ]:
                add_concept_tool_func(
                    concept_name=rel_name,
                    description=rel_desc,
                    relationships=[
                        {"relationship": "is_a", "related": ["Relationship_Type"]},
                        {"relationship": "part_of", "related": ["CartON_System"]}
                    ],
                    hide_youknow=True,
                    shared_connection=self._shared_conn
                )

            # --- Core ontology types ---
            add_concept_tool_func(
                concept_name="HyperCluster",
                description="A group of CartON concepts organized around a GIINT_Project within the fractal memory tier system. Each HyperCluster lives at a Memory_Tier (0=active in MEMORY.md, 1=archived in rules, 2=faint, 3=faintest). Contains concepts via HAS_PART, tracks status (active/done/archived), and has a one-line Why statement for MEMORY.md projection.",
                relationships=[
                    {"relationship": "is_a", "related": ["Carton_Ontology_Entity"]},
                    {"relationship": "part_of", "related": ["CartON_System"]}
                ],
                hide_youknow=True,
                shared_connection=self._shared_conn
            )

            add_concept_tool_func(
                concept_name="Memory_Tier",
                description="A tier in the fractal memory system. Tier 0 = MEMORY.md (active work, auto-injected). Tier 1 = rules files (completed GIINT_Projects). Tier 2 = faint memories (compressed collection names). Tier 3 = faintest memories (meta-compressed). Each tier has a file path for substrate projection.",
                relationships=[
                    {"relationship": "is_a", "related": ["Carton_Ontology_Entity"]},
                    {"relationship": "part_of", "related": ["CartON_System"]}
                ],
                hide_youknow=True,
                shared_connection=self._shared_conn
            )

            add_concept_tool_func(
                concept_name="UltraMap",
                description="A sequencing map showing how HyperClusters relate and which must complete before others. Encodes blocked-by dependencies and build order. Used to create task list dependencies when loaded.",
                relationships=[
                    {"relationship": "is_a", "related": ["Carton_Ontology_Entity"]},
                    {"relationship": "part_of", "related": ["CartON_System"]}
                ],
                hide_youknow=True,
                shared_connection=self._shared_conn
            )

            # --- Concrete tier instances ---
            tier_data = [
                ("Memory_Tier_0", "Active work tier. Projected to MEMORY.md. Auto-injected every conversation. Max ~100 lines of concept names + Why statements.", "/home/GOD/.claude/projects/-home-GOD/memory/MEMORY.md"),
                ("Memory_Tier_1", "Completed GIINT_Projects tier. Projected to .claude/rules/giint-projects-{date}.md. Auto-loaded every conversation.", "/home/GOD/.claude/rules/"),
                ("Memory_Tier_2", "Faint memories tier. Compressed collection names. Projected to .claude/rules/faint-memories-L1.md.", "/home/GOD/.claude/rules/faint-memories-L1.md"),
                ("Memory_Tier_3", "Faintest memories tier. Meta-compressed. Projected to .claude/rules/faintest-memories-L2.md.", "/home/GOD/.claude/rules/faintest-memories-L2.md"),
            ]
            for tier_name, tier_desc, tier_path in tier_data:
                level = tier_name[-1]  # "0", "1", "2", "3"
                add_concept_tool_func(
                    concept_name=tier_name,
                    description=tier_desc,
                    relationships=[
                        {"relationship": "is_a", "related": ["Memory_Tier"]},
                        {"relationship": "part_of", "related": ["CartON_System"]},
                        {"relationship": "has_level", "related": [f"Level_{level}"]},
                        {"relationship": "has_file_path", "related": [tier_path]},
                    ],
                    hide_youknow=True,
                    shared_connection=self._shared_conn
                )

            # --- HyperCluster template ---
            add_concept_tool_func(
                concept_name="HyperCluster_Template",
                description="Template for HyperCluster concepts. Enforces required relationships: must link to a GIINT_Project, a Memory_Tier, have a status, and a Why statement.",
                relationships=[
                    {"relationship": "is_a", "related": ["Carton_Template"]},
                    {"relationship": "part_of", "related": ["CartON_System"]},
                    {"relationship": "instantiates", "related": ["Template_Pattern"]},
                    {"relationship": "REQUIRES_RELATIONSHIP", "related": [
                        "Has_Giint_Project", "Has_Tier", "Has_Status", "Has_Why"
                    ]}
                ],
                hide_youknow=True,
                shared_connection=self._shared_conn
            )

            flag_file.write_text("Memory ontology type system bootstrapped successfully.\n")
            logger.info("✅ Memory ontology type system bootstrapped successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to bootstrap memory ontology types: {e}")
            raise

    def enforce_ontology_invariants(self) -> dict:
        """Enforce ALL ontology invariants on every startup. No flag file — runs every time.

        For each typed entity class (Skills, Flights, Personas, Skillsets):
        1. Scans the source of truth (filesystem, Neo4j)
        2. Ensures required relationships exist in Neo4j
        3. Ensures required ChromaDB entries exist

        Currently enforced:
        - Every skill on disk -> PART_OF Skillgraph in Neo4j + entry in ChromaDB skillgraphs

        Returns:
            dict with counts of what was enforced
        """
        import json
        stats = {"skills_checked": 0, "neo4j_fixed": 0, "chroma_fixed": 0, "errors": []}

        heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        skills_dir = Path(heaven_data_dir) / 'skills'

        if not skills_dir.exists():
            logger.info("No skills directory found, skipping skill enforcement")
            return stats

        # Get Neo4j connection
        graph, should_close = self._get_connection()

        try:
            # --- SEED SHIP ENFORCEMENT (root graph node, one per user) ---
            try:
                from carton_mcp.add_concept_tool import add_concept_tool_func
                from carton_mcp.ontology_graphs import ensure_ontology_completeness

                seed_ship_check = graph.execute_query(
                    "MATCH (n:Wiki {n: 'Seed_Ship'}) RETURN n.n as name LIMIT 1"
                )
                if not seed_ship_check:
                    add_concept_tool_func(
                        concept_name="Seed_Ship",
                        description="Root graph node for user's fleet. One per user. HAS starsystems, kardashev map, and SANCTUM.",
                        relationships=[
                            {"relationship": "is_a", "related": ["Seed_Ship"]},
                            {"relationship": "instantiates", "related": ["Seed_Ship_Template"]},
                        ],
                        hide_youknow=True,
                        shared_connection=graph,
                    )
                    logger.info("[INVARIANT] Created Seed_Ship root node")

                # Always ensure children exist (catches pre-existing Seed_Ship missing children)
                ensure_ontology_completeness(
                    "Seed_Ship", ["Seed_Ship"], {"is_a": ["Seed_Ship"]},
                    shared_connection=graph,
                )

                # --- STARSYSTEM ONTOLOGY ENFORCEMENT ---
                # Find all starsystems, fix PART_OF to Seed_Ship_Starsystems, ensure completeness
                starsystems = graph.execute_query(
                    "MATCH (ss:Wiki)-[:IS_A]->(:Wiki {n: 'Starsystem_Collection'}) RETURN ss.n as name"
                )
                if starsystems:
                    for ss_rec in starsystems:
                        ss_name = ss_rec["name"] if isinstance(ss_rec, dict) else ss_rec["name"]

                        # Check if already PART_OF Seed_Ship_Starsystems
                        has_ref = graph.execute_query(
                            "MATCH (ss:Wiki {n: $name})-[:PART_OF]->(:Wiki {n: 'Seed_Ship_Starsystems'}) RETURN ss.n LIMIT 1",
                            {"name": ss_name}
                        )
                        if not has_ref:
                            # Remove old All_Starsystems or STARSYSTEM_Collection refs
                            graph.execute_query(
                                "MATCH (ss:Wiki {n: $name})-[r:PART_OF]->(old:Wiki) "
                                "WHERE old.n IN ['All_Starsystems', 'STARSYSTEM_Collection'] DELETE r",
                                {"name": ss_name}
                            )
                            # Add proper Seed Ship membership (bidirectional)
                            graph.execute_query(
                                "MATCH (ss:Wiki {n: $name}), (target:Wiki {n: 'Seed_Ship_Starsystems'}) "
                                "MERGE (ss)-[:PART_OF]->(target) "
                                "MERGE (target)-[:HAS_PART]->(ss)",
                                {"name": ss_name}
                            )
                            logger.info(f"[INVARIANT] Migrated {ss_name} to Seed_Ship_Starsystems")

                        # Ensure starsystem ontology completeness (auto-creates Task_Collections etc.)
                        ensure_ontology_completeness(
                            ss_name, ["Starsystem_Collection"],
                            {"is_a": ["Starsystem_Collection"]},
                            shared_connection=graph,
                        )

            except Exception as e:
                logger.warning(f"[INVARIANT] Seed_Ship/starsystem enforcement failed: {e}")

            # --- ONTOLOGY TYPE MATERIALIZATION (bounded to ONTOLOGY_SCHEMAS keys) ---
            try:
                from carton_mcp.ontology_graphs import materialize_ontology_types, ensure_instances_have_is_a

                materialized = materialize_ontology_types(graph)
                if materialized:
                    logger.info(f"[INVARIANT] Materialized {len(materialized)} ontology types: {materialized}")
                    stats["ontology_types_materialized"] = len(materialized)

                linked = ensure_instances_have_is_a(graph)
                if linked:
                    logger.info(f"[INVARIANT] Linked {len(linked)} instances to ontology types")
                    stats["instances_linked"] = len(linked)

            except Exception as e:
                logger.warning(f"[INVARIANT] Ontology materialization failed: {e}")

            # --- SKILL ENFORCEMENT ---
            # BUG (Apr 18 2026): This entire section is broken.
            # (1) SET sg.t=timestamp() overwrites timestamps every boot — Skillgraph_ always "most recent"
            # (2) Nodes are flat stubs (PART_OF Skillgraph + IS_A Skillgraph_Entry only) — no real relationships
            # (3) ChromaDB goes to separate "skillgraphs" collection, invisible to normal chroma_query
            # Needs full rewrite to create complete skill graphs with all relationships.
            # 1. Get all skill dirs on disk (source of truth)
            skill_names = []
            for entry in skills_dir.iterdir():
                if entry.is_dir() and not entry.name.startswith('_') and not entry.name.startswith('Test') and not entry.name.startswith('Fix') and not entry.name.startswith('Live') and not entry.name.endswith('.json'):
                    skill_names.append(entry.name)

            # 2. Get all existing Skillgraph instances from Neo4j
            existing_sg = set()
            try:
                result = graph.execute_query(
                    "MATCH (s:Wiki)-[:HAS_INSTANCES]->(sg:Wiki) WHERE s.n = 'Skillgraph' RETURN sg.n as name"
                )
                for r in result:
                    existing_sg.add(r['name'])
            except Exception as e:
                logger.warning(f"Could not query Skillgraph instances: {e}")

            # 3. Get all existing ChromaDB skillgraph entries
            existing_chroma = set()
            try:
                import chromadb
                client = chromadb.HttpClient(host="localhost", port=8101)
                collection = client.get_or_create_collection(
                    name="skillgraphs",
                    metadata={"hnsw:space": "cosine"}
                )
                all_ids = collection.get(include=[])['ids']
                for cid in all_ids:
                    # IDs are like "skillgraph:Skillgraph_Make_Skill" or "skillgraph:mcp-skill-carton"
                    existing_chroma.add(cid)
            except Exception as e:
                logger.warning(f"Could not read ChromaDB skillgraphs: {e}")
                collection = None

            # 4. For each skill on disk, enforce invariants
            for skill_name in skill_names:
                stats["skills_checked"] += 1

                # Read metadata
                meta_path = skills_dir / skill_name / '_metadata.json'
                skill_md_path = skills_dir / skill_name / 'SKILL.md'
                domain = "Unknown"
                category = ""
                what_text = ""
                when_text = ""

                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text())
                        domain = meta.get('domain', 'Unknown')
                        category = meta.get('category', '')
                        what_text = meta.get('what', '')
                        when_text = meta.get('when', '')
                    except Exception:
                        pass

                if skill_md_path.exists() and not what_text:
                    try:
                        content = skill_md_path.read_text()
                        # Parse WHAT/WHEN from SKILL.md frontmatter description
                        for line in content.split('\n'):
                            stripped = line.strip()
                            if stripped.startswith('WHAT:'):
                                what_text = stripped[5:].strip()
                            elif stripped.startswith('WHEN:'):
                                when_text = stripped[5:].strip()
                    except Exception:
                        pass

                # Normalize to Skillgraph naming: Skillgraph_Title_Case
                sg_concept_name = "Skillgraph_" + skill_name.replace("-", "_").replace(" ", "_").title().replace(" ", "")
                # Fix: title() on underscored already works, just ensure consistency
                parts = skill_name.replace("-", "_").split("_")
                sg_concept_name = "Skillgraph_" + "_".join(p.capitalize() for p in parts)

                # Map category to pattern
                cat_lower = category.lower() if category else ""
                if "understand" in cat_lower:
                    pattern = "Understand_Skill_Pattern"
                    cat_formal = "Category_Understand"
                elif "preflight" in cat_lower:
                    pattern = "Preflight_Skill_Pattern"
                    cat_formal = "Category_Preflight"
                elif "single_turn" in cat_lower:
                    pattern = "Single_Turn_Skill_Pattern"
                    cat_formal = "Category_Single_Turn"
                else:
                    pattern = "Generic_Skill_Pattern"
                    cat_formal = category or ""

                # A. Enforce Neo4j: Skillgraph PART_OF Skillgraph container
                if sg_concept_name not in existing_sg:
                    try:
                        graph.execute_query(
                            "MERGE (sg:Wiki {n: $sg_name}) "
                            "SET sg.t = CASE WHEN sg.t IS NULL THEN datetime() ELSE sg.t END, sg.system_generated = true "
                            "WITH sg "
                            "MATCH (parent:Wiki {n: 'Skillgraph'}) "
                            "MERGE (parent)-[:HAS_INSTANCES]->(sg) "
                            "MERGE (sg)-[:PART_OF]->(parent) "
                            "MERGE (sg)-[:IS_A]->(:Wiki {n: 'Skillgraph_Entry'})",
                            {"sg_name": sg_concept_name}
                        )
                        stats["neo4j_fixed"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Neo4j {sg_concept_name}: {e}")

                # B. Enforce ChromaDB: skillgraph entry exists
                chroma_id = f"skillgraph:{sg_concept_name}"
                # Also check old-style IDs
                alt_chroma_id = f"skillgraph:{skill_name}"
                if chroma_id not in existing_chroma and alt_chroma_id not in existing_chroma and collection is not None:
                    try:
                        # Build document in same format as substrate_projector
                        doc_parts = [f"[SKILLGRAPH:{skill_name}]"]
                        doc_parts.append("is_a:Skill")
                        doc_parts.append(f"instantiates:{pattern}")
                        doc_parts.append(f"has_domain:{domain}")
                        if what_text:
                            doc_parts.append(f"what:{what_text}")
                        if when_text:
                            doc_parts.append(f"when:{when_text}")
                        doc_parts.append("[/SKILLGRAPH]")
                        doc_text = " ".join(doc_parts)

                        meta_dict = {
                            "name": sg_concept_name,
                            "skill": "Skill_" + "_".join(p.capitalize() for p in skill_name.replace("-", "_").split("_")),
                            "domain": domain,
                            "category": cat_formal,
                            "pattern": pattern,
                            "type": "skillgraph",
                        }

                        collection.upsert(
                            ids=[chroma_id],
                            documents=[doc_text],
                            metadatas=[meta_dict]
                        )
                        stats["chroma_fixed"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Chroma {skill_name}: {e}")

            # --- CLEANUP: Remove entries that don't correspond to skills on disk ---
            stats["neo4j_removed"] = 0
            stats["chroma_removed"] = 0

            # Build set of valid Skillgraph concept names from disk skills
            valid_sg_names = set()
            for sn in skill_names:
                parts = sn.replace("-", "_").split("_")
                valid_sg_names.add("Skillgraph_" + "_".join(p.capitalize() for p in parts))

            # Remove stale Neo4j Skillgraph entries
            for sg_name in existing_sg:
                if sg_name not in valid_sg_names:
                    try:
                        graph.execute_query(
                            "MATCH (parent:Wiki {n: 'Skillgraph'})-[r1:HAS_INSTANCES]->(sg:Wiki {n: $sg_name}) "
                            "OPTIONAL MATCH (sg)-[r2:PART_OF]->(parent) "
                            "OPTIONAL MATCH (sg)-[r3:IS_A]->(:Wiki {n: 'Skillgraph_Entry'}) "
                            "DELETE r1, r2, r3 "
                            "WITH sg WHERE NOT (sg)--() DELETE sg",
                            {"sg_name": sg_name}
                        )
                        stats["neo4j_removed"] += 1
                    except Exception as e:
                        stats["errors"].append(f"Neo4j remove {sg_name}: {e}")

            # Remove stale ChromaDB skillgraph entries
            if collection is not None:
                # Build valid chroma IDs from disk
                valid_chroma_ids = set()
                for sn in skill_names:
                    parts = sn.replace("-", "_").split("_")
                    sg_name = "Skillgraph_" + "_".join(p.capitalize() for p in parts)
                    valid_chroma_ids.add(f"skillgraph:{sg_name}")
                    valid_chroma_ids.add(f"skillgraph:{sn}")  # old-style ID

                stale_chroma_ids = [cid for cid in existing_chroma if cid not in valid_chroma_ids]
                if stale_chroma_ids:
                    try:
                        collection.delete(ids=stale_chroma_ids)
                        stats["chroma_removed"] = len(stale_chroma_ids)
                    except Exception as e:
                        stats["errors"].append(f"Chroma remove batch: {e}")

            logger.info(
                f"Ontology enforcement: {stats['skills_checked']} skills checked, "
                f"{stats['neo4j_fixed']} Neo4j fixed, {stats['chroma_fixed']} Chroma fixed, "
                f"{stats['neo4j_removed']} Neo4j removed, {stats['chroma_removed']} Chroma removed, "
                f"{len(stats['errors'])} errors"
            )
            return stats

        finally:
            if should_close:
                graph.close()

    def get_all_concept_names(self, exclude_concept: str = None) -> List[str]:
        """Get all concept names from Neo4j Wiki namespace.

        Filters out:
        - Old versioned concepts (ending in _v1, _v2, etc.) from sinking
        - Old renamed concepts (have evolved_to relationship) from rename operations

        Args:
            exclude_concept: Optional concept name to exclude from results

        Returns:
            List of active concept names (excludes obsolete versions)
        """
        graph, should_close = self._get_connection()
        try:
            # Build query with filters for obsolete concepts
            base_filters = [
                "NOT c.n =~ '.*_v[0-9]+$'",  # Exclude sunk versions (_v1, _v2, etc.)
                "NOT EXISTS((c)-[:EVOLVED_TO]->())"  # Exclude old renamed concepts
            ]

            if exclude_concept:
                base_filters.append("c.n <> $exclude")
                query = f"MATCH (c:Wiki) WHERE {' AND '.join(base_filters)} RETURN c.n as name"
                result = graph.execute_query(query, {"exclude": exclude_concept})
            else:
                query = f"MATCH (c:Wiki) WHERE {' AND '.join(base_filters)} RETURN c.n as name"
                result = graph.execute_query(query)
            return [record["name"] for record in result]
        finally:
            if should_close:
                graph.close()

    def _validate_query_safety(self, cypher_query: str) -> dict:
        """Validate query is safe (read-only, :Wiki namespace)"""
        import re
        query_upper = cypher_query.upper().strip()
        
        # Word-boundary match to avoid false positives (e.g. 'as created' matching 'CREATE')
        write_pattern = re.compile(r'\b(CREATE|MERGE|DELETE|DETACH)\b')
        if write_pattern.search(query_upper):
            return {"success": False, "error": "Write operations (CREATE/MERGE) not allowed. Use add_concept tool instead."}
        
        if ':Wiki' not in cypher_query:
            return {"success": False, "error": "Query must target :Wiki namespace (e.g., MATCH (c:Wiki))"}
        
        return {"success": True}

    def _get_neo4j_config(self):
        """Get Neo4j configuration from environment"""
        import os
        from .concept_config import ConceptConfig
        
        return ConceptConfig(
            github_pat=os.getenv('GITHUB_PAT', 'dummy'),
            repo_url=os.getenv('REPO_URL', 'dummy'),
            neo4j_url=os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687'),
            neo4j_username=os.getenv('NEO4J_USER', 'neo4j'),
            neo4j_password=os.getenv('NEO4J_PASSWORD', 'password'),
            base_path=None  # Will use HEAVEN_DATA_DIR (default /tmp/heaven_data) if None
        )

    def _serialize_node(self, node):
        """Serialize Neo4j Node to dict"""
        return dict(node)
    
    def _serialize_relationship(self, rel):
        """Serialize Neo4j Relationship to dict"""
        return {
            'type': type(rel).__name__,
            'relationship_type': rel.type,
            'properties': dict(rel)
        }
    
    def _serialize_path(self, path):
        """Serialize Neo4j Path to dict"""
        return {
            'nodes': [self._serialize_neo4j_value(n) for n in path.nodes],
            'relationships': [self._serialize_neo4j_value(r) for r in path.relationships]
        }
    
    def _serialize_collection(self, collection):
        """Serialize list/tuple items"""
        return [self._serialize_neo4j_value(item) for item in collection]
    
    def _serialize_dict(self, d):
        """Serialize dict values"""
        return {k: self._serialize_neo4j_value(v) for k, v in d.items()}
    
    def _serialize_neo4j_value(self, value):
        """Convert Neo4j types to JSON-serializable formats"""
        try:
            from neo4j.graph import Node, Relationship, Path
            
            if isinstance(value, Node):
                return self._serialize_node(value)
            elif isinstance(value, Relationship):
                return self._serialize_relationship(value)
            elif isinstance(value, Path):
                return self._serialize_path(value)
            elif isinstance(value, dict):
                return self._serialize_dict(value)
            elif isinstance(value, (list, tuple)):
                return self._serialize_collection(value)
            else:
                return value
        except ImportError:
            return value

    def _create_graph_connection(self):
        """Create and return a Neo4j graph connection"""
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        
        config = self._get_neo4j_config()
        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )
        graph._ensure_connection()
        return graph
    
    def _serialize_record(self, record):
        """Serialize a single Neo4j record"""
        serialized = {}
        for key in record.keys():
            serialized[key] = self._serialize_neo4j_value(record[key])
        return serialized
    
    def _execute_neo4j_query(self, cypher_query: str, parameters: dict):
        """Execute query against Neo4j"""
        graph, should_close = self._get_connection()

        try:
            with graph.driver.session() as session:
                result = session.run(cypher_query, parameters or {})
                serialized_results = [self._serialize_record(record) for record in result]
        finally:
            if should_close:
                graph.close()

        return serialized_results

    def _handle_query_errors(self, e: Exception) -> dict:
        """Handle query execution errors"""
        if isinstance(e, ImportError):
            logger.error("Neo4j driver not available")
            return {"success": False, "error": "Neo4j driver not available"}
        else:
            logger.error(f"Query execution failed: {str(e)}")
            return {"success": False, "error": str(e)}

    def query_wiki_graph(self, cypher_query: str, parameters: dict = None) -> dict:
        """Execute arbitrary Cypher query on :Wiki namespace (read-only)"""
        logger.info(f"Executing wiki graph query: {cypher_query[:100]}...")
        try:
            validation = self._validate_query_safety(cypher_query)
            if not validation["success"]:
                logger.warning(f"Query validation failed: {validation['error']}")
                return validation
            
            result = self._execute_neo4j_query(cypher_query, parameters or {})
            logger.info(f"Query executed successfully, returned {len(result) if isinstance(result, list) else 'N/A'} records")
            
            return {
                "success": True,
                "cypher_query": cypher_query,
                "parameters": parameters or {},
                "data": result,
                "naming_convention": "Title_Case_With_Underscores. Paths: /home/GOD/foo-bar → Home_God_Foo_Bar. Concepts: My_Concept_Name"
            }
            
        except Exception as e:
            return self._handle_query_errors(e)

    def _validate_depth(self, depth: int) -> dict:
        """Validate depth parameter"""
        if depth < 1 or depth > 3:
            return {"success": False, "error": "Depth must be between 1 and 3"}
        return {"success": True}

    def _build_network_query(self, depth: int, rel_types: Optional[List[str]] = None) -> str:
        """Build Cypher query for network traversal with filtering

        Args:
            depth: Relationship depth (1-3)
            rel_types: Optional list of relationship types to filter (e.g., ["IS_A", "PART_OF"])
                      If None, includes all relationship types
        """
        # Build relationship type filter for Cypher path
        if rel_types:
            # Convert to Cypher syntax: -[r:IS_A|PART_OF*1..depth]-
            rel_filter = f":{'''|'''.join(rel_types)}"
        else:
            # No filter: -[r*1..depth]-
            rel_filter = ""

        return f"""
        MATCH (source:Wiki {{n: $concept_name}})
        CALL {{
            WITH source
            MATCH (source)-[r{rel_filter}*1..{depth}]-(connected:Wiki)
            WHERE NOT connected.n =~ '.*_v[0-9]+$'
              AND NOT connected.n =~ '.*_Observation$'
              AND NOT connected.n =~ '^UserThought_.*'
              AND NOT connected.n =~ '^AgentMessage_.*'
              AND NOT connected.n =~ '^Sync_.*'
              AND NOT connected.n =~ '.*_Update_History$'
              AND NOT connected.n = 'Requires_Evolution'
            RETURN r, connected
        }}
        RETURN source.n as start_concept,
               [rel in r | type(rel)] as relationship_path,
               connected.n as connected_concept,
               connected.d as connected_description
        """

    def _clip_large_result(self, result: list, concept_name: str, max_items: int = 100) -> dict:
        """Clip large results and cache to file"""
        if not isinstance(result, list):
            return {"clipped": False, "data": result}
        if len(result) <= max_items:
            return {"clipped": False, "data": result}

        # Cache full result to file
        import os
        import json
        from datetime import datetime

        cache_dir = Path(os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')) / 'carton_cache'
        cache_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cache_file = cache_dir / f"{concept_name}_network_{timestamp}.json"

        with open(cache_file, 'w') as f:
            json.dump(result, f, indent=2)

        logger.info(f"Clipped large result ({len(result)} items) to {cache_file}")

        return {
            "clipped": True,
            "total_items": len(result),
            "showing_first": max_items,
            "data": result[:max_items],
            "cached_at": str(cache_file),
            "message": f"Response was too long ({len(result)} items). Showing first {max_items}. Full result cached at {cache_file}"
        }

    def get_concept_network(self, concept_name: str, depth: int = 1, rel_types: Optional[List[str]] = None) -> dict:
        """Get concept network with specified relationship depth (1-3 hops)

        Args:
            concept_name: Name of the concept to explore
            depth: Relationship depth (1-3)
            rel_types: Optional list of relationship types to filter (e.g., ["IS_A", "PART_OF"])
                      If None, includes all relationship types

        Returns:
            Network data with deduplication and optional clipping
        """
        logger.info(f"Getting concept network for '{concept_name}' with depth {depth}, rel_types={rel_types}")

        validation = self._validate_depth(depth)
        if not validation["success"]:
            return validation

        cypher_query = self._build_network_query(depth, rel_types)

        try:
            result = self._execute_neo4j_query(cypher_query, {"concept_name": concept_name})
            logger.info(f"Retrieved network for '{concept_name}' with {len(result) if isinstance(result, list) else 0} path records")

            # Deduplicate by connected_concept (aggregate paths per unique concept)
            unique_concepts = {}
            for record in result:
                connected_name = record.get("connected_concept")
                if connected_name not in unique_concepts:
                    unique_concepts[connected_name] = {
                        "start_concept": record.get("start_concept"),
                        "connected_concept": connected_name,
                        "connected_description": record.get("connected_description"),
                        "relationship_paths": []
                    }
                # Add this path to the aggregated paths
                unique_concepts[connected_name]["relationship_paths"].append(
                    record.get("relationship_path")
                )

            # Convert to list
            deduped_result = list(unique_concepts.values())
            logger.info(f"Deduplicated to {len(deduped_result)} unique concepts")

            # Clip if too large
            clipped_result = self._clip_large_result(deduped_result, concept_name)

            response = {
                "success": True,
                "concept_name": concept_name,
                "depth": depth,
                "network": clipped_result["data"]
            }

            # Add clipping metadata if clipped
            if clipped_result["clipped"]:
                response["clipped"] = True
                response["total_items"] = clipped_result["total_items"]
                response["showing_first"] = clipped_result["showing_first"]
                response["cached_at"] = clipped_result["cached_at"]
                response["message"] = clipped_result["message"]

            return response

        except Exception as e:
            return self._handle_query_errors(e)
    
    def list_missing_concepts(self) -> dict:
        """List all missing concepts with inferred relationships and suggestions"""
        logger.info("Listing missing concepts...")
        try:
            missing_file = self._get_missing_concepts_file()
            if not missing_file.exists():
                return self._return_no_missing_concepts()
            
            content = missing_file.read_text(encoding="utf-8")
            missing_concepts = self._parse_missing_concepts_content(content)
            
            logger.info(f"Found {len(missing_concepts)} missing concepts")
            return {
                "success": True,
                "missing_concepts": missing_concepts,
                "total_count": len(missing_concepts)
            }
            
        except Exception as e:
            logger.error(f"Error listing missing concepts: {str(e)}")
            return {"success": False, "error": f"Failed to list missing concepts: {str(e)}"}
    
    def _get_missing_concepts_file(self):
        """Get the path to missing concepts file"""
        from pathlib import Path
        config = self._get_neo4j_config()
        return Path(config.base_path) / "missing_concepts.md"
    
    def _return_no_missing_concepts(self) -> dict:
        """Return response when no missing concepts file exists"""
        return {
            "success": True,
            "missing_concepts": [],
            "message": "No missing concepts file found - all concepts exist or none have been created yet"
        }
    
    def _parse_missing_concepts_content(self, content: str) -> list:
        """Parse missing concepts from markdown content"""
        import re
        missing_concepts = []
        current_concept = None
        current_relationships = []
        current_similar = []
        
        for line in content.split('\n'):
            line = line.strip()
            
            if line.startswith('## ') and line != '## Missing Concepts':
                if current_concept:
                    missing_concepts.append(self._build_concept_data(current_concept, current_relationships, current_similar))
                
                current_concept = line[3:].strip()
                current_relationships = []
                current_similar = []
                
            elif line.startswith('- ') and current_concept:
                rel_data = self._parse_relationship_line(line)
                if rel_data:
                    current_relationships.append(rel_data)
                    
            elif line.startswith('**Similar existing concepts:**') and current_concept:
                current_similar = self._parse_similar_concepts_line(line)
        
        if current_concept:
            missing_concepts.append(self._build_concept_data(current_concept, current_relationships, current_similar))
        
        return missing_concepts
    
    def _parse_relationship_line(self, line: str):
        """Parse a relationship line from missing concepts"""
        import re
        rel_match = re.match(r'- ([^:]+): (.+)', line)
        if rel_match:
            rel_type, related = rel_match.groups()
            return {
                "type": rel_type.strip(),
                "related": [c.strip() for c in related.split(',')]
            }
        return None
    
    def _parse_similar_concepts_line(self, line: str) -> list:
        """Parse similar concepts line from missing concepts"""
        similar_text = line.replace('**Similar existing concepts:**', '').strip()
        if similar_text and similar_text != "None":
            return [c.strip() for c in similar_text.split(',')]
        return []
    
    def _build_concept_data(self, name: str, relationships: list, similar: list) -> dict:
        """Build concept data structure"""
        return {
            "name": name,
            "inferred_relationships": relationships,
            "similar_concepts": similar
        }
    
    def calculate_missing_concepts(self) -> dict:
        """Scan all concepts, update missing_concepts.md, and commit to GitHub"""
        logger.info("Calculating missing concepts across all existing concepts...")
        try:
            from .add_concept_tool import check_missing_concepts_and_manage_file, setup_git_repo, commit_and_push
            
            # Get config and setup repo
            config = self._get_neo4j_config()
            base_dir = config.base_path
            
            # Setup git repo (clone latest)
            result = setup_git_repo(config, base_dir)
            if "error" in result:
                return {"success": False, "error": f"Git setup failed: {result['error']}"}
            
            # Run missing concepts check (this scans all existing concepts)
            file_updates = check_missing_concepts_and_manage_file(base_dir, "")  # Empty concept name for full scan
            
            # If file was updated, commit and push
            if file_updates and any("Updated missing_concepts.md" in update for update in file_updates):
                commit_result = commit_and_push(config, base_dir, "Update missing concepts tracking")
                if "error" in commit_result:
                    return {"success": False, "error": f"Git commit failed: {commit_result['error']}"}
                
                # Now read the updated file
                missing_file = self._get_missing_concepts_file()
                if missing_file.exists():
                    content = missing_file.read_text(encoding="utf-8")
                    missing_concepts = self._parse_missing_concepts_content(content)
                    
                    return {
                        "success": True,
                        "message": "Missing concepts calculated and synced to GitHub",
                        "missing_concepts": missing_concepts,
                        "total_count": len(missing_concepts),
                        "file_updates": file_updates
                    }
                else:
                    return {
                        "success": True, 
                        "message": "No missing concepts found",
                        "missing_concepts": [],
                        "total_count": 0,
                        "file_updates": file_updates
                    }
            else:
                return {
                    "success": True,
                    "message": "No changes to missing concepts",
                    "missing_concepts": [],
                    "total_count": 0,
                    "file_updates": file_updates or ["No updates needed"]
                }
                
        except Exception as e:
            logger.error(f"Error calculating missing concepts: {str(e)}")
            return {"success": False, "error": f"Failed to calculate missing concepts: {str(e)}"}

    def create_missing_concepts(self, concepts_data: list) -> dict:
        """Create multiple missing concepts with AI-generated descriptions"""
        logger.info(f"Creating {len(concepts_data)} missing concepts...")

        try:
            from .add_concept_tool import add_concept_tool_func
            
            created_concepts = []
            failed_concepts = []
            
            for concept_data in concepts_data:
                concept_name = concept_data.get("concept_name")
                if not concept_name:
                    failed_concepts.append({
                        "error": "Missing concept_name",
                        "data": concept_data
                    })
                    continue
                
                description = concept_data.get("description")
                if not description:
                    # AI-generate description based on name and relationships
                    description = self._generate_concept_description(concept_name, concept_data.get("relationships", []))
                
                relationships = concept_data.get("relationships")
                if not relationships:
                    # Create a minimal WIP relationship
                    relationships = [{"relationship": "is_a", "related": ["Work_In_Progress"]}]
                
                try:
                    result = add_concept_tool_func(
                        concept_name,
                        description,
                        relationships,
                        shared_connection=self._shared_conn
                    )
                    created_concepts.append({
                        "name": concept_name,
                        "result": result
                    })
                    logger.info(f"Created concept: {concept_name}")
                    
                except Exception as e:
                    failed_concepts.append({
                        "name": concept_name,
                        "error": str(e),
                        "data": concept_data
                    })
                    logger.error(f"Failed to create concept {concept_name}: {str(e)}")
            
            return {
                "success": True,
                "created_count": len(created_concepts),
                "failed_count": len(failed_concepts),
                "created_concepts": created_concepts,
                "failed_concepts": failed_concepts
            }
            
        except Exception as e:
            logger.error(f"Error creating missing concepts: {str(e)}")
            return {"success": False, "error": f"Failed to create missing concepts: {str(e)}"}
    
    def _generate_concept_description(self, concept_name: str, relationships: list) -> str:
        """Generate AI description for a concept based on name and relationships"""
        # Simple description generation based on concept name patterns
        name_parts = concept_name.replace('_', ' ').replace('-', ' ').lower()
        
        if any(word in name_parts for word in ['tool', 'system', 'framework']):
            base = f"{concept_name.replace('_', ' ')} is a system or tool that provides specific functionality."
        elif any(word in name_parts for word in ['protocol', 'standard', 'format']):
            base = f"{concept_name.replace('_', ' ')} is a protocol or standard for data exchange and communication."
        elif any(word in name_parts for word in ['agent', 'intelligence', 'ai']):
            base = f"{concept_name.replace('_', ' ')} is an intelligent agent or AI system with specific capabilities."
        elif any(word in name_parts for word in ['integration', 'bridge', 'adapter']):
            base = f"{concept_name.replace('_', ' ')} is an integration layer or bridge between different systems."
        else:
            base = f"{concept_name.replace('_', ' ')} is a concept that requires further definition and exploration."
        
        # Add relationship context
        if relationships:
            rel_context = []
            for rel in relationships:
                rel_type = rel.get("relationship", "relates_to")
                related = rel.get("related", [])
                if related:
                    rel_context.append(f"It {rel_type} {', '.join(related[:2])}")
            
            if rel_context:
                base += " " + ". ".join(rel_context) + "."
        
        return base
    
    def deduplicate_concepts(self, similarity_threshold: float = 0.8) -> dict:
        """Find and analyze duplicate or similar concepts"""
        logger.info(f"Finding duplicate concepts with similarity threshold {similarity_threshold}...")
        
        try:
            # Get all concepts from Neo4j
            query = "MATCH (c:Wiki) RETURN c.n as name, c.d as description ORDER BY c.n"
            result = self._execute_neo4j_query(query, {})
            
            if not result:
                return {
                    "success": True,
                    "duplicates": [],
                    "message": "No concepts found in database"
                }
            
            concepts = [(record["name"], record.get("description", "")) for record in result]
            duplicates = []
            processed = set()
            
            from difflib import SequenceMatcher
            
            # Find similar concept names
            for i, (name1, desc1) in enumerate(concepts):
                if name1 in processed:
                    continue
                    
                similar_group = [{"name": name1, "description": desc1}]
                
                for j, (name2, desc2) in enumerate(concepts[i+1:], i+1):
                    if name2 in processed:
                        continue
                    
                    # Calculate name similarity
                    name_similarity = SequenceMatcher(None, name1.lower(), name2.lower()).ratio()
                    
                    # Also check for obvious patterns
                    name1_clean = name1.lower().replace('_', '').replace('-', '')
                    name2_clean = name2.lower().replace('_', '').replace('-', '')
                    
                    if (name_similarity >= similarity_threshold or 
                        name1_clean == name2_clean or
                        name1.lower().replace('_', ' ') == name2.lower().replace('_', ' ')):
                        
                        similar_group.append({"name": name2, "description": desc2})
                        processed.add(name2)
                
                if len(similar_group) > 1:
                    duplicates.append({
                        "group": similar_group,
                        "similarity_reasons": self._analyze_similarity(similar_group)
                    })
                    processed.add(name1)
            
            logger.info(f"Found {len(duplicates)} potential duplicate groups")
            
            return {
                "success": True,
                "duplicate_groups": duplicates,
                "total_groups": len(duplicates),
                "similarity_threshold": similarity_threshold,
                "analysis": f"Found {len(duplicates)} groups of similar concepts that may need manual review"
            }
            
        except Exception as e:
            logger.error(f"Error finding duplicates: {str(e)}")
            return {"success": False, "error": f"Failed to find duplicates: {str(e)}"}
    
    def _analyze_similarity(self, similar_group: list) -> list:
        """Analyze why concepts are considered similar"""
        reasons = []
        names = [item["name"] for item in similar_group]
        
        # Check for case variations
        if len(set(name.lower() for name in names)) < len(names):
            reasons.append("Case variations of the same concept")
        
        # Check for underscore/space variations  
        normalized = [name.lower().replace('_', ' ').replace('-', ' ') for name in names]
        if len(set(normalized)) < len(names):
            reasons.append("Different formatting (underscores, spaces, hyphens)")
        
        # Check for obvious duplicates
        if len(set(names)) != len(names):
            reasons.append("Exact duplicates")
        
        if not reasons:
            reasons.append("High textual similarity")
            
        return reasons

    def retroactive_autolink_all_concepts(self) -> dict:
        """Apply auto-linking to all existing concept descriptions retroactively"""
        logger.info("Starting retroactive auto-linking of all concepts...")

        try:
            from .add_concept_tool import auto_link_description, setup_git_repo, commit_and_push

            config = self._get_neo4j_config()
            base_dir = config.base_path

            # Setup fresh git repo
            setup_result = setup_git_repo(config, base_dir)
            if "error" in setup_result:
                return {"success": False, "error": setup_result["error"]}

            concepts_dir = Path(base_dir) / "concepts"
            if not concepts_dir.exists():
                return {"success": False, "error": "Concepts directory not found"}

            updated_concepts = []

            # Process each concept directory
            for concept_dir in concepts_dir.iterdir():
                if not concept_dir.is_dir():
                    continue

                concept_name = concept_dir.name
                logger.info(f"Processing concept: {concept_name}")

                # Process description.md
                desc_file = concept_dir / "components" / "description.md"
                if desc_file.exists():
                    original_content = desc_file.read_text(encoding="utf-8")
                    linked_content = auto_link_description(original_content, base_dir, concept_name)

                    if original_content != linked_content:
                        desc_file.write_text(linked_content)
                        logger.info(f"Updated description for {concept_name}")

                # Process main concept file
                main_file = concept_dir / f"{concept_name}.md"
                if main_file.exists():
                    content = main_file.read_text(encoding="utf-8")
                    lines = content.split('\n')

                    # Find and update the overview section
                    for i, line in enumerate(lines):
                        if "## Overview" in line and i + 1 < len(lines):
                            overview_text = lines[i + 1]
                            linked_overview = auto_link_description(overview_text, base_dir, concept_name)
                            if overview_text != linked_overview:
                                lines[i + 1] = linked_overview
                                main_file.write_text('\n'.join(lines))
                                break

                # Process _itself.md file
                itself_file = concept_dir / f"{concept_name}_itself.md"
                if itself_file.exists():
                    content = itself_file.read_text(encoding="utf-8")
                    lines = content.split('\n')

                    # Find and update the overview section
                    for i, line in enumerate(lines):
                        if "## Overview" in line and i + 1 < len(lines):
                            overview_text = lines[i + 1]
                            linked_overview = auto_link_description(overview_text, base_dir, concept_name)
                            if overview_text != linked_overview:
                                lines[i + 1] = linked_overview
                                itself_file.write_text('\n'.join(lines))
                                updated_concepts.append(concept_name)
                                break

            # Commit changes
            if updated_concepts:
                commit_msg = f"Retroactive auto-linking: Updated {len(updated_concepts)} concepts"
                commit_result = commit_and_push(config, base_dir, commit_msg)
                if "error" in commit_result:
                    return {"success": False, "error": commit_result["error"]}

            return {
                "success": True,
                "message": f"Retroactive auto-linking completed",
                "updated_concepts": updated_concepts,
                "total_updated": len(updated_concepts)
            }

        except Exception as e:
            logger.error(f"Error during retroactive auto-linking: {str(e)}")
            return {"success": False, "error": f"Failed to apply retroactive auto-linking: {str(e)}"}

    def get_collection_concepts(self, collection_name: str, max_depth: int = 10) -> dict:
        """Recursively traverse HAS_PART relationships to get all concepts in a collection

        Args:
            collection_name: Name of the collection concept to traverse
            max_depth: Maximum recursion depth to prevent infinite loops

        Returns:
            Dict with success status and list of member concepts with descriptions
        """
        logger.info(f"Getting concepts for collection '{collection_name}' (max_depth={max_depth})")

        try:
            # Query to recursively traverse HAS_PART relationships
            # Don't filter by description - we want to see ALL members including missing ones
            cypher_query = """
            MATCH path = (collection:Wiki {n: $collection_name})-[:HAS_PART*1..10]->(member:Wiki)
            RETURN DISTINCT member.n as name, member.d as description
            ORDER BY member.n
            """

            result = self._execute_neo4j_query(cypher_query, {"collection_name": collection_name})

            if not result:
                return {
                    "success": True,
                    "collection_name": collection_name,
                    "concepts": [],
                    "total_count": 0,
                    "warning": None,
                    "message": f"Collection '{collection_name}' is empty or does not exist"
                }

            # Separate concepts into defined and missing
            concepts = []
            missing_concept_names = []

            for record in result:
                concept_name = record["name"]
                description = record.get("description")

                if description is None or description == "":
                    # Missing concept - track name
                    missing_concept_names.append(concept_name)
                    concepts.append({
                        "name": concept_name,
                        "description": "[MISSING CONCEPT - NOT YET DEFINED]"
                    })
                else:
                    concepts.append({
                        "name": concept_name,
                        "description": description
                    })

            # Format warning message if there are missing concepts
            warning_message = None
            if missing_concept_names:
                warning_message = f"⚠️ Warnings: [{', '.join(missing_concept_names)}] are in {collection_name} but are not defined, themselves."

            logger.info(f"Found {len(concepts)} concepts in collection '{collection_name}' ({len(missing_concept_names)} missing)")

            return {
                "success": True,
                "collection_name": collection_name,
                "concepts": concepts,
                "total_count": len(concepts),
                "warning": warning_message
            }

        except Exception as e:
            logger.error(f"Error getting collection concepts: {str(e)}")
            return {"success": False, "error": f"Failed to get collection concepts: {str(e)}"}

    def list_all_collections(self) -> dict:
        """List all Carton_Collection concepts in the knowledge graph

        Collections are identified by IS_A Carton_Collection relationship.

        Returns:
            Dict with success status and list of collection names
        """
        logger.info("Listing all Carton_Collections...")

        try:
            # Query for concepts that are Carton_Collection type
            cypher_query = """
            MATCH (collection:Wiki)-[:IS_A]->(type:Wiki {n: "Carton_Collection"})
            OPTIONAL MATCH (collection)-[:HAS_PART]->(member:Wiki)
            WHERE NOT collection.n =~ '.*_v[0-9]+$'
              AND NOT collection.n =~ '.*_Observation$'
            RETURN DISTINCT collection.n as name, collection.d as description,
                   count(member) as concept_count
            ORDER BY collection.n
            """

            result = self._execute_neo4j_query(cypher_query, {})

            if not result:
                return {
                    "success": True,
                    "collections": [],
                    "total_count": 0,
                    "message": "No memory collections found"
                }

            collections = [
                {
                    "name": record["name"],
                    "description": record.get("description", "No description"),
                    "concept_count": record["concept_count"]
                }
                for record in result
            ]

            logger.info(f"Found {len(collections)} memory collections")

            return {
                "success": True,
                "collections": collections,
                "total_count": len(collections)
            }

        except Exception as e:
            logger.error(f"Error listing collections: {str(e)}")
            return {"success": False, "error": f"Failed to list collections: {str(e)}"}

    def scan_carton(self, query: str, max_results: int = 10) -> str:
        """
        Bottom-up aggregation RAG scan: conversations → concepts → collections

        Returns GPS coordinates of relevant knowledge organized hierarchically.
        De-duplicates so concepts in collections don't appear as orphaned.

        Args:
            query: Natural language query
            max_results: Maximum RAG results to process (default 10)

        Returns:
            Formatted GPS injection string
        """
        logger.info(f"Scanning CartON for: {query}")

        try:
            # Step 1: Query BOTH collections
            # Import after local import to avoid circular dependency
            from .server_fastmcp import chroma_query
            import re

            # Step 1a: Query carton_conversations for relevant conversations
            conversation_concepts = []
            try:
                conv_rag_result = chroma_query(
                    query=query,
                    collection_name="carton_conversations",
                    k=max_results,
                    max_tokens=5000
                )

                if "No relevant knowledge found" not in conv_rag_result and "Query failed" not in conv_rag_result:
                    for line in conv_rag_result.split('\n'):
                        match = re.match(r'^\d+\.\s+([^\(]+)\s+\(([0-9.]+)\)', line.strip())
                        if match:
                            conversation_concepts.append(match.group(1).strip())
            except Exception as e:
                logger.warning(f"Could not query carton_conversations: {e}")

            # Step 1b: Query carton_concepts for relevant user-created concepts
            user_concepts = []
            try:
                concepts_rag_result = chroma_query(
                    query=query,
                    collection_name="carton_concepts",
                    k=max_results,
                    max_tokens=5000
                )

                if "No relevant knowledge found" not in concepts_rag_result and "Query failed" not in concepts_rag_result:
                    for line in concepts_rag_result.split('\n'):
                        match = re.match(r'^\d+\.\s+([^\(]+)\s+\(([0-9.]+)\)', line.strip())
                        if match:
                            user_concepts.append(match.group(1).strip())
            except Exception as e:
                logger.warning(f"Could not query carton_concepts: {e}")

            if not conversation_concepts and not user_concepts:
                return "🔍 CartON Scan: No relevant knowledge found"

            # Step 2: Batch query - find concepts for ALL conversations in one query
            conversation_to_concepts = {conv: [] for conv in conversation_concepts}
            all_concepts_from_convs = set()

            if conversation_concepts:
                batch_query_concepts = """
                UNWIND $conv_names AS conv_name
                MATCH (c:Wiki)-[:PART_OF]->(conv:Wiki {n: conv_name})
                WHERE NOT c.n =~ '.*_v[0-9]+$'
                  AND NOT c.n =~ '.*_Observation$'
                  AND NOT c.n STARTS WITH 'UserThought_'
                  AND NOT c.n STARTS WITH 'AgentMessage_'
                  AND NOT c.n STARTS WITH 'ToolCall_'
                RETURN conv_name, c.n as concept_name
                """

                result = self._execute_neo4j_query(batch_query_concepts, {"conv_names": conversation_concepts})

                if result:
                    for row in result:
                        conv = row["conv_name"]
                        concept = row["concept_name"]
                        conversation_to_concepts[conv].append(concept)
                        all_concepts_from_convs.add(concept)

            # Step 3: Merge user concepts with concepts from conversations
            all_concepts = all_concepts_from_convs.union(set(user_concepts))

            # Step 4: Batch query - find collections for ALL concepts in one query
            concept_to_collections = {c: [] for c in all_concepts}
            all_collections = set()

            if all_concepts:
                batch_query_collections = """
                UNWIND $concept_names AS concept_name
                MATCH (col:Wiki)-[:HAS_PART]->(c:Wiki {n: concept_name})
                MATCH (col)-[:IS_A]->(type:Wiki)
                WHERE type.n IN ['Carton_Collection', 'Global_Collection', 'Local_Collection', 'Identity_Collection']
                RETURN concept_name, col.n as collection_name
                """

                result = self._execute_neo4j_query(batch_query_collections, {"concept_names": list(all_concepts)})

                if result:
                    for row in result:
                        concept = row["concept_name"]
                        collection = row["collection_name"]
                        concept_to_collections[concept].append(collection)
                        all_collections.add(collection)

            # Step 4: Build collection membership map
            collection_members = {}
            for concept, collections in concept_to_collections.items():
                for col in collections:
                    if col not in collection_members:
                        collection_members[col] = []
                    collection_members[col].append(concept)

            # Step 5: Categorize and de-duplicate
            # Orphaned concepts: concepts not in any collection
            orphaned_concepts = [c for c in all_concepts if not concept_to_collections.get(c)]

            # Orphaned conversations: conversations with no concepts
            orphaned_conversations = [conv for conv, concepts in conversation_to_concepts.items() if not concepts]

            # Step 5.5: Filter out metadata concepts (same rules as ChromaRAG)
            def should_show_in_gps(concept_name: str) -> bool:
                """Filter out internal metadata concepts from GPS display"""
                import re
                # Timestamped observations
                if re.match(r'^\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_Observation$', concept_name):
                    return False
                # Sync concepts
                if re.match(r'^Sync_\d+$', concept_name):
                    return False
                # Requires_Evolution marker
                if concept_name == 'Requires_Evolution':
                    return False
                # Sunk concepts (_v1, _v2, etc.)
                if re.match(r'.*_v\d+$', concept_name):
                    return False
                # Day timeline concepts
                if re.match(r'^Day_\d{4}_\d{2}_\d{2}$', concept_name):
                    return False
                # Raw conversation timelines
                if re.match(r'^Raw_Conversation_Timeline_\d{4}_\d{2}_\d{2}$', concept_name):
                    return False
                # Conversation transcripts (should be in separate collection)
                if concept_name.startswith(('Conversation_', 'UserThought_', 'AgentMessage_', 'ToolCall_')):
                    return False
                # Update_History metadata concepts (K_Update_History, C_Update_History, etc.)
                if re.match(r'^[A-Z\d]_Update_History$', concept_name):
                    return False
                return True

            # Filter orphaned concepts (user-created concepts only - exclude metadata)
            orphaned_concepts = [c for c in orphaned_concepts if should_show_in_gps(c)]

            # Note: orphaned_conversations are NOT filtered - they are conversation concepts by definition

            # Step 6: Format GPS injection
            lines = ["🔍 CartON Scan Results"]
            lines.append("=" * 60)

            if collection_members:
                lines.append("\n📦 Relevant Collections (curated knowledge):")
                for col_name, members in sorted(collection_members.items()):
                    lines.append(f"  - {col_name} (contains: {', '.join(members[:3])}{'...' if len(members) > 3 else ''})")

            if orphaned_concepts:
                lines.append("\n📋 Orphaned Concepts (not in collections):")
                for concept in sorted(orphaned_concepts)[:10]:
                    # Find source conversation
                    source_conv = None
                    for conv, concepts in conversation_to_concepts.items():
                        if concept in concepts:
                            source_conv = conv
                            break

                    if source_conv:
                        lines.append(f"  - {concept} (from {source_conv})")
                    else:
                        lines.append(f"  - {concept}")

            if orphaned_conversations:
                lines.append("\n💬 Orphaned Conversations (no concepts extracted):")
                for conv in sorted(orphaned_conversations)[:5]:
                    lines.append(f"  - {conv}")

            lines.append("\n💡 Recommendation: Start with collections (most organized), then fill gaps with orphaned concepts/conversations")

            result = "\n".join(lines)
            logger.info(f"CartON scan complete: {len(collection_members)} collections, {len(orphaned_concepts)} orphaned concepts, {len(orphaned_conversations)} orphaned conversations")

            return result

        except Exception as e:
            logger.error(f"Error scanning CartON: {str(e)}", exc_info=True)
            return f"❌ CartON scan failed: {str(e)}"