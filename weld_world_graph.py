#!/usr/bin/env python3
"""
weld_world_graph.py — one-time, MERGE-only migration that WELDS the Starsystem world graph
into the canonical Seed_Ship hierarchy.

CANON (Isaac verbatim Mar-12, cohered 05-30):
  - Seed_Ship IS_A Starsystem (the root); all starsystems PART_OF Seed_Ship.
  - A Starsystem HAS its giint project (HAS_GIINT_PROJECT — already correct) AND HAS its own
    Starsystem_Collection (SIBLING, not parent).
  - The collection holds 4 category buckets: {SS}_Idea_Collections / _Design_Collections /
    _Architecture_Collections / _Task_Collections.
  - Task HCs live PART_OF the Task_Collections and maps_to the starlog graph (later leg).

VERSIONING FEAR IS LAW: MERGE-only, ZERO deletes, dry-run DEFAULT, full export before apply,
unmatchable items REPORTED never guessed. This script READS the graph in dry-run and writes
NOTHING; every write path lives strictly under `if args.apply:`.

The 6 weld legs (each computes a list of planned operations — NO writes in dry-run):
  a. seed_ship_isa          : MERGE (Seed_Ship)-[:IS_A]->(Starsystem)            [additive]
  b. starsystems_to_seedship: for each s IS_A Starsystem (excl Seed_Ship):
                              MERGE (s)-[:PART_OF]->(Seed_Ship) + (Seed_Ship)-[:HAS_PART]->(s)
  c. has_collection         : match an existing Starsystem_Collection by conservative name rule;
                              matched -> MERGE (s)-[:HAS_COLLECTION]->(c) + (c)-[:COLLECTION_OF]->(s);
                              unmatched -> would_create_collections (creation listed, not done in dry-run)
  d. category_buckets       : for each collection, ensure 4 buckets; existing -> MERGE HAS_PART+inverse;
                              missing -> would_create_buckets
  e. hc_weld                : for each HC NOT already PART_OF a *_Task_Collections, trace
                              (hc)-[:HAS_GIINT_PROJECT]->(p)<-[:HAS_GIINT_PROJECT]-(s IS_A Starsystem);
                              EXACTLY ONE s -> MERGE (hc)-[:PART_OF]->({s}_Task_Collections)+inverse;
                              zero/multiple -> unmatched_hcs (reason recorded). NEVER guess.
  f. maps_to_report         : REPORT-ONLY — Task-HCs lacking any MAPS_TO edge (later cross-link leg).

Relationship names are UPPER_SNAKE in neo4j: IS_A, PART_OF, HAS_PART, HAS_COLLECTION,
COLLECTION_OF, HAS_GIINT_PROJECT, MAPS_TO. The :Wiki label is the node label.

Env: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, HEAVEN_DATA_DIR (read by the carton connection).

Usage:
  python3 weld_world_graph.py            # DRY-RUN (default): compute + write manifest, touch NOTHING
  python3 weld_world_graph.py --apply    # EXECUTE (export first, then MERGE) — implemented, run deliberately
"""

import argparse
import datetime
import json
import os
import sys
import traceback


def _fail(item, exc):
    """Structured per-item failure record carrying the traceback for debugging (never aborts the run)."""
    return {"item": item, "error": repr(exc), "traceback": traceback.format_exc()}

# carton-mcp is the canonical source of the graph connection + add_concept primitive.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

MANIFEST_PATH = "/tmp/weld_manifest.json"

# The 4 category buckets a Starsystem_Collection holds (suffixes appended to the collection base).
BUCKET_SUFFIXES = (
    "_Idea_Collections",
    "_Design_Collections",
    "_Architecture_Collections",
    "_Task_Collections",
)


# ---------------------------------------------------------------------------
# connection
# ---------------------------------------------------------------------------
def get_graph():
    """The shared module-level neo4j connection (same surface as sync_manifest_to_carton)."""
    from carton_mcp.add_concept_tool import _get_module_connection
    graph = _get_module_connection()
    if graph is None:
        raise RuntimeError("no neo4j connection available (check NEO4J_* env vars)")
    return graph


def q(graph, cypher, params=None):
    """execute_query -> List[Dict]; per-item exception-safety is the caller's job."""
    return graph.execute_query(cypher, params or {})


