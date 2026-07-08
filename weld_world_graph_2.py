#!/usr/bin/env python3
"""
weld_world_graph_2.py — WELD-2: maps_to join + HAS_STARLOG inverses + orphan reattach.

Sibling of weld_world_graph.py (weld-1). Same discipline: MERGE-only, ZERO deletes, dry-run
DEFAULT, full export before apply, unmatchable items REPORTED never guessed. This script READS
the graph in dry-run and writes NOTHING; every write path lives strictly under `if args.apply:`.

CANON (the-starsystem-world-graph-geometry): a Starsystem HAS_STARLOG its Starlog_Project(s)
(the inverse of the bottom-up Starlog_Project PART_OF Starsystem the starlog writer creates);
a Task HC MAPS_TO the starlog graph of its starsystem; orphans (Starlog_Projects / HCs / Giint_*
nodes with no path to a typed starsystem) reattach by join-by-name-core, and unmatchables go to a
CLASSIFIED CULL REPORT for Isaac — NEVER deleted (this tool has no DELETE path at all).

The 5 weld-2 legs (each computes a plan list — NO writes in dry-run):
  A. has_starlog_inverses : for every (sp:Starlog_Project)-[:PART_OF]->(ss IS_A Starsystem),
                            MERGE (ss)-[:HAS_STARLOG]->(sp).
  B. maps_to              : for each SEATED Task HC, derive its starsystem
                            (hc -PART_OF-> *_Task_Collections bucket -PART_OF-> collection
                             <-HAS_COLLECTION- starsystem), then MERGE
                            (hc)-[:MAPS_TO]->(sp:Starlog_Project) for EACH Starlog_Project of that
                            starsystem. GRAIN = project (COARSER, defensible) — session-grain is
                            impossible/ambiguous live (sessions PART_OF projects are sparse: most
                            seated HCs' starsystems have 0 attached Starlog_Sessions). Multi-project
                            fan-out is REPORTED. No project for the starsystem -> cull row.
  C. starlog_orphan_reattach : for each Starlog_Project NOT PART_OF a typed starsystem, name-core
                            match its existing Starsystem_* parent (or its own name-core) against the
                            typed starsystems; match -> MERGE (sp)-[:PART_OF]->(ss) + the LEG-A
                            inverse (ss)-[:HAS_STARLOG]->(sp). No match -> cull row.
  D. hc_orphan_reattach   : for each orphan HC (not seated in a *_Task_Collections), attempt:
                            (i) HC -[:HAS_GIINT_PROJECT]-> gp <-[:HAS_GIINT_PROJECT]- (ss typed)
                                -> MERGE (hc)-[:PART_OF]->({ss}_Task_Collections) + inverse;
                            else (ii) HC name-core ↔ typed-ss name-core -> same MERGE.
                            No match -> cull row.
  E. giint_orphan_reattach : for each TOP-of-orphan-chain Giint_*/GIINT_* node (the highest ancestor
                            that is itself orphaned — never mid-chain), attempt:
                            (i) walk its PART_OF giint chain up to a Giint_Project, then Giint_Project
                                ↔ typed-ss via has_giint_project inverse OR name-core match;
                            else (ii) the node's own name-core ↔ typed-ss name-core.
                            Match -> MERGE (top)-[:PART_OF]->(ss). No match -> cull row (grouped by
                            project-name-core so the report is ~groups, not thousands of rows).

KNOWN WELD-1 DEFECT FIXED HERE: weld-1's apply_edge MATCH-MERGE silently no-ops when an endpoint
node does not exist. In --apply this version COUNTS the matched-rows of every MERGE and REPORTS
any no-op (matched==0) per leg, so a silent miss can never masquerade as success.

Relationship names are UPPER_SNAKE in neo4j: IS_A, PART_OF, HAS_PART, HAS_COLLECTION, COLLECTION_OF,
HAS_GIINT_PROJECT, HAS_STARLOG, MAPS_TO. The :Wiki label is the node label.

Env: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, HEAVEN_DATA_DIR (read by the carton connection).

Usage:
  python3 weld_world_graph_2.py            # DRY-RUN (default): compute + write manifest+cull, touch NOTHING
  python3 weld_world_graph_2.py --apply    # EXECUTE (export first, then MERGE) — run deliberately
"""

import argparse
import datetime
import json
import os
import re
import sys
import traceback


MANIFEST_PATH = "/tmp/weld2_dryrun_manifest.md"
MANIFEST_JSON_PATH = "/tmp/weld2_dryrun_manifest.json"
CULL_PATH = "/tmp/weld2_cull_report.md"

# Names matching this are transient test nodes from a CONCURRENT agent (starlog-writer-canon E2E);
# excluded from every candidate set so they never enter the dry-run plan or cull report.
EXCLUDE_NAME_RE = re.compile(r"canon_writer_test", re.IGNORECASE)


def _excluded(name):
    return bool(name) and bool(EXCLUDE_NAME_RE.search(name))


def _is_unnamed(name):
    """A '*_Unnamed' node is mistyped/garbage residue — NEVER a reattach endpoint. Orphan legs route
    these to the cull report instead of planning an edge, so the no-unnamed-edge invariant holds."""
    return bool(name) and name.endswith("_Unnamed")


