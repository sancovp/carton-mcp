#!/usr/bin/env python3
"""
CartON Observation Queue Worker Daemon

Processes observation queue files from $HEAVEN_DATA_DIR/carton_queue/
Runs continuously in background, processing observations asynchronously.

Usage:
    python3 observation_worker_daemon.py

Environment Variables:
    GITHUB_PAT: GitHub Personal Access Token
    REPO_URL: GitHub repository URL
    NEO4J_URI: Neo4j connection URI
    NEO4J_USER: Neo4j username
    NEO4J_PASSWORD: Neo4j password
    HEAVEN_DATA_DIR: Base directory (default: /tmp/heaven_data)
"""

import os
import sys
import time
import json
import traceback
import threading
from pathlib import Path
from typing import Dict, Any

# Import worker function (absolute import for standalone script execution)
from carton_mcp.add_concept_tool import _add_observation_worker, get_observation_queue_dir, auto_link_description, normalize_concept_name

# Batch size for UNWIND operations - M4 can handle 20k but we use 2k for safety
UNWIND_BATCH_SIZE = 2000

# Module-level ChromaDB cache — same pattern as server_fastmcp._rag_cache
_rag_cache: dict = {}


def create_wiki_files_for_concepts(concepts_data: list) -> dict:
    """
    Create wiki markdown files for concepts.

    This is the missing piece - daemon creates Neo4j entries but wiki files
    are required for ChromaDB RAG indexing.

    Args:
        concepts_data: List of dicts with {name, description, relationships}
            relationships is Dict[str, List[str]] mapping rel_type to targets

    Returns:
        dict with counts: {files_created, files_skipped, errors}
    """
    heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    wiki_concepts_dir = Path(heaven_data_dir) / 'wiki' / 'concepts'
    wiki_concepts_dir.mkdir(parents=True, exist_ok=True)

    files_created = 0
    files_skipped = 0
    errors = []

    for concept in concepts_data:
        name = concept.get('name', '')
        if not name:
            continue

        description = concept.get('description', f'No description for {name}')
        relationships = concept.get('relationships', {})

        # Normalize name for filesystem
        normalized_name = normalize_concept_name(name)

        # Create concept directory
        concept_dir = wiki_concepts_dir / normalized_name
        concept_dir.mkdir(parents=True, exist_ok=True)

        # Create _itself.md file (this is what ChromaDB indexes)
        itself_file = concept_dir / f"{normalized_name}_itself.md"

        try:
            # Build the _itself.md content
            itself_content = [
                f"# {normalized_name}",
                "",
                "## Overview",
                description,
                "",
                "## Relationships"
            ]

            # Add relationships sorted by type
            for rel_type in sorted(relationships.keys()):
                items = relationships[rel_type]
                if not items:
                    continue
                itself_content.extend(["", f"### {rel_type.replace('_', ' ').title()}", ""])
                for item in items:
                    normalized_item = normalize_concept_name(item)
                    item_url = f"../{normalized_item}/{normalized_item}_itself.md"
                    itself_content.append(f"- {normalized_name} {rel_type} [{item}]({item_url})")

            # Write the file
            itself_file.write_text("\n".join(itself_content))
            files_created += 1

        except Exception as e:
            errors.append(f"Failed to create {normalized_name}: {e}")
            print(f"[WikiFiles] ERROR creating {normalized_name}: {e}", file=sys.stderr)

    if files_created > 0:
        print(f"[WikiFiles] Created {files_created} wiki files", file=sys.stderr)

    return {
        'files_created': files_created,
        'files_skipped': files_skipped,
        'errors': errors
    }


def batch_create_concepts_neo4j(concepts_data: list, shared_connection) -> dict:
    """
    Batch create concepts using UNWIND - 900x faster than individual queries.

    Args:
        concepts_data: List of dicts with {name, canonical, description, relationships}
            relationships is Dict[str, List[str]] mapping rel_type to targets
        shared_connection: Shared Neo4j connection

    Returns:
        dict with counts: {concepts_created, relationships_created, errors}
    """
    from datetime import datetime
    from collections import defaultdict

    if not concepts_data:
        return {'concepts_created': 0, 'relationships_created': 0, 'errors': []}

    graph = shared_connection
    errors = []

    # Ensure indexes exist (idempotent, runs once per session)
    try:
        graph.execute_query("CREATE INDEX wiki_name IF NOT EXISTS FOR (w:Wiki) ON (w.n)")
        graph.execute_query("CREATE INDEX wiki_canonical IF NOT EXISTS FOR (w:Wiki) ON (w.c)")
    except Exception as idx_err:
        # Index might already exist or query failed - continue anyway
        print(f"[UNWIND] Index creation note: {idx_err}", file=sys.stderr)

    # Prepare concept rows for UNWIND
    concept_rows = []
    for c in concepts_data:
        name = c.get('name', '')
        if not name:
            continue
        name = normalize_concept_name(name)
        concept_rows.append({
            'name': name,
            'canonical': name.lower().replace(' ', '_'),
            'description': c.get('description', f'No description for {name}'),
            'timestamp': c.get('timestamp'),  # Pass through original timestamp if available
            'update_mode': c.get('desc_update_mode', 'append'),  # append/prepend/replace
            'source': c.get('source', 'agent'),  # Timeline source — who/what created this concept
            # NOTE: layer is determined by REQUIRES_EVOLUTION relationship, not a property
            # SOUP = has REQUIRES_EVOLUTION, ONT = no REQUIRES_EVOLUTION
        })

    # Section-level dedup: before UNWIND, fetch existing descriptions and strip
    # sections that already exist. Prevents identical paragraphs from accumulating
    # across repeated appends (e.g. daemon reruns, observation re-emissions).
    append_names = [r['name'] for r in concept_rows if r['update_mode'] == 'append']
    if append_names and graph:
        try:
            existing_result = graph.execute_query(
                "UNWIND $names AS name MATCH (n:Wiki {n: name}) WHERE n.d IS NOT NULL RETURN n.n AS name, n.d AS desc",
                {'names': append_names}
            )
            existing_map = {}
            if existing_result:
                records = existing_result[0] if isinstance(existing_result, tuple) else existing_result
                for record in records:
                    try:
                        rname = record.get('name', '') if isinstance(record, dict) else record['name']
                        rdesc = record.get('desc', '') if isinstance(record, dict) else record['desc']
                        if rname and rdesc:
                            existing_map[rname] = rdesc
                    except (TypeError, KeyError):
                        continue

            # Strip wiki links for comparison. Uses _itself.md) as the literal end
            # anchor (URLs can contain ( ) when concept names have parens like Orient()).
            # Also handles orphan residue from prior partial strips. See matching
            # logic in add_concept_tool.auto_link_description and substrate_projector.
            # TODO: consolidate these three copies into one shared utility in carton_utils.
            import re
            def _strip_links(s):
                if not s:
                    return s
                for _ in range(200):
                    prev = s
                    s = re.sub(r"\[([^\[\]]*?)\]\(\.\./.+?_itself\.md\)", r"\1", s)
                    s = re.sub(r"\(\.\./.+?_itself\.md\)", "", s)
                    s = re.sub(r"/[^/\s]*?_itself\.md\)+", "", s)
                    s = re.sub(r"_itself\.md\)+", "", s)
                    if s == prev:
                        break
                s = re.sub(r"\[([^\[\]]*?)\]", r"\1", s)
                s = re.sub(r"[\[\]]", "", s)
                s = re.sub(r"  +", " ", s)
                return s.strip()

            for row in concept_rows:
                if row['update_mode'] != 'append' or row['name'] not in existing_map:
                    continue
                existing = existing_map[row['name']]
                if not existing:
                    continue
                # Split by section separator, strip wiki links for comparison
                existing_sections = set(_strip_links(s) for s in existing.split('\n\n---\n\n') if s.strip())
                new_sections = [s.strip() for s in row['description'].split('\n\n---\n\n') if s.strip()]
                novel = [s for s in new_sections if _strip_links(s) not in existing_sections]
                if not novel:
                    row['update_mode'] = 'skip'  # nothing new to add
                    print(f"[DEDUP] Skipping duplicate append for {row['name']}", file=sys.stderr)
                else:
                    row['description'] = '\n\n---\n\n'.join(novel)
        except Exception as dedup_err:
            print(f"[DEDUP] Pre-dedup query failed (continuing without dedup): {dedup_err}", file=sys.stderr)

    # UNWIND: Create all concept nodes at once (set linked=false for new concepts)
    # Use original timestamp if provided, otherwise use current datetime
    # desc_update_mode: append (default) | prepend | replace | skip (deduped)
    # NOTE: layer is determined by REQUIRES_EVOLUTION relationship, not a property
    try:
        create_query = """
        UNWIND $concepts AS c
        MERGE (n:Wiki {n: c.name})
        ON CREATE SET n.c = c.canonical, n.linked = false
        SET n.d = CASE
            WHEN n.d IS NULL OR n.d = ''
                THEN c.description
            WHEN c.update_mode = 'skip'
                THEN n.d
            WHEN n.d = c.description
                THEN n.d
            WHEN c.description CONTAINS n.d
                THEN c.description
            WHEN n.d CONTAINS c.description
                THEN n.d
            WHEN c.update_mode = 'append'
                THEN n.d + '\n\n---\n\n' + c.description
            WHEN c.update_mode = 'prepend'
                THEN c.description + '\n\n---\n\n' + n.d
            ELSE c.description
        END
        SET n.t = CASE WHEN n.t IS NULL THEN (CASE WHEN c.timestamp IS NOT NULL THEN datetime(c.timestamp) ELSE datetime() END) ELSE n.t END
        SET n.last_modified = datetime()
        SET n.linked = false
        SET n.source = CASE WHEN n.source IS NULL THEN c.source ELSE n.source END
        """
        graph.execute_query(create_query, {'concepts': concept_rows})
        print(f"[UNWIND] Created {len(concept_rows)} concept nodes", file=sys.stderr)
    except Exception as e:
        errors.append(f"Concept creation failed: {e}")
        print(f"[UNWIND] ERROR creating concepts: {e}", file=sys.stderr)

    # Flatten all relationships and group by type
    rels_by_type = defaultdict(list)
    for c in concepts_data:
        source = normalize_concept_name(c.get('name', ''))
        if not source:
            continue
        relationships = c.get('relationships', {})
        for rel_type, targets in relationships.items():
            rel_type_upper = rel_type.upper()
            for target in targets:
                target_normalized = normalize_concept_name(target)
                rels_by_type[rel_type_upper].append({
                    'source': source,
                    'target': target_normalized
                })
                
                # Create inverse relationships for bidirectionality
                inverse_map = {
                    'PART_OF': 'HAS_PART',
                    'HAS_PART': 'PART_OF',
                    'IS_A': 'HAS_INSTANCES',
                    'INSTANTIATES': 'INSTANTIATED_BY',
                }
                if rel_type_upper in inverse_map:
                    inv_type = inverse_map[rel_type_upper]
                    rels_by_type[inv_type].append({
                        'source': target_normalized,
                        'target': source
                    })

    # UNWIND per relationship type (Neo4j can't do dynamic rel types)
    total_rels = 0
    for rel_type, rels in rels_by_type.items():
        try:
            rel_query = f"""
            UNWIND $rels AS r
            MATCH (source:Wiki {{n: r.source}})
            MERGE (target:Wiki {{n: r.target}})
            ON CREATE SET target.d = 'AUTO CREATED: stub node referenced as {rel_type} target by ' + r.source + '. Not yet fully defined.',
                          target.linked = false,
                          target.t = datetime()
            MERGE (source)-[rel:{rel_type}]->(target)
            SET rel.ts = datetime()
            """
            graph.execute_query(rel_query, {'rels': rels})
            total_rels += len(rels)
        except Exception as e:
            errors.append(f"Relationship {rel_type} failed: {e}")
            print(f"[UNWIND] ERROR creating {rel_type} relationships: {e}", file=sys.stderr)

    print(f"[UNWIND] Created {total_rels} relationships across {len(rels_by_type)} types", file=sys.stderr)

    # Check for SOUP items that can be promoted now that new concepts exist
    promoted = check_and_promote_soup_items(graph, [c['name'] for c in concept_rows])
    if promoted > 0:
        print(f"[UNWIND] Promoted {promoted} SOUP items to ONT", file=sys.stderr)

    return {
        'concepts_created': len(concept_rows),
        'relationships_created': total_rels,
        'errors': errors,
        'promoted': promoted
    }