# ---------------------------------------------------------------------------
# MATCHER v2 — BASE-EQUALITY collection<->starsystem matcher (REPORTS its decision, never guesses)
#
# A collection CANDIDATE must satisfy BOTH (asserted by the caller via the candidate set built in
# leg_has_collection): (a) IS_A Starsystem_Collection, AND (b) name ENDS WITH '_Collection'. This
# (b) gate is what excludes the 13 mistyped '*_Unnamed' nodes — they are IS_A Starsystem_Collection
# but their names end in '_Unnamed', so they are NEVER in the candidate set and can NEVER match.
#
# Match rule (case-normalized, EXACT base equality — no fuzzy substring):
#   collection BASE = collection name with optional 'Starsystem_' prefix stripped and the
#                     '_Collection' suffix stripped, casefolded.
#   starsystem SS_BASE variants = starsystem name with 'Starsystem_' prefix stripped, then:
#     - 'strip_prefix'        : the remainder as-is
#     - 'strip_path_Home_God' : remainder with a leading 'Home_God_' path prefix stripped
#     - 'strip_path_Tmp'      : remainder with a leading 'Tmp_' path prefix stripped
#     - 'home_god_special'    : when the remainder IS EXACTLY 'Home_God' (so the path-prefix strip
#                               would leave empty), also try base 'Home' — this is the documented
#                               Home_Collection <-> Starsystem_Home_God special case.
#   MATCH iff a collection BASE == a starsystem SS_BASE variant (first variant that hits wins;
#   the rule name of the variant that matched is recorded per pair in the manifest).
# ---------------------------------------------------------------------------
def collection_match_base(collection_name):
    """The BASE of a CANDIDATE collection: strip optional 'Starsystem_' prefix + '_Collection'
    suffix, casefolded. (Callers only pass names already gated to end with '_Collection'.)"""
    b = collection_name
    if b.startswith("Starsystem_"):
        b = b[len("Starsystem_"):]
    if b.endswith("_Collection"):
        b = b[: -len("_Collection")]
    return b.casefold()


def starsystem_base_variants(starsystem_name):
    """The (rule_name, ss_base) variants for a starsystem, in priority order, all casefolded.
    The first that equals a candidate collection's BASE is the match (and its rule is recorded)."""
    b = starsystem_name
    if b.startswith("Starsystem_"):
        b = b[len("Starsystem_"):]
    out = [("strip_prefix", b.casefold())]
    for pp in ("Home_God_", "Tmp_"):
        if b.startswith(pp):
            out.append(("strip_path_" + pp.rstrip("_"), b[len(pp):].casefold()))
    if b == "Home_God":
        # special case: 'Starsystem_Home_God' -> base 'Home' matches 'Starsystem_Home_Collection'
        out.append(("home_god_special", "home"))
    # de-dup preserving order (rule of first occurrence wins)
    seen, dedup = set(), []
    for rule, base in out:
        if base not in seen:
            seen.add(base)
            dedup.append((rule, base))
    return dedup


def build_candidate_index(existing_collections):
    """From the set of nodes IS_A Starsystem_Collection, keep ONLY the candidates (names ending in
    '_Collection') and index them by BASE. Returns (coll_by_base, candidates):
      coll_by_base: { base -> [collection_name, ...] }  (a base with >1 entry is COLLECTION-side ambiguous)
      candidates:   sorted list of candidate collection names (the '_Unnamed' nodes are excluded here).
    """
    candidates = sorted(c for c in existing_collections if c.endswith("_Collection"))
    coll_by_base = {}
    for c in candidates:
        coll_by_base.setdefault(collection_match_base(c), []).append(c)
    return coll_by_base, candidates


def match_collection(starsystem_name, coll_by_base):
    """Return (collection_name, rule) for the first starsystem base-variant that equals exactly ONE
    candidate collection's base; (None, None, reason) semantics via the tuple shape:
      - ('CollName', 'rule')          -> matched
      - (None, None)                  -> no candidate base matched
      - (None, 'AMBIGUOUS:<base>')    -> a base matched but >1 collection owns it (never match)
    NO guessing — pure base equality over the pre-built candidate index."""
    for rule, base in starsystem_base_variants(starsystem_name):
        if base in coll_by_base:
            owners = coll_by_base[base]
            if len(owners) == 1:
                return owners[0], rule
            # base matched multiple candidate collections -> ambiguous, do NOT match
            return None, "AMBIGUOUS:" + base
    return None, None


