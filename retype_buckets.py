#!/usr/bin/env python3
"""
retype_buckets.py — one-time retype of the 304 category buckets created by the
2026-06-11 weld from IS_A Starsystem_Collection to the canonical IS_A Collection_Category.

WHY (Isaac ruled 2026-06-11 ~04:20: 'yes'):
  The 2026-06-11 weld (weld_world_graph.py leg_d) created 4 category buckets per starsystem —
  names ending in one of {_Idea_Collections, _Design_Collections, _Architecture_Collections,
  _Task_Collections} — and typed them IS_A Starsystem_Collection. That was a mistype. CANON
  (ontology_graphs.ONTOLOGY_SCHEMAS["Starsystem_Collection"]) says these category children are
  is_a Collection_Category. The memory walker (ontology_graphs.get_expanded_metagraph step 2)
  reads:
      MATCH (hc)-[:PART_OF]->(cat)-[:IS_A]->(:Wiki {n:'Collection_Category'}) RETURN cat.n
  so while the buckets are IS_A Starsystem_Collection, that walker query MISSES and a seated
  HC's `collection_category` field is None. Retyping the buckets to IS_A Collection_Category
  makes the graph match its canonical reader → collection_category becomes NON-NULL (the payoff).

SELECTION (strict, arithmetic-gated):
  candidate = node IS_A Starsystem_Collection
              AND name ENDS WITH one of the 4 bucket suffixes
              AND name does NOT end with plain '_Collection' (canon collections end '_Collection';
                  the bucket suffixes all end '_Collections' with a trailing 's', so this excludes
                  the 79 canon collections cleanly).
  EXPECT EXACTLY 304.  Strict before-state: 383 IS_A Starsystem_Collection = 79 canon + 304 buckets.
  If the candidate count != 304: STOP at dry-run, report, do NOT apply (the arithmetic gate is the
  safety — do not "fix" the selection to force 304).

VERSIONING FEAR IS LAW: dry-run DEFAULT, --apply opt-in, full export of candidates' current
relationships BEFORE any mutation, MERGE the new class edge BEFORE deleting the old one, per-item
exception-safe, post-counts printed and asserted.

--apply (only permitted when dry-run == 304 exactly AND export written non-trivial), per candidate n:
  1. MERGE (n)-[:IS_A]->(:Wiki {n:'Collection_Category'})   — MERGE the class node itself; if it is
     being created, give it is_a Carton_Ontology_Entity (so the type node is itself well-formed).
  2. DELETE the (n)-[:IS_A]->(:Wiki {n:'Starsystem_Collection'}) edge.
  Post-counts (both printed): IS_A Starsystem_Collection MUST == 79 ; IS_A Collection_Category >= 304.

Env: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, HEAVEN_DATA_DIR (read by the carton connection).

Usage:
  python3 retype_buckets.py            # DRY-RUN (default): count + sample candidates, touch NOTHING
  python3 retype_buckets.py --apply    # EXECUTE (export first, then MERGE new IS_A + DELETE old) —
                                       #   GUARDED: refuses unless dry-run count == 304 exactly.
"""

import argparse
import datetime
import json
import os
import sys
import traceback


def _fail(item, exc):
    """Structured per-item failure record carrying the traceback (never aborts the run)."""
    return {"item": item, "error": repr(exc), "traceback": traceback.format_exc()}


# carton-mcp is the canonical source of the graph connection (same surface as weld_world_graph.py).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

MANIFEST_PATH = "/tmp/bucket_retype_manifest.json"

# The 4 category-bucket suffixes the weld appended (all end '_Collections' — plural — which is what
# distinguishes them from the 79 canon collections whose names end plain '_Collection').
BUCKET_SUFFIXES = (
    "_Idea_Collections",
    "_Design_Collections",
    "_Architecture_Collections",
    "_Task_Collections",
)

OLD_TYPE = "Starsystem_Collection"
NEW_TYPE = "Collection_Category"
EXPECTED_CANDIDATES = 304


# ---------------------------------------------------------------------------
# connection
# ---------------------------------------------------------------------------
def get_graph():
    """The shared module-level neo4j connection (same surface as weld_world_graph.get_graph)."""
    from carton_mcp.add_concept_tool import _get_module_connection
    graph = _get_module_connection()
    if graph is None:
        raise RuntimeError("no neo4j connection available (check NEO4J_* env vars)")
    return graph


def q(graph, cypher, params=None):
    """execute_query -> List[Dict]; per-item exception-safety is the caller's job."""
    return graph.execute_query(cypher, params or {})