# Welds REJECTED by commander review of the dry-run manifest (2026-06-11). An edge whose
# (src, rel, dst) appears here is NEVER planned/applied; it is routed to the cull report under the
# recorded reason. Data-driven: add a tuple+reason here to reject any future weld on review.
REJECTED_WELDS = {
    ("Giint_Mcp", "PART_OF", "Starsystem_Home_God_Starsystem_Mcp"):
        "generic-core/contentless-stub — rejected by commander review",
}


def _rejected_reason(src, rel, dst):
    return REJECTED_WELDS.get((src, rel, dst))


def _fail(item, exc):
    """Structured per-item failure record carrying the traceback (never aborts the run)."""
    return {"item": item, "error": repr(exc), "traceback": traceback.format_exc()}


# carton-mcp is the canonical source of the graph connection.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# ---------------------------------------------------------------------------
# connection
# ---------------------------------------------------------------------------
def get_graph():
    """The shared module-level neo4j connection (same surface as weld-1)."""
    from carton_mcp.add_concept_tool import _get_module_connection
    graph = _get_module_connection()
    if graph is None:
        raise RuntimeError("no neo4j connection available (check NEO4J_* env vars)")
    return graph


def q(graph, cypher, params=None):
    """execute_query -> List[Dict]; per-item exception-safety is the caller's job."""
    return graph.execute_query(cypher, params or {})


# ---------------------------------------------------------------------------
# name-core matcher (mirrors weld-1 matcher v2): strip known prefixes, casefold,
# collapse underscores. Used to join an orphan to a typed starsystem by base equality.
# ---------------------------------------------------------------------------
_SS_PREFIXES = ("Starsystem_", "Home_God_", "Tmp_")
_GIINT_PREFIXES = ("Giint_Project_", "GIINT_Project_", "Giint_", "GIINT_")
_HC_PREFIXES = ("Hypercluster_",)
_SP_PREFIXES = ("Starlog_Project_",)


def name_core(name, prefixes):
    """Lowercased, underscore-collapsed base after stripping each prefix in `prefixes` once,
    repeatedly (so 'Starsystem_Home_God_X' -> strip Starsystem_, then Home_God_ -> 'x')."""
    b = name or ""
    changed = True
    while changed:
        changed = False
        for p in prefixes:
            if b.startswith(p):
                b = b[len(p):]
                changed = True
    b = b.casefold()
    b = re.sub(r"_+", "_", b).strip("_")
    return b


def build_ss_core_index(typed_starsystems):
    """{ core -> [starsystem_name, ...] } over the typed starsystems, trying both the SS prefix set
    and the path-stripped variants. A core owned by >1 starsystem is AMBIGUOUS (never matched)."""
    idx = {}
    for s in typed_starsystems:
        if s == "Seed_Ship":
            continue
        cores = set()
        cores.add(name_core(s, ("Starsystem_",)))
        cores.add(name_core(s, _SS_PREFIXES))
        for c in cores:
            if c:
                idx.setdefault(c, set()).add(s)
    # collapse sets to sorted lists
    return {c: sorted(v) for c, v in idx.items()}


def match_ss_by_core(candidate_core, ss_core_index):
    """Return (ss_name, 'matched') | (None, 'no_core_match') | (None, 'AMBIGUOUS:<core>')."""
    if not candidate_core:
        return None, "empty_core"
    owners = ss_core_index.get(candidate_core)
    if not owners:
        return None, "no_core_match"
    if len(owners) == 1:
        return owners[0], "matched"
    return None, "AMBIGUOUS:" + candidate_core


# ---------------------------------------------------------------------------
# shared reads
# ---------------------------------------------------------------------------
def read_world(graph):
    """All the shared sets the legs need. Excludes *canon_writer_test* names everywhere."""
    typed_ss = sorted(
        r["n"] for r in q(graph,
            "MATCH (s:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem'}) RETURN s.n AS n")
        if not _excluded(r["n"]))
    return {"typed_ss": typed_ss, "typed_ss_set": set(typed_ss)}


# ---------------------------------------------------------------------------
# LEG A — HAS_STARLOG inverses
# ---------------------------------------------------------------------------
def leg_a_has_starlog(graph):
    planned, failures = [], []
    try:
        rows = q(graph, """
            MATCH (sp:Wiki)-[:IS_A]->(:Wiki {n:'Starlog_Project'})
            MATCH (sp)-[:PART_OF]->(ss:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem'})
            RETURN DISTINCT sp.n AS sp, ss.n AS ss ORDER BY ss, sp
        """)
        for r in rows:
            if _excluded(r["sp"]) or _excluded(r["ss"]):
                continue
            planned.append({"src": r["ss"], "rel": "HAS_STARLOG", "dst": r["sp"]})
    except Exception as e:
        failures.append(_fail("leg_a", e))
    return {"planned": planned, "failures": failures}