def default_collection_name(starsystem_name):
    """The name we WOULD create for an unmatched starsystem: {s.n}_Collection."""
    return f"{starsystem_name}_Collection"


def collection_base(collection_name):
    """The base of a collection name = strip a trailing '_Collection' if present, else the whole name.
    Buckets are '{base}{suffix}'."""
    if collection_name.endswith("_Collection"):
        return collection_name[: -len("_Collection")]
    return collection_name


# ---------------------------------------------------------------------------
# the legs — each returns plan structures; NONE write the graph
# ---------------------------------------------------------------------------
def leg_seed_ship_isa(graph):
    """a. plan MERGE (Seed_Ship)-[:IS_A]->(Starsystem) — additive, keep existing is_a edges."""
    planned = []
    try:
        already = q(graph,
                    "MATCH (:Wiki {n:'Seed_Ship'})-[:IS_A]->(:Wiki {n:'Starsystem'}) RETURN count(*) AS c")
        exists = already and already[0]["c"] > 0
        if not exists:
            planned.append({"src": "Seed_Ship", "rel": "IS_A", "dst": "Starsystem"})
    except Exception as e:
        return {"planned": planned, "failures": [_fail("seed_ship_isa", e)]}
    return {"planned": planned, "failures": []}


def leg_starsystems_to_seedship(graph, starsystems):
    """b. for every starsystem s (excl Seed_Ship): MERGE (s)-[:PART_OF]->(Seed_Ship) and inverse."""
    planned, failures = [], []
    for s in starsystems:
        if s == "Seed_Ship":
            continue
        try:
            planned.append({"src": s, "rel": "PART_OF", "dst": "Seed_Ship"})
            planned.append({"src": "Seed_Ship", "rel": "HAS_PART", "dst": s})
        except Exception as e:
            failures.append(_fail(s, e))
    return {"planned": planned, "failures": failures}


def leg_has_collection(graph, starsystems, existing_collections):
    """c. (MATCHER v2 + CREATE-ALL) match each starsystem to a CANDIDATE collection (IS_A
    Starsystem_Collection AND name ENDS WITH '_Collection') by BASE equality; matched -> plan
    HAS_COLLECTION + COLLECTION_OF; UNMATCHED -> would_create the {s}_Collection PLUS the
    (s)-[:HAS_COLLECTION]->(new) + inverse edges (Isaac's CREATE-ALL ruling: every starsystem
    gets a collection). INVARIANT: matched + would_create == 79 (every starsystem accounted once).

    The candidate set is built ONCE from existing_collections; the '*_Unnamed' nodes are excluded
    by the '_Collection'-suffix gate in build_candidate_index, so they appear in NO plan section."""
    planned, would_create, decisions, failures = [], [], [], []
    ambiguous = []
    coll_by_base, candidates = build_candidate_index(existing_collections)
    matched_colls = set()

    for s in starsystems:
        if s == "Seed_Ship":
            continue
        try:
            coll, rule = match_collection(s, coll_by_base)
            if coll:
                planned.append({"src": s, "rel": "HAS_COLLECTION", "dst": coll})
                planned.append({"src": coll, "rel": "COLLECTION_OF", "dst": s})
                decisions.append({"starsystem": s, "matched_collection": coll, "rule": rule})
                matched_colls.add(coll)
            else:
                # rule here is None (no base hit) OR 'AMBIGUOUS:<base>' (base hit >1 collection)
                if rule and rule.startswith("AMBIGUOUS:"):
                    base = rule.split(":", 1)[1]
                    ambiguous.append({"starsystem": s, "ambiguous_base": base,
                                      "candidates": sorted(coll_by_base.get(base, []))})
                # CREATE-ALL: unmatched (incl. ambiguous-no-match) starsystem gets a created collection
                cn = default_collection_name(s)
                would_create.append({
                    "collection": cn,
                    "for_starsystem": s,
                    "is_a": "Starsystem_Collection",
                    "part_of": s,
                    "tried_bases": [b for _, b in starsystem_base_variants(s)],
                })
                # CREATE-ALL also plans the s -> new-collection edges (what --apply would MERGE after
                # the creation runs). Endpoints are real once leg run_apply creates the collection first.
                planned.append({"src": s, "rel": "HAS_COLLECTION", "dst": cn})
                planned.append({"src": cn, "rel": "COLLECTION_OF", "dst": s})
                decisions.append({"starsystem": s, "matched_collection": None,
                                  "rule": ("ambiguous" if (rule and rule.startswith("AMBIGUOUS:"))
                                           else None),
                                  "would_create": cn})
        except Exception as e:
            failures.append(_fail(s, e))

    # every CANDIDATE collection (real, non-_Unnamed) that nothing matched -> report it
    unmatched_collections = [c for c in candidates if c not in matched_colls]

    return {"planned": planned, "would_create_collections": would_create,
            "decisions": decisions, "ambiguous": ambiguous,
            "unmatched_collections": unmatched_collections, "failures": failures}