# ---------------------------------------------------------------------------
# selection — pure neo4j, REPORTS its arithmetic, never guesses
# ---------------------------------------------------------------------------
def select_candidates(graph):
    """Return the sorted list of candidate bucket names: IS_A Starsystem_Collection AND name ends
    with one of the 4 bucket suffixes AND name does NOT end plain '_Collection'.

    The suffix filter is done with an ANY(...) over the 4 suffixes; the '_Collection' exclusion is a
    belt-and-suspenders gate (the suffixes already all end '_Collections' with a trailing 's', so no
    canon collection can pass the suffix filter — but we assert it explicitly per the spec)."""
    rows = q(graph, """
        MATCH (n:Wiki)-[:IS_A]->(:Wiki {n:$old})
        WHERE ANY(suf IN $suffixes WHERE n.n ENDS WITH suf)
          AND NOT n.n ENDS WITH '_Collection'
        RETURN n.n AS n ORDER BY n.n
    """, {"old": OLD_TYPE, "suffixes": list(BUCKET_SUFFIXES)})
    return [r["n"] for r in rows]


def selection_arithmetic(graph):
    """Verify the before-state arithmetic: total IS_A Starsystem_Collection == canon + buckets.
    canon = names ending plain '_Collection'; buckets = the candidate set. Returns a dict."""
    total = q(graph,
              "MATCH (n:Wiki)-[:IS_A]->(:Wiki {n:$old}) RETURN count(n) AS c",
              {"old": OLD_TYPE})[0]["c"]
    canon = q(graph,
              "MATCH (n:Wiki)-[:IS_A]->(:Wiki {n:$old}) WHERE n.n ENDS WITH '_Collection' "
              "RETURN count(n) AS c",
              {"old": OLD_TYPE})[0]["c"]
    candidates = select_candidates(graph)
    return {
        "total_is_a_old": total,
        "canon_collections": canon,
        "candidate_buckets": len(candidates),
        "arithmetic_ok": (canon + len(candidates) == total),
        "candidates": candidates,
    }


# ---------------------------------------------------------------------------
# export (MANDATORY before any mutation)
# ---------------------------------------------------------------------------
def export_candidates(graph, candidates, ts):
    """Export every candidate node's current OUTGOING relationships before any write."""
    export = {"exported_at": ts, "old_type": OLD_TYPE, "new_type": NEW_TYPE,
              "candidate_count": len(candidates), "nodes": {}}
    for n in candidates:
        try:
            rels = q(graph, """
                MATCH (c:Wiki {n:$n})-[r]->(t:Wiki)
                RETURN type(r) AS rel, t.n AS target ORDER BY rel, target
            """, {"n": n})
            export["nodes"][n] = [{"rel": r["rel"], "target": r["target"]} for r in rels]
        except Exception as e:
            export["nodes"][n] = {"export_error": repr(e), "traceback": traceback.format_exc()}
    path = f"/tmp/bucket_retype_export_{ts}.json"
    with open(path, "w") as f:
        json.dump(export, f, indent=2)
    return path


# ---------------------------------------------------------------------------
# apply (IMPLEMENTED — export first, then MERGE new IS_A + DELETE old). Run deliberately.
# ---------------------------------------------------------------------------
def ensure_new_type_node(graph):
    """MERGE the Collection_Category class node itself; if creating it, give it is_a
    Carton_Ontology_Entity (so the type node is well-formed). Idempotent."""
    graph.execute_query("""
        MERGE (t:Wiki {n:$new})
        ON CREATE SET t.d = 'A category container within a starsystem collection (Collection_Category type node).'
        WITH t
        MERGE (oe:Wiki {n:'Carton_Ontology_Entity'})
        MERGE (t)-[:IS_A]->(oe)
    """, {"new": NEW_TYPE})


def retype_one(graph, name):
    """Per node: MERGE new IS_A edge FIRST, then DELETE the old IS_A edge. Order is load-bearing
    (additive-before-destructive): the node is never momentarily un-typed."""
    graph.execute_query("""
        MATCH (n:Wiki {n:$name}), (newt:Wiki {n:$new})
        MERGE (n)-[:IS_A]->(newt)
    """, {"name": name, "new": NEW_TYPE})
    graph.execute_query("""
        MATCH (n:Wiki {n:$name})-[r:IS_A]->(:Wiki {n:$old})
        DELETE r
    """, {"name": name, "old": OLD_TYPE})