# ---------------------------------------------------------------------------
# LEG B — maps_to (project grain)
# ---------------------------------------------------------------------------
def leg_b_maps_to(graph):
    planned, fanout, cull, failures = [], [], [], []
    try:
        seated = [r["n"] for r in q(graph, """
            MATCH (h:Wiki)-[:IS_A]->(:Wiki {n:'Hypercluster'})
            WHERE EXISTS { (h)-[:PART_OF]->(tc:Wiki) WHERE tc.n ENDS WITH '_Task_Collections' }
            RETURN h.n AS n ORDER BY n
        """) if not _excluded(r["n"])]
    except Exception as e:
        return {"planned": planned, "fanout": fanout, "cull": cull,
                "failures": [_fail("leg_b:list", e)]}

    for h in seated:
        try:
            # derive starsystem: HC -> bucket -PART_OF-> collection <-HAS_COLLECTION- ss
            ss_rows = q(graph, """
                MATCH (h:Wiki {n:$h})-[:PART_OF]->(tc:Wiki) WHERE tc.n ENDS WITH '_Task_Collections'
                MATCH (tc)-[:PART_OF]->(coll:Wiki)<-[:HAS_COLLECTION]-(ss:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem'})
                RETURN DISTINCT ss.n AS ss
            """, {"h": h})
            owners = sorted({r["ss"] for r in ss_rows if not _excluded(r["ss"])})
            if not owners:
                cull.append({"category": "maps_to_no_starsystem", "hc": h,
                             "why": "seated HC's _Task_Collections bucket has no HAS_COLLECTION starsystem"})
                continue
            if len(owners) > 1:
                cull.append({"category": "maps_to_ambiguous_starsystem", "hc": h,
                             "candidates": owners,
                             "why": "bucket resolves to >1 typed starsystem — coarser edge not safe"})
                continue
            ss = owners[0]
            projs = sorted({r["sp"] for r in q(graph, """
                MATCH (sp:Wiki)-[:PART_OF]->(ss:Wiki {n:$ss})
                WHERE sp.n STARTS WITH 'Starlog_Project'
                MATCH (sp)-[:IS_A]->(:Wiki {n:'Starlog_Project'})
                RETURN DISTINCT sp.n AS sp
            """, {"ss": ss}) if not _excluded(r["sp"])})
            if not projs:
                cull.append({"category": "maps_to_no_project", "hc": h, "starsystem": ss,
                             "why": "derived starsystem has no Starlog_Project to map to"})
                continue
            for sp in projs:
                planned.append({"src": h, "rel": "MAPS_TO", "dst": sp})
            if len(projs) > 1:
                fanout.append({"hc": h, "starsystem": ss, "project_count": len(projs),
                               "projects": projs})
        except Exception as e:
            failures.append(_fail(h, e))
    return {"planned": planned, "fanout": fanout, "cull": cull, "failures": failures}


# ---------------------------------------------------------------------------
# LEG C — starlog orphan reattach
# ---------------------------------------------------------------------------
def leg_c_starlog_orphans(graph, ss_core_index):
    planned, decisions, cull, failures = [], [], [], []
    try:
        rows = q(graph, """
            MATCH (p:Wiki)-[:IS_A]->(:Wiki {n:'Starlog_Project'})
            WHERE NOT EXISTS { (p)-[:PART_OF]->(s:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem'}) }
            RETURN p.n AS p, [(p)-[:PART_OF]->(x:Wiki) | x.n] AS parents ORDER BY p
        """)
    except Exception as e:
        return {"planned": planned, "decisions": decisions, "cull": cull,
                "failures": [_fail("leg_c:list", e)]}

    for r in rows:
        p = r["p"]
        if _excluded(p):
            continue
        if _is_unnamed(p):
            cull.append({"category": "starlog_orphan_unnamed_node", "project": p,
                         "parents": [], "tried": [],
                         "why": "node name ends _Unnamed (garbage residue) — never a reattach endpoint"})
            continue
        parents = [x for x in (r["parents"] or []) if not _excluded(x)]
        try:
            # candidate cores: each Starsystem_*-named parent's core, then the project's own core
            cand_cores = []
            for par in parents:
                if par.startswith("Starsystem_"):
                    cand_cores.append((par, name_core(par, ("Starsystem_",))))
                    cand_cores.append((par, name_core(par, _SS_PREFIXES)))
            cand_cores.append((p, name_core(p, _SP_PREFIXES)))

            matched_ss, via, reason = None, None, None
            tried = []
            for src, core in cand_cores:
                tried.append({"from": src, "core": core})
                ss, res = match_ss_by_core(core, ss_core_index)
                if ss:
                    matched_ss, via = ss, src
                    break
                if res.startswith("AMBIGUOUS:"):
                    reason = res
            if matched_ss:
                planned.append({"src": p, "rel": "PART_OF", "dst": matched_ss})
                planned.append({"src": matched_ss, "rel": "HAS_STARLOG", "dst": p})
                decisions.append({"project": p, "matched_starsystem": matched_ss, "via": via})
            else:
                cull.append({"category": "starlog_orphan_unmatched", "project": p,
                             "parents": parents, "tried": tried,
                             "why": reason or "no name-core match to any typed starsystem"})
        except Exception as e:
            failures.append(_fail(p, e))
    return {"planned": planned, "decisions": decisions, "cull": cull, "failures": failures}


