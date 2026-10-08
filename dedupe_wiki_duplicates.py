"""Dedupe duplicate :Wiki nodes — DRY-RUN BY DEFAULT. Built 2026-08-22.

WHAT THIS IS FOR. The :Wiki namespace has NO uniqueness constraint (13 other labels in the
same database do), so nothing ever refused a second node with the same name. Isaac
2026-08-21, verbatim: "there should be *ZERO DUPLICATES* because all these things *ARE
THEMSELVES*". A universal IS ITSELF: exactly one node. Measured 2026-08-22: 111 names
across 43,716 nodes, worst System_Event at 41,751.

THE ORDER IS LOAD-BEARING and this tool is step 2 of 3:
    1. STOP EVERY WRITER  (deduping first just lets it refill)
    2. DEDUPE             (this tool)
    3. REQUIRE c.n IS UNIQUE on :Wiki  (neo4j REFUSES to create it while duplicates
       remain, which makes it a forcing function that cannot be applied prematurely)

⛔ THE EDGE FAN-OUT IS THE PART THAT IS EASY TO GET WRONG, and getting it wrong preserves
the damage while hiding its cause. MERGE on a duplicated name MATCHES ALL N copies, so
every edge ever written to that name was written to EVERY copy. Measured: on a shattered
type, every incoming edge count is an EXACT INTEGER MULTIPLE of the copy count
(Traversal_Step 397 copies -> HAS_PART 397, HAS_INSTANCES 794 = 2x, PART_OF 1191 = 3x;
State_Machine 291 -> 291/582/873; Execution_State 149 -> 149/298/447).

So a dedupe that merely REPOINTS every edge onto the survivor keeps the inflation: the
survivor ends up with N parallel edges to the same neighbour. This tool MERGEs edges onto
the survivor instead, so (source, type, target) collapses to ONE edge -- and it REPORTS
the collapse count as a first-class number, because that number is the actual repair.

SURVIVOR CHOICE is deterministic and content-preferring: most relationships wins, then
the earliest t (the original), then the lowest elementId as a stable tie-break. The copies
are usually byte-identical -- that is what makes the dedupe safe, and the tool VERIFIES
that assumption per name and flags any name whose copies differ in description, so a
genuine content conflict is never silently discarded.

SAFETY (the weld_world_graph.py precedent): dry-run DEFAULT, --apply opt-in, full export
of every affected name BEFORE any mutation, per-name exception safety, batched deletes,
and a post-condition assert that each processed name ends at exactly 1 node.

── THE TWINS MODE (--twins, issue #201) ────────────────────────────────────────────────
The same-name mode above is BLIND to the second duplicate class: NORMALIZATION TWINS —
distinct stored names that normalize_concept_name maps to ONE name (hyphen/underscore
twins, case twins like _v1/_V1, camel-hump twins like TreeShell_/Treeshell_). Ruling
2026-08-28: the equivalence class is NORMALIZATION-STABILITY (group on
normalize_concept_name(n.n)), NOT hyphen-only. 4,228 hyphen/underscore pairs was the
measured lower bound (2026-08-25, stale — re-measure at execution: the --twins dry run
IS the re-measure). These are legacy residue of writers that bypassed the normalize
chokepoint, plus the live remove-exact-vs-add-normalize divergence (both fenced
2026-08-28: normalize_concept_name sanitizes at the chokepoint, carton_utils'
write-path matchers gained a normalized fallback).

SURVIVOR RULE (ruling #4): the surviving NAME is always the NORMALIZATION-STABLE one
(normalize(name) == name — i.e. the group key); content and edges MERGE ONTO it. The
most-relationships heuristic chooses NOTHING at the name level — it is a content-donor
detector only. A group with NO stable-named node is flagged needs_rename and SKIPPED by
--apply: that row goes through the carton rename_concept tool (proactive evolution,
updates all refs), never create-then-merge. The content_differs flag is a PROMPT TO
LOOK, never a verdict — expected shape at scale is one-side-content/one-side-edges,
so --apply carries a real description onto an empty/stub-descriptioned survivor
automatically and flags every other difference for the export→look→merge flow.

ACCEPTED RESIDUAL (ruling #6): no normalized-uniqueness constraint is expressible in
neo4j (the live wiki_name_unique constraint guards EXACT names only), so re-entry is
fenced by (a) every writer routing through the hardened normalize_concept_name
chokepoint and (b) scheduled re-runs of THIS tool's --twins dry-run (record the
cadence at execution).
"""

