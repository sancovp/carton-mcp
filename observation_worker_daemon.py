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
import re
import sys
import time
import json
import traceback
import threading
from pathlib import Path
from typing import Dict, Any

# Import worker function (absolute import for standalone script execution)
from carton_mcp.add_concept_tool import _add_observation_worker, get_observation_queue_dir, auto_link_description, normalize_concept_name, observation_validation_errors
from carton_mcp.carton_pathguard import check_write, CartonPathRefused
from carton_mcp.carton_deadletter import (
    PROCESSED, REQUEUE, backoff_delays, batch_disposition, batch_failure_reason, dead_letter,
    dead_letter_report, retry_attempts, run_with_retry)
# The pid-lock acquisition (issue #276 item 4). Absolute form deliberately, matching the
# imports above: the import-consistency guards in the test suites match on that module path.
from carton_mcp.carton_worker_control import WORKER_PID_FILE, acquire_pid_lock

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

        # Concept directory + _itself.md file (this is what ChromaDB indexes)
        concept_dir = wiki_concepts_dir / normalized_name
        itself_file = concept_dir / f"{normalized_name}_itself.md"

        # #206 wiki-lane containment, BEFORE the mkdir so a garbage name mints
        # nothing at all. A refusal is recorded per-concept and the drain
        # continues — the loop's existing per-concept error discipline.
        try:
            check_write(str(itself_file), "wiki")
        except CartonPathRefused as e:
            errors.append(f"Refused {normalized_name}: {e}")
            print(f"[WikiFiles] REFUSED {normalized_name}: {e}", file=sys.stderr)
            continue

        concept_dir.mkdir(parents=True, exist_ok=True)

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

    def _persist_outcome(node_name, err):
        """Durable edit outcome (issue 142): a failed edit used to be SILENT at every durable
        surface (the error lived only on the in-memory queue row). Persist failures as a node
        property — get_concept shows properties, so the default read surface now surfaces them —
        and CLEAR it on success so a stale error never outlives a later good edit. Best-effort:
        outcome-recording must never break the batch (this function's own discipline)."""
        try:
            if err:
                graph.execute_query(
                    "MATCH (c:Wiki {n: $n}) SET c.kv_edit_error = $e, c.kv_edit_error_at = datetime()",
                    {"n": node_name, "e": err})
            else:
                graph.execute_query(
                    "MATCH (c:Wiki {n: $n}) REMOVE c.kv_edit_error, c.kv_edit_error_at",
                    {"n": node_name})
        except Exception as pe:
            print(f"[KV-EDIT] {node_name}: outcome-persist failed (non-fatal): {pe}", file=sys.stderr)

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
            _persist_outcome(name, row['kv_edit_error'])
            continue
        # Fetch the CURRENT n.d (the file content EditHelper will edit).
        try:
            cur = graph.execute_query("MATCH (c:Wiki {n: $n}) RETURN c.d AS d LIMIT 1", {"n": name})
            current_nd = cur[0]['d'] if (cur and cur[0].get('d')) else None
        except Exception as e:
            row['update_mode'] = 'skip'
            row['kv_edit_error'] = f"could not read current n.d: {e}"
            print(f"[KV-EDIT] {name}: read n.d failed — n.d unchanged: {e}", file=sys.stderr)
            _persist_outcome(name, row['kv_edit_error'])
            continue
        if not current_nd:
            row['update_mode'] = 'skip'
            row['kv_edit_error'] = "node has no existing n.d to edit"
            print(f"[KV-EDIT] {name}: no existing n.d — n.d unchanged", file=sys.stderr)
            _persist_outcome(name, row['kv_edit_error'])
            continue
        # UNDO LOG: write the PRE-edit n.d before touching anything.
        try:
            undo_dir = _carton_undo_dir_for_today()
            from datetime import datetime
            # ATTEMPT-TIMESTAMPED (issue 142): one undo file PER ATTEMPT, never clobbered.
            # The old single {name}.json meant a FAILED attempt overwrote the successful
            # edit's undo from the same day — the safety net destroyed by the next miss.
            undo_file = undo_dir / f"{name}.{datetime.now().strftime('%H%M%S_%f')}.json"
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
            _persist_outcome(name, row['kv_edit_error'])
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
            _persist_outcome(name, None)  # success clears any stale kv_edit_error
        except ToolError as e:
            # 0 or >1 match (or other EditHelper refusal) — n.d UNCHANGED.
            row['update_mode'] = 'skip'
            row['kv_edit_error'] = f"str_replace refused (0 or >1 match): {e}"
            print(f"[KV-EDIT] {name}: str_replace refused — n.d unchanged: {e}", file=sys.stderr)
            _persist_outcome(name, row['kv_edit_error'])
        except Exception as e:
            row['update_mode'] = 'skip'
            row['kv_edit_error'] = f"str_replace failed: {e}"
            print(f"[KV-EDIT] {name}: str_replace failed — n.d unchanged: {e}", file=sys.stderr)
            _persist_outcome(name, row['kv_edit_error'])
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
                # `desc` is BACKTICKED because it is a RESERVED WORD on an embedded backend
                # (kuzu parses it as the DESC sort keyword and the whole query fails). Backticks
                # are valid identifier quoting in both dialects and the returned key is still
                # `desc`, so nothing downstream changes — measured 2026-08-12.
                "UNWIND $names AS name MATCH (n:Wiki {n: name}) WHERE n.d IS NOT NULL RETURN n.n AS name, n.d AS `desc`",
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
    nodes_written = False
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
                THEN n.d + $sep + c.description
            WHEN c.update_mode = 'prepend'
                THEN c.description + $sep + n.d
            ELSE c.description
        END
        SET n.t = CASE WHEN n.t IS NULL THEN (CASE WHEN c.timestamp IS NOT NULL THEN datetime(c.timestamp) ELSE datetime() END) ELSE n.t END
        SET n.last_modified = datetime()
        SET n.linked = false
        SET n.source = CASE WHEN n.source IS NULL THEN c.source ELSE n.source END
        SET n.region = coalesce(c.region, n.region, 'soup')
        """
        # ⛔ THE SEPARATOR IS A PARAMETER, NOT A CYPHER LITERAL, and that is load-bearing rather
        # than stylistic. It used to be the literal '\n\n---\n\n' inside the query text, which
        # relies on the ENGINE processing backslash escapes in a string literal. neo4j does;
        # kuzu 0.11.3 does NOT — it drops the backslashes, so the separator silently became
        # 'nn---nn' and EVERY appended description would have been quietly corrupted with no
        # error anywhere. Measured 2026-08-12. As a parameter the bytes are the driver's problem
        # on both engines, which is what makes one query string correct everywhere.
        graph.execute_query(create_query, {'concepts': concept_rows, 'sep': '\n\n---\n\n'})
        nodes_written = True
        print(f"[UNWIND] Created {len(concept_rows)} concept nodes", file=sys.stderr)
    except Exception as e:
        errors.append(f"Concept creation failed: {e}")
        print(f"[UNWIND] ERROR creating concepts: {e}", file=sys.stderr)
        traceback.print_exc()

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
                #
                # THE DOMAIN AXES ARE COLLECTIONS. Every concept carries has_domain (and its
                # finer siblings), so the inverse IS the domain's membership: a domain node
                # reached by CONTAINS_CONCEPTS returns everything tagged with it, and domains
                # already nest into HWSS by part_of, which makes the whole axis a recursive
                # many-to-many collection lattice with no extra structure to maintain.
                #
                # The inverse is CONTAINS_CONCEPTS and deliberately NOT has_part: activate_collection
                # recurses HAS_PART to depth 10, so making a domain a HAS_PART parent of its
                # thousands of members would import the graph on every activation. A distinct
                # edge gives the membership without the recursion, which is what the writer-side
                # map in add_concept_tool.py already does for the sibling domain relations.
                inverse_map = {
                    'PART_OF': 'HAS_PART',
                    'HAS_PART': 'PART_OF',
                    'IS_A': 'HAS_INSTANCES',
                    'INSTANTIATES': 'INSTANTIATED_BY',
                    'HAS_DOMAIN': 'CONTAINS_CONCEPTS',
                    'HAS_SUBDOMAIN': 'CONTAINS_CONCEPTS',
                    'HAS_SUBSUBDOMAIN': 'CONTAINS_CONCEPTS',
                    'HAS_ACTUAL_DOMAIN': 'CONTAINS_CONCEPTS',
                    'HAS_PERSONAL_DOMAIN': 'CONTAINS_CONCEPTS',
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
            # ⛔ THE PREFIX MATCH IS DONE IN PYTHON, NOT IN CYPHER, and that is a fix rather than
            # a preference. The old form derived the type with a CASE and then used that variable
            # as a pattern property; an embedded backend cannot evaluate a CASE-derived variable
            # there ("Cannot evaluate expression with type VARIABLE", measured on kuzu 0.11.3
            # 2026-08-12), so the whole block silently did nothing and no timeline stub was ever
            # typed. It is also simply the wrong place for the work: python already holds the
            # names, prefix matching is not database work, and one UNWIND over pre-computed rows
            # is engine-neutral, shorter, and does the matching once instead of per row per pass.
            # Order stays load-bearing: 'Iteration_Summary_' before 'Iteration_' (prefix overlap).
            TIMELINE_PREFIXES = (
                ('Iteration_Summary_', 'Iteration_Summary'),
                ('User_Message_', 'User_Message'),
                ('Agent_Message_', 'Agent_Message'),
                ('Tool_Call_', 'Tool_Call'),
                ('Unnamed_Conversation_At_', 'Conversation'),
                ('Conversation_', 'Conversation'),
                ('Iteration_', 'Iteration'),
            )
            typed_rows = []
            for target in batch_targets:
                for prefix, typ in TIMELINE_PREFIXES:
                    if target.startswith(prefix):
                        typed_rows.append({'name': target, 'typ': typ})
                        break            # first match wins, exactly as the CASE did
            if typed_rows:
                graph.execute_query("""
                UNWIND $rows AS row
                MATCH (n:Wiki {n: row.name}) WHERE NOT (n)-[:IS_A]->()
                MERGE (t:Wiki {n: row.typ})
                MERGE (n)-[:IS_A]->(t)
                MERGE (t)-[:HAS_INSTANCES]->(n)
                """, {'rows': typed_rows})
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

    # ⛔ concepts_created REPORTS THE WRITE, NOT THE INPUT (issue 176). It used to be
    # len(concept_rows) unconditionally — so when the node-create UNWIND raised, the caller's
    # `neo4j_succeeded = result['concepts_created'] > 0` still read True, the worker loop moved
    # every file to processed/, and the batch vanished: queue consumed, nothing written, nothing
    # dead-lettered (the exact silent-loss shape measured on the tenant box, where 23 consumed
    # files left a 1-node store). Zero here makes the loop dead-letter the batch to failed/
    # loudly instead.
    return {
        'concepts_created': len(concept_rows) if nodes_written else 0,
        'relationships_created': total_rels,
        'errors': errors,
        'promoted': promoted,
        'properties_set': props_applied
    }


def _concept_row(data: dict, name: str, rels_dict: dict, source: str) -> dict:
    """One concept's row for the batch write, read off a raw_concept file or one entry of a
    concepts list. ONE builder for both, so the two can never again carry different keys."""
    return {
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
        'source': source,
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
    }


def parse_queue_file_to_concepts(queue_file: Path) -> list:
    """
    Parse a queue file into flat list of concept dicts for batch processing.

    Handles three formats:
    - raw_concept files: single concept
    - concepts list files: {"concepts": [...]}, each item carrying every key a raw_concept
      file does (properties included); `source` falls back to the file's own
    - observation files: N+1 concepts (wrapper + parts via observation tags)

    Returns:
        List of dicts with {name, description, relationships, ...} — `_concept_row`'s keys
        for the first two formats
    """
    from carton_mcp.add_concept_tool import normalize_concept_name, OBSERVATION_TAGS, OBSERVATION_NON_TAG_KEYS
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

            concepts.append(_concept_row(data, name, rels_dict, data.get('source', 'agent')))
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

            # THE SAME ROW AS A raw_concept FILE, read off this entry. This branch used to build
            # its own five-key dict, so a concept sent in a list lost its properties and every
            # SOMA-verdict key on the way to the graph, and a caller that needed properties had
            # to send one file per concept. Only `source` falls back to the file's own value.
            concepts.append(_concept_row(concept_data, name, rels_dict,
                                         concept_data.get('source', data.get('source', 'agent'))))

        if concepts:
            print(f"[Parse] Parsed {len(concepts)} concepts from concepts-list format in {queue_file.name}", file=sys.stderr)
    else:
        # Observation - N+1 concepts
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        observation_name = f"{timestamp}_Observation"

        # Collect all part concepts — scan ALL keys, skip known non-tag keys
        # (the set lives in add_concept_tool as OBSERVATION_NON_TAG_KEYS — ONE
        # home, shared with observation_validation_errors, issue #198)
        all_parts = []
        _NON_TAG_KEYS = OBSERVATION_NON_TAG_KEYS
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


def _process_timeline_merge(data: dict, graph) -> bool:
    """Process one timeline_merge payload on the LIVE worker path.

    The proven merge logic (transfer CREATED_DURING from the Unnamed conversation
    node to the real one, then delete the Unnamed) previously lived ONLY inside
    process_queue_file — dead code with zero callers since the worker loop moved
    to parse_queue_file_to_concepts — so every timeline_merge queue file parsed
    to [] and dead-lettered UNPROCESSED (found 2026-07-19 during the issue-61
    triage: all 172 retried merge files bounced straight back to failed/, and
    fresh merges were dead-lettering daily). Returns True on success (caller
    consumes the file), False on any failure (caller dead-letters it).

    THE SEMANTICS ARE NO LONGER THE DEAD PATH'S -- this line used to say "same query semantics as
    the dead path, deliberately unchanged", and that stopped being true on 2026-08-24 while the
    sentence stayed. Two deliberate divergences, both to stop edge loss: (a) EVERY relationship
    type is transferred in both directions before the delete, not just CREATED_DURING; (b) the
    delete is REFUSED outright when the merge target does not exist. The dead copy in
    process_queue_file still has the original semantics and is NOT maintained in lockstep -- this
    is the implementation of record.
    """
    unnamed = data.get('unnamed_concept')
    real = data.get('real_concept')
    if not unnamed or not real or graph is None:
        return False
    try:
        result = graph.execute_query(
            """
            MATCH (c:Wiki)-[old:CREATED_DURING]->(unnamed:Wiki {n: $unnamed})
            MATCH (real:Wiki {n: $real})
            MERGE (c)-[:CREATED_DURING]->(real)
            DELETE old
            SET c.timeline_linked = true
            RETURN count(c) as transferred
            """,
            {'unnamed': unnamed, 'real': real},
        )
        count = result[0]['transferred'] if result else 0

        # TRANSFER EVERY OTHER RELATIONSHIP BEFORE DELETING (fixed 2026-08-24, measured).
        # The query above moves ONLY CREATED_DURING; the DETACH DELETE below then destroys every
        # OTHER edge on the placeholder. Measured on a live placeholder: 95 CREATED_DURING (moved)
        # but also PART_OF / HAS_PART / HAS_INSTANCES (silently destroyed). That is real data loss:
        # the doc-mirror journal attaches its entries to the ACTIVE conversation via part_of, and
        # during the first window the active conversation IS this placeholder -- so every journal
        # entry written before a precompact assigns real_concept would lose its position in the
        # conversation at the very next compaction, with nothing reporting it.
        # Relationship types cannot be parameterised in Cypher, so they are read FROM THE DB and
        # sanitised to ^[A-Z_]+$ before interpolation -- the same discipline remove_relationship uses.
        for direction in ("in", "out"):
            q = ("MATCH (x:Wiki)-[r]->(u:Wiki {n: $unnamed}) RETURN DISTINCT type(r) AS t"
                 if direction == "in" else
                 "MATCH (u:Wiki {n: $unnamed})-[r]->(x:Wiki) RETURN DISTINCT type(r) AS t")
            try:
                rows = graph.execute_query(q, {'unnamed': unnamed}) or []
            except Exception:
                rows = []
            for row in rows:
                rtype = (row.get('t') or '') if isinstance(row, dict) else ''
                if rtype == 'CREATED_DURING' or not re.fullmatch(r'[A-Z_]+', rtype):
                    continue
                move = (
                    f"MATCH (x:Wiki)-[old:{rtype}]->(u:Wiki {{n: $unnamed}}) "
                    f"MATCH (real:Wiki {{n: $real}}) "
                    f"MERGE (x)-[:{rtype}]->(real) DELETE old RETURN count(x) AS n"
                    if direction == "in" else
                    f"MATCH (u:Wiki {{n: $unnamed}})-[old:{rtype}]->(x:Wiki) "
                    f"MATCH (real:Wiki {{n: $real}}) "
                    f"MERGE (real)-[:{rtype}]->(x) DELETE old RETURN count(x) AS n"
                )
                try:
                    mres = graph.execute_query(move, {'unnamed': unnamed, 'real': real})
                    moved = mres[0]['n'] if mres else 0
                    if moved:
                        count += moved
                        print(f"[Worker] Timeline merge: moved {moved} {rtype} ({direction}) "
                              f"{unnamed} -> {real}", file=sys.stderr)
                except Exception as e:
                    # FAIL LOUD, never silently drop an edge we were about to delete.
                    print(f"[Worker] Timeline merge FAILED to move {rtype} ({direction}) "
                          f"{unnamed} -> {real}: {e}", file=sys.stderr)
                    return False

        # NEVER DELETE WHEN THE TARGET IS ABSENT (2026-08-24, completing the all-types transfer
        # added above). Every transfer above MATCHes `real`, so if `real` does not exist they all
        # matched nothing and moved nothing; a DETACH DELETE here would then destroy the
        # placeholder's PART_OF/HAS_PART edges with nowhere to have moved them, SILENTLY --
        # precisely what the FAIL LOUD branch above refuses to do. Dead-letter instead; the file is
        # retryable once the real conversation lands.
        #
        # ⛔ THIS BRANCH WAS THE NORMAL PATH UNTIL 2026-09-16, and the sentence that used to stand
        # here said the opposite. It read: "Not reachable on the normal path (the daemon sorts
        # queue files by name and the conversation concept is queued before the merge in the same
        # run)". Queue ORDER was never the relevant thing. The caller collected concepts across
        # the whole batch and wrote them only afterwards, while dispatching merges inline during
        # that same collection pass — so the target was unwritten no matter which file sorted
        # first, and this refusal fired on EVERY compaction. Measured 2026-09-14, 2026-09-15 and
        # 2026-09-16: three windows whose journal entries stayed on the placeholder while their
        # message ladders sat on the real node, because precompact writes those directly and they
        # never needed a merge. The caller now defers merges to Phase 2m, after the batch write.
        # So this refusal is correct and stays; what changed is that it should now be reached only
        # by the two genuinely exceptional cases: the conversation concept dead-lettered while its
        # merge did not, and a retry of a merge older than its conversation.
        _exists = graph.execute_query(
            "MATCH (r:Wiki {n: $real}) RETURN count(r) AS n", {'real': real})
        if not (_exists and _exists[0].get('n')):
            print(f"[Worker] Timeline merge: real conversation {real} does NOT exist -- refusing to "
                  f"delete {unnamed}, dead-lettering so its edges are not lost", file=sys.stderr)
            return False
        graph.execute_query("MATCH (n:Wiki {n: $name}) DETACH DELETE n", {'name': unnamed})
        print(f"[Worker] Timeline merge: {unnamed} -> {real} ({count} relationships transferred)", file=sys.stderr)
        log_system_event(graph, "timeline_merge", f"Merged {unnamed} -> {real}, {count} relationships transferred", "observation_daemon")
        return True
    except Exception as e:
        print(f"[Worker] Timeline merge error for {unnamed} -> {real}: {e}", file=sys.stderr)
        return False


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


def _graph_open_preflight(timeout_s: int = 60) -> dict:
    """Prove the graph can be opened, in a CHILD process, so a native crash is survivable.

    Returns {"openable": bool, "reason": str, "evidence": [str]}. Never raises: a
    preflight that itself blew up must not be the thing that takes the box down.

    The child runs the SAME construction `_create_shared_neo4j` uses, so a pass here
    means the real open will pass too. A negative returncode is death by signal —
    that is the corrupt-database case, and the one this exists to name.
    """
    import subprocess  # function-local, matching this module's established import style
    probe = (
        "from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder;"
        "import os;"
        "k=KnowledgeGraphBuilder("
        "uri=os.getenv('NEO4J_URI','bolt://host.docker.internal:7687'),"
        "user=os.getenv('NEO4J_USER','neo4j'),"
        "password=os.getenv('NEO4J_PASSWORD','password'));"
        "k._ensure_connection()"
    )
    evidence = []

    # Size the store's files first — this is what tells an operator WHICH failure it is.
    db_path = os.getenv("KUZU_DB_PATH")
    if db_path:
        try:
            main_bytes = os.path.getsize(db_path) if os.path.exists(db_path) else 0
            wal_path = db_path + ".wal"
            wal_bytes = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
            evidence.append(f"{db_path} = {main_bytes} bytes; {wal_path} = {wal_bytes} bytes")
            if wal_bytes > main_bytes:
                evidence.append(
                    "the write-ahead log is LARGER than the main file — unreplayed writes"
                )
        except Exception as exc:
            evidence.append(f"could not size the database files: {exc}")

    try:
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {
            "openable": False,
            "reason": f"opening the graph did not finish within {timeout_s}s (hung)",
            "evidence": evidence,
        }
    except Exception as exc:
        # The preflight could not run. Do NOT block the box on our own probe failing.
        return {"openable": True, "reason": f"preflight skipped: {exc}", "evidence": evidence}

    if proc.returncode < 0:
        import signal as _signal
        try:
            signame = _signal.Signals(-proc.returncode).name
        except Exception:
            signame = f"signal {-proc.returncode}"
        return {
            "openable": False,
            "reason": f"opening the graph died by {signame} — the database file is unreadable",
            "evidence": evidence,
        }
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        if tail:
            evidence.append(f"child stderr: {tail[-1][:200]}")
        return {
            "openable": False,
            "reason": f"opening the graph exited {proc.returncode}",
            "evidence": evidence,
        }
    return {"openable": True, "reason": "graph opened cleanly", "evidence": evidence}


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
        # MICROSECONDS, not seconds. An instance name must be UNIQUE to the instance
        # (Isaac 2026-08-21: "there are *zero instances* with universal names because
        # instances have instance names"). At second resolution two events in the same
        # second got the SAME name, and the CREATE below then made two nodes for them —
        # measured: System_Event_2026_07_19T04_59_59_timeline_merge existed 77 times.
        ts = datetime.now().strftime("%Y_%m_%dT%H_%M_%S_%f")
        event_name = f"System_Event_{ts}_{event_type}"
        day_name = f"Day_{datetime.now().strftime('%Y_%m_%d')}"

        # THE TYPE NODE IS MERGED, NEVER CREATED. This line used to read
        #     CREATE (e)-[:IS_A]->(:Wiki {n: "System_Event"})
        # which minted a BRAND NEW System_Event node on every single call, so the
        # universal was shattered into 41,721 byte-identical copies and `is_a
        # System_Event` converged on nothing. A universal IS ITSELF — exactly one node.
        # The instance is still CREATEd (it is genuinely new each time); only the type
        # it points at is MERGEd.
        # ⛔ EVERY MERGE IS COLLAPSED WITH `WITH ... LIMIT 1` BEFORE THE CREATE, AND THAT IS
        # LOAD-BEARING ON A GRAPH THAT STILL HOLDS DUPLICATES — it is not defensive styling.
        # MERGE on a name that has N duplicate nodes MATCHES ALL N and returns N ROWS, and
        # every downstream clause then runs ONCE PER ROW. So the CREATE below became N
        # creates. MEASURED IN PRODUCTION 2026-08-22, by deploying the CREATE->MERGE fix
        # onto the still-shattered graph: `MERGE (etype:Wiki {n:"System_Event"})` matched
        # the 41,751 duplicate type nodes and THREE events created 125,253 instance nodes
        # in about three minutes.
        #
        # THE GENERAL LAW, which the ordering of this whole repair depends on: converting
        # CREATE to MERGE does not merely fail to help on a shattered graph, IT AMPLIFIES.
        # The de-duplication must therefore come BEFORE (or together with) any CREATE->MERGE
        # conversion, never after it. A collapsed MERGE is safe in both worlds: exactly one
        # row whether the name has 1 node or 41,751, so this is correct before AND after the
        # dedupe lands.
        query = """
        MERGE (timeline:Wiki {n: "System_Timeline"})
        ON CREATE SET timeline.d = "Timeline of all background system events (daemon, linker, summarizer, projector)",
                      timeline.t = datetime(), timeline.source = "system"
        WITH timeline LIMIT 1
        MERGE (day:Wiki {n: $day})
        ON CREATE SET day.d = "Day container", day.t = datetime()
        WITH timeline, day LIMIT 1
        MERGE (timeline)-[:HAS_PART]->(day)
        WITH day LIMIT 1
        MERGE (etype:Wiki {n: "System_Event"})
        ON CREATE SET etype.d = "A background system event (daemon, linker, summarizer, projector).",
                      etype.t = datetime(), etype.source = "system"
        WITH day, etype LIMIT 1
        CREATE (e:Wiki {n: $name, d: $desc, t: datetime(), source: $source, linked: true, timeline_linked: true})
        MERGE (e)-[:IS_A]->(etype)
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

    # LINKER DEBOUNCE (Isaac 2026-08-09, issue 142): only link nodes UNTOUCHED for this many
    # seconds. Every write/edit resets last_modified in the same SET that flips linked=false,
    # so the window restarts on each modification — an actively-edited node is NEVER linked
    # mid-session (which is what made surgical str-edits compose against stale linked text),
    # and gets linked exactly once after the dust settles. Nodes with no last_modified (legacy
    # backlog) link immediately, preserving existing behavior for them.
    _DEFAULT_DEBOUNCE_S = 1800
    _raw_debounce = os.getenv('CARTON_LINKER_DEBOUNCE_S', str(_DEFAULT_DEBOUNCE_S))
    try:
        linker_debounce_s = int(_raw_debounce)
        if linker_debounce_s < 0:
            raise ValueError("negative")
    except (ValueError, TypeError):
        print(f"[Linker] ERROR: CARTON_LINKER_DEBOUNCE_S={_raw_debounce!r} is not a "
              f"non-negative integer — using default {_DEFAULT_DEBOUNCE_S}s", file=sys.stderr)
        linker_debounce_s = _DEFAULT_DEBOUNCE_S
    print(f"[Linker] Debounce: {linker_debounce_s}s (nodes modified more recently are skipped)",
          file=sys.stderr)

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
            
            # Query for unlinked concepts (batch of 100) — newest-eligible first. THE DEBOUNCE
            # (issue 142): skip anything modified within the window; last_modified is stamped in
            # the same SET that flips linked=false, so each write/edit restarts the window and an
            # actively-edited node is never linked mid-session. last_modified IS NULL (legacy
            # backlog / nodes created outside the UNWIND path) links immediately, as before.
            #
            # ⛔ THE CUTOFF IS COMPUTED IN PYTHON, NOT WITH duration() IN CYPHER (issue 176).
            # `datetime() - duration({seconds: $s})` is neo4j-only: kuzu 0.11.3 has no duration()
            # and tries to parse the map literal AS an interval string — measured on the tenant
            # box: `Conversion exception: Error occurred during parsing interval. Given:
            # "{seconds: 1800}"`, crashing this thread every cycle forever (95 logged crashloops)
            # so nothing was ever linked or timeline-linked there. Python already holds the
            # clock; one UTC cutoff parameter compared with datetime($cutoff) is engine-neutral
            # (the kuzu adapter translates datetime( → timestamp(, both engines parse the ISO
            # literal, and both stamp last_modified as a UTC instant). Same pattern as the
            # separator-as-parameter and prefix-match-in-python fixes above.
            # A node of a VERBATIM type (Desc_Content, the raw content carton keeps as written) is never
            # selected, so the linker never rewrites a doc(m) content node (card 813); the predicate is
            # carton_utils.linker_eligible, the one the crown counts over the live graph.
            from datetime import datetime as _dt, timedelta as _td, timezone as _tz
            from carton_mcp.carton_utils import VERBATIM_TYPES, linker_eligible
            cutoff = (_dt.now(_tz.utc) - _td(seconds=linker_debounce_s)).strftime('%Y-%m-%dT%H:%M:%S')
            query = f"""
            MATCH (c:Wiki)
            WHERE {linker_eligible('c')}
            RETURN c.n as name, c.d as description
            ORDER BY c.t DESC
            LIMIT 100
            """

            result = linker_neo4j.execute_query(
                query, {'cutoff': cutoff, 'verbatim_types': list(VERBATIM_TYPES)})

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