# ---------------------------------------------------------------------------
# LEG D — HC orphan reattach
# ---------------------------------------------------------------------------
def leg_d_hc_orphans(graph, ss_core_index):
    planned, decisions, cull, failures = [], [], [], []
    try:
        orphans = [r["n"] for r in q(graph, """
            MATCH (h:Wiki)-[:IS_A]->(:Wiki {n:'Hypercluster'})
            WHERE NOT EXISTS { (h)-[:PART_OF]->(tc:Wiki) WHERE tc.n ENDS WITH '_Task_Collections' }
            RETURN h.n AS n ORDER BY n
        """) if not _excluded(r["n"])]
    except Exception as e:
        return {"planned": planned, "decisions": decisions, "cull": cull,
                "failures": [_fail("leg_d:list", e)]}

    for h in orphans:
        try:
            if _is_unnamed(h):
                cull.append({"category": "hc_orphan_unnamed_node", "hc": h,
                             "why": "node name ends _Unnamed (garbage residue) — never a reattach endpoint"})
                continue
            matched_ss, via = None, None
            # route (i): HC -> giint project <- typed ss via has_giint_project
            gp_owners = q(graph, """
                MATCH (h:Wiki {n:$h})-[:HAS_GIINT_PROJECT]->(gp:Wiki)
                MATCH (ss:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem'})
                MATCH (ss)-[:HAS_GIINT_PROJECT]->(gp)
                RETURN DISTINCT ss.n AS ss
            """, {"h": h})
            owners = sorted({r["ss"] for r in gp_owners if not _excluded(r["ss"])})
            if len(owners) == 1:
                matched_ss, via = owners[0], "giint_project_inverse"
            elif len(owners) > 1:
                cull.append({"category": "hc_orphan_ambiguous_giint", "hc": h,
                             "candidates": owners, "why": "giint project owned by >1 typed starsystem"})
                continue
            # route (ii): HC name-core ↔ typed-ss name-core
            if not matched_ss:
                core = name_core(h, _HC_PREFIXES)
                ss, res = match_ss_by_core(core, ss_core_index)
                if ss:
                    matched_ss, via = ss, "hc_name_core"
                elif res.startswith("AMBIGUOUS:"):
                    cull.append({"category": "hc_orphan_ambiguous_namecore", "hc": h,
                                 "core": core, "why": res})
                    continue
            if matched_ss:
                tc = f"{matched_ss}_Task_Collections"
                planned.append({"src": h, "rel": "PART_OF", "dst": tc})
                planned.append({"src": tc, "rel": "HAS_PART", "dst": h})
                # NOTE: target bucket may not exist; counted as a no-op at apply-time and reported.
                decisions.append({"hc": h, "matched_starsystem": matched_ss,
                                  "target_bucket": tc, "via": via})
            else:
                cull.append({"category": "hc_orphan_unmatched", "hc": h,
                             "hc_core": name_core(h, _HC_PREFIXES),
                             "why": "no giint-inverse owner and no name-core match"})
        except Exception as e:
            failures.append(_fail(h, e))
    return {"planned": planned, "decisions": decisions, "cull": cull, "failures": failures}


