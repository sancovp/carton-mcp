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


def _carton_undo_dir_for_today() -> Path:
    """Per-day undo-log dir: $HEAVEN_DATA_DIR/carton_undo/<YYYY-MM-DD>/.

    Also performs the DAILY CLEAR: any carton_undo/<date>/ dir whose date is not
    today is removed (the undo log is intentionally ephemeral — undo is a same-day
    safety net, not durable history). Best-effort; never raises.
    """
    from datetime import datetime
    import shutil
    heaven_data = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    base = Path(heaven_data) / 'carton_undo'
    today = datetime.now().strftime('%Y-%m-%d')
    # Daily rotation: drop any date-dir that is not today's.
    try:
        if base.exists():
            for d in base.iterdir():
                if d.is_dir() and d.name != today:
                    shutil.rmtree(d, ignore_errors=True)
    except Exception as e:
        print(f"[KV-EDIT] undo daily-clear skipped: {e}", file=sys.stderr)
    today_dir = base / today
    today_dir.mkdir(parents=True, exist_ok=True)
    return today_dir


def _apply_carton_kv_edits(concept_rows: list, graph) -> None:
    """CartON KV 'edit' mode (Python pre-step — Cypher can't do EditHelper str_replace).

    For each row with update_mode == 'edit': fetch the CURRENT n.d, write the PRE-edit
    n.d to a per-node daily undo log, then surgically str-replace old_str_for_edit_case
    -> the row's description (new_str) via EditHelper (exactly-once enforced; raises
    ToolError on 0 or >1 match). On success the row is rewritten as a 'replace' whose
    description is the edited n.d (so the UNWIND CASE writes the whole edited n.d, and the
    fence-preservation guard — which only acts on replace rows — finds every fence still
    present byte-identical and carries nothing forward). On ANY failure (no current n.d,
    0/>1 match, EditHelper error) the row is set to update_mode='skip' so n.d is left
    UNCHANGED, and the error is recorded on the row for surfacing. Wrapped so a single bad
    edit can never break the whole batch write.

    Mutates concept_rows in place. Reuses heaven_base EditHelper via a temp-file round-trip
    (EditHelper operates on a FILE).
    """
    import tempfile
    try:
        from heaven_base.tools.network_edit_tool import EditHelper
        from heaven_base.baseheaventool import ToolError
    except Exception as e:
        # EditHelper unavailable — fail every edit row safely (n.d unchanged) rather than guess.
        for row in concept_rows:
            if row.get('update_mode') == 'edit':
                row['update_mode'] = 'skip'
                row['kv_edit_error'] = f"EditHelper unavailable: {e}"
                print(f"[KV-EDIT] EditHelper import failed, skipping edit for {row['name']}: {e}", file=sys.stderr)
        return

    for row in concept_rows:
        if row.get('update_mode') != 'edit':
            continue
        name = row['name']
        old_str = row.get('old_str_for_edit_case')
        new_str = row.get('description', '')
        if old_str is None:
            row['update_mode'] = 'skip'
            row['kv_edit_error'] = "edit mode requires old_str_for_edit_case (was None)"
            print(f"[KV-EDIT] {name}: no old_str_for_edit_case — n.d unchanged", file=sys.stderr)
            continue
        # Fetch the CURRENT n.d (the file content EditHelper will edit).
        try:
            cur = graph.execute_query("MATCH (c:Wiki {n: $n}) RETURN c.d AS d LIMIT 1", {"n": name})
            current_nd = cur[0]['d'] if (cur and cur[0].get('d')) else None
        except Exception as e:
            row['update_mode'] = 'skip'
            row['kv_edit_error'] = f"could not read current n.d: {e}"
            print(f"[KV-EDIT] {name}: read n.d failed — n.d unchanged: {e}", file=sys.stderr)
            continue
        if not current_nd:
            row['update_mode'] = 'skip'
            row['kv_edit_error'] = "node has no existing n.d to edit"
            print(f"[KV-EDIT] {name}: no existing n.d — n.d unchanged", file=sys.stderr)
            continue
        # UNDO LOG: write the PRE-edit n.d before touching anything.
        try:
            undo_dir = _carton_undo_dir_for_today()
            undo_file = undo_dir / f"{name}.json"
            from datetime import datetime
            undo_file.write_text(json.dumps({
                "node": name,
                "pre_edit_d": current_nd,
                "old_str": old_str,
                "new_str": new_str,
                "ts": datetime.now().isoformat(),
            }, indent=2))
        except Exception as e:
            # Undo log is a safety net; if it can't be written, REFUSE the edit (don't edit
            # without the ability to undo).
            row['update_mode'] = 'skip'
            row['kv_edit_error'] = f"undo-log write failed, edit refused: {e}"
            print(f"[KV-EDIT] {name}: undo-log write failed — edit refused: {e}", file=sys.stderr)
            continue
        # Surgical str-replace via EditHelper on a temp file (exactly-once enforced).
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as tf:
                tf.write(current_nd)
                tmp_path = Path(tf.name)
            EditHelper().str_replace(tmp_path, old_str, new_str)
            edited_nd = tmp_path.read_text()
            row['description'] = edited_nd
            row['update_mode'] = 'replace'  # write the whole edited n.d via the UNWIND CASE
            print(f"[KV-EDIT] {name}: applied surgical edit (old->new), n.d rewritten", file=sys.stderr)
        except ToolError as e:
            # 0 or >1 match (or other EditHelper refusal) — n.d UNCHANGED.
            row['update_mode'] = 'skip'
            row['kv_edit_error'] = f"str_replace refused (0 or >1 match): {e}"
            print(f"[KV-EDIT] {name}: str_replace refused — n.d unchanged: {e}", file=sys.stderr)
        except Exception as e:
            row['update_mode'] = 'skip'
            row['kv_edit_error'] = f"str_replace failed: {e}"
            print(f"[KV-EDIT] {name}: str_replace failed — n.d unchanged: {e}", file=sys.stderr)
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except Exception:
                    pass


