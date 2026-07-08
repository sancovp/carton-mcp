#!/usr/bin/env python3
"""THE KILL-CRITERION RUN (Griess-constructor program, phase 0 — Isaac GO 2026-07-05).

Runs deduce_aut + provenance_substitutability READ-ONLY against the live carton graph + the SOMA
OWL world and writes the TSV ledger (autoresearch-style, committed) that gates M2-M5.

Cohorts:
  - middle_strata (THE SPEC'S SELECTION): :Wiki nodes with property region in {code, system_type},
    deterministic order, first N (default 25 of the 441 that existed at build time).
  - definition_bearing (SUPPLEMENTARY, labeled): every graph class carrying REQUIRES_RELATIONSHIP
    edges + every OWL class carrying restrictions — added because the middle-strata nodes were
    measured (2026-07-05) to carry NO definition structure on either surface (they are treeshell
    node concepts / test probes), and a ledger of pure NO_DEFINITION rows cannot evaluate whether
    Aut bites at all. Reported as a deviation, not hidden.

Verdicts (honest rules, from the brief + two additions the data forced):
  BITES     = a nontrivial formal orbit has >=1 substitution hit backed by >=3 distinct concepts.
  NO_BITE   = orbits nontrivial, provenance rich (>=3 observations on nontrivial orbits), zero hits.
  THIN_DATA = orbits nontrivial but provenance too sparse to judge (absence is WEAK evidence).
  TRIVIAL_AUT   (addition) = Aut_formal is the trivial group — every slot uniquely colored; the
                formal symmetry cannot bite because there is none. Distinct from NO_BITE.
  NO_DEFINITION (addition) = the class resolves on neither surface / with zero slots — the read
                surfaces carry no definition structure for it (the spec's "possible!" finding).

WRITES NOTHING to neo4j, POSTs NOTHING to SOMA. Output: the TSV ledger + a summary block on stdout.
"""

import argparse
import logging
import os
from datetime import datetime