# ---------------------------------------------------------------------------
# LEG E — giint orphan reattach (top-of-chain only)
# ---------------------------------------------------------------------------
def leg_e_giint_orphans(graph, ss_core_index):
    planned, decisions, cull, failures = [], [], [], []
    # TOP-of-orphan-chain: orphaned Giint_*/GIINT_* with NO orphaned giint PART_OF-parent above it.
    try:
        tops = [r["n"] for r in q(graph, """
            MATCH (gn:Wiki) WHERE (gn.n STARTS WITH 'Giint_' OR gn.n STARTS WITH 'GIINT_')
              AND NOT EXISTS { (gn)-[:PART_OF*1..6]->(s:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem'}) }
              AND NOT EXISTS {
                (gn)-[:PART_OF]->(par:Wiki)
                WHERE (par.n STARTS WITH 'Giint_' OR par.n STARTS WITH 'GIINT_')
                  AND NOT EXISTS { (par)-[:PART_OF*1..6]->(s2:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem'}) }
              }
            RETURN gn.n AS n ORDER BY n
        """) if not _excluded(r["n"])]
    except Exception as e:
        return {"planned": planned, "decisions": decisions, "cull_groups": {},
                "failures": [_fail("leg_e:list", e)]}

    cull_groups = {}  # project-name-core -> {count, sample:[...]}
    for gn in tops:
        try:
            if _is_unnamed(gn):
                g = cull_groups.setdefault("__unnamed_garbage__", {"count": 0, "sample": []})
                g["count"] += 1
                if len(g["sample"]) < 5:
                    g["sample"].append(gn)
                continue
            matched_ss, via = None, None
            # route (i): walk up to a Giint_Project, then giint-inverse OR project name-core
            gproj_rows = q(graph, """
                MATCH (gn:Wiki {n:$gn})
                OPTIONAL MATCH (gn)-[:PART_OF*0..6]->(gp:Wiki)-[:IS_A]->(:Wiki {n:'Giint_Project'})
                RETURN DISTINCT gp.n AS gp
            """, {"gn": gn})
            gprojs = sorted({r["gp"] for r in gproj_rows if r["gp"] and not _excluded(r["gp"])})
            for gp in gprojs:
                inv = q(graph, """
                    MATCH (ss:Wiki)-[:IS_A]->(:Wiki {n:'Starsystem'})
                    MATCH (ss)-[:HAS_GIINT_PROJECT]->(:Wiki {n:$gp})
                    RETURN DISTINCT ss.n AS ss
                """, {"gp": gp})
                owners = sorted({r["ss"] for r in inv if not _excluded(r["ss"])})
                if len(owners) == 1:
                    matched_ss, via = owners[0], "giint_project_inverse"
                    break
                core = name_core(gp, _GIINT_PREFIXES)
                ss, res = match_ss_by_core(core, ss_core_index)
                if ss:
                    matched_ss, via = ss, "giint_project_name_core"
                    break
            # route (ii): the node's own name-core
            if not matched_ss:
                core = name_core(gn, _GIINT_PREFIXES)
                ss, res = match_ss_by_core(core, ss_core_index)
                if ss:
                    matched_ss, via = ss, "self_name_core"

            if matched_ss and _rejected_reason(gn, "PART_OF", matched_ss):
                reason = _rejected_reason(gn, "PART_OF", matched_ss)
                g = cull_groups.setdefault("__rejected_by_commander__", {"count": 0, "sample": [],
                                                                          "reason": reason})
                g["count"] += 1
                if len(g["sample"]) < 5:
                    g["sample"].append(f"{gn} -X-> {matched_ss} ({reason})")
            elif matched_ss:
                planned.append({"src": gn, "rel": "PART_OF", "dst": matched_ss})
                decisions.append({"giint_top": gn, "matched_starsystem": matched_ss, "via": via})
            else:
                grp = name_core(gprojs[0], _GIINT_PREFIXES) if gprojs else name_core(gn, _GIINT_PREFIXES)
                grp = grp or "(none)"
                g = cull_groups.setdefault(grp, {"count": 0, "sample": []})
                g["count"] += 1
                if len(g["sample"]) < 5:
                    g["sample"].append(gn)
        except Exception as e:
            failures.append(_fail(gn, e))
    return {"planned": planned, "decisions": decisions, "cull_groups": cull_groups,
            "failures": failures, "tops_total": len(tops)}


# ---------------------------------------------------------------------------
# apply (export FIRST, then MERGE; counts matched-rows so a no-op cannot hide)
# ---------------------------------------------------------------------------
def export_touched_nodes(graph, all_planned_edges, ts):
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
    path = f"/tmp/weld2_export_{ts}.json"
    with open(path, "w") as f:
        json.dump(export, f, indent=2)
    return path


def apply_edge_counted(graph, src, rel, dst):
    """MERGE (src)-[:REL]->(dst) only when BOTH endpoints exist; RETURN how many endpoints matched.
    rel is a literal (validated UPPER_SNAKE); src/dst parameterized. Returns matched_endpoints (0,1,2);
    2 == both nodes found and the MERGE ran; <2 == a silent no-op weld-1 would have hidden."""
    if not rel.replace("_", "").isalpha():
        raise ValueError(f"unsafe rel type: {rel!r}")
    rows = graph.execute_query(
        f"""
        OPTIONAL MATCH (s:Wiki {{n:$s}})
        OPTIONAL MATCH (t:Wiki {{n:$t}})
        WITH s, t, (CASE WHEN s IS NULL THEN 0 ELSE 1 END) + (CASE WHEN t IS NULL THEN 0 ELSE 1 END) AS matched
        FOREACH (_ IN CASE WHEN s IS NOT NULL AND t IS NOT NULL THEN [1] ELSE [] END |
                 MERGE (s)-[:{rel}]->(t))
        RETURN matched
        """,
        {"s": src, "t": dst},
    )
    return rows[0]["matched"] if rows else 0


def run_apply(graph, manifest, all_edges, ts):
    failures = manifest.setdefault("apply_failures", [])
    noops = []
    export_path = export_touched_nodes(graph, all_edges, ts)
    manifest["export_path"] = export_path
    applied, skipped = 0, 0
    for e in all_edges:
        try:
            matched = apply_edge_counted(graph, e["src"], e["rel"], e["dst"])
            if matched == 2:
                applied += 1
            else:
                skipped += 1
                noops.append({"edge": f"{e['src']}-{e['rel']}->{e['dst']}",
                              "matched_endpoints": matched})
        except Exception as ex:
            failures.append(_fail(f"edge:{e['src']}-{e['rel']}->{e['dst']}", ex))
    manifest["apply_applied"] = applied
    manifest["apply_noops"] = noops
    manifest["apply_noop_count"] = skipped
    return manifest