def check_and_promote_soup_items(graph, new_concept_names: list) -> int:
    """DISABLED: SOMA validates inline. No background polling needed."""
    return 0
    if not new_concept_names:
        return 0

    promoted_count = 0

    try:
        # Find SOUP items whose reason mentions any of the new concepts
        # The reason contains what's missing, e.g., "Pet is_a ? (unknown)"
        query = """
        MATCH (s:Wiki)-[r:REQUIRES_EVOLUTION]->(re:Wiki {n: "Requires_Evolution"})
        WHERE any(name IN $new_names WHERE r.reason CONTAINS name)
        RETURN s.n as name, r.reason as reason
        """
        result = graph.execute_query(query, {'new_names': new_concept_names})

        if not result:
            return 0

        for record in result:
            name = record.get('name') if isinstance(record, dict) else record['name']
            reason = record.get('reason') if isinstance(record, dict) else record['reason']

            # Re-validate via YOUKNOW — the reasoner confirms chain now completes
            try:
                from youknow_kernel.compiler import youknow as youknow_validate
                # Reconstruct statement from ALL concept relationships in Neo4j
                # Must query ALL rels so Skills (22 fields) can be fully re-validated
                rel_query = """
                MATCH (c:Wiki {n: $name})-[r]->(t:Wiki)
                WHERE type(r) <> 'REQUIRES_EVOLUTION'
                RETURN type(r) as rel, t.n as target
                """
                rels = graph.execute_query(rel_query, {'name': name})
                if rels:
                    # Build statement: "Name is_a X, part_of Y, produces Z"
                    triples = []
                    for rel_rec in rels:
                        rel_type = (rel_rec.get('rel') if isinstance(rel_rec, dict) else rel_rec['rel']).lower()
                        target = rel_rec.get('target') if isinstance(rel_rec, dict) else rel_rec['target']
                        if target:
                            triples.append(f"{rel_type} {target}")
                    if triples:
                        statement = f"{name} {', '.join(triples)}"
                        yk_result = youknow_validate(statement)
                        if yk_result == "OK":
                            # Chain completes — promote to ONT
                            promote_query = """
                            MATCH (s:Wiki {n: $name})-[r:REQUIRES_EVOLUTION]->(re:Wiki {n: "Requires_Evolution"})
                            DELETE r
                            """
                            graph.execute_query(promote_query, {'name': name})
                            promoted_count += 1
                            print(f"[Promote] {name}: SOUP → ONT (youknow confirmed)", file=sys.stderr)
                        else:
                            print(f"[Promote] {name}: still SOUP — {yk_result[:80]}", file=sys.stderr)
                        continue
            except ImportError:
                print(f"[Promote] youknow_kernel not available — skipping re-validation for {name}", file=sys.stderr)
            except Exception as e:
                print(f"[Promote] YOUKNOW re-validation failed for {name}: {e}", file=sys.stderr)

            # Fallback: if youknow not available, still promote (old behavior)
            promote_query = """
            MATCH (s:Wiki {n: $name})-[r:REQUIRES_EVOLUTION]->(re:Wiki {n: "Requires_Evolution"})
            DELETE r
            """
            graph.execute_query(promote_query, {'name': name})
            promoted_count += 1
            print(f"[Promote] {name}: SOUP → ONT (fallback — youknow unavailable)", file=sys.stderr)

    except Exception as e:
        print(f"[Promote] Error checking SOUP items: {e}", file=sys.stderr)

    return promoted_count