def drain_once(queue_dir: Path, shared_neo4j) -> dict:
    """Drain ONE batch of the queue — the worker loop's whole write path, callable on its own.

    Phase 1 parses up to UNWIND_BATCH_SIZE files (validation dead-letters first), Phase 2 writes
    them in one batch with retry, Phase 2.5 runs the post-write effects, Phase 2m the timeline
    merges, Phase 3 files every payload as processed, requeued or dead-lettered. `worker_daemon`
    calls this once per tick; a test calls it directly with its own queue dir and connection.

    Returns {"connection", "files", "processed", "failed"}: the connection to keep using (a
    stale one is replaced inside), how many files this batch took (0 = the queue was empty, and
    nothing else ran), and how many were filed as processed and as failed.
    """
    queue_files = sorted(queue_dir.glob('*.json'))
    if not queue_files:
        return {'connection': shared_neo4j, 'files': 0, 'processed': 0, 'failed': 0}
    processed = 0
    failed = 0

    # Health check Neo4j before each batch — reconnect if stale
    shared_neo4j = _ensure_neo4j_alive(shared_neo4j)

    # TRUE UNWIND: Parse batch of files into flat concept list
    batch_files = queue_files[:UNWIND_BATCH_SIZE]
    print(f"[Worker] UNWIND batch: {len(batch_files)} files (queue has {len(queue_files)} total)", file=sys.stderr)

    # Phase 1: Parse all files into flat concept array
    all_concepts = []
    parsed_files = []  # Track which files parsed successfully
    failed_files = []  # Track parse failures
    # TIMELINE MERGES ARE COLLECTED HERE AND RUN AFTER THE CONCEPT WRITE (Phase 2m).
    # Executing them inline in this parse phase IS the defect — see Phase 2m below.
    merge_files = []

    for queue_file in batch_files:
        # #198: the four-required-rels observation validation, LIVE
        # on the UNWIND lane as a LOUD DEAD-LETTER. The old validator
        # only existed in the dead process_queue_file path, so the
        # live lane validated nothing. A failing observation file is
        # annotated with the named reason (error_message — the key
        # check_failed_observations/retry_failed_observations already
        # read) and moved to failed/; the drain NEVER crashes.
        try:
            with open(queue_file) as _vf:
                _vdata = json.load(_vf)
        except Exception:
            _vdata = None  # unreadable files fall through to parse, which dead-letters them
        if _vdata is not None:
            _verrors = observation_validation_errors(_vdata)
            if _verrors:
                _vreason = "; ".join(_verrors)
                print(f"[Worker] VALIDATION dead-letter {queue_file.name}: {_vreason}", file=sys.stderr)
                # The reason travels WITH the file to the mover, which records it.
                # The wording is unchanged from when this branch annotated inline,
                # because it is the string the #198 rule documents.
                failed_files.append((
                    queue_file,
                    f"observation validation failed (issue #198): {_vreason}",
                    None))
                continue
        concepts = parse_queue_file_to_concepts(queue_file)
        if concepts:
            all_concepts.extend(concepts)
            parsed_files.append(queue_file)
            continue
        # Empty parse: check for a TIMELINE-MERGE file (no concept
        # payload, so the parse legitimately returns []). Its handler
        # previously lived only in the dead process_queue_file path,
        # which made EVERY merge file dead-letter unprocessed (found
        # 2026-07-19, issue-61 triage). Route it to the live handler.
        try:
            with open(queue_file) as _qf:
                merge_data = json.load(_qf)
        except Exception:
            merge_data = None
        if merge_data and merge_data.get('timeline_merge'):
            # DEFERRED TO PHASE 2m — never run here. The merge's target conversation
            # is a CONCEPT queued by the same precompact run, and every concept in
            # this batch is only ACCUMULATED in this phase: it does not exist in the
            # graph until the batch write below. Running the merge here therefore
            # found its target absent on every compaction, refused the delete (which
            # is correct — the placeholder's edges must never be destroyed with
            # nowhere to have moved them), and dead-lettered a file its own error text
            # calls retryable. Nothing retries a dead-lettered merge, so a transient
            # ordering failure became permanent loss of the conversation POSITION of
            # every journal entry in that window — the message ladder survived because
            # precompact writes it straight at the real node and never needs the merge.
            # Measured 2026-09-14, 2026-09-15 and 2026-09-16, three windows stranded.
            merge_files.append((queue_file, merge_data))
        else:
            failed_files.append((queue_file, (
                "the payload could not be parsed into any concept: it matches none of "
                "the queue's known shapes (raw_concept / concepts-list / observation / "
                "timeline_merge), or its JSON is unreadable."), None))

    print(f"[Worker] Parsed {len(all_concepts)} concepts from {len(parsed_files)} files", file=sys.stderr)

    # NOTE: Auto-linking is handled by background thread (linker_thread)
    # Main loop just inserts fast, linker picks up unlinked nodes asynchronously

    # Phase 2: UNWIND batch create in Neo4j (single batch operation)
    neo4j_succeeded = False
    _write_attempts = 0
    _write_errors = []
    if all_concepts and shared_neo4j:
        # RETRY WITH BACKOFF BEFORE CONDEMNING THE BATCH.
        #
        # A failure here does not lose ONE payload — it dead-letters every payload
        # parsed in the same batch (see the `failed_files.extend` below), up to
        # UNWIND_BATCH_SIZE of them. So a momentary store outage cost up to 2000
        # payloads at once, each filed as permanently broken, with nothing recording
        # that they were only standing next to a failed write.
        #
        # The reconnect between attempts is the half that actually recovers: the
        # common failure is a connection that went stale under the transaction, and
        # replacing it is what makes the next attempt succeed. Re-running the write is
        # safe because the node UNWIND is a MERGE and the append path already
        # de-duplicates, so a retry after a failed attempt cannot double-write.
        def _attempt_batch_write():
            r = batch_create_concepts_neo4j(all_concepts, shared_neo4j)
            print(f"[Worker] UNWIND result: {r['concepts_created']} concepts, {r['relationships_created']} rels", file=sys.stderr)
            if r['errors']:
                print(f"[Worker] UNWIND errors: {r['errors'][:3]}", file=sys.stderr)
            return r

        def _reconnect_before_retry(attempt_no, delay, _r):
            # Replacing the connection is the half that actually recovers.
            nonlocal shared_neo4j
            print(f"[Worker] batch write FAILED (attempt {attempt_no}) — "
                  f"{len(parsed_files)} file(s) at stake; waited {delay:.1f}s, "
                  f"reconnecting and retrying", file=sys.stderr)
            shared_neo4j = _ensure_neo4j_alive(shared_neo4j)
            if shared_neo4j is None:
                print("[Worker] no graph connection could be re-established — "
                      "stopping the retries", file=sys.stderr)
                return False
            return True

        result, _write_attempts = run_with_retry(
            _attempt_batch_write,
            # Success = concepts were created AND no fatal errors
            lambda r: r['concepts_created'] > 0,
            backoff_delays(retry_attempts()),
            before_retry=_reconnect_before_retry,
        )
        _write_errors = result['errors']
        neo4j_succeeded = result['concepts_created'] > 0

        if neo4j_succeeded and _write_attempts > 1:
            print(f"[Worker] batch write RECOVERED on attempt {_write_attempts} — "
                  f"{len(parsed_files)} file(s) saved from the dead-letter queue",
                  file=sys.stderr)

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
        # States only what THIS site knows. It used to say "files stay in queue" — a claim about
        # the files' FATE, which is decided two phases below and which, until issue 280, decided
        # the opposite in the same iteration. The site that does not decide the fate no longer
        # asserts it; Phase 3 announces it, because Phase 3 is what determines it.
        print("[Worker] ERROR: no Neo4j connection — nothing will be attempted this batch", file=sys.stderr)

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
        #
        # GRADE-EXEMPT effects (2026-08-20, e2e run-11 cascade): the gate above
        # exists for PROJECTORS — handlers that render the concept's OWN content
        # to files (dchain_skill_project / dchain_rule_project), where an
        # incomplete (SOUP/CODE) concept must not project. A cascade-COMPLETION
        # effect is a different kind: its firing condition is fully encoded in
        # its d-chain premise (the giint readiness cascade concludes only when
        # every level marked giint_level_ready), and the EVENT concept's verdict
        # grade says nothing about that condition — a giint project INSTANCE
        # grades CODE by construction ("N d-chain(s) pending"), so gating its
        # stamp on is_system_type silently dropped it forever (measured: all 4
        # cascade marks persisted in tenant soma_triples, giint_ready stamp never
        # dispatched, requirement-6 stalled). Effects named here dispatch at any
        # grade; the d-chain premise IS their gate.
        _GRADE_EXEMPT_EFFECTS = {
            # canonical (2026-08-20): store-side handler in the store's own
            # package, so the lean BOX worker (the remote-enqueue drainer,
            # which can never install llm_intelligence) can dispatch it.
            "carton_mcp.giint_effects:stamp_giint_project_ready",
            # legacy path — store rows registered before the move still name it;
            # llm_intelligence.projects keeps a thin delegate under this name.
            "llm_intelligence.projects:stamp_giint_project_ready",
            # issue #148: the carton_task kanban-card sync. A task INSTANCE
            # never grades is_system_type (it grades soup/code), so gating
            # this on the grade drops it forever — the same measured GIINT
            # cascade failure. Its d-chain premise (code_gap) IS the gate;
            # the handler is env-gated + never-raising on its own.
            "carton_mcp.substrate_projector:sync_task_kanban_card",
            # issue #712: the doc-mirror board's build-freed ratchet. A lane
            # TRANSITION instance grades soup/code and never is_system_type, exactly
            # like the card above, so gating it on the grade would drop it forever.
            # Its d-chain premise — the non-build lanes listed positively, with
            # code_gap first so an incomplete transition skips — IS the gate.
            "carton_mcp.doc_mirror_kanban_effects:ratchet_on_build_freed",
            # card 780: LFPOOP join A. Each partial (call graph, rollup wiring, ring
            # set) is a vaulted-type INSTANCE that grades code, never is_system_type;
            # its d-chain premise (code_gap) IS the gate.
            "carton_mcp.lfpoop_join_effects:write_rollup_wiring",
            "carton_mcp.lfpoop_join_effects:write_learned_ring_set",
            "carton_mcp.lfpoop_join_effects:write_ab3_states",
        }
        import importlib as _importlib
        _eff_seen = set()
        for c in all_concepts:
            for eff in (c.get("release_effects") or []):
                handler = (eff.get("handler") or "").strip()
                if (not c.get("is_system_type")
                        and handler not in _GRADE_EXEMPT_EFFECTS):
                    continue
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
            # The move itself lives in llm_intelligence.pbml_lane so this daemon
            # and the WakingDreamer odyssey tick share ONE implementation. The
            # tick exists because under a tenant lane the dispatching worker is
            # the BOX worker, which is lean BY RULING and hits the ImportError
            # branch below forever — so the ecosystem-side tick is the lane that
            # actually runs there. Only the graph access differs between the two
            # callers, which is why the module takes an injected query function.
            from llm_intelligence.pbml_lane import apply_pbml_move, match_trigger
            for c in all_concepts:
                trigger = match_trigger(c)
                if not trigger:
                    continue
                move = apply_pbml_move(c, shared_neo4j.execute_query)
                if not move.get("moved"):
                    print(f"[Worker] PBML lane move skipped for {c.get('name','')}: {move.get('reason')}", file=sys.stderr)
                    continue
                print(f"[Worker] 🔄 PBML auto-move: {move['trigger']} → {move['task_id']} in {move['project_id']}: {move.get('treekanban_sync', {})}", file=sys.stderr)
                if move.get("archived_card"):
                    print(f"[Worker] 🏁 PBML archive: card #{move['archived_card']} moved to archive", file=sys.stderr)
                if move.get("archive_error"):
                    print(f"[Worker] PBML archive move failed: {move['archive_error']}", file=sys.stderr)
                # Odyssey ML trigger: done_signal fires the full ML pipeline.
                # Deliberately NOT inside pbml_lane — the two callers fire odyssey
                # at different points in their own flow, so each owns its trigger.
                if trigger == "done_signal":
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

    # Phase 2m: TIMELINE MERGES, AFTER THE CONCEPT WRITE AND NEVER BESIDE IT.
    #
    # A merge names two nodes: the placeholder session_start minted when the window
    # OPENED, and the real Conversation node precompact mints when it CLOSED. The
    # second is an ordinary concept dropped in the same queue run, so it exists only
    # once the batch write above has run. Dispatching the merge in the parse phase —
    # which is what this code did until 2026-09-16 — asks it to find a node this very
    # batch has not written yet, on every single compaction.
    #
    # It is deliberately NOT gated on neo4j_succeeded: a batch holding only merge
    # files parses no concepts at all, so neo4j_succeeded is False while the targets
    # landed in some earlier batch and the merges are perfectly runnable.
    #
    # The failure text is unchanged and still accurate — it is the string the
    # timeline-merge dev-flow rule documents — but it should now be reachable only
    # for the cases it actually describes: a target whose own concept dead-lettered,
    # or a retry of a merge older than its conversation.
    for _merge_file, _merge_data in merge_files:
        if _process_timeline_merge(_merge_data, shared_neo4j):
            _merge_file.unlink(missing_ok=True)
        else:
            failed_files.append((_merge_file, (
                "timeline merge failed: the merge target conversation does not "
                "exist yet, or one of the placeholder's edges could not be moved "
                "onto it. Retryable once the real conversation node lands."), None))

    # Phase 3: Move files based on Neo4j result — THREE outcomes, never two.
    #
    # ⛔ THIS BLOCK USED TO ASK ONE QUESTION, `did the write succeed`, AND TREAT
    # EVERY NO AS THE SAME NO (issue 280). With no connection at all, Phase 2's
    # `if all_concepts and shared_neo4j` is false, so the retry lane — including
    # the reconnect that is the half which actually recovers — never runs:
    # _write_attempts stays 0 and _write_errors stays empty. This block then
    # condemned every parsed file with `batch write to the graph failed (unknown)
    # after 0 attempt(s)`, in the SAME batch iteration in which the line one phase
    # earlier printed `files stay in queue`. Both cannot be true and the log was
    # the one that was wrong. Measured on the live pile before the fix.
    #
    # The decision lives in carton_deadletter.batch_disposition, as a PURE
    # function, so the three-way rule is driven by a test with no graph at all;
    # drain_once is what lets a test drive the filing around it too.
    _disposition = batch_disposition(neo4j_succeeded, _write_attempts)
    if _disposition == PROCESSED:
        processed_dir = queue_dir / 'processed'
        processed_dir.mkdir(exist_ok=True)
        for queue_file in parsed_files:
            try:
                queue_file.rename(processed_dir / queue_file.name)
                processed += 1
            except Exception as e:
                print(f"[Worker] Failed to move {queue_file.name}: {e}", file=sys.stderr)
    elif _disposition == REQUEUE:
        # NOTHING WAS ATTEMPTED. There was no graph connection, so the write was
        # never tried and these payloads have no failure of their own to report.
        # They STAY IN THE QUEUE, which is what the message printed one phase
        # earlier already promised, and the next tick retries them once
        # _ensure_neo4j_alive re-establishes the connection at the top of the
        # batch. A payload that was never attempted is not a defective payload.
        #
        # THE COST, stated here rather than discovered later: while the store
        # stays down the queue IS the retry buffer, by design, and it grows
        # without bound. That is the deliberate trade — an unbounded queue is
        # recoverable and a dead-lettered payload filed under a reason that says
        # nothing was tried is not.
        if parsed_files:
            print(f"[Worker] no graph connection — {len(parsed_files)} file(s) STAY "
                  f"IN THE QUEUE for the next tick; nothing was attempted, so "
                  f"nothing is dead-lettered", file=sys.stderr)
    else:
        # Neo4j failed after every retry — dead-letter the parsed files WITH the
        # store's own error text. These payloads are not defective; they were
        # standing in a batch whose write failed, and the recorded reason is what
        # lets a later reader tell those two cases apart at all.
        if parsed_files:
            _reason = batch_failure_reason(_write_errors, _write_attempts)
            print(f"[Worker] Neo4j write failed after {_write_attempts} attempt(s) — "
                  f"dead-lettering {len(parsed_files)} file(s), each carrying the reason",
                  file=sys.stderr)
            failed_files.extend(
                (f, _reason, _write_attempts) for f in parsed_files)

    # Move every failed file, EACH CARRYING ITS OWN REASON.
    # This replaces a bare rename that recorded nothing: a payload landed in
    # failed/ with no trace of why, so a transient rejection and a permanently
    # malformed one were indistinguishable forever after.
    if failed_files:
        failed_dir = queue_dir / 'failed'
        for queue_file, reason, attempts in failed_files:
            if dead_letter(queue_file, failed_dir, reason, attempts=attempts):
                failed += 1


    return {'connection': shared_neo4j, 'files': len(batch_files), 'processed': processed,
            'failed': failed}