def report_nameonly_starlog_projects(graph):
    """ADDENDUM (commander review 2026-06-11): Starlog_Project_*-NAMED nodes that are NOT IS_A
    Starlog_Project. The spec census counted by name-prefix while the legs select by IS_A — canon
    says a name prefix is convention, not type, which explains the LEG_C 170-vs-3 divergence.
    REPORT ONLY: typing-by-prefix is a RULING for Isaac; this tool neither types nor welds them."""
    rows = q(graph, """
        MATCH (p:Wiki) WHERE p.n STARTS WITH 'Starlog_Project_'
          AND NOT EXISTS { (p)-[:IS_A]->(:Wiki {n:'Starlog_Project'}) }
        RETURN p.n AS n ORDER BY n
    """)
    names = [r["n"] for r in rows if not _excluded(r["n"])]
    total_prefix = q(graph,
        "MATCH (p:Wiki) WHERE p.n STARTS WITH 'Starlog_Project_' RETURN count(p) AS c")[0]["c"]
    total_isa = q(graph, """
        MATCH (p:Wiki)-[:IS_A]->(:Wiki {n:'Starlog_Project'})
        WHERE p.n STARTS WITH 'Starlog_Project_' RETURN count(DISTINCT p) AS c""")[0]["c"]
    return {"count": len(names), "total_by_prefix": total_prefix,
            "total_by_isa": total_isa, "sample": names[:5]}


# ---------------------------------------------------------------------------
# compute + report
# ---------------------------------------------------------------------------
def compute(graph, dry_run):
    ts = datetime.datetime.now().isoformat()
    world = read_world(graph)
    ss_core_index = build_ss_core_index(world["typed_ss"])

    a = leg_a_has_starlog(graph)
    b = leg_b_maps_to(graph)
    c = leg_c_starlog_orphans(graph, ss_core_index)
    d = leg_d_hc_orphans(graph, ss_core_index)
    e = leg_e_giint_orphans(graph, ss_core_index)

    all_failures = (a["failures"] + b["failures"] + c["failures"] +
                    d["failures"] + e["failures"])

    try:
        nameonly = report_nameonly_starlog_projects(graph)
    except Exception as ex:
        nameonly = {"count": -1, "total_by_prefix": -1, "total_by_isa": -1, "sample": []}
        all_failures.append(_fail("nameonly_starlog_report", ex))

    manifest = {
        "generated_at": ts,
        "dry_run": dry_run,
        "nameonly_starlog_projects": nameonly,
        "world": {"typed_starsystems": len(world["typed_ss"])},
        "legs": {
            "A_has_starlog": {"planned": a["planned"]},
            "B_maps_to": {"planned": b["planned"], "fanout": b["fanout"], "cull": b["cull"]},
            "C_starlog_orphans": {"planned": c["planned"], "decisions": c["decisions"],
                                  "cull": c["cull"]},
            "D_hc_orphans": {"planned": d["planned"], "decisions": d["decisions"],
                             "cull": d["cull"]},
            "E_giint_orphans": {"planned": e["planned"], "decisions": e["decisions"],
                                "cull_groups": e["cull_groups"], "tops_total": e["tops_total"]},
        },
        "failures": all_failures,
    }

    # counts
    leg_a_count = len(a["planned"])
    leg_b_count = len(b["planned"])
    leg_c_matched = len(c["decisions"])
    leg_c_cull = len(c["cull"])
    leg_d_matched = len(d["decisions"])
    leg_d_cull = len(d["cull"])
    leg_e_matched = len(e["decisions"])
    leg_e_cull = sum(g["count"] for g in e["cull_groups"].values())
    manifest["counts"] = {
        "LEG_A_COUNT": leg_a_count,
        "LEG_B_COUNT": leg_b_count,
        "LEG_B_FANOUT": len(b["fanout"]),
        "LEG_B_CULL": len(b["cull"]),
        "LEG_C_MATCHED": leg_c_matched, "LEG_C_CULL": leg_c_cull,
        "LEG_D_MATCHED": leg_d_matched, "LEG_D_CULL": leg_d_cull,
        "LEG_E_MATCHED": leg_e_matched, "LEG_E_CULL": leg_e_cull,
        "LEG_E_TOPS": e["tops_total"],
        "failures": len(all_failures),
    }
    return manifest, ts


def _unnamed_edges(manifest):
    """Invariant guard: no leg proposes an edge to/from a node whose name ends in '_Unnamed'."""
    bad = []
    for leg in manifest["legs"].values():
        for e in leg.get("planned", []):
            if e["src"].endswith("_Unnamed") or e["dst"].endswith("_Unnamed"):
                bad.append(e)
    return bad