def parse_queue_file_to_concepts(queue_file: Path) -> list:
    """
    Parse a queue file into flat list of concept dicts for batch processing.

    Handles three formats:
    - raw_concept files: single concept
    - concepts list files: {"concepts": [...]} with name/description/relationships per item
    - observation files: N+1 concepts (wrapper + parts via observation tags)

    Returns:
        List of dicts with {name, description, relationships}
    """
    from carton_mcp.add_concept_tool import normalize_concept_name, OBSERVATION_TAGS
    from datetime import datetime

    try:
        with open(queue_file, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[Parse] Failed to read {queue_file.name}: {e}", file=sys.stderr)
        return []

    concepts = []

    if data.get('raw_concept') or data.get('concept_name'):
        # Raw concept - single concept (detect by raw_concept flag OR concept_name key)
        name = normalize_concept_name(data.get('concept_name', ''))
        if name:
            # Convert relationships list to dict
            rels_dict = {}
            for rel in data.get('relationships', []):
                rel_type = rel.get('relationship', '')
                related = rel.get('related', [])
                if rel_type and related:
                    rels_dict[rel_type] = related

            concepts.append({
                'name': name,
                'description': data.get('description', ''),
                'relationships': rels_dict,
                'timestamp': data.get('timestamp'),  # Pass through original timestamp
                'desc_update_mode': data.get('desc_update_mode', 'append'),  # append/prepend/replace
                'skip_ontology_healing': data.get('skip_ontology_healing', False),
                # YOUKNOW CODE decision — triggers substrate projection in Phase 2.5a
                'is_code': data.get('is_code', False),
                'gen_target': data.get('gen_target'),
                # SOMA SYSTEM_TYPE decision (doc 28) — CODE + all d-chains pass.
                # Phase 2.5a routes projection on is_system_type + is_a, not gen_target.
                'is_system_type': data.get('is_system_type', False),
                # SOUP tracking — daemon creates REQUIRES_EVOLUTION if is_soup=True
                'is_soup': data.get('is_soup', False),
                'soup_reason': data.get('soup_reason'),
                # Timeline source — who/what created this concept
                'source': data.get('source', 'agent'),
                # Target descs — cached KV from EC desc= on +{} claims
                'target_descs': data.get('target_descs', {}),
            })
    elif data.get('concepts') and isinstance(data['concepts'], list):
        # Concepts list format: {"concepts": [{name, description, relationships}, ...]}
        # Used by observe_from_identity_pov and batch concept submissions
        for concept_data in data['concepts']:
            name = normalize_concept_name(concept_data.get('name', ''))
            if not name:
                continue

            # Convert relationships - handle both formats:
            # Format A: {"relationship": "type", "related": ["target"]}
            # Format B: {"type": "rel_type", "target": "target_name"}
            rels_dict = {}
            for rel in concept_data.get('relationships', []):
                if 'relationship' in rel and 'related' in rel:
                    # Format A (standard CartON)
                    rel_type = rel['relationship']
                    related = rel['related']
                    if rel_type and related:
                        rels_dict.setdefault(rel_type, []).extend(
                            related if isinstance(related, list) else [related]
                        )
                elif 'type' in rel and 'target' in rel:
                    # Format B (used by some remote sessions)
                    rel_type = rel['type']
                    target = rel['target']
                    if rel_type and target:
                        rels_dict.setdefault(rel_type, []).append(target)

            concepts.append({
                'name': name,
                'description': concept_data.get('description', ''),
                'relationships': rels_dict,
                'desc_update_mode': concept_data.get('desc_update_mode', 'append'),
                'source': concept_data.get('source', data.get('source', 'agent')),
            })

        if concepts:
            print(f"[Parse] Parsed {len(concepts)} concepts from concepts-list format in {queue_file.name}", file=sys.stderr)
    else:
        # Observation - N+1 concepts
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        observation_name = f"{timestamp}_Observation"

        # Collect all part concepts — scan ALL keys, skip known non-tag keys
        all_parts = []
        _NON_TAG_KEYS = {'confidence', 'hide_youknow', 'desc_update_mode', 'raw_concept', 'fixed', 'error_message', 'error_traceback'}
        for tag in data:
            if tag in _NON_TAG_KEYS:
                continue
            tag_concepts = data.get(tag, [])
            if not isinstance(tag_concepts, list):
                continue
            for concept_data in tag_concepts:
                if not isinstance(concept_data, dict):
                    continue
                name = normalize_concept_name(concept_data.get('name', ''))
                if not name:
                    continue

                # Convert relationships list to dict
                rels_dict = {}
                for rel in concept_data.get('relationships', []):
                    rel_type = rel.get('relationship', '')
                    related = rel.get('related', [])
                    if rel_type and related:
                        rels_dict[rel_type] = related

                # Add tag and observation link
                rels_dict['has_tag'] = [tag]
                rels_dict['part_of'] = rels_dict.get('part_of', []) + [observation_name]

                all_parts.append({
                    'name': name,
                    'description': concept_data.get('description', ''),
                    'relationships': rels_dict,
                    'desc_update_mode': concept_data.get('desc_update_mode', 'append'),
                    'source': data.get('source', 'agent'),
                })

        # Create observation wrapper
        if all_parts:
            part_names = [p['name'] for p in all_parts]
            concepts.append({
                'name': observation_name,
                'description': f"Observation at {timestamp} with {len(all_parts)} parts: {', '.join(part_names[:5])}{'...' if len(part_names) > 5 else ''}",
                'relationships': {
                    'is_a': ['Observation'],
                    'has_parts': part_names
                },
                'source': data.get('source', 'agent'),
            })
            concepts.extend(all_parts)

    return concepts


def process_queue_file(queue_file: Path, shared_connection=None) -> bool:
    """
    Process a single observation queue file.

    Args:
        queue_file: Path to JSON queue file
        shared_connection: Shared Neo4j connection to reuse

    Returns:
        True if processed successfully, False otherwise
    """
    try:
        print(f"[Worker] Processing {queue_file.name}...", file=sys.stderr)

        # Read observation data
        with open(queue_file, 'r') as f:
            observation_data = json.load(f)

        # Dispatch based on job type
        if observation_data.get('timeline_merge'):
            # Timeline merge: transfer CREATED_DURING from Unnamed → real Conversation, delete Unnamed
            unnamed = observation_data['unnamed_concept']
            real = observation_data['real_concept']
            graph = shared_connection or _create_shared_neo4j()
            if graph:
                try:
                    # Transfer all CREATED_DURING relationships
                    merge_query = """
                    MATCH (c:Wiki)-[old:CREATED_DURING]->(unnamed:Wiki {n: $unnamed})
                    MATCH (real:Wiki {n: $real})
                    MERGE (c)-[:CREATED_DURING]->(real)
                    DELETE old
                    SET c.timeline_linked = true
                    RETURN count(c) as transferred
                    """
                    result = graph.execute_query(merge_query, {'unnamed': unnamed, 'real': real})
                    count = result[0]['transferred'] if result else 0

                    # Delete the Unnamed concept
                    graph.execute_query("MATCH (n:Wiki {n: $name}) DETACH DELETE n", {'name': unnamed})
                    print(f"[Worker] Timeline merge: {unnamed} → {real} ({count} relationships transferred)", file=sys.stderr)
                    log_system_event(graph, "timeline_merge", f"Merged {unnamed} → {real}, {count} relationships transferred", "observation_daemon")
                except Exception as e:
                    print(f"[Worker] Timeline merge error: {e}", file=sys.stderr)

            queue_file.unlink(missing_ok=True)
            return True

        elif observation_data.get('raw_concept'):
            # Raw concept - use daemon's own batch_create_concepts_neo4j (NOT add_concept_tool_func which re-queues!)
            # Convert relationships from list format to dict format
            rel_list = observation_data.get('relationships', [])
            rel_dict = {}
            for r in rel_list:
                rel_type = r.get('relationship', '')
                related = r.get('related', [])
                if rel_type:
                    rel_dict[rel_type] = related

            concept_data = [{
                'name': observation_data['concept_name'],
                'description': observation_data.get('description', ''),
                'relationships': rel_dict,
                'timestamp': observation_data.get('timestamp')  # Pass through original timestamp
            }]
            batch_result = batch_create_concepts_neo4j(concept_data, shared_connection)

            # Create REQUIRES_EVOLUTION relationship if SOUP (incomplete chain)
            if observation_data.get('is_soup') and shared_connection:
                soup_reason = observation_data.get('soup_reason', 'Chain incomplete')
                soup_query = """
                MATCH (c:Wiki {n: $name})
                MERGE (re:Wiki {n: "Requires_Evolution", c: "requires_evolution"})
                MERGE (c)-[r:REQUIRES_EVOLUTION]->(re)
                SET r.reason = $reason, r.ts = datetime()
                """
                shared_connection.execute_query(soup_query, {
                    'name': observation_data['concept_name'],
                    'reason': soup_reason
                })
                print(f"[Worker] SOUP: {observation_data['concept_name']} -> REQUIRES_EVOLUTION", file=sys.stderr)

            result = f"Created concept: {batch_result}"

            # MEMORY TIER COMPILATION TRIGGER
            # Fires when:
            # 1. Concept IS_A Hypercluster or Ultramap (HC created/updated)
            # 2. Concept PART_OF a GIINT_Project_ or Hypercluster_ (member added to HC)
            is_a_targets = [t.lower() for t in rel_dict.get('is_a', [])]
            part_of_targets = rel_dict.get('part_of', [])

            is_hc_or_ultramap = 'hypercluster' in is_a_targets or 'ultramap' in is_a_targets
            # Fire on ANY concept in the GIINT hierarchy — not just direct PART_OF project
            # Components are PART_OF Features, Deliverables PART_OF Components, Tasks PART_OF Deliverables
            # All need to trigger recompile since MEMORY.md shows the full expanded hierarchy
            concept_name = rel_dict.get('concept_name', '') or queue_data.get('concept_name', '')
            is_giint_concept = concept_name.startswith('Giint_') or concept_name.startswith('GIINT_')
            is_hc_member = is_giint_concept or any(
                t.startswith('Giint_') or t.startswith('GIINT_')
                or t.startswith('Hypercluster_')
                for t in part_of_targets
            )

            if is_hc_or_ultramap or is_hc_member:
                try:
                    # Debounce: only recompile if >60s since last compile
                    import time
                    # CONNECTS_TO: /tmp/memory_compile_last.txt (read/write) — debounce for memory compilation
                    debounce_file = Path("/tmp/memory_compile_last.txt")
                    now = time.time()
                    should_compile = True
                    if debounce_file.exists():
                        last_compile = float(debounce_file.read_text().strip())
                        if now - last_compile < 60:
                            should_compile = False
                    if should_compile:
                        from carton_mcp.substrate_projector import compile_memory_tier
                        compile_result = compile_memory_tier(0, shared_connection=shared_connection)
                        compile_memory_tier(1, shared_connection=shared_connection)
                        compile_memory_tier(2, shared_connection=shared_connection)
                        debounce_file.write_text(str(now))
                        print(f"[Worker] Memory recompiled (all tiers): {compile_result}", file=sys.stderr)
                    else:
                        print(f"[Worker] Memory compile debounced (< 60s)", file=sys.stderr)
                except Exception as compile_err:
                    print(f"[Worker] Memory compilation failed (non-blocking): {compile_err}", file=sys.stderr)

        else:
            # Observation batch - call observation worker
            result = _add_observation_worker(observation_data, shared_connection=shared_connection)

        print(f"[Worker] {result}", file=sys.stderr)

        # Move processed file to processed directory
        processed_dir = queue_file.parent / 'processed'
        processed_dir.mkdir(exist_ok=True)

        processed_file = processed_dir / queue_file.name
        queue_file.rename(processed_file)

        print(f"[Worker] Moved to processed: {processed_file.name}", file=sys.stderr)

        return True

    except Exception as e:
        print(f"[Worker] Error processing {queue_file.name}: {e}", file=sys.stderr)
        traceback.print_exc()

        # Add "fixed": false marker to JSON before moving to failed
        try:
            observation_data['fixed'] = False
            observation_data['error_message'] = str(e)
            observation_data['error_traceback'] = traceback.format_exc()

            with open(queue_file, 'w') as f:
                json.dump(observation_data, f, indent=2)
        except Exception as marker_error:
            print(f"[Worker] Could not add fixed marker: {marker_error}", file=sys.stderr)

        # Move failed file to failed directory
        failed_dir = queue_file.parent / 'failed'
        failed_dir.mkdir(exist_ok=True)

        failed_file = failed_dir / queue_file.name
        queue_file.rename(failed_file)

        print(f"[Worker] Moved to failed: {failed_file.name}", file=sys.stderr)

        return False


def git_commit_all_changes():
    """
    Commit all filesystem changes after processing batch.
    ONE commit for all observations processed.
    """
    try:
        import subprocess

        heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        wiki_path = Path(heaven_data_dir) / 'wiki'

        if not wiki_path.exists():
            return

        # Check if there are uncommitted changes
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=wiki_path,
            capture_output=True,
            text=True
        )

        if not result.stdout.strip():
            return  # No changes

        # Add all changes
        subprocess.run(['git', 'add', '.'], cwd=wiki_path, check=True)

        # Commit with batch message
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(
            ['git', 'commit', '-m', f'CartON batch update {timestamp}'],
            cwd=wiki_path,
            capture_output=True,
            text=True
        )

        print(f"[Worker] Git commit complete", file=sys.stderr)

    except Exception as e:
        print(f"[Worker] Git commit error: {e}", file=sys.stderr)


