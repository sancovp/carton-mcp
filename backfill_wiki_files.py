#!/usr/bin/env python3
"""
Backfill wiki files from Neo4j concepts.

One-time script to create wiki markdown files for all concepts in Neo4j
that are missing wiki files. This fixes the sync gap where concepts
were created in Neo4j but wiki files were never generated.

Usage:
    python3 backfill_wiki_files.py [--dry-run]

Environment Variables:
    NEO4J_URI: Neo4j connection URI
    NEO4J_USER: Neo4j username
    NEO4J_PASSWORD: Neo4j password
    HEAVEN_DATA_DIR: Base directory (default: /tmp/heaven_data)
"""

import os
import sys
from pathlib import Path


def normalize_concept_name(name: str) -> str:
    """Normalize concept name for filesystem."""
    if not name:
        return ""
    # Replace spaces with underscores, title case each word
    normalized = name.replace(' ', '_')
    # Title case but preserve existing caps in acronyms
    parts = normalized.split('_')
    result_parts = []
    for part in parts:
        if part.isupper() and len(part) > 1:
            result_parts.append(part)
        elif part:
            result_parts.append(part[0].upper() + part[1:] if len(part) > 1 else part.upper())
    return '_'.join(result_parts)


def get_all_concepts_from_neo4j():
    """Query Neo4j for all concepts with their descriptions and relationships."""
    from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

    graph = KnowledgeGraphBuilder(
        uri=os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687'),
        user=os.getenv('NEO4J_USER', 'neo4j'),
        password=os.getenv('NEO4J_PASSWORD', 'password')
    )

    # Get all concepts
    concepts_query = """
    MATCH (c:Wiki)
    RETURN c.n as name, c.d as description
    """
    concepts_result = graph.execute_query(concepts_query)

    concepts = {}
    for record in concepts_result:
        name = record.get('name', '') if isinstance(record, dict) else record['name']
        desc = record.get('description', '') if isinstance(record, dict) else record['description']
        if name:
            concepts[name] = {
                'name': name,
                'description': desc or f'No description for {name}',
                'relationships': {}
            }

    # Get all relationships for each concept
    rels_query = """
    MATCH (c:Wiki)-[r]->(t:Wiki)
    RETURN c.n as source, type(r) as rel_type, t.n as target
    """
    rels_result = graph.execute_query(rels_query)

    for record in rels_result:
        source = record.get('source', '') if isinstance(record, dict) else record['source']
        rel_type = record.get('rel_type', '') if isinstance(record, dict) else record['rel_type']
        target = record.get('target', '') if isinstance(record, dict) else record['target']

        if source in concepts and rel_type and target:
            rel_type_lower = rel_type.lower()
            if rel_type_lower not in concepts[source]['relationships']:
                concepts[source]['relationships'][rel_type_lower] = []
            concepts[source]['relationships'][rel_type_lower].append(target)

    graph.close()
    return list(concepts.values())


def create_wiki_file(concept: dict, wiki_concepts_dir: Path) -> tuple[bool, str]:
    """Create wiki file for a single concept. Returns (created, reason)."""
    name = concept.get('name', '')
    if not name:
        return False, "empty name"

    description = concept.get('description', f'No description for {name}')
    relationships = concept.get('relationships', {})

    normalized_name = normalize_concept_name(name)
    concept_dir = wiki_concepts_dir / normalized_name
    itself_file = concept_dir / f"{normalized_name}_itself.md"

    # Skip if file already exists
    if itself_file.exists():
        return False, "exists"

    # Create directory
    concept_dir.mkdir(parents=True, exist_ok=True)

    # Build content
    itself_content = [
        f"# {normalized_name}",
        "",
        "## Overview",
        description,
        "",
        "## Relationships"
    ]

    for rel_type in sorted(relationships.keys()):
        items = relationships[rel_type]
        if not items:
            continue
        itself_content.extend(["", f"### {rel_type.replace('_', ' ').title()}", ""])
        for item in items:
            normalized_item = normalize_concept_name(item)
            item_url = f"../{normalized_item}/{normalized_item}_itself.md"
            itself_content.append(f"- {normalized_name} {rel_type} [{item}]({item_url})")

    itself_file.write_text("\n".join(itself_content))
    return True, "created"


def backfill_wiki_files(dry_run: bool = False):
    """Main backfill function."""
    heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    wiki_concepts_dir = Path(heaven_data_dir) / 'wiki' / 'concepts'

    print(f"Wiki directory: {wiki_concepts_dir}")
    print(f"Dry run: {dry_run}")
    print()

    # Get all concepts from Neo4j
    print("Fetching concepts from Neo4j...")
    concepts = get_all_concepts_from_neo4j()
    print(f"Found {len(concepts)} concepts in Neo4j")

    # Check existing wiki files
    existing_files = set()
    if wiki_concepts_dir.exists():
        for concept_dir in wiki_concepts_dir.iterdir():
            if concept_dir.is_dir():
                itself_file = concept_dir / f"{concept_dir.name}_itself.md"
                if itself_file.exists():
                    existing_files.add(concept_dir.name)

    print(f"Found {len(existing_files)} existing wiki files")
    print()

    # Find missing
    missing = []
    for concept in concepts:
        normalized = normalize_concept_name(concept['name'])
        if normalized not in existing_files:
            missing.append(concept)

    print(f"Missing wiki files: {len(missing)}")

    if not missing:
        print("All concepts have wiki files!")
        return

    # Show some examples
    print("\nFirst 10 missing concepts:")
    for c in missing[:10]:
        print(f"  - {c['name']}")

    if dry_run:
        print("\n[DRY RUN] Would create wiki files for all missing concepts")
        return

    # Create wiki files
    print("\nCreating wiki files...")
    wiki_concepts_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    errors = 0

    for i, concept in enumerate(missing):
        try:
            success, reason = create_wiki_file(concept, wiki_concepts_dir)
            if success:
                created += 1
            if (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{len(missing)} ({created} created)")
        except Exception as e:
            errors += 1
            print(f"  Error creating {concept['name']}: {e}")

    print(f"\nBackfill complete!")
    print(f"  Created: {created}")
    print(f"  Errors: {errors}")
    print(f"  Already existed: {len(missing) - created - errors}")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    backfill_wiki_files(dry_run=dry_run)
