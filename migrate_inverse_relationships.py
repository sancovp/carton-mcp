#!/usr/bin/env python3
"""
Migration tool to add missing inverse relationship files to existing concepts.

This script:
1. Queries Neo4j for all relationships
2. For each relationship with an inverse (is_a -> has_instances, etc.)
3. Checks if inverse file exists on target concept's filesystem
4. Creates missing inverse files

Usage:
    python3 migrate_inverse_relationships.py
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

def normalize_concept_name(name: str) -> str:
    """Normalize concept name to Title_Case_With_Underscores format."""
    return name.replace(' ', '_').title()


def migrate_inverse_relationships():
    """Migrate all missing inverse relationships to filesystem."""

    # Get config
    from concept_config import ConceptConfig

    github_pat = os.getenv('GITHUB_PAT')
    repo_url = os.getenv('REPO_URL')
    branch = os.getenv('BRANCH', 'main')

    if not github_pat or not repo_url:
        print("ERROR: GITHUB_PAT and REPO_URL environment variables must be set")
        sys.exit(1)

    base_path_override = os.getenv('BASE_PATH')

    config = ConceptConfig(
        github_pat=github_pat,
        repo_url=repo_url,
        neo4j_url=os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687'),
        neo4j_username=os.getenv('NEO4J_USER', 'neo4j'),
        neo4j_password=os.getenv('NEO4J_PASSWORD', 'password'),
        branch=branch,
        base_path=base_path_override
    )

    base_dir = Path(config.base_path)
    concepts_dir = base_dir / "concepts"

    # Define inverse relationships
    relationship_inverses = {
        'IS_A': 'has_instances',
        'PART_OF': 'has_parts',
        'DEPENDS_ON': 'supports',
        'INSTANTIATES': 'has_instances',
        'RELATES_TO': 'relates_to'
    }

    print("Querying Neo4j for all relationships...")

    # Query Neo4j for all relationships
    from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

    graph = KnowledgeGraphBuilder(
        uri=config.neo4j_url,
        user=config.neo4j_username,
        password=config.neo4j_password
    )

    # Get all relationships that have inverses
    query = """
    MATCH (source:Wiki)-[r]->(target:Wiki)
    WHERE type(r) IN ['IS_A', 'PART_OF', 'DEPENDS_ON', 'INSTANTIATES', 'RELATES_TO']
    RETURN source.n as source_name, type(r) as rel_type, target.n as target_name
    ORDER BY target_name, rel_type
    """

    results = graph.execute_query(query)
    graph.close()

    print(f"Found {len(results)} relationships to process")

    # Group relationships by target concept and inverse relationship type
    # Structure: {target_concept: {inverse_rel_type: [source_concepts]}}
    inverse_map = defaultdict(lambda: defaultdict(list))

    for record in results:
        source_name = record['source_name']
        rel_type = record['rel_type']
        target_name = record['target_name']

        inverse_rel = relationship_inverses.get(rel_type)
        if inverse_rel:
            inverse_map[target_name][inverse_rel].append(source_name)

    # Track statistics
    stats = {
        'concepts_processed': 0,
        'files_created': 0,
        'entries_added': 0,
        'entries_skipped': 0
    }

    print(f"\nProcessing {len(inverse_map)} target concepts...")

    # Create missing inverse files
    for target_name, inverse_rels in inverse_map.items():
        stats['concepts_processed'] += 1

        normalized_target = normalize_concept_name(target_name)
        target_dir = concepts_dir / normalized_target
        target_components = target_dir / "components"

        # Create directories if needed
        target_dir.mkdir(parents=True, exist_ok=True)
        target_components.mkdir(exist_ok=True)

        for inverse_rel, source_concepts in inverse_rels.items():
            inverse_dir = target_components / inverse_rel
            inverse_dir.mkdir(exist_ok=True)

            inverse_file = inverse_dir / f"{normalized_target}_{inverse_rel}.md"

            # Check if file exists
            if inverse_file.exists():
                existing_content = inverse_file.read_text()
            else:
                # Create new file
                existing_content = f"# {inverse_rel.title()} Relationships for {normalized_target}\n\n"
                stats['files_created'] += 1

            # Add missing entries
            entries_to_add = []
            for source_name in source_concepts:
                normalized_source = normalize_concept_name(source_name)
                source_url = f"../{normalized_source}/{normalized_source}_itself.md"
                entry = f"- {normalized_target} {inverse_rel} [{source_name}]({source_url})"

                if entry not in existing_content:
                    entries_to_add.append(entry)
                    stats['entries_added'] += 1
                else:
                    stats['entries_skipped'] += 1

            # Write updated file if we added entries
            if entries_to_add:
                updated_content = existing_content.rstrip() + "\n" + "\n".join(entries_to_add) + "\n"
                inverse_file.write_text(updated_content)

                print(f"  Updated {target_name}/{inverse_rel}: added {len(entries_to_add)} entries")

    # Print statistics
    print("\n" + "="*60)
    print("Migration complete!")
    print("="*60)
    print(f"Concepts processed:  {stats['concepts_processed']}")
    print(f"Files created:       {stats['files_created']}")
    print(f"Entries added:       {stats['entries_added']}")
    print(f"Entries skipped:     {stats['entries_skipped']} (already existed)")
    print("="*60)


if __name__ == "__main__":
    try:
        migrate_inverse_relationships()
    except Exception as e:
        import traceback
        print(f"\nERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