import argparse
import datetime
import json
import os
import sys
from collections import defaultdict


def _rows(r):
    return (r[0] if isinstance(r, tuple) else r) or []


def _normalize(name):
    """The one chokepoint normalizer — the equivalence-class key for --twins.
    Lazy import; resolves to the INSTALLED carton_mcp (same law as connect())."""
    from carton_mcp.add_concept_tool import normalize_concept_name
    return normalize_concept_name(name)


def connect():
    from carton_mcp.observation_worker_daemon import _create_shared_neo4j
    return _create_shared_neo4j()


def find_duplicates(g, limit=None):
    """Every name with more than one :Wiki node, worst first."""
    q = """
    MATCH (n:Wiki) WITH n.n AS nm, count(*) AS c WHERE c > 1
    RETURN nm AS name, c AS copies ORDER BY c DESC
    """
    if limit:
        q += f" LIMIT {int(limit)}"
    return [(x['name'], x['copies']) for x in _rows(g.execute_query(q, {}))]


def inspect(g, name):
    """Per-name plan: survivor, content agreement, and the edge fan-out to collapse."""
    nodes = _rows(g.execute_query("""
        MATCH (n:Wiki {n:$n})
        OPTIONAL MATCH (n)-[r]-()
        WITH n, count(r) AS deg
        RETURN elementId(n) AS eid, deg, toString(n.t) AS t,
               substring(coalesce(n.d,''),0,4000) AS d
        ORDER BY deg DESC, t ASC, eid ASC
    """, {"n": name}))
    if not nodes:
        return None
    survivor = nodes[0]
    descs = {x['d'] for x in nodes}
    incoming = _rows(g.execute_query("""
        MATCH (s)-[r]->(n:Wiki {n:$n})
        RETURN type(r) AS rel, count(r) AS edges, count(DISTINCT s) AS distinct_sources
        ORDER BY edges DESC
    """, {"n": name}))
    outgoing = _rows(g.execute_query("""
        MATCH (n:Wiki {n:$n})-[r]->(t)
        RETURN type(r) AS rel, count(r) AS edges, count(DISTINCT t) AS distinct_targets
        ORDER BY edges DESC
    """, {"n": name}))
    # After MERGE-repointing, (source,type,survivor) collapses to one edge per distinct
    # neighbour. The difference is the inflation this repair actually removes.
    in_edges = sum(x['edges'] for x in incoming)
    in_after = sum(x['distinct_sources'] for x in incoming)
    out_edges = sum(x['edges'] for x in outgoing)
    out_after = sum(x['distinct_targets'] for x in outgoing)
    return {
        'name': name,
        'copies': len(nodes),
        'survivor_eid': survivor['eid'],
        'survivor_degree': survivor['deg'],
        'survivor_t': survivor['t'],
        'content_identical': len(descs) == 1,
        'distinct_descriptions': len(descs),
        'edges_before': in_edges + out_edges,
        'edges_after': in_after + out_after,
        'edges_collapsed': (in_edges - in_after) + (out_edges - out_after),
        'incoming': incoming,
        'outgoing': outgoing,
    }