def write_cull_report(manifest, path):
    legs = manifest["legs"]
    lines = ["# WELD-2 CLASSIFIED CULL REPORT", ""]
    lines.append(f"Generated: {manifest['generated_at']}  (dry_run={manifest['dry_run']})")
    lines.append("NO DELETES — every row below is an UNMATCHABLE item reported for Isaac's review.")
    lines.append("")

    def section(title, rows, render):
        lines.append(f"## {title}  ({len(rows)})")
        if not rows:
            lines.append("  (none)")
        for r in rows:
            lines.append("  - " + render(r))
        lines.append("")

    section("B. maps_to — seated Task-HCs with no defensible starlog target",
            legs["B_maps_to"]["cull"],
            lambda r: f"[{r['category']}] {r.get('hc')} — {r['why']}"
                      + (f" candidates={r['candidates']}" if r.get('candidates') else "")
                      + (f" ss={r['starsystem']}" if r.get('starsystem') else ""))
    section("C. starlog orphan Starlog_Projects with no name-core starsystem match",
            legs["C_starlog_orphans"]["cull"],
            lambda r: f"{r['project']} — parents={r.get('parents')} — {r['why']}")
    section("D. orphan HCs with no giint-inverse owner and no name-core match",
            legs["D_hc_orphans"]["cull"],
            lambda r: f"[{r['category']}] {r['hc']} — {r['why']}"
                      + (f" core={r.get('hc_core') or r.get('core')}" if (r.get('hc_core') or r.get('core')) else ""))

    # E is grouped
    lines.append(f"## E. giint orphan top-of-chain nodes — UNMATCHABLE (grouped by project-name-core)")
    egroups = legs["E_giint_orphans"]["cull_groups"]
    total_e = sum(g["count"] for g in egroups.values())
    lines.append(f"  total unmatchable giint tops: {total_e}  across {len(egroups)} groups")
    for grp, g in sorted(egroups.items(), key=lambda kv: -kv[1]["count"]):
        lines.append(f"  - group '{grp}': count={g['count']}  sample={g['sample']}")
    lines.append("")

    # ADDENDUM (commander review 2026-06-11)
    nameonly = manifest.get("nameonly_starlog_projects", {})
    lines.append("## ADDENDUM. untyped name-only Starlog_Project nodes — typing-by-prefix is a "
                 "RULING for Isaac (canon: name prefix is convention, not type); not welded, not typed")
    lines.append(f"  count: {nameonly.get('count')}  "
                 f"(by name-prefix: {nameonly.get('total_by_prefix')}; "
                 f"by IS_A: {nameonly.get('total_by_isa')} — the legs select by IS_A, which is "
                 f"why LEG_C diverged from the spec's prefix-counted census)")
    for s in nameonly.get("sample", []):
        lines.append(f"  - sample: {s}")
    lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))


def write_manifest_md(manifest, ts, cull_path, unnamed_bad, sanity):
    c = manifest["counts"]
    legs = manifest["legs"]

    def sample(rows, render, n=5):
        out = [("    " + render(r)) for r in rows[:n]]
        return out or ["    (none)"]

    lines = []
    lines.append("# WELD-2 DRY-RUN MANIFEST  (maps_to + HAS_STARLOG inverses + orphan reattach)")
    lines.append("")
    lines.append(f"Generated: {ts}   dry_run={manifest['dry_run']}   "
                 f"typed_starsystems={manifest['world']['typed_starsystems']}")
    lines.append(f"Cull report: {cull_path}")
    lines.append("")
    lines.append("## MARKERS")
    lines.append(f"LEG_A_COUNT={c['LEG_A_COUNT']}")
    lines.append(f"LEG_B_COUNT={c['LEG_B_COUNT']}  (grain=Starlog_Project; project-grain chosen — "
                 f"sessions sparse/ambiguous; FANOUT={c['LEG_B_FANOUT']} multi-project HCs; "
                 f"CULL={c['LEG_B_CULL']})")
    lines.append(f"LEG_C_MATCHED={c['LEG_C_MATCHED']}  LEG_C_CULL={c['LEG_C_CULL']}")
    lines.append(f"LEG_D_MATCHED={c['LEG_D_MATCHED']}  LEG_D_CULL={c['LEG_D_CULL']}")
    lines.append(f"LEG_E_MATCHED={c['LEG_E_MATCHED']}  LEG_E_CULL={c['LEG_E_CULL']}  "
                 f"(LEG_E_TOPS={c['LEG_E_TOPS']})")
    lines.append(f"failures={c['failures']}")
    lines.append("")
    lines.append("## SANITY (spec invariants vs LIVE — divergence reported honestly)")
    for s in sanity:
        lines.append(f"  {s}")
    lines.append("")
    lines.append("## SAMPLES (first 5 each)")
    lines.append("### LEG A — HAS_STARLOG inverses")
    lines += sample(legs["A_has_starlog"]["planned"], lambda e: f"{e['src']} -HAS_STARLOG-> {e['dst']}")
    lines.append("### LEG B — maps_to (project grain)")
    lines += sample(legs["B_maps_to"]["planned"], lambda e: f"{e['src']} -MAPS_TO-> {e['dst']}")
    lines.append("### LEG B — multi-project FANOUT (reported)")
    lines += sample(legs["B_maps_to"]["fanout"],
                    lambda x: f"{x['hc']} -> {x['starsystem']} ({x['project_count']} projects)")
    lines.append("### LEG C — starlog orphan reattach (matched)")
    lines += sample(legs["C_starlog_orphans"]["decisions"],
                    lambda x: f"{x['project']} -PART_OF-> {x['matched_starsystem']} (via {x['via']})")
    lines.append("### LEG D — HC orphan reattach (matched)")
    lines += sample(legs["D_hc_orphans"]["decisions"],
                    lambda x: f"{x['hc']} -PART_OF-> {x['target_bucket']} (via {x['via']})")
    lines.append("### LEG E — giint orphan reattach (matched)")
    lines += sample(legs["E_giint_orphans"]["decisions"],
                    lambda x: f"{x['giint_top']} -PART_OF-> {x['matched_starsystem']} (via {x['via']})")
    lines.append("")
    lines.append("## UNNAMED-EDGE GUARD")
    lines.append(f"  edges touching a *_Unnamed node: {len(unnamed_bad)}  "
                 f"(MUST be 0; samples: {unnamed_bad[:3]})")
    lines.append("")
    with open(MANIFEST_PATH, "w") as f:
        f.write("\n".join(lines))