def worker_daemon():
    """
    Main daemon loop.

    Continuously watches queue directory and processes files.
    When queue is empty, pushes git changes.
    """
    # PID FILE LOCK - prevents duplicate workers from spawning
    # This prevents race conditions during MCP restart that cause:
    # - Multiple workers competing for queue files
    # - Concurrent Neo4j writes → deadlock
    # - Neo4j CPU spike (200% = 2 workers)
    # - Docker resource exhaustion
    #
    # The acquisition itself lives in carton_worker_control — the module that already owns
    # worker lifecycle (matching, stopping, spawning), one capability one module. It is there
    # rather than inline because the ORDER of open-vs-flock is the thing that has to be
    # PROVEN, and it cannot be proven here: this function starts chroma servers and never
    # returns, so no test can call it. See its docstring for issue #276 item 4 — the old
    # `open(pid_file, 'w')` truncated the file AT OPEN, before flock could refuse, so a
    # starter that lost the race blanked the winner's pid on its way out.
    #
    # `pid_fd` is bound for this function's whole lifetime on purpose: closing the handle
    # RELEASES the lock, and a released lock is how two workers end up draining one queue.
    pid_file = WORKER_PID_FILE

    try:
        pid_fd, _acquired = acquire_pid_lock(pid_file)
    except Exception as e:
        print(f"[Worker] ERROR: Failed to acquire PID lock: {e}", file=sys.stderr)
        sys.exit(1)
    if not _acquired:
        print(f"[Worker] Another worker already running (PID file locked) - exiting gracefully", file=sys.stderr)
        sys.exit(0)  # Exit gracefully - no error
    print(f"[Worker] Acquired PID lock (PID {os.getpid()})", file=sys.stderr)

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

    # GIVE THE DEAD-LETTER PILE A READER. Its failures had none: the directory simply
    # accumulated, and nothing anywhere reported how big it was or what was in it, so
    # months of lost writes went unnoticed. Reported at every startup, never fatal —
    # this is a number to look at, not a gate to fail on.
    try:
        for _line in dead_letter_report(queue_dir / 'failed').splitlines():
            print(f"[Worker] {_line}", file=sys.stderr)
    except Exception as _dl_err:
        print(f"[Worker] dead-letter report skipped: {_dl_err}", file=sys.stderr)

    # PREFLIGHT: prove the graph can be OPENED before we try to open it for real.
    #
    # WHY A SUBPROCESS (measured 2026-08-21): kuzu is embedded C++, and an unreplayable
    # write-ahead log makes `kuzu.Database(path)` die by SIGSEGV. A signal kills the
    # interpreter outright — no exception, no traceback, no dead-letter, nothing this
    # process can log about itself. Under supervisord the worker reaches RUNNING before
    # it opens the DB, so `autorestart=true` treats every death as a normal exit and
    # respawns unconditionally: a tenant box crashlooped 274 TIMES over ~15 minutes
    # while reporting Up with its port published and answering nothing at all. That is
    # the silent-failure shape this codebase exists to refuse.
    #
    # Opening in a CHILD makes the crash observable: the child takes the signal, the
    # parent survives to say exactly what is wrong and stop. Exit 78 (EX_CONFIG) is
    # listed in supervisord's `exitcodes`, so supervisord stops respawning and leaves
    # the program visibly EXITED instead of hiding the fault in a respawn loop.
    _preflight = _graph_open_preflight()
    if not _preflight["openable"]:
        print("\n" + "=" * 78, file=sys.stderr)
        print("[Worker] FATAL: THE GRAPH CANNOT BE OPENED. THIS BOX CANNOT SERVE.", file=sys.stderr)
        print(f"[Worker] cause      : {_preflight['reason']}", file=sys.stderr)
        for _line in _preflight["evidence"]:
            print(f"[Worker] evidence   : {_line}", file=sys.stderr)
        print("[Worker] what to do : this process OWNS the database file, so nothing else in", file=sys.stderr)
        print("[Worker]              the box can read or write the graph while it is down.", file=sys.stderr)
        print("[Worker]              A large .wal beside a tiny main file means an unreplayable", file=sys.stderr)
        print("[Worker]              write-ahead log from a kill mid-write. BACK UP BOTH FILES", file=sys.stderr)
        print("[Worker]              before any recovery attempt — the WAL holds the writes.", file=sys.stderr)
        print("[Worker] NOT respawning: exiting 78 so this stays visible instead of looping.", file=sys.stderr)
        print("=" * 78 + "\n", file=sys.stderr)
        sys.exit(78)

    # Create shared Neo4j connection for entire daemon lifetime
    shared_neo4j = _create_shared_neo4j()

    # THE WORKER IS CARTON'S SERVER. It owns the graph file and drains the queue, so it is the
    # one process every SDK operation must run in — and it serves them: `POST /call
    # {operation, params}` behind the account's key (carton_api). A tenant's MCP, on their own
    # machine, calls every tool here; Ribcage and every other program call the same door. The
    # operations are the MCP's tools, loaded from server_fastmcp into THIS process; its graph
    # connection resolves to this worker's own store (one embedded store per path per process,
    # graph_store.embedded_store), so a served `get_concept` and the drain share one handle.
    #
    # It serves on every backend: on kuzu nothing else can open the file, and on neo4j a box
    # without it would come up healthy, publish a port and answer nothing — the API is the
    # box's only service surface.
    #
    # FAIL-OPEN BY DESIGN: a server that will not bind must never stop the queue drain — the box
    # keeps ingesting, and says loudly that nothing can reach it.
    _carton_api_server = None
    try:
        from carton_mcp import carton_api
        _api_port = int(os.getenv("CARTON_PORT", carton_api.DEFAULT_PORT))
        _carton_api_server, _ = carton_api.serve_in_thread(_api_port)
        _api_host = os.getenv("CARTON_HOST", "127.0.0.1")
        _backend = (os.getenv("GRAPH_BACKEND") or "neo4j").strip().lower()
        print(f"[Worker] carton api on {_api_host}:{_api_port} — the SDK's operations on POST /call "
              f"(backend: {_backend}; auth: {'ON' if carton_api.required_key() else 'off — loopback only'}; "
              f"this process owns the graph)", file=sys.stderr)
    except Exception as exc:
        traceback.print_exc()
        print(f"[Worker] WARNING: carton api did not start ({exc}). The queue drain continues, "
              f"but NOTHING CAN REACH CARTON until it does — the api is the box's only service "
              f"surface.", file=sys.stderr)

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

            # One batch: parse → write → effects → merges → file. The whole drain is
            # drain_once, so a test runs exactly what this loop runs.
            _drained = drain_once(queue_dir, shared_neo4j)
            shared_neo4j = _drained['connection']

            if _drained['files']:
                processed_count += _drained['processed']
                failed_count += _drained['failed']
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