def leg_category_buckets(graph, has_collection_result, existing_wiki_names):
    """d. for each collection (matched OR to-be-created), ensure the 4 buckets.
    Existing bucket -> plan MERGE (coll)-[:HAS_PART]->(bucket) + inverse; missing -> would_create."""
    planned, would_create, failures = [], [], []

    # collections in play = matched collections + the collections we'd create
    coll_names = set()
    for d in has_collection_result["decisions"]:
        if d.get("matched_collection"):
            coll_names.add(d["matched_collection"])
        elif d.get("would_create"):
            coll_names.add(d["would_create"])

    for coll in sorted(coll_names):
        try:
            base = collection_base(coll)
            for suffix in BUCKET_SUFFIXES:
                bucket = f"{base}{suffix}"
                if bucket in existing_wiki_names:
                    planned.append({"src": coll, "rel": "HAS_PART", "dst": bucket})
                    planned.append({"src": bucket, "rel": "PART_OF", "dst": coll})
                else:
                    would_create.append({
                        "bucket": bucket,
                        "for_collection": coll,
                        "is_a": "Starsystem_Collection",
                        "part_of": coll,
                    })
        except Exception as e:
            failures.append(_fail(coll, e))
    return {"planned": planned, "would_create_buckets": would_create, "failures": failures}


def leg_hc_weld(graph):
    """e. weld each HC (not already in a *_Task_Collections) to its starsystem's Task_Collections,
    ONLY when exactly one starsystem owns the HC's giint project. Else -> unmatched_hcs (reason).

    A matched (welded) HC is NEVER also an unmatched HC. If its target {s}_Task_Collections bucket
    does not yet exist, that is a NOTE on the welded item (recorded in `notes`, surfaced to the
    commander), NOT an unmatched entry — the bucket is planned for creation in leg_d
    (would_create_buckets). This keeps the arithmetic clean:
        welded_HCs + unmatched_HCs + already_placed == total_HCs."""
    planned, unmatched, notes, welded_hcs, failures = [], [], [], set(), []

    try:
        hcs = [r["n"] for r in q(graph, """
            MATCH (h:Wiki)-[:IS_A]->(:Wiki {n:'Hypercluster'})
            WHERE NOT EXISTS { (h)-[:PART_OF]->(tc:Wiki) WHERE tc.n ENDS WITH '_Task_Collections' }
            RETURN h.n AS n ORDER BY n
        """)]
    except Exception as e:
        return {"planned": planned, "unmatched_hcs": unmatched, "notes": notes,
                "welded_count": 0, "failures": [_fail("hc_weld:list", e)]}

    for h in hcs:
        try:
            projs = [r["p"] for r in q(graph,
                     "MATCH (h:Wiki {n:$h})-[:HAS_GIINT_PROJECT]->(p:Wiki) RETURN p.n AS p", {"h": h})]
            if not projs:
                unmatched.append({"hc": h, "reason": "no_project_edge"})
                continue

            owners = set()
            for p in projs:
                for r in q(graph, """
                    MATCH (s:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem'})
                    MATCH (s)-[:HAS_GIINT_PROJECT]->(:Wiki {n:$p})
                    RETURN s.n AS s
                """, {"p": p}):
                    owners.add(r["s"])

            if len(owners) == 1:
                s = next(iter(owners))
                tc = f"{s}_Task_Collections"
                planned.append({"src": h, "rel": "PART_OF", "dst": tc})
                planned.append({"src": tc, "rel": "HAS_PART", "dst": h})
                welded_hcs.add(h)
                # NOTE-only: target bucket may not exist yet (created by leg_d) — surfaced, not unmatched.
                tc_exists = bool(q(graph, "MATCH (t:Wiki {n:$t}) RETURN count(*) AS c", {"t": tc})[0]["c"])
                if not tc_exists:
                    notes.append({"hc": h, "note": "target_task_collections_missing",
                                  "target": tc, "owner": s,
                                  "detail": "HC welded; bucket planned for creation in leg_d"})
            elif len(owners) == 0:
                unmatched.append({"hc": h, "reason": "project_orphaned_no_owning_starsystem",
                                  "projects": projs})
            else:
                unmatched.append({"hc": h, "reason": "ambiguous_multiple_starsystems",
                                  "projects": projs, "candidates": sorted(owners)})
        except Exception as e:
            failures.append(_fail(h, e))

    return {"planned": planned, "unmatched_hcs": unmatched, "notes": notes,
            "welded_count": len(welded_hcs), "failures": failures}