# The INSTALLED package (this repo's convention: pyproject maps carton_mcp -> the repo root;
# `pip install --no-deps .` after source changes, same as every other carton test/script).
from carton_mcp.aut_deducer import (
    DEFAULT_THRESHOLD,
    _camel_to_title_underscore,
    deduce_aut,
    load_owl_world,
    make_executor,
    owl_class_index,
    provenance_substitutability,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_aut_kill_criterion")
# neo4j emits a WARNING notification per query touching a rel type with zero instances
# (HAS_REQUIRED_PART has none yet) — informational for this read-only sweep, not actionable noise.
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

LEDGER_COLUMNS = ["cohort", "class", "slot_count", "aut_order", "orbit_count",
                  "nontrivial_orbits", "substitution_hits", "observations", "verdict", "surfaces"]


def select_middle_strata(execute, n: int):
    rows = execute(
        "MATCH (c:Wiki) WHERE c.region IN ['code','system_type'] "
        "RETURN c.n AS name ORDER BY c.n LIMIT $n", {"n": n}) or []
    return [r["name"] for r in rows]


def select_definition_bearing(execute, world, owl_index):
    """Every class that actually declares definition slots: graph templates with
    REQUIRES_RELATIONSHIP + every OWL class with restrictions (one Title_Case name per class —
    iterate world.classes() directly so single-word classes like Event are not lost)."""
    import owlready2
    rows = execute(
        "MATCH (c:Wiki)-[:REQUIRES_RELATIONSHIP]->(:Wiki) RETURN DISTINCT c.n AS name ORDER BY c.n",
        {}) or []
    names = [r["name"] for r in rows]
    seen = set(names)
    for cls in sorted(world.classes(), key=lambda c: c.name):
        title = _camel_to_title_underscore(cls.name)
        if title in seen:
            continue
        if any(isinstance(x, owlready2.Restriction)
               for x in list(cls.is_a) + list(getattr(cls, "equivalent_to", []) or [])):
            seen.add(title)
            names.append(title)
    return names


def verdict_for(aut, prov, threshold=DEFAULT_THRESHOLD):
    nontrivial = [i for i, o in enumerate(aut["orbits"]) if len(o) > 1]
    if not aut["slots"]:
        return "NO_DEFINITION", 0, 0
    if not nontrivial:
        return "TRIVIAL_AUT", 0, sum(p["observation_count"] for p in prov)
    hits = sum(prov[i]["substitution_hits"] for i in nontrivial)
    obs = sum(prov[i]["observation_count"] for i in nontrivial)
    if hits >= 1:
        return "BITES", hits, obs
    if obs >= threshold:
        return "NO_BITE", hits, obs
    return "THIN_DATA", hits, obs


def run_class(cohort, name, execute, owl_index):
    try:
        aut = deduce_aut(name, execute=execute, owl_index=owl_index)
    except LookupError as e:
        # Expected, typed control flow: the class carries no definition on either surface —
        # that IS the NO_DEFINITION finding (the spec's "possible!" branch), not a swallowed error.
        logger.info("NO_DEFINITION: %s", e)
        return {"cohort": cohort, "class": name, "slot_count": 0, "aut_order": 1,
                "orbit_count": 0, "nontrivial_orbits": 0, "substitution_hits": 0,
                "observations": 0, "verdict": "NO_DEFINITION", "surfaces": "none"}
    prov = provenance_substitutability(name, aut["orbits"], execute)
    verdict, hits, obs = verdict_for(aut, prov)
    return {
        "cohort": cohort, "class": name,
        "slot_count": len(aut["slots"]), "aut_order": aut["order"],
        "orbit_count": len(aut["orbits"]),
        "nontrivial_orbits": sum(1 for o in aut["orbits"] if len(o) > 1),
        "substitution_hits": hits, "observations": obs, "verdict": verdict,
        "surfaces": "+".join(k for k, v in
                             {"graph": any(s.get("source") == "graph" for s in aut["slots"]),
                              "owl": any(s.get("source") == "owl" for s in aut["slots"])}.items() if v) or "resolved_empty",
    }


def write_ledger(path: str, results: list):
    with open(path, "w") as f:
        f.write("# aut kill-criterion ledger — phase 0 (READ-ONLY run) — generated "
                f"{datetime.now().isoformat()}\n")
        f.write("\t".join(LEDGER_COLUMNS) + "\n")
        for r in results:
            f.write("\t".join(str(r[c]) for c in LEDGER_COLUMNS) + "\n")


def print_summary(results: list, n_middle: int, n_bearing: int, ledger_path: str):
    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("\n== KILL-CRITERION SUMMARY ==")
    print(f"classes examined: {len(results)} "
          f"(middle_strata={n_middle}, definition_bearing={n_bearing})")
    for v in ("BITES", "NO_BITE", "THIN_DATA", "TRIVIAL_AUT", "NO_DEFINITION"):
        print(f"{v}: {counts.get(v, 0)}")
    print(f"ledger: {ledger_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--n", type=int, default=25, help="middle-strata sample size (deterministic)")
    ap.add_argument("--output", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aut_kill_criterion_ledger.tsv"))
    args = ap.parse_args()

    execute = make_executor()                       # fail-loud neo4j (READ-ONLY use)
    world, loaded = load_owl_world()                # fail-loud OWL
    index = owl_class_index(world)
    print(f"# OWL loaded: {loaded}; classes indexed: {len(set(id(c) for c in index.values()))}")

    middle = select_middle_strata(execute, args.n)
    bearing = [n for n in select_definition_bearing(execute, world, index) if n not in set(middle)]
    print(f"# middle_strata selected: {len(middle)} (of region in {{code,system_type}}); "
          f"definition_bearing (supplementary): {len(bearing)}")

    results = [run_class("middle_strata", n, execute, index) for n in middle]
    results += [run_class("definition_bearing", n, execute, index) for n in bearing]

    write_ledger(args.output, results)
    print_summary(results, len(middle), len(bearing), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