def post_counts(graph):
    """The two assertion counts after apply."""
    old_c = q(graph,
              "MATCH (n:Wiki)-[:IS_A]->(:Wiki {n:$old}) RETURN count(n) AS c",
              {"old": OLD_TYPE})[0]["c"]
    new_c = q(graph,
              "MATCH (n:Wiki)-[:IS_A]->(:Wiki {n:$new}) RETURN count(n) AS c",
              {"new": NEW_TYPE})[0]["c"]
    return old_c, new_c


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Retype the 304 weld category buckets IS_A Starsystem_Collection -> IS_A Collection_Category.")
    ap.add_argument("--apply", action="store_true",
                    help="EXECUTE the retype (export first, then MERGE new IS_A + DELETE old). "
                         "GUARDED: refuses unless the dry-run candidate count == 304 exactly. "
                         "Default is DRY-RUN.")
    ap.add_argument("--manifest", default=MANIFEST_PATH, help="manifest output path")
    args = ap.parse_args()

    ts = datetime.datetime.now().isoformat().replace(":", "_").replace(".", "_")
    graph = get_graph()

    arith = selection_arithmetic(graph)
    candidates = arith["candidates"]
    count = len(candidates)

    print("=" * 64)
    print("RETYPE BUCKETS — %s" % ("APPLY" if args.apply else "DRY-RUN"))
    print("=" * 64)
    print(f"  total IS_A {OLD_TYPE:<22}: {arith['total_is_a_old']}")
    print(f"  canon collections (end '_Collection') : {arith['canon_collections']}")
    print(f"  candidate buckets (the retype set)    : {count}")
    print(f"  arithmetic (canon + buckets == total) : {arith['arithmetic_ok']}")
    print("-" * 64)
    print("  first 10 candidate names:")
    for c in candidates[:10]:
        print(f"    {c}")
    if not candidates:
        print("    (none)")
    print("-" * 64)

    gate_ok = (count == EXPECTED_CANDIDATES)
    if gate_ok:
        print(f"  DRYRUN_COUNT_304_OK  (candidate count == {EXPECTED_CANDIDATES})")
    else:
        print(f"  GATE FAILED: candidate count == {count}, expected {EXPECTED_CANDIDATES}. "
              f"NOT applying. Reporting the discrepancy.")

    manifest = {
        "generated_at": ts,
        "apply": args.apply,
        "old_type": OLD_TYPE,
        "new_type": NEW_TYPE,
        "selection": {k: v for k, v in arith.items() if k != "candidates"},
        "candidate_count": count,
        "gate_ok": gate_ok,
        "candidates_sample": candidates[:20],
        "candidates": candidates,
    }

    if args.apply:
        if not gate_ok:
            print("\nREFUSING --apply: dry-run gate (count==304) did not pass. Touching NOTHING.")
            with open(args.manifest, "w") as fh:
                json.dump(manifest, fh, indent=2)
            print(f"MANIFEST written to {args.manifest}")
            sys.exit(2)

        # EXPORT FIRST (mandatory, before any mutation)
        export_path = export_candidates(graph, candidates, ts)
        size = os.path.getsize(export_path)
        manifest["export_path"] = export_path
        manifest["export_bytes"] = size
        if size <= 2:
            print(f"\nREFUSING --apply: export file {export_path} is trivial ({size} bytes). Touching NOTHING.")
            with open(args.manifest, "w") as fh:
                json.dump(manifest, fh, indent=2)
            sys.exit(3)
        print(f"  EXPORT_OK  path={export_path}  bytes={size}")

        # ensure the new class node is well-formed, then retype each candidate
        ensure_new_type_node(graph)
        failures = []
        retyped = 0
        for name in candidates:
            try:
                retype_one(graph, name)
                retyped += 1
            except Exception as e:
                failures.append(_fail(name, e))
        manifest["retyped"] = retyped
        manifest["failures"] = failures

        old_c, new_c = post_counts(graph)
        manifest["post_counts"] = {"is_a_starsystem_collection": old_c,
                                   "is_a_collection_category": new_c}
        print("-" * 64)
        print(f"  retyped nodes                : {retyped}")
        print(f"  failures                     : {len(failures)}")
        print(f"  POST: IS_A {OLD_TYPE:<22}: {old_c}  (MUST == 79)")
        print(f"  POST: IS_A {NEW_TYPE:<22}: {new_c}  (MUST >= 304)")
        postcounts_ok = (old_c == 79 and new_c >= 304)
        manifest["postcounts_ok"] = postcounts_ok
        if postcounts_ok:
            print(f"  APPLY_POSTCOUNTS_OK  (79 / {new_c})")
        else:
            print(f"  APPLY_POSTCOUNTS FAILED  (got {old_c} / {new_c}, want 79 / >=304)")

    with open(args.manifest, "w") as fh:
        json.dump(manifest, fh, indent=2)
    print("=" * 64)
    print(f"MANIFEST written to {args.manifest}")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"\nFATAL: {ex}")
        traceback.print_exc()
        sys.exit(1)