def leg_maps_to_report(graph):
    """f. REPORT-ONLY: Task-HCs (HCs in a *_Task_Collections) lacking ANY MAPS_TO edge."""
    missing, failures = [], []
    try:
        rows = q(graph, """
            MATCH (h:Wiki)-[:IS_A]->(:Wiki {n:'Hypercluster'})
            WHERE EXISTS { (h)-[:PART_OF]->(tc:Wiki) WHERE tc.n ENDS WITH '_Task_Collections' }
            AND NOT EXISTS { (h)-[:MAPS_TO]->(:Wiki) }
            RETURN h.n AS n ORDER BY n
        """)
        missing = [r["n"] for r in rows]
    except Exception as e:
        failures.append(_fail("maps_to_report", e))
    return {"maps_to_missing": missing, "failures": failures}


# ---------------------------------------------------------------------------
# apply (IMPLEMENTED — exports first, then executes MERGE/creations). Run deliberately.
# ---------------------------------------------------------------------------
def export_touched_nodes(graph, all_planned_edges, ts):
    """Export every node that will gain an edge (names + current relationships) before any write."""
    names = set()
    for e in all_planned_edges:
        names.add(e["src"])
        names.add(e["dst"])
    export = {"exported_at": ts, "nodes": {}}
    for n in sorted(names):
        try:
            rels = q(graph, """
                MATCH (c:Wiki {n:$n})-[r]->(t:Wiki)
                RETURN type(r) AS rel, t.n AS target ORDER BY rel, target
            """, {"n": n})
            export["nodes"][n] = [{"rel": r["rel"], "target": r["target"]} for r in rels]
        except Exception as e:
            export["nodes"][n] = {"export_error": repr(e), "traceback": traceback.format_exc()}
    path = f"/tmp/weld_export_{ts}.json"
    with open(path, "w") as f:
        json.dump(export, f, indent=2)
    return path


def apply_edge(graph, src, rel, dst):
    """MERGE (src)-[:REL]->(dst). rel is a literal (validated UPPER_SNAKE); src/dst parameterized."""
    if not rel.replace("_", "").isalpha():
        raise ValueError(f"unsafe rel type: {rel!r}")
    graph.execute_query(
        f"MATCH (s:Wiki {{n:$s}}), (t:Wiki {{n:$t}}) MERGE (s)-[:{rel}]->(t)",
        {"s": src, "t": dst},
    )


def apply_creation(graph, concept_name, is_a, part_of, description):
    """Synchronous node creation via the sanctioned add_concept_tool_func path."""
    from carton_mcp.add_concept_tool import add_concept_tool_func
    rels = [
        {"relationship": "is_a", "related": [is_a]},
        {"relationship": "part_of", "related": [part_of]},
    ]
    add_concept_tool_func(
        concept_name=concept_name,
        description=description,
        relationships=rels,
        hide_youknow=True,
        shared_connection=graph,
        _skip_ontology_healing=True,
    )