def _compute_region(c: dict) -> str | None:
    """Map a concept's SOMA verdict into its CartON REGION enum (the VERTICAL proof axis).

    CartON is the regioned KG (Isaac 2026-06-16): every node carries a mutable `region` property
    whose value is one of soup | code | system_type | ont (the SOMA-verdict gradient) — plus `cb`
    (the one non-SOMA region, out of scope this sprint). It is a SCRATCH-lane property (work-state
    reflected from the verdict, NOT ontological meaning — meaning stays in the is_a/part_of graph),
    queryable via query_by_properties.

    TREESHELL IS NOT A REGION (Isaac 2026-06-19 — the unify-treeshell decision). `treeshell` is the
    CODE-OBJECT LENS — one of four lenses (AGENT/DOMAIN/PLACE/CODE-OBJECT) on the HORIZONTAL axis,
    ORTHOGONAL to this vertical proof-region. A TreeShell node carries `is_a TreeShell_Node` (the
    lens marker, queryable as a graph edge) AND gets a real vertical region here from its SOMA
    verdict (node_sync now routes through add_concept_tool_func -> SOMA -> code). So the old
    `is_a TreeShell_Node -> region='treeshell'` early-return is REMOVED: it conflated the two axes
    (it shadowed the verdict, so a treeshell node could never be code/system_type). Now they are
    independent — region = the vertical verdict; the lens = the is_a edge.

    Returns the region, or None when this write carries no verdict/structural signal (so the daemon
    must NOT clobber an already-climbed region — see the coalesce in the UNWIND). `ont` is not set
    here yet (SOMA does not surface is_ont to carton); the enum reserves it for that refinement.
    """
    rels = c.get('relationships') or {}
    is_a = [str(t).lower().replace(' ', '_') for t in (rels.get('is_a') or [])]
    if any(t.startswith('cb_') or t.startswith('crystal_ball') for t in is_a):
        return 'cb'
    if c.get('is_system_type'):
        return 'system_type'
    if c.get('is_code'):
        return 'code'
    if c.get('is_soup'):
        return 'soup'
    return None  # no verdict signal on this write -> don't clobber the existing region


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
            'update_mode': c.get('desc_update_mode', 'append'),  # append/prepend/replace/edit
            'old_str_for_edit_case': c.get('old_str_for_edit_case'),  # CartON KV 'edit' mode: str-replace target within n.d
            'removed_fences': c.get('removed_fences', []),  # CartON KV fence-preservation guard
            'source': c.get('source', 'agent'),  # Timeline source — who/what created this concept
            'region': _compute_region(c),  # CartON region enum (soup/code/system_type/ont/cb/treeshell); None = no signal, don't clobber
            # NOTE: the SOUP-vs-not "layer" is ALSO mirrored by the REQUIRES_EVOLUTION relationship
            # (legacy); `region` is the queryable partition property (the regioned-KG reification).
        })

    # CartON KV 'edit' mode (surgical str-replace within n.d). Runs FIRST: it converts each
    # successful 'edit' row into a 'replace' row whose description is the edited n.d, so the
    # downstream dedup (append-only), fence-preservation guard (replace-only), and UNWIND CASE
    # all see a normal replace. A failed edit becomes a 'skip' (n.d unchanged). Wrapped inside
    # the helper so it can never break the batch write.
    try:
        if graph and any(r.get('update_mode') == 'edit' for r in concept_rows):
            _apply_carton_kv_edits(concept_rows, graph)
    except Exception as kv_edit_err:
        print(f"[KV-EDIT] edit pre-step skipped (batch continues): {kv_edit_err}", file=sys.stderr)

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

    # CartON KV FENCE-PRESERVATION GUARD (Python pre-step — Cypher can't extract fences).
    # A REPLACE re-derivation of n.d must NOT silently delete a CartonObj fence. For each
    # replace row, fetch the CURRENT n.d and carry forward (verbatim) any fence present in the
    # old n.d but absent by name from the incoming description — EXCEPT names explicitly listed
    # in removed_fences (the remove_fence op). append/prepend already keep old n.d, so only
    # replace is at risk. Wrapped so it can never break the write.
    try:
        from carton_mcp.carton_kv import carry_forward_fences
        for row in concept_rows:
            if row.get('update_mode') != 'replace':
                continue
            cur = graph.execute_query(
                "MATCH (c:Wiki {n: $n}) RETURN c.d AS d LIMIT 1", {"n": row['name']})
            old_nd = cur[0]['d'] if (cur and cur[0].get('d')) else ''
            if old_nd and 'CartonObj' in old_nd:
                row['description'] = carry_forward_fences(
                    old_nd, row['description'], row.get('removed_fences', []))
    except Exception as e:
        print(f"[UNWIND] fence-preservation guard skipped: {e}", file=sys.stderr)

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
            WHEN c.update_mode = 'replace'
                THEN c.description
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
        SET n.region = coalesce(c.region, n.region, 'soup')
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

    # TIMELINE-STUB TYPING (Isaac 2026-06-20: "user message etc on timeline have no is_a ...
    # those should be fixed they are obvious"). A timeline node referenced ONLY as a relationship
    # TARGET (e.g. summarizes/surfaced_from/part_of) — never written as a SOURCE carrying its own
    # is_a — is born as a bare AUTO-CREATED stub by the MERGE above with NO is_a edge. Yet its TYPE
    # is unambiguous from its name prefix (User_Message_* IS_A User_Message, etc.). Type any
    # still-untyped timeline-prefixed node AMONG THIS BATCH'S rel targets, by prefix. Bounded to the
    # targets just touched (cheap, index-backed n-lookup), idempotent (MERGE), additive (never
    # touches n.d, never deletes). The HAS_INSTANCES inverse mirrors the writer's IS_A inverse_map
    # above. Order is load-bearing: 'Iteration_Summary_' is matched BEFORE 'Iteration_' (prefix
    # overlap) — first matching WHEN wins. The existing untyped nodes were repaired by a one-time
    # backfill (scripts/backfill_timeline_is_a.py); this is the SOURCE half that stops recurrence.
    try:
        batch_targets = list({r['target'] for rels in rels_by_type.values() for r in rels})
        if batch_targets:
            graph.execute_query("""
            UNWIND $targets AS name
            MATCH (n:Wiki {n: name}) WHERE NOT (n)-[:IS_A]->()
            WITH n, CASE
                WHEN n.n STARTS WITH 'Iteration_Summary_'       THEN 'Iteration_Summary'
                WHEN n.n STARTS WITH 'User_Message_'            THEN 'User_Message'
                WHEN n.n STARTS WITH 'Agent_Message_'           THEN 'Agent_Message'
                WHEN n.n STARTS WITH 'Tool_Call_'               THEN 'Tool_Call'
                WHEN n.n STARTS WITH 'Unnamed_Conversation_At_' THEN 'Conversation'
                WHEN n.n STARTS WITH 'Conversation_'            THEN 'Conversation'
                WHEN n.n STARTS WITH 'Iteration_'               THEN 'Iteration'
                ELSE null END AS typ
            WHERE typ IS NOT NULL
            MERGE (t:Wiki {n: typ})
            MERGE (n)-[:IS_A]->(t)
            MERGE (t)-[:HAS_INSTANCES]->(n)
            """, {'targets': batch_targets})
    except Exception as e:
        print(f"[UNWIND] timeline stub typing skipped: {e}", file=sys.stderr)

    # CartON KV: a concept whose description carries an is_schema=true CartonObj fence is auto-typed
    # IS_A Carton_Kv_Schema (browsable SOUP registry); schema=X refs get USED_BY_KV edges. Cheap
    # 'CartonObj' substring gate; wrapped so it can never break the write.
    try:
        from carton_mcp.carton_utils import register_kv_schemas
        for c in concepts_data:
            desc = c.get('description', '') or ''
            if 'CartonObj' in desc:
                register_kv_schemas(c.get('name', ''), desc, graph)
    except Exception as e:
        print(f"[UNWIND] KV schema registration skipped: {e}", file=sys.stderr)

    # NODE PROPERTIES (the 🏷 property channel — scratch lane, the-property-layer-doctrine).
    # Applied HERE, AFTER the node MERGE (lines above) created/updated every node, so the
    # node is GUARANTEED to exist (set_concept_properties MATCHes, never MERGEs) — this is
    # exactly what removes the old race that forced sm config into n.d as <sm_spec> JSON:
    # the daemon writes the node and sets its properties in the SAME drain, in order. Each
    # producer (add_concept_tool_func, dragonbones db_carton) carries `properties` in the
    # queue JSON; here we apply them via the canonical property surface (reserved-key refuse,
    # scalar/flat-list validation, best-effort SOMA trail for ontology-bearing nodes). Wrapped
    # so a property failure can NEVER break the concept/relationship write (the node already
    # landed). Properties are rare (sm gates / scratch state), so per-concept calls are fine.
    props_applied = 0
    try:
        from carton_mcp.carton_utils import set_concept_properties
        for c in concepts_data:
            props = c.get('properties') or {}
            if not props:
                continue
            cname = normalize_concept_name(c.get('name', ''))
            if not cname:
                continue
            res = set_concept_properties(cname, props, mode="merge", shared_connection=graph)
            if res.get('success'):
                props_applied += len(res.get('updated_keys') or [])
                if res.get('refused_keys'):
                    print(f"[PROPS] {cname}: refused reserved keys {res['refused_keys']}", file=sys.stderr)
            else:
                errors.append(f"set_properties({cname}) failed: {res.get('error')}")
                print(f"[PROPS] ERROR {cname}: {res.get('error')}", file=sys.stderr)
        if props_applied:
            print(f"[PROPS] Set {props_applied} node properties across the batch", file=sys.stderr)
    except Exception as e:
        print(f"[PROPS] property application skipped (batch continues): {e}", file=sys.stderr)

    # SOUP→CODE promotion is SOMA's job now: the SOMA verdict's is_code flag drives
    # the inline REQUIRES_EVOLUTION removal (Phase 2.5a). The old youknow-based
    # background re-validation (check_and_promote_soup_items) was DISABLED and is
    # removed — youknow (:8102) is dead; SOMA is the validator.
    promoted = 0

    return {
        'concepts_created': len(concept_rows),
        'relationships_created': total_rels,
        'errors': errors,
        'promoted': promoted,
        'properties_set': props_applied
    }


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
                'desc_update_mode': data.get('desc_update_mode', 'append'),  # append/prepend/replace/edit
                # CartON KV 'edit' mode: the old_str to surgically str-replace within the existing
                # n.d (the description above is the new_str). Applied by batch_create_concepts_neo4j.
                'old_str_for_edit_case': data.get('old_str_for_edit_case'),
                'removed_fences': data.get('removed_fences', []),  # CartON KV fence-preservation guard (MAIN worker-loop path; the raw_concept branch in process_queue_file already forwards it)
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
                # RELEASE-LAW projection effects (FIX-5 step 3): the release_effect
                # facts SOMA surfaced in the verdict, [{handler, arg}]. Phase 2.5a
                # imports + dispatches each AFTER the neo4j write (gated on is_system_type).
                'release_effects': data.get('release_effects', []),
                # AUTHORIZATION-TYPED fillable requests (the carton brain, Isaac 2026-06-28):
                # SOMA gaps whose fill authority is NOT observing_agent, parsed by add_concept_tool
                # via the SOMA SDK into [{authorization, concept, gap, expected_type, reason,
                # reply_contract, request_id}]. Phase 2.5d durably PARKS each (the passive/pull
                # leg of the request/resume protocol). Mirrors release_effects above — without
                # this line they are DROPPED here and never reach any dispatch.
                'fillable_requests': data.get('fillable_requests', []),
                # CARTON-BUNDLE-BACK composed triples (Isaac 2026-06-28): SOMA's backward-chain
                # compose DEDUCED these [{concept, prop, value}] and surfaced them in the composed=
                # verdict section; add_concept_tool parsed them. Phase 2.5e MERGEs each as a neo4j
                # edge AFTER the node write so carton's KG realizes SOMA's deductions. Mirrors
                # release_effects above — without this line they are DROPPED and never reach the KG.
                'composed_triples': data.get('composed_triples', []),
                # L3b PURE-MEREO SUGGESTIONS (Isaac 2026-06-28): unique admissible candidates SOMA
                # found for still-empty slots with no authorizing d-chain; [{concept, prop,
                # expected_type, candidate, reviewer_role}]. Phase 2.5f durably PARKS each for review
                # (mints a run-id for L3c). Mirrors composed_triples — without this line they are
                # DROPPED and no review item is ever created.
                'compose_suggestions': data.get('compose_suggestions', []),
                # NODE PROPERTIES (the 🏷 property channel). batch_create_concepts_neo4j
                # applies these via set_concept_properties AFTER the node MERGE (node
                # exists in the same drain → no race). Scalars/flat-lists only. {} when none.
                'properties': data.get('properties', {}),
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
                'desc_update_mode': observation_data.get('desc_update_mode', 'append'),  # forward replace/append/prepend to batch_create (default append = unchanged behavior)
                'removed_fences': observation_data.get('removed_fences', []),  # CartON KV: intentionally-deleted fences (fence-preservation guard must NOT carry these back)
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

        # Chroma via the daemon (urllib-only client, ZERO chroma import in this worker process —
        # the daemon owns chromadb/langchain/onnxruntime). The worker keeps the aho-corasick linker
        # automaton in memory but no longer loads the chroma neural stack.
        from carton_mcp.chroma_client import chroma_index as _daemon_index, chroma_route as _daemon_route

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
                coll = _daemon_route(concept_name) if concept_name else "domain_knowledge"
                by_collection.setdefault(coll, []).append(fpath)
            for coll, paths in by_collection.items():
                for fpath in paths:
                    try:
                        result = _daemon_index(coll, fpath, upsert=True)
                        if result.get("status") == "success":
                            added += result.get("files_added", 0) + result.get("files_updated", 0)
                    except Exception as e:
                        print(f"[Worker] RAG ingest failed for {fpath} -> {coll}: {e}", file=sys.stderr)
            print(f"[Worker] RAG targeted sync done: {added} ingested across {len(by_collection)} collections", file=sys.stderr)
        else:
            # Fallback: mtime-based incremental scan into domain_knowledge
            print("[Worker] RAG incremental sync (mtime-based)...", file=sys.stderr)
            result = _daemon_index("domain_knowledge", str(wiki_dir), upsert=True, glob="**/*_itself.md")
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