def sync_rag_incremental(changed_files: list[str] | None = None):
    """
    Sync concepts to ChromaRAG. If changed_files provided, ingest ONLY those.
    Otherwise falls back to mtime-based incremental scan.
    """
    try:
        heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        chroma_dir = Path(heaven_data_dir) / 'chroma_db'
        wiki_dir = Path(heaven_data_dir) / 'wiki' / 'concepts'

        if not wiki_dir.exists():
            return

        from carton_mcp.smart_chroma_rag import SmartChromaRAG, route_concept_to_collection

        def _get_rag(collection_name):
            if collection_name not in _rag_cache:
                _rag_cache[collection_name] = SmartChromaRAG(
                    persist_dir=str(chroma_dir),
                    collection_name=collection_name,
                )
            return _rag_cache[collection_name]

        if changed_files:
            # Fast path: route each file to its correct collection
            print(f"[Worker] RAG targeted sync: {len(changed_files)} files", file=sys.stderr)
            added = 0
            # Group files by collection
            by_collection = {}
            for fpath in changed_files:
                # Extract concept name from path: .../ConceptName/ConceptName_itself.md
                fname = os.path.basename(fpath)
                concept_name = fname.replace("_itself.md", "") if "_itself.md" in fname else ""
                coll = route_concept_to_collection(concept_name) if concept_name else "domain_knowledge"
                by_collection.setdefault(coll, []).append(fpath)
            for coll, paths in by_collection.items():
                rag = _get_rag(coll)
                for fpath in paths:
                    try:
                        result = rag.ingest_path(doc_path=fpath, upsert=True)
                        if result.get("status") == "success":
                            added += result.get("files_added", 0) + result.get("files_updated", 0)
                    except Exception as e:
                        print(f"[Worker] RAG ingest failed for {fpath} -> {coll}: {e}", file=sys.stderr)
            print(f"[Worker] RAG targeted sync done: {added} ingested across {len(by_collection)} collections", file=sys.stderr)
        else:
            # Fallback: mtime-based incremental scan into domain_knowledge
            print("[Worker] RAG incremental sync (mtime-based)...", file=sys.stderr)
            rag = _get_rag("domain_knowledge")
            result = rag.ingest_path(
                doc_path=str(wiki_dir),
                glob="**/*_itself.md",
                upsert=True
            )
            if result.get("status") == "success":
                print(
                    f"[Worker] RAG sync complete: "
                    f"+{result.get('files_added', 0)} "
                    f"~{result.get('files_updated', 0)} "
                    f"={result.get('files_skipped', 0)} "
                    f"({result.get('total_chunks', 0)} chunks)",
                    file=sys.stderr
                )
            else:
                print(f"[Worker] RAG sync failed: {result.get('message', 'Unknown error')}", file=sys.stderr)

    except Exception as e:
        print(f"[Worker] RAG sync error: {e}", file=sys.stderr)
        traceback.print_exc()