def print_summary(manifest):
    c = manifest["counts"]
    print("=" * 64)
    print("WELD WORLD GRAPH 2 — %s" % ("DRY-RUN" if manifest["dry_run"] else "APPLY"))
    print("=" * 64)
    for k in ("LEG_A_COUNT", "LEG_B_COUNT", "LEG_B_FANOUT", "LEG_B_CULL",
              "LEG_C_MATCHED", "LEG_C_CULL", "LEG_D_MATCHED", "LEG_D_CULL",
              "LEG_E_MATCHED", "LEG_E_CULL", "LEG_E_TOPS", "failures"):
        print(f"  {k} = {c[k]}")
    print("-" * 64)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="WELD-2: maps_to + HAS_STARLOG inverses + orphan reattach (MERGE-only).")
    ap.add_argument("--apply", action="store_true",
                    help="EXECUTE the weld (export first, then MERGE). Default is DRY-RUN.")
    args = ap.parse_args()

    dry_run = not args.apply
    graph = get_graph()

    manifest, ts = compute(graph, dry_run)
    c = manifest["counts"]

    # collect every planned edge (for export + apply)
    all_edges = []
    for leg in manifest["legs"].values():
        all_edges.extend(leg.get("planned", []))

    # invariant guard: no edge touches a *_Unnamed node
    unnamed_bad = _unnamed_edges(manifest)

    # SANITY: spec invariants vs LIVE (report divergence; do NOT fake numbers)
    sanity = []
    sanity.append(f"SPEC: LEG_A≈200(±10)  | LIVE: LEG_A={c['LEG_A_COUNT']}  "
                  f"-> {'OK' if 190 <= c['LEG_A_COUNT'] <= 210 else 'DIVERGES (live world smaller than spec census)'}")
    sanity.append(f"SPEC: LEG_C matched+cull==170  | LIVE: {c['LEG_C_MATCHED']}+{c['LEG_C_CULL']}="
                  f"{c['LEG_C_MATCHED'] + c['LEG_C_CULL']}  "
                  f"-> {'OK' if c['LEG_C_MATCHED'] + c['LEG_C_CULL'] == 170 else 'DIVERGES (live orphan-project count != 170; spec census stale)'}")
    sanity.append(f"SPEC: LEG_D matched+cull==54   | LIVE: {c['LEG_D_MATCHED']}+{c['LEG_D_CULL']}="
                  f"{c['LEG_D_MATCHED'] + c['LEG_D_CULL']}  "
                  f"-> {'OK' if c['LEG_D_MATCHED'] + c['LEG_D_CULL'] == 54 else 'DIVERGES (live orphan-HC count != 54)'}")
    sanity.append(f"INVARIANT: no edge touches a *_Unnamed node  -> "
                  f"{'OK (0)' if not unnamed_bad else 'VIOLATED (' + str(len(unnamed_bad)) + ')'}")

    write_cull_report(manifest, CULL_PATH)
    write_manifest_md(manifest, ts, CULL_PATH, unnamed_bad, sanity)
    with open(MANIFEST_JSON_PATH, "w") as f:
        json.dump(manifest, f, indent=2)

    if args.apply:
        if unnamed_bad:
            print("REFUSING --apply: planned edges touch *_Unnamed nodes:", unnamed_bad[:5])
            sys.exit(2)
        manifest = run_apply(graph, manifest, all_edges, ts)
        with open(MANIFEST_JSON_PATH, "w") as f:
            json.dump(manifest, f, indent=2)

    print_summary(manifest)
    print("\n".join("  " + s for s in sanity))
    print(f"\nMANIFEST written to {MANIFEST_PATH}")
    print(f"CULL report written to {CULL_PATH}")
    print(f"JSON manifest written to {MANIFEST_JSON_PATH}")
    if args.apply:
        print(f"EXPORT written to {manifest.get('export_path')}")
        print(f"APPLIED edges: {manifest.get('apply_applied')}  "
              f"NO-OP (missing endpoint) edges: {manifest.get('apply_noop_count')}")
    # the E2E markers, machine-greppable, last
    print(f"\nLEG_A_COUNT={c['LEG_A_COUNT']}")
    print(f"LEG_B_COUNT={c['LEG_B_COUNT']} (grain=Starlog_Project, FANOUT={c['LEG_B_FANOUT']}, CULL={c['LEG_B_CULL']})")
    print(f"LEG_C_MATCHED={c['LEG_C_MATCHED']} LEG_C_CULL={c['LEG_C_CULL']}")
    print(f"LEG_D_MATCHED={c['LEG_D_MATCHED']} LEG_D_CULL={c['LEG_D_CULL']}")
    print(f"LEG_E_MATCHED={c['LEG_E_MATCHED']} LEG_E_CULL={c['LEG_E_CULL']}")
    print("MANIFEST_WRITTEN_OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"\nFATAL: {ex}")
        traceback.print_exc()
        sys.exit(1)