# CONNECTS_TO: /tmp/active_hypercluster.txt (read/write) — actuated shadow of the
# Seed_Ship.active_hypercluster graph property; also read by substrate_projector.compile_memory_tier.
_ACTIVE_HC_FILE = Path("/tmp/active_hypercluster.txt")


def _sync_active_hypercluster(shared_connection) -> bool:
    """FIRST CARTON AUTOMATION — graph property = control surface, file = actuated shadow.

    Pattern: property-condition -> action (abstraction-cypher lineage). This is the first
    instance of the graph-property-condition→action pattern (pseudo-SOMA triggers): a value
    on the graph is the single control surface, and the always-running daemon actuates the
    filesystem + recompiles memory to match it.

    Set via: set_properties('Seed_Ship', {'active_hypercluster': 'Hypercluster_X'}).

    Reads Seed_Ship.active_hypercluster. If it differs from /tmp/active_hypercluster.txt AND
    names a real typed Hypercluster, writes the file and recompiles MEMORY.md tier 0. NEVER
    points the file at a non-existent HC. Entirely exception-safe — the worker loop can NEVER
    die from this (any error logs and returns False).

    Returns True iff the file was updated (and a recompile fired); False otherwise.
    """
    try:
        if shared_connection is None:
            return False

        # Read the control-surface property (parameterless, cheap single-node query).
        prop_result = shared_connection.execute_query(
            "MATCH (s:Wiki {n:'Seed_Ship'}) RETURN s.active_hypercluster AS hc"
        )
        records = prop_result[0] if isinstance(prop_result, tuple) else prop_result
        prop_hc = None
        if records:
            rec = records[0]
            prop_hc = rec.get('hc') if isinstance(rec, dict) else rec['hc']
        if not prop_hc or not str(prop_hc).strip():
            return False  # property missing/empty — no action, file left alone
        prop_hc = str(prop_hc).strip()

        # Read current file content (missing file == "").
        try:
            file_hc = _ACTIVE_HC_FILE.read_text().strip() if _ACTIVE_HC_FILE.exists() else ""
        except Exception:
            file_hc = ""

        if prop_hc == file_hc:
            return False  # already in sync — idempotent no-op

        # VALIDATE the target exists and is typed as a Hypercluster before touching the file.
        valid_result = shared_connection.execute_query(
            "MATCH (h:Wiki {n:$hc})-[:IS_A]->(:Wiki {n:'Hypercluster'}) RETURN h.n AS n",
            {'hc': prop_hc}
        )
        valid_records = valid_result[0] if isinstance(valid_result, tuple) else valid_result
        if not valid_records:
            print(f"[CartonAutomation] WARNING: active_hypercluster property names a non-HC: "
                  f"{prop_hc} — file NOT updated", file=sys.stderr)
            return False

        # Valid + changed: actuate the file, then recompile tier 0.
        _ACTIVE_HC_FILE.write_text(prop_hc)
        print(f"[CartonAutomation] active HC -> {prop_hc} (property-driven)", file=sys.stderr)
        try:
            from carton_mcp.substrate_projector import compile_memory_tier
            compile_memory_tier(0, shared_connection=shared_connection)
        except Exception as compile_err:
            print(f"[CartonAutomation] tier-0 recompile failed (non-blocking): {compile_err}", file=sys.stderr)
        return True

    except Exception as e:
        print(f"[CartonAutomation] _sync_active_hypercluster error (non-fatal): {e}", file=sys.stderr)
        return False


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
SYSTEM_SOURCES = {"observation_daemon", "precompact", "hierarchical_summarizer", "linker", "substrate_projector", "webbing_agent"}
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

    # Also start the chroma DAEMON (:8190) — the SOLE importer of chromadb/langchain/onnxruntime in the
    # whole system. It owns the EMBEDDER + exposes embed/query/index/add_texts over HTTP. Every client
    # (carton MCP, flight-predictor, skill-manager, heaven, AND this worker's own sync_rag_incremental)
    # calls it via the urllib-only chroma_client, so NOTHING else imports the chroma neural stack. The
    # :8101 server above is just the vector STORE the daemon talks to.
    _chroma_daemon_port = os.getenv('CHROMA_DAEMON_PORT', '8190')
    _subprocess.Popen(
        ["python3", "-m", "carton_mcp.chroma_daemon", "--port", str(_chroma_daemon_port)],
        stdout=open("/tmp/chroma_daemon.log", "w"),
        stderr=_subprocess.STDOUT,
    )
    print(f"[Worker] chroma daemon (embedder) started on port {_chroma_daemon_port}", file=sys.stderr)

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
            # FIRST CARTON AUTOMATION (property-condition -> action): sync the active-HC
            # control surface (Seed_Ship.active_hypercluster graph property) to its actuated
            # file shadow once per loop iteration — cheap single-node query, runs even when the
            # queue is empty. Exception-safe internally; can NEVER kill this loop.
            _sync_active_hypercluster(shared_neo4j)

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
                                        # FRONTIER SIGNAL (Isaac 2026-06-19): a cell is still on the
                                        # metacompilation FRONTIER (an unfilled auto-stub) only when there
                                        # is NOTHING AFTER the auto-created string — i.e. it STARTS WITH the
                                        # 'AUTO CREATED' marker AND still ENDS WITH 'Not yet fully defined.'
                                        # (the marker's last sentence). Once a cell is FILLED (real content
                                        # appended after the marker), it no longer ends with that sentence,
                                        # so it is NOT frontier and must NOT be clobbered. The marker stays
                                        # as the birth-record (referenced-into-existence) — filled-ness is
                                        # the STRUCTURAL signal (content-after-marker), not the marker itself.
                                        """MERGE (n:Wiki {n: $name})
                                        SET n.d = CASE
                                            WHEN n.d IS NULL OR n.d = '' OR (n.d STARTS WITH 'AUTO CREATED' AND n.d ENDS WITH 'Not yet fully defined.')
                                            THEN $desc ELSE n.d END,
                                            n.t = datetime()""",
                                        {'name': target_name, 'desc': target_desc}
                                    )
                                except Exception as e:
                                    print(f"[Worker] target_desc write failed for {target_name}: {e}", file=sys.stderr)

                elif not shared_neo4j:
                    print("[Worker] ERROR: No Neo4j connection — files stay in queue", file=sys.stderr)

                # REFACTOR-PLAN [SOMA-UNIFICATION 2026-06-16] — THE SOLE LIVE CALLER of the carton
                #   ontology fabricator. journal Scalable_Publishing_Giint_Architecture_Soma_Unification_Removal (14:10).
                #   CHANGE: the ensure_ontology_completeness call below fabricates the project/feature/component
                #   _Unnamed mereology skeletons — that gap is now computed by SOMA's gnosys-vault GIINT
                #   presence d-chains (PROVEN LIVE, FIX-4), so this fabrication is REDUNDANT.
                #   ENACT (once verified): comment-out the ensure_ontology_completeness block; REPLACE with a
                #   DIRECT call to ontology_graphs._auto_create_task_hypercluster for giint_task concepts ONLY
                #   (Task-HC creation has NO SOMA replacement — the one piece that must stay). Keep Phase 2.5a
                #   (release_effect dispatch) + 2.5c (PBML) untouched. Then delete the skip_ontology_healing parse (L~409).
                # Phase 2.5: GIINT _Unnamed fabrication DISABLED 2026-06-16 (SOMA-unification).
                #   The old ensure_ontology_completeness call here fabricated project/feature/component
                #   _Unnamed mereology skeletons. That gap is now COMPUTED by SOMA's gnosys-vault GIINT
                #   presence d-chains (PROVEN LIVE, FIX-4) and surfaced as unmet_requirement in the verdict,
                #   not fabricated over → fabrication REMOVED (replace-before-remove satisfied).
                #   RE-HOMED here: Task-HC creation for giint_task (NO SOMA equivalent) via a direct
                #   _auto_create_task_hypercluster call. journal Soma_Unification_Removal.
                if all_concepts and neo4j_succeeded:
                    try:
                        from carton_mcp.ontology_graphs import _auto_create_task_hypercluster
                        for c in all_concepts:
                            if c.get("skip_ontology_healing", False):
                                continue
                            rels = c.get("relationships", {})
                            if isinstance(rels, list):
                                rels = {r.get("relationship", ""): r.get("related", []) for r in rels if isinstance(r, dict)}
                            c_isa = [t.lower() for t in rels.get("is_a", [])]
                            # giint_task Task-HC creation has NO SOMA equivalent → keep (re-homed direct call).
                            # _auto_create_task_hypercluster is idempotent (_concept_exists guard) + ignores rels.
                            if "giint_task" in c_isa:
                                hc = _auto_create_task_hypercluster(c.get("name", ""), rels, shared_neo4j)
                                if hc:
                                    print(f"[Worker] Task-HC: {c.get('name','')} → {hc}", file=sys.stderr)
                    except Exception as ont_err:
                        print(f"[Worker] Task-HC creation error: {ont_err}", file=sys.stderr)

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
                    # RELEASE-LAW dispatch (FIX-5 step 3) — SOMA surfaced
                    # release_effect(handler, arg) facts in the verdict for the
                    # projection d-chains (dchain_skill_project / dchain_rule_project);
                    # add_concept_tool parsed them into c["release_effects"]. SOMA does
                    # NOT run them (it is the inner reflection — it cannot act outward
                    # mid-process; it releases the verdict UP). WE — the outer Python
                    # layer that called /event — import + run each handler now, AFTER
                    # the neo4j write, so the projector can read the concept off our
                    # shared connection. This REPLACES the prior hardcoded is_a routing:
                    # the d-chain decides WHAT projects; the daemon just dispatches
                    # whatever handler each fact names (universal — no domain knowledge).
                    # GATED on is_system_type: a SOUP/CODE skill is still in d-chain
                    # scope so SOMA surfaces its release_effect, but an incomplete
                    # concept must NOT project.
                    import importlib as _importlib
                    _eff_seen = set()
                    for c in all_concepts:
                        if not c.get("is_system_type"):
                            continue
                        for eff in (c.get("release_effects") or []):
                            handler = (eff.get("handler") or "").strip()
                            # arg = the CartON neo4j node name (c.name). SOMA's
                            # release_effect arg is the SOMA-normalized (lowercase_
                            # underscore) form of THIS SAME concept — it does NOT match
                            # the Title_Case neo4j node the projector reads via
                            # get_concept_content. This queue file is for exactly one
                            # concept and its release_effects all pertain to it, so c.name
                            # is the correct, resolvable node name. (The eff.arg is kept in
                            # the verdict only as a human-readable trace of which concept.)
                            arg = c.get("name", "").strip()
                            if not handler or not arg or (handler, arg) in _eff_seen:
                                continue
                            _eff_seen.add((handler, arg))
                            try:
                                mod_path, fn_name = handler.split(":", 1)
                                fn = getattr(_importlib.import_module(mod_path), fn_name)
                                res = fn(arg, shared_connection=shared_neo4j)
                                print(f"[Worker] 🔮 release_effect {handler}({arg}) → {res}", file=sys.stderr)
                                # NOTE: the worker-loop neo4j handle is shared_neo4j (NOT
                                # shared_connection — the old is_a-routing code referenced an
                                # undefined `shared_connection` here, a latent NameError that
                                # never fired because that path apparently never ran live).
                                log_system_event(shared_neo4j, "release_effect_dispatched", f"{handler}({arg}) → {res}", "soma_release")
                            except Exception as e:
                                print(f"[Worker] release_effect dispatch failed {handler}({arg}): {e}", file=sys.stderr)

                # Phase 2.5d: SOMA authorization-typed request PARK (the carton brain, passive leg).
                # add_concept_tool parsed SOMA's soma_requests= block into c["fillable_requests"]
                # (typed by WHO is authorized to fill: human_* / system_deduction / …). Durably PARK
                # each so it survives restarts and waits for its filler — the durable suspension the
                # request/resume protocol needs (a human answers later as a NEW SOMA event → SOMA
                # re-derives → the parked chain advances; re-derivation IS the resume). The ACTIVE fill
                # (manufacture an LLM expert, POST the answer back, re-derive) runs through
                # soma_sdk.resolve() + default_fillers when a reachable SOMA_URL + an llm_call are
                # wired; until then this PARK leg alone runs and nothing is dropped. Logic lives in the
                # library (soma_fillers.park_fillable_requests); the daemon just dispatches + logs.
                if all_concepts and neo4j_succeeded:
                    try:
                        from carton_mcp.soma_fillers import park_fillable_requests
                        _parked = park_fillable_requests(all_concepts)
                        for _rid in _parked:
                            print(f"[Worker] 🧠 soma_request parked → {_rid}", file=sys.stderr)
                        if _parked and shared_neo4j:
                            log_system_event(shared_neo4j, "soma_requests_parked",
                                             f"{len(_parked)} parked", "soma_request")
                    except Exception as e:
                        print(f"[Worker] soma_request park error: {e}", file=sys.stderr)

                # Phase 2.5e: CARTON-BUNDLE-BACK — realize SOMA's DEDUCED composed triples into the KG.
                # add_concept_tool parsed SOMA's composed= verdict section into c["composed_triples"]
                # ([{concept, prop, value}]). SOMA's backward-chain compose (L3a) found these matches in
                # the store and DEDUCED graph additions the user never stated (e.g. SOMA inferred
                # spaghetti's cuisine is italian from its ingredients). SOMA is the INNER reflection: it
                # releases the deductions UP and never touches carton's KG. WE — the outer layer — MERGE
                # each as a directed :PROP edge here (AFTER the node write), or carton stays dumb (Isaac:
                # "that's literally SOMA's job"). The logic lives in the library
                # (soma_fillers.realize_composed_triples, unit-testable via an injected execute); the
                # daemon just dispatches + logs (mirrors Phase 2.5d / park_fillable_requests).
                if all_concepts and neo4j_succeeded and shared_neo4j:
                    try:
                        from carton_mcp.soma_fillers import realize_composed_triples
                        _realized = realize_composed_triples(all_concepts, shared_neo4j.execute_query)
                        for (_s, _r, _v) in _realized:
                            print(f"[Worker] 🧬 composed (SOMA-deduced) → ({_s})-[:{_r}]->({_v})", file=sys.stderr)
                        if _realized:
                            log_system_event(shared_neo4j, "soma_composed_realized",
                                             f"{len(_realized)} deduced triples realized into KG", "soma_compose")
                    except Exception as e:
                        print(f"[Worker] composed realize error: {e}", file=sys.stderr)

                # Phase 2.5f: L3b PURE-MEREO SUGGESTION PARK (the review queue, passive leg).
                # add_concept_tool parsed SOMA's compose_suggestions= block into c["compose_suggestions"]
                # (a unique admissible candidate for a still-empty slot with NO authorizing d-chain).
                # SOMA did NOT compose it (that is L3a); it SUGGESTS it. We durably PARK each for review
                # (mints a stable run-id for the L3c reviewer event). INERT — parking only, no graph
                # mutation. Logic in the library (soma_fillers.park_compose_suggestions); daemon
                # dispatches + logs (mirrors Phase 2.5d / 2.5e).
                if all_concepts and neo4j_succeeded:
                    try:
                        from carton_mcp.soma_fillers import park_compose_suggestions
                        _sg_parked = park_compose_suggestions(all_concepts)
                        for _rid in _sg_parked:
                            print(f"[Worker] 🔎 compose-suggestion parked for review → {_rid}", file=sys.stderr)
                        if _sg_parked and shared_neo4j:
                            log_system_event(shared_neo4j, "compose_suggestions_parked",
                                             f"{len(_sg_parked)} parked for review", "soma_suggestion")
                    except Exception as e:
                        print(f"[Worker] compose-suggestion park error: {e}", file=sys.stderr)

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