def git_push_if_needed():
    """
    Push git changes if there are unpushed commits.
    Only pushes once after queue is empty.
    """
    try:
        import subprocess

        github_pat = os.getenv('GITHUB_PAT')
        repo_url = os.getenv('REPO_URL')
        branch = os.getenv('BRANCH', 'main')
        heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        wiki_path = Path(heaven_data_dir) / 'wiki'

        if not wiki_path.exists():
            return

        # Check if there are unpushed commits
        result = subprocess.run(
            ['git', 'rev-list', f'origin/{branch}..{branch}', '--count'],
            cwd=wiki_path,
            capture_output=True,
            text=True
        )

        unpushed_count = int(result.stdout.strip()) if result.returncode == 0 else 0

        if unpushed_count == 0:
            return

        print(f"[Worker] Pushing {unpushed_count} unpushed commits...", file=sys.stderr)

        # Push
        auth_url = repo_url.replace('https://', f'https://{github_pat}@')
        result = subprocess.run(
            ['git', 'push', auth_url, branch],
            cwd=wiki_path,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            print(f"[Worker] Git push successful ({unpushed_count} commits)", file=sys.stderr)
        else:
            print(f"[Worker] Git push failed: {result.stderr}", file=sys.stderr)

    except Exception as e:
        print(f"[Worker] Git push error: {e}", file=sys.stderr)


def _create_shared_neo4j():
    """Create persistent Neo4j connection for worker daemon lifetime."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        conn = KnowledgeGraphBuilder(
            uri=os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687'),
            user=os.getenv('NEO4J_USER', 'neo4j'),
            password=os.getenv('NEO4J_PASSWORD', 'password')
        )
        conn._ensure_connection()
        print("[Worker] Neo4j shared connection established", file=sys.stderr)
        return conn
    except Exception as e:
        print(f"[Worker] WARNING: Failed to create shared Neo4j connection: {e}", file=sys.stderr)
        return None


def _ensure_neo4j_alive(conn):
    """Health check Neo4j connection, reconnect if stale. Returns working connection or None."""
    if conn is None:
        return _create_shared_neo4j()
    try:
        conn.execute_query("RETURN 1")
        return conn
    except Exception as e:
        print(f"[Worker] Neo4j connection stale ({e}), reconnecting...", file=sys.stderr)
        try:
            conn.close()
        except Exception:
            pass
        return _create_shared_neo4j()


_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "to", "for", "with", "that",
    "this", "it", "as", "at", "by", "from", "on", "are", "is", "was", "were",
    "be", "been", "has", "have", "had", "not", "but", "so", "if", "we", "you",
    "he", "she", "they", "do", "did", "will", "can", "all", "its", "their",
    "which", "who", "when", "where", "what", "how", "any", "into", "about",
    "also", "than", "then", "these", "those", "each", "both", "more", "such",
    "some", "other", "after", "before", "via", "per", "within", "without",
    "our", "my", "your", "his", "her", "us", "me", "no", "up", "out", "s",
})

def compute_description_score(description: str, concept_cache: list) -> int:
    """Return % of meaningful words in description that exist in CartON (0-100).

    Builds a flat token set from concept_cache (e.g. 'Giint_Project_Foo' yields
    tokens {'giint', 'project', 'foo', 'giint_project_foo'}).  Each meaningful
    word in the description is checked against this set.  Stop words are excluded
    from both numerator and denominator.
    """
    import re
    if not description or not concept_cache:
        return 0

    # Build flat token set from all concept names
    concept_tokens: set = set()
    for name in concept_cache:
        lower = name.lower()
        concept_tokens.add(lower)
        for part in lower.split("_"):
            if part:
                concept_tokens.add(part)

    # Tokenize description
    raw_words = re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", description)
    meaningful = [w.lower() for w in raw_words if w.lower() not in _STOP_WORDS and len(w) > 1]

    if not meaningful:
        return 0

    matched = sum(1 for w in meaningful if w in concept_tokens)
    return round(matched / len(meaningful) * 100)


CHAT_SOURCES = {"agent", "dragonbones_hook", "session_start"}
SYSTEM_SOURCES = {"observation_daemon", "precompact", "hierarchical_summarizer", "linker", "substrate_projector"}
ODYSSEY_SOURCES = {"narrative_organ", "odyssey_organ"}

# CONNECTS_TO: /tmp/heaven_data/active_conversation.json (read/write) — tracks active conversation for timeline linking
ACTIVE_CONV_MARKER = Path("/tmp/heaven_data/active_conversation.json")


def log_system_event(neo4j_conn, event_type: str, description: str, source: str):
    """Log a system event directly to Neo4j (bypasses queue to avoid recursion).

    Creates a System_Event_{datetime} concept on the System_Timeline.
    """
    if not neo4j_conn:
        return
    try:
        from datetime import datetime
        ts = datetime.now().strftime("%Y_%m_%dT%H_%M_%S")
        event_name = f"System_Event_{ts}_{event_type}"
        day_name = f"Day_{datetime.now().strftime('%Y_%m_%d')}"

        query = """
        MERGE (timeline:Wiki {n: "System_Timeline"})
        ON CREATE SET timeline.d = "Timeline of all background system events (daemon, linker, summarizer, projector)",
                      timeline.t = datetime(), timeline.source = "system"
        MERGE (day:Wiki {n: $day})
        ON CREATE SET day.d = "Day container", day.t = datetime()
        MERGE (timeline)-[:HAS_PART]->(day)
        CREATE (e:Wiki {n: $name, d: $desc, t: datetime(), source: $source, linked: true, timeline_linked: true})
        CREATE (e)-[:IS_A]->(:Wiki {n: "System_Event"})
        MERGE (e)-[:PART_OF]->(day)
        """
        neo4j_conn.execute_query(query, {
            'name': event_name,
            'desc': description,
            'source': source,
            'day': day_name,
        })
    except Exception as e:
        print(f"[SystemEvent] Error logging {event_type}: {e}", file=sys.stderr)


def link_concepts_to_timeline(neo4j_conn):
    """Link concepts to their conversation on the timeline via CREATED_DURING.

    Reads active_conversation.json to find the current conversation concept.
    For concepts with chat sources and no CREATED_DURING, creates the relationship.
    """
    if not ACTIVE_CONV_MARKER.exists():
        return 0

    try:
        marker = json.loads(ACTIVE_CONV_MARKER.read_text())
        # Prefer real_concept (set by precompact after merge) over unnamed placeholder
        conv_name = marker.get("real_concept") or marker.get("concept_name")
        if not conv_name:
            return 0
    except Exception:
        return 0

    # Find concepts with chat sources that have no CREATED_DURING relationship
    query = """
    MATCH (c:Wiki)
    WHERE c.source IN $chat_sources
      AND c.timeline_linked IS NULL
      AND NOT (c)-[:CREATED_DURING]->(:Wiki)
      AND NOT c.n STARTS WITH 'Unnamed_Conversation'
    RETURN c.n as name
    LIMIT 200
    """
    try:
        result = neo4j_conn.execute_query(query, {'chat_sources': list(CHAT_SOURCES)})
        if not result:
            return 0

        # Create CREATED_DURING relationships in batch
        link_query = """
        UNWIND $names AS concept_name
        MATCH (c:Wiki {n: concept_name})
        MERGE (conv:Wiki {n: $conv_name})
        MERGE (c)-[:CREATED_DURING]->(conv)
        SET c.timeline_linked = true
        """
        names = [r['name'] if isinstance(r, dict) else r['name'] for r in result]
        neo4j_conn.execute_query(link_query, {'names': names, 'conv_name': conv_name})

        if names:
            print(f"[Linker] Timeline: linked {len(names)} concepts to {conv_name}", file=sys.stderr)
        return len(names)
    except Exception as e:
        print(f"[Linker] Timeline linking error: {e}", file=sys.stderr)
        return 0


ODYSSEY_CONCEPT_TYPES = {"Episode", "Journey", "Epic", "Odyssey", "Executive_Summary",
                         "Iteration_Summary", "Phase", "Subphase", "Framework_Report"}


def link_concepts_to_odyssey_timeline(neo4j_conn):
    """Link narrative/BML concepts to the Odyssey_Timeline.

    Detects concepts that IS_A any of the odyssey concept types and creates
    PART_OF → Odyssey_Timeline if not already linked.
    """
    if not neo4j_conn:
        return 0

    try:
        query = """
        MATCH (c:Wiki)-[:IS_A]->(t:Wiki)
        WHERE t.n IN $odyssey_types
          AND c.odyssey_linked IS NULL
          AND NOT (c)-[:PART_OF]->(:Wiki {n: "Odyssey_Timeline"})
        RETURN c.n as name
        LIMIT 100
        """
        result = neo4j_conn.execute_query(query, {'odyssey_types': list(ODYSSEY_CONCEPT_TYPES)})
        if not result:
            return 0

        names = [r['name'] if isinstance(r, dict) else r['name'] for r in result]

        link_query = """
        MERGE (timeline:Wiki {n: "Odyssey_Timeline"})
        ON CREATE SET timeline.d = "Timeline of BML cycles, narrative levels (Episode → Journey → Epic → Odyssey), and ML organ outputs",
                      timeline.t = datetime(), timeline.source = "system"
        WITH timeline
        UNWIND $names AS concept_name
        MATCH (c:Wiki {n: concept_name})
        MERGE (c)-[:PART_OF]->(timeline)
        SET c.odyssey_linked = true
        """
        neo4j_conn.execute_query(link_query, {'names': names})

        if names:
            print(f"[Linker] Odyssey: linked {len(names)} concepts to Odyssey_Timeline", file=sys.stderr)
        return len(names)
    except Exception as e:
        print(f"[Linker] Odyssey timeline linking error: {e}", file=sys.stderr)
        return 0


def linker_thread(stop_event: threading.Event):
    """
    Background thread that auto-links concept descriptions.

    Runs continuously, picking up concepts where linked=false and processing them.
    Uses Aho-Corasick for O(n) matching.
    Also links concepts to their conversation on the timeline via CREATED_DURING.
    """
    print("[Linker] Background auto-linker thread starting...", file=sys.stderr)
    
    # Create own Neo4j connection for this thread
    linker_neo4j = _create_shared_neo4j()
    if not linker_neo4j:
        print("[Linker] ERROR: Cannot start without Neo4j connection", file=sys.stderr)
        return
    
    heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    base_path = str(Path(heaven_data_dir) / 'wiki')
    
    linked_total = 0
    cache_refresh_interval = 300  # Refresh cache every 5 mins
    last_cache_refresh = 0
    concept_cache = []
    
    while not stop_event.is_set():
        try:
            # Refresh concept cache periodically
            now = time.time()
            if now - last_cache_refresh > cache_refresh_interval or not concept_cache:
                try:
                    from carton_mcp.carton_utils import CartOnUtils
                    utils = CartOnUtils(shared_connection=linker_neo4j)
                    concept_cache = utils.get_all_concept_names()
                    print(f"[Linker] Cache refreshed: {len(concept_cache)} concepts", file=sys.stderr)
                    last_cache_refresh = now
                except Exception as e:
                    print(f"[Linker] Cache refresh error: {e}", file=sys.stderr)
            
            # Query for unlinked concepts (batch of 100) — newest first so recent adds get scored fast
            query = """
            MATCH (c:Wiki)
            WHERE c.linked = false OR c.linked IS NULL
            RETURN c.n as name, c.d as description
            ORDER BY c.t DESC
            LIMIT 100
            """
            
            result = linker_neo4j.execute_query(query)

            # extract records from result (may be tuple or list)
            records = result[0] if isinstance(result, tuple) else result
            if not records or len(records) == 0:
                # No unlinked concepts - sleep longer
                stop_event.wait(30)
                continue
            
            batch_linked = 0
            for record in records:
                if stop_event.is_set():
                    break
                    
                name = record.get('name', '') if isinstance(record, dict) else record['name']
                desc = record.get('description', '') if isinstance(record, dict) else record['description']
                
                if name and desc and concept_cache:
                    try:
                        linked_desc = auto_link_description(desc, base_path, name, concept_cache=concept_cache)
                        score = compute_description_score(desc, concept_cache)

                        # Update concept with linked description and mark as linked
                        if linked_desc != desc:
                            update_query = """
                            MATCH (c:Wiki {n: $name})
                            SET c.d = $description, c.linked = true, c.score = $score
                            """
                            linker_neo4j.execute_query(update_query, {'name': name, 'description': linked_desc, 'score': score})
                            batch_linked += 1
                        else:
                            # No description changes, just mark as linked + store score
                            update_query = """
                            MATCH (c:Wiki {n: $name})
                            SET c.linked = true, c.score = $score
                            """
                            linker_neo4j.execute_query(update_query, {'name': name, 'score': score})
                    except Exception as e:
                        # Mark as linked anyway to avoid infinite retry
                        try:
                            update_query = """
                            MATCH (c:Wiki {n: $name})
                            SET c.linked = true
                            """
                            linker_neo4j.execute_query(update_query, {'name': name})
                        except:
                            pass
                else:
                    # No description, just mark as linked
                    try:
                        update_query = """
                        MATCH (c:Wiki {n: $name})
                        SET c.linked = true
                        """
                        linker_neo4j.execute_query(update_query, {'name': name})
                    except:
                        pass
                
                # Brief pause between individual concepts
                time.sleep(0.01)
            
            linked_total += batch_linked
            if batch_linked > 0:
                print(f"[Linker] Linked {batch_linked} in batch (total: {linked_total})", file=sys.stderr)

            # Timeline linking — connect concepts to active conversation
            timeline_count = link_concepts_to_timeline(linker_neo4j)
            # Odyssey timeline linking — connect narrative/BML concepts
            odyssey_count = link_concepts_to_odyssey_timeline(linker_neo4j)
            if batch_linked > 0 or timeline_count > 0 or odyssey_count > 0:
                log_system_event(linker_neo4j, "linker_batch", f"Auto-linked {batch_linked} descriptions, {timeline_count} chat timeline, {odyssey_count} odyssey timeline", "linker")

            # Brief pause between batches
            stop_event.wait(1)
            
        except Exception as e:
            print(f"[Linker] Error: {e}", file=sys.stderr)
            traceback.print_exc()
            stop_event.wait(10)
    
    print(f"[Linker] Thread shutting down. Total linked: {linked_total}", file=sys.stderr)


def worker_daemon():
    """
    Main daemon loop.

    Continuously watches queue directory and processes files.
    When queue is empty, pushes git changes.
    """
    import fcntl

    # PID FILE LOCK - prevents duplicate workers from spawning
    # This prevents race conditions during MCP restart that cause:
    # - Multiple workers competing for queue files
    # - Concurrent Neo4j writes → deadlock
    # - Neo4j CPU spike (200% = 2 workers)
    # - Docker resource exhaustion
    pid_file = Path('/tmp/carton_worker.pid')

    try:
        pid_fd = open(pid_file, 'w')
        fcntl.flock(pid_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        pid_fd.write(str(os.getpid()))
        pid_fd.flush()
        print(f"[Worker] Acquired PID lock (PID {os.getpid()})", file=sys.stderr)
    except BlockingIOError:
        print(f"[Worker] Another worker already running (PID file locked) - exiting gracefully", file=sys.stderr)
        sys.exit(0)  # Exit gracefully - no error
    except Exception as e:
        print(f"[Worker] ERROR: Failed to acquire PID lock: {e}", file=sys.stderr)
        sys.exit(1)

    print("[Worker] CartON Observation Queue Worker starting...", file=sys.stderr)

    # Start ONE shared ChromaDB HTTP server for the entire container.
    # All other processes (MCP, flight-predictor, skill-manager, etc.) connect
    # via chromadb.HttpClient(host="localhost", port=8101) — no HNSW loads elsewhere.
    import subprocess as _subprocess
    _heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    _chroma_dir = Path(_heaven_data_dir) / 'chroma_db'
    _chroma_dir.mkdir(parents=True, exist_ok=True)
    _subprocess.Popen(
        ["python3", "-m", "chromadb.cli.cli", "run",
         "--path", str(_chroma_dir),
         "--host", "localhost",
         "--port", "8101"],
        stdout=open("/tmp/chroma_server.log", "w"),
        stderr=_subprocess.STDOUT,
    )
    import time as _time; _time.sleep(2)  # wait for server ready
    print("[Worker] ChromaDB HTTP server started on port 8101", file=sys.stderr)

    # Verify environment variables
    required_env = ['NEO4J_URI', 'NEO4J_USER', 'NEO4J_PASSWORD']
    optional_env = ['GITHUB_PAT', 'REPO_URL']
    missing_required = [var for var in required_env if not os.getenv(var)]
    missing_optional = [var for var in optional_env if not os.getenv(var)]

    if missing_required:
        print(f"[Worker] ERROR: Missing required environment variables: {', '.join(missing_required)}", file=sys.stderr)
        sys.exit(1)

    if missing_optional:
        print(f"[Worker] WARNING: Missing optional environment variables: {', '.join(missing_optional)} (GitHub push disabled)", file=sys.stderr)

    queue_dir = get_observation_queue_dir()
    print(f"[Worker] Watching queue directory: {queue_dir}", file=sys.stderr)

    # Create shared Neo4j connection for entire daemon lifetime
    shared_neo4j = _create_shared_neo4j()

    # Start background linker thread
    linker_stop_event = threading.Event()
    linker = threading.Thread(target=linker_thread, args=(linker_stop_event,), daemon=True)
    linker.start()
    print("[Worker] Background linker thread started", file=sys.stderr)

    processed_count = 0
    failed_count = 0
    last_push_processed_count = 0

    while True:
        try:
            # Get all JSON files in queue directory
            queue_files = sorted(queue_dir.glob('*.json'))

            if queue_files:
                # Health check Neo4j before each batch — reconnect if stale
                shared_neo4j = _ensure_neo4j_alive(shared_neo4j)

                # TRUE UNWIND: Parse batch of files into flat concept list
                batch_files = queue_files[:UNWIND_BATCH_SIZE]
                print(f"[Worker] UNWIND batch: {len(batch_files)} files (queue has {len(queue_files)} total)", file=sys.stderr)

                # Phase 1: Parse all files into flat concept array
                all_concepts = []
                parsed_files = []  # Track which files parsed successfully
                failed_files = []  # Track parse failures

                for queue_file in batch_files:
                    concepts = parse_queue_file_to_concepts(queue_file)
                    if concepts:
                        all_concepts.extend(concepts)
                        parsed_files.append(queue_file)
                    else:
                        failed_files.append(queue_file)

                print(f"[Worker] Parsed {len(all_concepts)} concepts from {len(parsed_files)} files", file=sys.stderr)

                # NOTE: Auto-linking is handled by background thread (linker_thread)
                # Main loop just inserts fast, linker picks up unlinked nodes asynchronously

                # Phase 2: UNWIND batch create in Neo4j (single batch operation)
                neo4j_succeeded = False
                if all_concepts and shared_neo4j:
                    result = batch_create_concepts_neo4j(all_concepts, shared_neo4j)
                    print(f"[Worker] UNWIND result: {result['concepts_created']} concepts, {result['relationships_created']} rels", file=sys.stderr)

                    if result['errors']:
                        print(f"[Worker] UNWIND errors: {result['errors'][:3]}", file=sys.stderr)

                    # Success = concepts were created AND no fatal errors
                    neo4j_succeeded = result['concepts_created'] > 0

                    # Create REQUIRES_EVOLUTION for SOUP concepts (incomplete — not projected)
                    for c in all_concepts:
                        if c.get('is_soup') and shared_neo4j:
                            soup_reason = c.get('soup_reason', 'Chain incomplete')
                            try:
                                shared_neo4j.execute_query(
                                    """MATCH (n:Wiki {n: $name})
                                    MERGE (re:Wiki {n: "Requires_Evolution", c: "requires_evolution"})
                                    MERGE (n)-[r:REQUIRES_EVOLUTION]->(re)
                                    SET r.reason = $reason, r.ts = datetime()""",
                                    {'name': c['name'], 'reason': soup_reason}
                                )
                                print(f"[Worker] SOUP: {c['name']} -> REQUIRES_EVOLUTION", file=sys.stderr)
                            except Exception as e:
                                print(f"[Worker] SOUP REQUIRES_EVOLUTION failed for {c['name']}: {e}", file=sys.stderr)

                    # Write target_descs — cached descriptions from EC desc= on +{} claims
                    for c in all_concepts:
                        td = c.get('target_descs', {})
                        if td and shared_neo4j:
                            for target_name, target_desc in td.items():
                                try:
                                    shared_neo4j.execute_query(
                                        """MERGE (n:Wiki {n: $name})
                                        SET n.d = CASE
                                            WHEN n.d IS NULL OR n.d = '' OR n.d STARTS WITH 'AUTO CREATED'
                                            THEN $desc ELSE n.d END,
                                            n.t = datetime()""",
                                        {'name': target_name, 'desc': target_desc}
                                    )
                                except Exception as e:
                                    print(f"[Worker] target_desc write failed for {target_name}: {e}", file=sys.stderr)

                elif not shared_neo4j:
                    print("[Worker] ERROR: No Neo4j connection — files stay in queue", file=sys.stderr)

                # Phase 2.5: Enforce GIINT ontology completeness (auto-create superstructure)
                if all_concepts and neo4j_succeeded:
                    try:
                        from carton_mcp.ontology_graphs import ensure_ontology_completeness
                        GIINT_TYPES = {"giint_project", "giint_feature", "giint_component",
                                       "giint_deliverable", "giint_task"}
                        for c in all_concepts:
                            # Skip concepts auto-created by ensure_ontology_completeness
                            # (they already have their hierarchy — re-running would double-scaffold)
                            if c.get("skip_ontology_healing", False):
                                continue
                            rels = c.get("relationships", {})
                            if isinstance(rels, list):
                                rels = {r.get("relationship", ""): r.get("related", []) for r in rels if isinstance(r, dict)}
                            c_isa = [t.lower() for t in rels.get("is_a", [])]
                            if not GIINT_TYPES.intersection(c_isa):
                                continue
                            auto_created = ensure_ontology_completeness(
                                concept_name=c.get("name", ""),
                                is_a_list=rels.get("is_a", []),
                                relationship_dict=rels,
                                shared_connection=shared_neo4j,
                            )
                            if auto_created:
                                print(f"[Worker] GIINT superstructure: {c.get('name','')} → {auto_created}", file=sys.stderr)
                    except Exception as ont_err:
                        print(f"[Worker] GIINT ontology enforcement error: {ont_err}", file=sys.stderr)

                # Phase 2.5a: Auto-crystallize valid concepts (SOMA decided).
                # Doc 28 fix: route projection on is_system_type + is_a, not the
                # legacy YOUKNOW is_code + gen_target. SOMA does not emit gen_target;
                # is_system_type=True means CODE + all d-chains pass (fully admitted),
                # so projection d-chains are free to fire. The concept's is_a tells
                # us which projector to dispatch.
                #
                # is_code (structure valid, d-chains pending) still removes
                # REQUIRES_EVOLUTION — the SOUP→CODE promotion is independent of
                # whether projection fires this round.
                if all_concepts and neo4j_succeeded:
                    for c in all_concepts:
                        if (c.get("is_code") or c.get("is_system_type")) and shared_neo4j:
                            try:
                                shared_neo4j.execute_query(
                                    """MATCH (s:Wiki {n: $name})-[r:REQUIRES_EVOLUTION]->(re)
                                    DELETE r""",
                                    {'name': c['name']}
                                )
                                print(f"[Worker] SOUP→CODE: {c['name']} REQUIRES_EVOLUTION removed", file=sys.stderr)
                            except Exception as e:
                                print(f"[Worker] REQUIRES_EVOLUTION removal failed for {c['name']}: {e}", file=sys.stderr)
                    try:
                        from carton_mcp.substrate_projector import project_to_skill, SkillSubstrate, project_to_rule, RuleSubstrate
                        for c in all_concepts:
                            # Projection only fires for SYSTEM_TYPE — CODE concepts
                            # still have unmet d-chains and are not fully admitted.
                            if not c.get("is_system_type"):
                                continue
                            # Extract is_a from the concept's relationships. The
                            # dict-of-lists shape is the parsed form; the list shape
                            # appears when relationships pass through untouched.
                            rels = c.get("relationships", {})
                            if isinstance(rels, list):
                                rels = {r.get("relationship", ""): r.get("related", []) for r in rels if isinstance(r, dict)}
                            c_isa = [t.lower().replace(" ", "_") for t in rels.get("is_a", [])]
                            try:
                                if "skill" in c_isa:
                                    result = project_to_skill(SkillSubstrate(), c.get("name", ""), shared_connection=shared_neo4j)
                                    print(f"[Worker] 🔮 SYSTEM_TYPE → Skill crystallized: {c.get('name','')} → {result}", file=sys.stderr)
                                    log_system_event(shared_connection, "skill_crystallized", f"SYSTEM_TYPE → Skill: {c.get('name','')} → {result}", "substrate_projector")
                                elif "claude_code_rule" in c_isa:
                                    rule_result = project_to_rule(RuleSubstrate(), c.get("name", ""), shared_connection=shared_neo4j)
                                    print(f"[Worker] 🛡️ SYSTEM_TYPE → Rule projected: {c.get('name','')} → {rule_result}", file=sys.stderr)
                                    log_system_event(shared_connection, "rule_projected", f"SYSTEM_TYPE → Rule: {c.get('name','')} → {rule_result}", "substrate_projector")
                                # Future is_a routes: flight_config, persona, mcp_server, etc.
                                else:
                                    print(f"[Worker] SYSTEM_TYPE is_a={c_isa} not yet handled for {c.get('name','')}", file=sys.stderr)
                            except Exception as e:
                                print(f"[Worker] SYSTEM_TYPE crystallization failed for {c.get('name','')}: {e}", file=sys.stderr)
                    except ImportError:
                        print("[Worker] substrate_projector not available, skipping crystallization", file=sys.stderr)

                # Phase 2.5b REMOVED 2026-05-12: legacy rule bypass path that
                # gated on substring(is_a, "claude_code_rule") and bypassed YOUKNOW
                # d-chain validation. Rules now flow through Phase 2.5a via the
                # gen_target="rule_file" branch, gated by is_code AND gen_target
                # like skills. validate_system_type._infer_from_context fills the
                # required Claude_Code_Rule fields (has_scope, has_name, has_content)
                # before structural validation passes.

                # Phase 2.5c: PBML auto-lane-move — detect phase-completion concepts → GIINT update_task_status
                if all_concepts and neo4j_succeeded:
                    try:
                        from llm_intelligence.projects import update_task_status as giint_update_task
                        # done_signal → is_done → IN_REVIEW → measure lane
                        # inclusion_map → is_measured → DONE → learn lane
                        # bml_learning → is_measured → DONE → learn lane, THEN direct TK move to archive
                        PBML_TRIGGERS = {
                            "done_signal": {"is_done": True, "is_blocked": False, "blocked_description": None, "is_ready": False},
                            "inclusion_map": {"is_done": True, "is_blocked": False, "blocked_description": None, "is_ready": False, "is_measured": True},
                            "bml_learning": {"is_done": True, "is_blocked": False, "blocked_description": None, "is_ready": False, "is_measured": True},
                            "odyssey_learning_decision": {"is_done": True, "is_blocked": False, "blocked_description": None, "is_ready": False, "is_measured": True},
                        }
                        # Triggers that also need direct TK archive move (GIINT has no archive status)
                        # Odyssey_Learning_Decision is the AUTHORITATIVE trigger — GNOSYS bml_learning no longer archives
                        ARCHIVE_TRIGGERS = {"odyssey_learning_decision"}
                        for c in all_concepts:
                            rels = c.get("relationships", {})
                            if isinstance(rels, list):
                                rels = {r.get("relationship", ""): r.get("related", []) for r in rels if isinstance(r, dict)}
                            c_isa = [t.lower().replace(" ", "_") for t in rels.get("is_a", [])]
                            # Match against triggers
                            matched_trigger = None
                            for trigger_type in PBML_TRIGGERS:
                                if trigger_type in c_isa:
                                    matched_trigger = trigger_type
                                    break
                            if not matched_trigger:
                                continue
                            # Extract GIINT path from part_of relationships
                            part_of_targets = rels.get("part_of", [])
                            giint_task = None
                            giint_deliverable = None
                            for target in part_of_targets:
                                t_lower = target.lower()
                                if t_lower.startswith("giint_task_"):
                                    giint_task = target
                                elif t_lower.startswith("giint_deliverable_"):
                                    giint_deliverable = target
                            if not giint_task and not giint_deliverable:
                                print(f"[Worker] PBML trigger {matched_trigger} for {c.get('name','')} — no GIINT task/deliverable in part_of, skipping", file=sys.stderr)
                                continue
                            # Resolve GIINT path from Neo4j (task → deliverable → component → feature → project)
                            try:
                                target_name = giint_task or giint_deliverable
                                path_query = (
                                    "MATCH (t:Wiki {n: $target})-[:PART_OF]->(d:Wiki)-[:PART_OF]->(comp:Wiki)"
                                    "-[:PART_OF]->(f:Wiki)-[:PART_OF]->(p:Wiki) "
                                    "WHERE p.n STARTS WITH 'Giint_Project_' "
                                    "RETURN p.n AS project, f.n AS feature, comp.n AS component, d.n AS deliverable, t.n AS task"
                                )
                                with shared_neo4j.driver.session() as neo_session:
                                    result = neo_session.run(path_query, target=target_name).single()
                                if not result:
                                    print(f"[Worker] PBML trigger {matched_trigger} — could not resolve GIINT path for {target_name}", file=sys.stderr)
                                    continue
                                # Strip GIINT prefixes for update_task_status params
                                project_id = result["project"].replace("Giint_Project_", "")
                                feature_name = result["feature"].replace("Giint_Feature_", "")
                                component_name = result["component"].replace("Giint_Component_", "")
                                deliverable_name = result["deliverable"].replace("Giint_Deliverable_", "")
                                task_id = result["task"].replace("Giint_Task_", "") if result["task"] else None
                                if not task_id:
                                    print(f"[Worker] PBML trigger {matched_trigger} — no task_id resolved, skipping", file=sys.stderr)
                                    continue
                                params = PBML_TRIGGERS[matched_trigger].copy()
                                update_result = giint_update_task(
                                    project_id=project_id,
                                    feature_name=feature_name,
                                    component_name=component_name,
                                    deliverable_name=deliverable_name,
                                    task_id=task_id,
                                    key_insight=c.get("description", "")[:200],
                                    **params
                                )
                                print(f"[Worker] 🔄 PBML auto-move: {matched_trigger} → {task_id} in {project_id}: {update_result.get('treekanban_sync', {})}", file=sys.stderr)
                                # Odyssey ML trigger: done_signal fires the full ML pipeline
                                if matched_trigger == "done_signal":
                                    try:
                                        from odyssey.utils import dispatch_chain as odyssey_dispatch_chain
                                        concept_name = c.get("name", "")
                                        # Fire in background thread to not block daemon
                                        _odyssey_thread = threading.Thread(
                                            target=odyssey_dispatch_chain,
                                            args=(concept_name,),
                                            daemon=True,
                                            name=f"odyssey_{concept_name[:40]}",
                                        )
                                        _odyssey_thread.start()
                                        print(f"[Worker] 🔬 Odyssey ML chain triggered for {concept_name}", file=sys.stderr)
                                    except ImportError:
                                        print("[Worker] Odyssey not installed, skipping ML verification", file=sys.stderr)
                                    except Exception as ody_err:
                                        print(f"[Worker] Odyssey trigger failed: {ody_err}", file=sys.stderr)
                                # Archive triggers: after GIINT moves to learn, directly move TK card to archive
                                if matched_trigger in ARCHIVE_TRIGGERS:
                                    try:
                                        from heaven_bml_sqlite.heaven_bml_sqlite_client import HeavenBMLSQLiteClient
                                        tk_board = os.getenv("GIINT_TREEKANBAN_BOARD")
                                        if tk_board:
                                            tk_client = HeavenBMLSQLiteClient()
                                            tk_cards = tk_client.get_all_cards(tk_board)
                                            import json as _json
                                            for tk_card in tk_cards:
                                                tk_tags = tk_card.get("tags", [])
                                                if isinstance(tk_tags, str):
                                                    tk_tags = _json.loads(tk_tags) if tk_tags.startswith("[") else [tk_tags]
                                                if task_id in tk_tags and tk_card.get("status") == "learn":
                                                    archive_result = tk_client._make_request("PUT", f"/api/sqlite/cards/{tk_card['id']}", {"board": tk_board, "status": "archive"})
                                                    if archive_result:
                                                        print(f"[Worker] 🏁 PBML archive: card #{tk_card['id']} moved to archive", file=sys.stderr)
                                                    break
                                    except Exception as arch_err:
                                        print(f"[Worker] PBML archive move failed: {arch_err}", file=sys.stderr)
                            except Exception as path_err:
                                print(f"[Worker] PBML path resolution failed for {c.get('name','')}: {path_err}", file=sys.stderr)
                    except ImportError:
                        print("[Worker] GIINT not available, skipping PBML auto-lane-move", file=sys.stderr)
                    except Exception as pbml_err:
                        print(f"[Worker] PBML auto-lane-move error: {pbml_err}", file=sys.stderr)

                # Phase 2.5d: Resolve _Unnamed stubs when real concept fills the slot
                # TEMPORARY — moves to SOMA Prolog when YOUKNOW integrates into SOMA.
                if all_concepts and neo4j_succeeded and shared_neo4j:
                    for c in all_concepts:
                        rels = c.get("relationships", {})
                        if isinstance(rels, list):
                            rels = {r.get("relationship", ""): r.get("related", []) for r in rels if isinstance(r, dict)}
                        part_of_targets = rels.get("part_of", [])
                        is_a_types = [t for t in rels.get("is_a", [])]
                        concept_name = c.get("name", "")
                        if not part_of_targets or not is_a_types:
                            continue
                        for parent_name in part_of_targets:
                            for is_a_type in is_a_types:
                                unnamed_name = f"{is_a_type}_Unnamed"
                                try:
                                    result = shared_neo4j.execute_query(
                                        "MATCH (p:Wiki {n: $parent})-[r]->(stub:Wiki {n: $stub}) "
                                        "RETURN type(r) AS rel_type LIMIT 1",
                                        {'parent': parent_name, 'stub': unnamed_name}
                                    )
                                    if not result:
                                        continue
                                    rel_type = result[0]['rel_type']
                                    shared_neo4j.execute_query(
                                        f"MATCH (p:Wiki {{n: $parent}})-[old:{rel_type}]->(stub:Wiki {{n: $stub}}) "
                                        f"DELETE old WITH p MATCH (real:Wiki {{n: $real}}) "
                                        f"CREATE (p)-[:{rel_type}]->(real)",
                                        {'parent': parent_name, 'stub': unnamed_name, 'real': concept_name}
                                    )
                                    shared_neo4j.execute_query(
                                        "MATCH (stub:Wiki {n: $stub}), (real:Wiki {n: $real}) "
                                        "SET stub.d = 'RESOLVED: evolved into ' + $real "
                                        "MERGE (stub)-[:EVOLVED_TO]->(real) "
                                        "MERGE (real)-[:EVOLVED_FROM]->(stub)",
                                        {'stub': unnamed_name, 'real': concept_name}
                                    )
                                    print(f"[Worker] stub resolved: {unnamed_name} -> {concept_name} (parent: {parent_name}, rel: {rel_type})", file=sys.stderr)
                                except Exception as stub_err:
                                    print(f"[Worker] Stub resolution failed for {concept_name}: {stub_err}", file=sys.stderr)

                # Phase 2.5b: Create wiki files for ChromaDB indexing (only if Neo4j succeeded)
                if all_concepts and neo4j_succeeded:
                    wiki_result = create_wiki_files_for_concepts(all_concepts)
                    if wiki_result['errors']:
                        print(f"[Worker] Wiki file errors: {wiki_result['errors'][:3]}", file=sys.stderr)
                    # Targeted RAG sync: only ingest files we just wrote (no 188k scan)
                    hdd = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
                    written_paths = []
                    for c in all_concepts:
                        n = c.get('name', '').replace(' ', '_')
                        p = os.path.join(hdd, 'wiki', 'concepts', n, f'{n}_itself.md')
                        if os.path.exists(p):
                            written_paths.append(p)
                    if written_paths:
                        sync_rag_incremental(changed_files=written_paths)

                # Phase 3: Move files based on Neo4j result
                if neo4j_succeeded:
                    processed_dir = queue_dir / 'processed'
                    processed_dir.mkdir(exist_ok=True)
                    for queue_file in parsed_files:
                        try:
                            queue_file.rename(processed_dir / queue_file.name)
                            processed_count += 1
                        except Exception as e:
                            print(f"[Worker] Failed to move {queue_file.name}: {e}", file=sys.stderr)
                else:
                    # Neo4j failed — move parsed files to failed/ so they don't vanish
                    if parsed_files:
                        print(f"[Worker] Neo4j write failed — moving {len(parsed_files)} files to failed/", file=sys.stderr)
                        failed_files.extend(parsed_files)

                # Move failed parse files
                if failed_files:
                    failed_dir = queue_dir / 'failed'
                    failed_dir.mkdir(exist_ok=True)
                    for queue_file in failed_files:
                        try:
                            queue_file.rename(failed_dir / queue_file.name)
                            failed_count += 1
                        except Exception:
                            pass

                print(f"[Worker] Batch done. Total: {processed_count} processed, {failed_count} failed", file=sys.stderr)

            else:
                # Queue is empty - commit and push if we processed anything new
                # NOTE: Git operations DISABLED in daemon - use nightly cron instead
                # NOTE: RAG sync disabled - it blocks for 30+ min scanning 188k files
                # Set CARTON_GIT_AUTO=true to enable (NOT RECOMMENDED - causes high IO load)
                if os.getenv('CARTON_GIT_AUTO') == 'true' and processed_count > last_push_processed_count:
                    git_commit_all_changes()
                    # sync_rag_incremental()  # DISABLED: blocking, use carton_management(sync_rag=True) manually
                    git_push_if_needed()
                    last_push_processed_count = processed_count

            # Sleep before checking again
            time.sleep(1)

        except KeyboardInterrupt:
            print("[Worker] Shutting down...", file=sys.stderr)
            linker_stop_event.set()  # Signal linker to stop
            break

        except Exception as e:
            print(f"[Worker] Daemon error: {e}", file=sys.stderr)
            traceback.print_exc()
            time.sleep(5)  # Wait before retrying

    # Wait for linker thread to finish
    linker_stop_event.set()
    linker.join(timeout=5)
    print(f"[Worker] Shutdown complete. Final stats: {processed_count} processed, {failed_count} failed", file=sys.stderr)


if __name__ == "__main__":
    worker_daemon()