def apply_one(g, plan, batch=2000):
    """MERGE every edge onto the survivor, then delete the other copies."""
    name, keep = plan['name'], plan['survivor_eid']
    # BATCHED, and it MUST be (fixed 2026-08-25). These two loops used to issue ONE unbatched query
    # per relationship type. That is fine for a name with a few hundred edges -- Traversal_Step (397
    # copies) went through cleanly -- and it is fatal for the one name that actually matters:
    # System_Event carries 335,862 edges, so a single rel type is hundreds of thousands of
    # MERGE+DELETE in ONE transaction. Measured 2026-08-25: it killed the connection ("Failed to read
    # from defunct connection"), took the neo4j container down with it, and reported 0/1 deduped. The
    # graph survived intact ONLY because the transaction rolled back whole (verified after: 41,751
    # copies still present, 682,459 total nodes). Note the `batch` parameter already existed and was
    # applied ONLY to the DETACH DELETE loop below -- the edge moves, the expensive half, never used
    # it. This is why the dedupe appeared "blocked" for days: nobody had run it at the size where it
    # breaks, so the failure looked like a decision waiting on a human.
    for rel in [x['rel'] for x in plan['incoming']]:
        while True:
            moved = _rows(g.execute_query(f"""
                MATCH (s)-[r:{rel}]->(dup:Wiki {{n:$n}}) WHERE elementId(dup) <> $keep
                WITH s, r LIMIT {int(batch)}
                MATCH (surv:Wiki) WHERE elementId(surv) = $keep
                MERGE (s)-[:{rel}]->(surv)
                DELETE r
                RETURN count(*) AS c
            """, {"n": name, "keep": keep}))[0]['c']
            if not moved:
                break
    for rel in [x['rel'] for x in plan['outgoing']]:
        while True:
            moved = _rows(g.execute_query(f"""
                MATCH (dup:Wiki {{n:$n}})-[r:{rel}]->(t) WHERE elementId(dup) <> $keep
                WITH r, t LIMIT {int(batch)}
                MATCH (surv:Wiki) WHERE elementId(surv) = $keep
                MERGE (surv)-[:{rel}]->(t)
                DELETE r
                RETURN count(*) AS c
            """, {"n": name, "keep": keep}))[0]['c']
            if not moved:
                break
    while True:
        left = _rows(g.execute_query(
            "MATCH (n:Wiki {n:$n}) RETURN count(n) AS c", {"n": name}))[0]['c']
        if left <= 1:
            break
        g.execute_query(f"""
            MATCH (dup:Wiki {{n:$n}}) WHERE elementId(dup) <> $keep
            WITH dup LIMIT {int(batch)} DETACH DELETE dup
        """, {"n": name, "keep": keep})
    final = _rows(g.execute_query(
        "MATCH (n:Wiki {n:$n}) RETURN count(n) AS c", {"n": name}))[0]['c']
    assert final == 1, f"POST-CONDITION FAILED for {name}: {final} nodes remain, expected 1"
    return final


# ── THE TWINS MODE (issue #201): normalization-stability equivalence class ──────────


def find_twin_groups(g, limit=None):
    """Group every :Wiki name by normalize_concept_name(n.n); groups with >= 2 DISTINCT
    stored names are normalization-twin groups. Grouping runs client-side (the normalizer
    is Python — it cannot run in Cypher). Worst first by total node count. Returns
    [(key, [name, ...], total_nodes), ...]."""
    rows = _rows(g.execute_query(
        "MATCH (n:Wiki) WHERE n.n IS NOT NULL "
        "WITH n.n AS nm, count(*) AS c RETURN nm AS name, c AS nodes", {}))
    by_key = defaultdict(list)
    for r in rows:
        by_key[_normalize(r['name'])].append((r['name'], r['nodes']))
    groups = []
    for key, members in by_key.items():
        if len(members) < 2:
            continue
        names = [m[0] for m in members]
        total = sum(m[1] for m in members)
        groups.append((key, names, total))
    groups.sort(key=lambda x: (-x[2], x[0]))
    if limit:
        groups = groups[:int(limit)]
    return groups


def inspect_twins(g, key, names):
    """Per-group plan. SURVIVOR NAME = the normalization-STABLE one (== key), per the
    2026-08-28 ruling — never the most-relationships name. Survivor NODE among the
    stable-named nodes by (deg DESC, t ASC, eid ASC) — the same tie-break the same-name
    mode uses, legitimate here because those copies share the one stable name. A group
    with NO stable-named node is needs_rename=True (route through rename_concept)."""
    nodes = _rows(g.execute_query("""
        MATCH (n:Wiki) WHERE n.n IN $names
        OPTIONAL MATCH (n)-[r]-()
        WITH n, count(r) AS deg
        RETURN n.n AS name, elementId(n) AS eid, deg, toString(n.t) AS t,
               substring(coalesce(n.d,''),0,4000) AS d
        ORDER BY deg DESC, t ASC, eid ASC
    """, {"names": names}))
    if not nodes:
        return None
    stable_nodes = [x for x in nodes if x['name'] == key]
    survivor = stable_nodes[0] if stable_nodes else None
    real_descs = {x['d'] for x in nodes if x['d'] and not x['d'].startswith('AUTO CREATED')}
    # content-donor detection (one-side-content/one-side-edges shape): a real description
    # to carry onto a survivor whose own d is empty/auto-stub. Longest wins deterministically.
    donor_desc = max(real_descs, key=len) if real_descs else None
    incoming = _rows(g.execute_query("""
        MATCH (s)-[r]->(n:Wiki) WHERE n.n IN $names
        RETURN type(r) AS rel, count(r) AS edges, count(DISTINCT s) AS distinct_sources
        ORDER BY edges DESC
    """, {"names": names}))
    outgoing = _rows(g.execute_query("""
        MATCH (n:Wiki)-[r]->(t) WHERE n.n IN $names
        RETURN type(r) AS rel, count(r) AS edges, count(DISTINCT t) AS distinct_targets
        ORDER BY edges DESC
    """, {"names": names}))
    in_edges = sum(x['edges'] for x in incoming)
    in_after = sum(x['distinct_sources'] for x in incoming)
    out_edges = sum(x['edges'] for x in outgoing)
    out_after = sum(x['distinct_targets'] for x in outgoing)
    return {
        'key': key,
        'names': names,
        'total_nodes': len(nodes),
        'removable': len(nodes) - (1 if survivor else 0),
        'needs_rename': survivor is None,
        'survivor_eid': survivor['eid'] if survivor else None,
        'survivor_has_content': bool(survivor and survivor['d']
                                     and not survivor['d'].startswith('AUTO CREATED')),
        'donor_desc': donor_desc,
        'content_differs': len(real_descs) > 1,
        'distinct_descriptions': len(real_descs),
        'edges_before': in_edges + out_edges,
        'edges_after': in_after + out_after,
        'edges_collapsed': (in_edges - in_after) + (out_edges - out_after),
        'incoming': incoming,
        'outgoing': outgoing,
    }