def run_apply(graph, manifest, ts):
    """Execute the manifest. EXPORT FIRST, then creations, then edges. Per-item exception-safe."""
    failures = manifest.setdefault("failures", [])

    # collect every planned edge across legs (for the pre-write export)
    all_edges = []
    for leg in ("seed_ship_isa", "starsystems_to_seedship", "has_collection",
                "category_buckets", "hc_weld"):
        all_edges.extend(manifest["legs"].get(leg, {}).get("planned", []))

    export_path = export_touched_nodes(graph, all_edges, ts)
    manifest["export_path"] = export_path

    # 1) creations FIRST (so edge endpoints exist as real typed nodes)
    for entry in manifest.get("would_create_collections", []):
        try:
            apply_creation(graph, entry["collection"], entry["is_a"], entry["part_of"],
                           f"Starsystem_Collection for {entry['for_starsystem']}")
        except Exception as e:
            failures.append(_fail("create:" + entry["collection"], e))
    for entry in manifest.get("would_create_buckets", []):
        try:
            apply_creation(graph, entry["bucket"], entry["is_a"], entry["part_of"],
                           f"Category bucket for {entry['for_collection']}")
        except Exception as e:
            failures.append(_fail("create:" + entry["bucket"], e))

    # 2) edges
    for leg in ("seed_ship_isa", "starsystems_to_seedship", "has_collection",
                "category_buckets", "hc_weld"):
        for e in manifest["legs"].get(leg, {}).get("planned", []):
            try:
                apply_edge(graph, e["src"], e["rel"], e["dst"])
            except Exception as ex:
                failures.append(_fail(f"edge:{e['src']}-{e['rel']}->{e['dst']}", ex))
    return manifest


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def compute_manifest(graph, dry_run):
    """Compute all 6 legs (READ-ONLY) and assemble the manifest dict."""
    ts = datetime.datetime.now().isoformat()

    # shared reads
    starsystems = sorted(set(
        r["n"] for r in q(graph,
            "MATCH (s:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem'}) RETURN s.n AS n")))
    existing_collections = set(
        r["n"] for r in q(graph,
            "MATCH (c:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem_Collection'}) RETURN c.n AS n"))
    existing_wiki_names = set(
        r["n"] for r in q(graph, "MATCH (c:Wiki) RETURN c.n AS n"))

    a = leg_seed_ship_isa(graph)
    b = leg_starsystems_to_seedship(graph, starsystems)
    c = leg_has_collection(graph, starsystems, existing_collections)
    d = leg_category_buckets(graph, c, existing_wiki_names)
    e = leg_hc_weld(graph)
    f = leg_maps_to_report(graph)

    all_failures = (a["failures"] + b["failures"] + c["failures"] +
                    d["failures"] + e["failures"] + f["failures"])

    manifest = {
        "generated_at": ts,
        "dry_run": dry_run,
        "legs": {
            "seed_ship_isa": {"planned": a["planned"]},
            "starsystems_to_seedship": {"planned": b["planned"]},
            "has_collection": {"planned": c["planned"], "decisions": c["decisions"],
                               "ambiguous": c["ambiguous"],
                               "unmatched_collections": c["unmatched_collections"]},
            "category_buckets": {"planned": d["planned"]},
            "hc_weld": {"planned": e["planned"], "notes": e["notes"],
                        "welded_count": e["welded_count"]},
            "maps_to_report": {"report_only": True},
        },
        "would_create_collections": c["would_create_collections"],
        "would_create_buckets": d["would_create_buckets"],
        "unmatched_hcs": e["unmatched_hcs"],
        "maps_to_missing": f["maps_to_missing"],
        "failures": all_failures,
        "totals": {
            "starsystems_total": len(starsystems),
            "existing_collections": len(existing_collections),
            "matched_collections": len(c["decisions"]) - len(c["would_create_collections"]),
            "seed_ship_isa_planned": len(a["planned"]),
            "starsystems_to_seedship_planned": len(b["planned"]),
            "has_collection_planned": len(c["planned"]),
            "category_buckets_planned": len(d["planned"]),
            "hc_weld_planned": len(e["planned"]),
            "hc_weld_welded": e["welded_count"],
            "would_create_collections": len(c["would_create_collections"]),
            "would_create_buckets": len(d["would_create_buckets"]),
            "ambiguous_starsystems": len(c["ambiguous"]),
            "unmatched_collections": len(c["unmatched_collections"]),
            "unmatched_hcs": len(e["unmatched_hcs"]),
            "maps_to_missing": len(f["maps_to_missing"]),
            "failures": len(all_failures),
            # CREATE-ALL invariant: every starsystem accounted for exactly once
            "matched_plus_create_collections": (
                (len(c["decisions"]) - len(c["would_create_collections"]))
                + len(c["would_create_collections"])),
        },
    }
    return manifest, ts