def apply_twins(g, plan, batch=2000):
    """MERGE every edge of every non-survivor node in the group onto the stable-named
    survivor, carry content when the survivor has none (one-side-content/one-side-edges),
    then delete the twins. REFUSES a needs_rename group (that is rename_concept's job)."""
    if plan['needs_rename']:
        raise RuntimeError(
            f"group {plan['key']!r} has NO normalization-stable node — use the carton "
            f"rename_concept tool (proactive evolution) on {plan['names']}, never create-then-merge")
    names, keep = plan['names'], plan['survivor_eid']
    for rel in [x['rel'] for x in plan['incoming']]:
        while True:
            moved = _rows(g.execute_query(f"""
                MATCH (s)-[r:{rel}]->(dup:Wiki) WHERE dup.n IN $names AND elementId(dup) <> $keep
                WITH s, r LIMIT {int(batch)}
                MATCH (surv:Wiki) WHERE elementId(surv) = $keep
                MERGE (s)-[:{rel}]->(surv)
                DELETE r
                RETURN count(*) AS c
            """, {"names": names, "keep": keep}))[0]['c']
            if not moved:
                break
    for rel in [x['rel'] for x in plan['outgoing']]:
        while True:
            moved = _rows(g.execute_query(f"""
                MATCH (dup:Wiki)-[r:{rel}]->(t) WHERE dup.n IN $names AND elementId(dup) <> $keep
                WITH r, t LIMIT {int(batch)}
                MATCH (surv:Wiki) WHERE elementId(surv) = $keep
                MERGE (surv)-[:{rel}]->(t)
                DELETE r
                RETURN count(*) AS c
            """, {"names": names, "keep": keep}))[0]['c']
            if not moved:
                break
    # ONE-SIDE-CONTENT/ONE-SIDE-EDGES: carry the donor description onto a content-less
    # survivor. Only when the survivor has NO real content — a survivor with its own
    # content is never overwritten (that difference stays flagged for the human look).
    if plan['donor_desc'] and not plan['survivor_has_content']:
        g.execute_query(
            "MATCH (surv:Wiki) WHERE elementId(surv) = $keep SET surv.d = $d",
            {"keep": keep, "d": plan['donor_desc']})
    while True:
        left = _rows(g.execute_query(
            "MATCH (n:Wiki) WHERE n.n IN $names RETURN count(n) AS c",
            {"names": names}))[0]['c']
        if left <= 1:
            break
        g.execute_query(f"""
            MATCH (dup:Wiki) WHERE dup.n IN $names AND elementId(dup) <> $keep
            WITH dup LIMIT {int(batch)} DETACH DELETE dup
        """, {"names": names, "keep": keep})
    final = _rows(g.execute_query(
        "MATCH (n:Wiki) WHERE n.n IN $names RETURN collect(n.n) AS left",
        {"names": names}))[0]['left']
    assert final == [plan['key']], (
        f"POST-CONDITION FAILED for {plan['key']}: {final} remain, expected [{plan['key']}]")
    return 1


def twins_main(g, args):
    """The --twins flow: dry-run grouping/counts by default; --apply exports every doomed
    node in full first, then merges each group onto its stable-named survivor. A group
    flagged needs_rename is ALWAYS skipped by --apply (rename_concept's job)."""
    if args.key:
        key = _normalize(args.key)
        rows = _rows(g.execute_query(
            "MATCH (n:Wiki) WHERE n.n IS NOT NULL "
            "WITH DISTINCT n.n AS nm RETURN nm", {}))
        names = [r['nm'] for r in rows if _normalize(r['nm']) == key]
        groups = [(key, names, 0)] if len(names) > 1 else []
    else:
        groups = find_twin_groups(g, args.limit)
    print(f"{len(groups)} normalization-twin group(s) selected "
          f"(equivalence class: normalize_concept_name(n.n))\n")

    plans, tot_nodes, tot_removable, tot_collapsed = [], 0, 0, 0
    conflicts, renames = [], []
    for key, names, _ in groups:
        p = inspect_twins(g, key, names)
        if not p or p['total_nodes'] < 2:
            continue
        plans.append(p)
        tot_nodes += p['total_nodes']
        tot_removable += p['removable']
        tot_collapsed += p['edges_collapsed']
        if p['content_differs']:
            conflicts.append((key, p['distinct_descriptions']))
        if p['needs_rename']:
            renames.append((key, names))
        flags = []
        if p['needs_rename']:
            flags.append('⚠ NEEDS RENAME (no stable-named node)')
        if p['content_differs']:
            flags.append('⚠ CONTENT DIFFERS')
        print(f"  {key[:48]:<48} names={len(names):>3} nodes={p['total_nodes']:>5}  "
              f"edges {p['edges_before']:>6} -> {p['edges_after']:>6} "
              f"(collapse {p['edges_collapsed']:>6})  {' '.join(flags)}")

    print(f"\nTOTALS: {len(plans)} twin groups | {tot_nodes} nodes | "
          f"{tot_removable} removable | {tot_collapsed} duplicate edges collapsed")
    if renames:
        print(f"\n⚠ {len(renames)} group(s) with NO normalization-stable member — "
              f"these route through rename_concept (proactive evolution), NOT this tool:")
        for k, ns in renames[:20]:
            print(f"    {k}  <- {ns}")
    if conflicts:
        print(f"\n⚠ {len(conflicts)} group(s) whose real descriptions differ — the flag "
              f"is a prompt to LOOK (export → look → merge), never a verdict:")
        for k, d in conflicts[:20]:
            print(f"    {k}  ({d} distinct real descriptions)")

    if not args.apply:
        print("\nDRY-RUN: nothing was modified. Re-run with --apply to execute "
              "(the batch merge is a separately gated step).")
        return 0

    stamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    path = f"/tmp/heaven_data/wiki_twins_export_{stamp}.json"
    doomed = []
    for p in plans:
        for row in _rows(g.execute_query(
                "MATCH (n:Wiki) WHERE n.n IN $names "
                "RETURN n.n AS name, elementId(n) AS eid, properties(n) AS props",
                {"names": p['names']})):
            doomed.append({'key': p['key'], 'name': row['name'], 'eid': row['eid'],
                           'survivor': row['eid'] == p['survivor_eid'],
                           'props': row['props']})
    json.dump({'exported_at': stamp,
               'plans': [{k: v for k, v in p.items() if k != 'donor_desc'} for p in plans],
               'nodes': doomed},
              open(path, 'w'), indent=2, default=str)
    print(f"\nexport written: {path}  ({len(doomed)} nodes captured in full)\nAPPLYING...")
    done = skipped = 0
    for p in plans:
        if p['needs_rename']:
            skipped += 1
            print(f"  SKIP {p['key'][:56]} (needs rename_concept)", flush=True)
            continue
        try:
            apply_twins(g, p)
            done += 1
            print(f"  OK {p['key'][:56]} <- {len(p['names'])} names -> 1", flush=True)
        except Exception as e:
            import traceback
            print(f"  FAILED {p['key'][:56]}: {e}", file=sys.stderr, flush=True)
            traceback.print_exc()
    print(f"\n{done}/{len(plans)} twin groups merged, {skipped} skipped for rename")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--apply', action='store_true',
                    help='EXECUTE (export first, then MERGE edges onto the survivor and '
                         'delete the copies). Default is DRY-RUN: touch nothing.')
    ap.add_argument('--limit', type=int, default=None, help='only the N worst names')
    ap.add_argument('--name', default=None, help='operate on ONE name (safest first run)')
    ap.add_argument('--twins', action='store_true',
                    help='issue #201 mode: dedupe NORMALIZATION TWINS — distinct names '
                         'grouped by normalize_concept_name(n.n); survivor = the '
                         'normalization-stable name; content/edges merge onto it')
    ap.add_argument('--key', default=None,
                    help='--twins only: operate on ONE normalized key (safest first run)')
    args = ap.parse_args()

    g = connect()
    if args.twins:
        return twins_main(g, args)
    if args.key:
        ap.error("--key is only valid with --twins")
    if args.name:
        targets = [(args.name, 0)]
    else:
        targets = find_duplicates(g, args.limit)
    print(f"{len(targets)} duplicated name(s) selected\n")

    plans, tot_copies, tot_removable, tot_collapsed, conflicts = [], 0, 0, 0, []
    for name, _ in targets:
        p = inspect(g, name)
        if not p or p['copies'] < 2:
            continue
        plans.append(p)
        tot_copies += p['copies']
        tot_removable += p['copies'] - 1
        tot_collapsed += p['edges_collapsed']
        if not p['content_identical']:
            conflicts.append((name, p['distinct_descriptions']))
        print(f"  {name[:52]:<52} copies={p['copies']:>6}  "
              f"edges {p['edges_before']:>7} -> {p['edges_after']:>7} "
              f"(collapse {p['edges_collapsed']:>7})"
              f"{'' if p['content_identical'] else '   ⚠ CONTENT DIFFERS'}")

    print(f"\nTOTALS: {len(plans)} names | {tot_copies} nodes | {tot_removable} removable "
          f"| {tot_collapsed} duplicate edges collapsed")
    if conflicts:
        print(f"\n⚠ {len(conflicts)} name(s) whose copies do NOT agree on description — "
              f"these are NOT byte-identical and a survivor choice DISCARDS content:")
        for n, d in conflicts[:20]:
            print(f"    {n}  ({d} distinct descriptions)")

    if not args.apply:
        print("\nDRY-RUN: nothing was modified. Re-run with --apply to execute.")
        return 0

    stamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    path = f"/tmp/heaven_data/wiki_dedupe_export_{stamp}.json"
    # EXPORT THE NODES, NOT JUST THE PLAN (fixed 2026-08-25). The header called this a "full export"
    # and it wrote ONLY the plans -- name, survivor id, edge counts. That is a record of what WOULD be
    # merged; it cannot restore a single deleted node. Measured: 1,236 bytes for an operation that
    # deletes 41,750 nodes. A destructive tool whose rollback artifact contains none of the destroyed
    # content is not safe, whatever the docstring says. Now every node that is about to be deleted is
    # dumped in full first -- its properties as stored -- so the operation is genuinely reversible.
    doomed = []
    for p in plans:
        for row in _rows(g.execute_query(
            "MATCH (n:Wiki {n:$n}) RETURN elementId(n) AS eid, properties(n) AS props",
                {"n": p['name']})):
            doomed.append({'name': p['name'], 'eid': row['eid'],
                           'survivor': row['eid'] == p['survivor_eid'], 'props': row['props']})
    json.dump({'exported_at': stamp, 'plans': plans, 'nodes': doomed},
              open(path, 'w'), indent=2, default=str)
    print(f"\nexport written: {path}  ({len(doomed)} nodes captured in full)\nAPPLYING...")
    done = 0
    for p in plans:
        try:
            apply_one(g, p)
            done += 1
            print(f"  OK {p['name'][:60]} -> 1", flush=True)
        except Exception as e:
            # PRINT THE TRACEBACK (fixed 2026-08-25). This used to print the exception's str() alone,
            # which on 2026-08-25 rendered a connection death as one opaque line -- no frame, no query,
            # no indication that the failure was a transaction size limit rather than a logic error.
            # Diagnosing it meant re-deriving from the source what the one line should have said. A
            # destructive tool's failure path is exactly where the traceback matters most.
            import traceback
            print(f"  FAILED {p['name'][:60]}: {e}", file=sys.stderr, flush=True)
            traceback.print_exc()
    print(f"\n{done}/{len(plans)} names deduped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