def print_summary(manifest):
    t = manifest["totals"]
    print("=" * 64)
    print("WELD WORLD GRAPH — %s" % ("DRY-RUN" if manifest["dry_run"] else "APPLY"))
    print("=" * 64)
    print(f"  starsystems_total            : {t['starsystems_total']}")
    print(f"  existing_collections         : {t['existing_collections']}")
    print(f"  matched_collections          : {t['matched_collections']}")
    print(f"  a. seed_ship_isa     planned : {t['seed_ship_isa_planned']}")
    print(f"  b. starsystems->seed planned : {t['starsystems_to_seedship_planned']}")
    print(f"  c. has_collection    planned : {t['has_collection_planned']}")
    print(f"  d. category_buckets  planned : {t['category_buckets_planned']}")
    print(f"  e. hc_weld           planned : {t['hc_weld_planned']}")
    print(f"  would_create_collections     : {t['would_create_collections']}")
    print(f"  would_create_buckets         : {t['would_create_buckets']}")
    print(f"  ambiguous_starsystems        : {t['ambiguous_starsystems']}")
    print(f"  unmatched_collections        : {t['unmatched_collections']}")
    print(f"  unmatched_hcs                : {t['unmatched_hcs']}")
    print(f"  maps_to_missing              : {t['maps_to_missing']}")
    print(f"  failures                     : {t['failures']}")
    print(f"  matched + would_create_colls : {t['matched_plus_create_collections']}"
          f"  (must == {t['starsystems_total']})")
    print("-" * 64)

    def show(label, items, fmt):
        print(f"  first 5 {label}:")
        for it in items[:5]:
            print("    " + fmt(it))
        if not items:
            print("    (none)")

    show("b edges", manifest["legs"]["starsystems_to_seedship"]["planned"],
         lambda e: f"{e['src']} -{e['rel']}-> {e['dst']}")
    show("would_create_collections", manifest["would_create_collections"],
         lambda x: f"{x['collection']}  (for {x['for_starsystem']})")
    show("would_create_buckets", manifest["would_create_buckets"],
         lambda x: f"{x['bucket']}  (for {x['for_collection']})")
    show("unmatched_hcs", manifest["unmatched_hcs"],
         lambda x: f"{x['hc']}  reason={x['reason']}")
    show("maps_to_missing", manifest["maps_to_missing"], lambda x: x)
    print("=" * 64)


def main():
    ap = argparse.ArgumentParser(description="Weld the Starsystem world graph into Seed_Ship (MERGE-only).")
    ap.add_argument("--apply", action="store_true",
                    help="EXECUTE the weld (export first, then MERGE). Default is DRY-RUN.")
    ap.add_argument("--manifest", default=MANIFEST_PATH, help="manifest output path")
    args = ap.parse_args()

    dry_run = not args.apply
    graph = get_graph()

    manifest, ts = compute_manifest(graph, dry_run)

    if args.apply:
        manifest = run_apply(graph, manifest, ts)
        # re-run the leg probes after, print before/after counts
        manifest["post_apply_counts"] = {
            "starsystems_touching_seedship": q(graph, """
                MATCH (s:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem'})
                WHERE (s)-[:PART_OF]->(:Wiki {n:'Seed_Ship'})
                RETURN count(DISTINCT s) AS c""")[0]["c"],
            "has_collection_edges": q(graph,
                "MATCH ()-[r:HAS_COLLECTION]->() RETURN count(r) AS c")[0]["c"],
            "hcs_in_task_collections": q(graph, """
                MATCH (h:Wiki)-[:IS_A]->(:Wiki {n:'Hypercluster'})
                WHERE EXISTS { (h)-[:PART_OF]->(tc:Wiki) WHERE tc.n ENDS WITH '_Task_Collections' }
                RETURN count(DISTINCT h) AS c""")[0]["c"],
        }

    with open(args.manifest, "w") as fh:
        json.dump(manifest, fh, indent=2)

    print_summary(manifest)
    print(f"\nMANIFEST written to {args.manifest}")
    if args.apply:
        print(f"EXPORT written to {manifest.get('export_path')}")
        print("POST-APPLY counts:", json.dumps(manifest.get("post_apply_counts", {})))


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        import traceback
        print(f"\nFATAL: {ex}")
        traceback.print_exc()
        sys.exit(1)
