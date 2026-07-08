#!/usr/bin/env python3
"""
E2E test for step 3 of the SM-branching build: `substrate_projector.project_state_machine` now
reads a Traversal_Step's parallel-flat-list `branch_to`/`branch_pattern`/`branch_weight` properties
(via the new pure helper `_step_spec_from_row`) and calls `create_sm_chain_live` with REAL
multi-branch step specs — instead of assuming a single linear `next` per step (which was
structurally incompatible with branching: a step with 2+ branches has no single `next` to follow).

Regression proof for the PRE-EXISTING scalar-`next` authoring path lives in
`automation/dragonbones/tests/test_sm_ec_e2e.py` — re-run UNCHANGED against this same live neo4j
as part of this build's dev-flow (see the `dragonbones-carton-retrieval-state-machines` skill).
THIS file covers ONLY the NEW branching-authoring read-path `project_state_machine` gained:

  (1) MULTI-BRANCH: a step carrying branch_to/branch_pattern/branch_weight (all 3 parallel lists,
      same length) -> project_state_machine builds a REAL multi-branch SM via create_sm_chain_live
      -> verify via direct Cypher that BOTH resulting NEXT_STEP edges carry the exact
      required_pattern/weight per branch (not just that the function returned success).
  (2) MISMATCHED LENGTH: a step whose branch_pattern is SHORTER than its branch_to (3 targets, 1
      pattern) and whose branch_weight is entirely ABSENT -> every missing pattern degrades to
      None and every missing weight degrades to 1.0 (create_sm_chain's own float-cast default),
      and the handler never raises (still returns a normal success string).

Self-cleaning: every node created is prefixed 'Zztest_PsmBranch_' and DETACH-DELETEd at the end
(prefix sweep, same backup-cleanup idiom as automation/dragonbones/tests/test_sm_ec_e2e.py). Run:
  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... python3 tests/test_project_state_machine_branching_e2e.py
"""
import os
import sys

os.environ.setdefault("NEO4J_URI", "bolt://host.docker.internal:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "password")
os.environ.setdefault("HEAVEN_DATA_DIR", "/tmp/heaven_data")

from carton_mcp import sm_gate
from carton_mcp.add_concept_tool import _get_module_connection
from carton_mcp.substrate_projector import project_state_machine

PFX = "Zztest_PsmBranch_"


def _conn():
    return _get_module_connection()


def _mk_run(conn):
    def run(query, params=None):
        rows = conn.execute_query(query, params or {})
        return [dict(r) if not isinstance(r, dict) else r for r in (rows or [])]
    return run


def _ensure_types(run):
    for t in (sm_gate.T_SM_CHAIN, sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP,
              sm_gate.T_EXECUTION_STATE, "Concept"):
        run("MERGE (n:Wiki {n:$n})", {"n": t})


def _cleanup(run):
    run("MATCH (c:Wiki) WHERE c.n STARTS WITH $p DETACH DELETE c", {"p": PFX})


def _seed_step(run, sm, step_id, **props):
    run("MERGE (c:Wiki {n:$n}) SET c.d=$d", {"n": step_id, "d": step_id + "."})
    run("MATCH (c:Wiki {n:$n}),(t:Wiki {n:'Traversal_Step'}) MERGE (c)-[:IS_A]->(t)", {"n": step_id})
    run("MATCH (c:Wiki {n:$n}),(p:Wiki {n:$p}) MERGE (c)-[:PART_OF]->(p)", {"n": step_id, "p": sm})
    set_clauses = ", ".join(f"s.{k}=${k}" for k in props)
    if set_clauses:
        run(f"MATCH (s:Wiki {{n:$n}}) SET {set_clauses}", {"n": step_id, **props})


def _seed_sm(run, gated, sm):
    for nm in (gated, sm):
        run("MERGE (c:Wiki {n:$n}) SET c.d=$d", {"n": nm, "d": nm + "."})
    run("MATCH (c:Wiki {n:$n}),(t:Wiki {n:'State_Machine'}) MERGE (c)-[:IS_A]->(t)", {"n": sm})
    run("MATCH (c:Wiki {n:$n}),(t:Wiki {n:'Concept'}) MERGE (c)-[:IS_A]->(t)", {"n": gated})
    run("MATCH (m:Wiki {n:$n}) SET m.sm_gates=$g", {"n": sm, "g": gated})
    # has_domain/has_subdomain/has_personal_domain (Isaac 2026-07-04): project_state_machine now
    # REQUIRES these off the SM concept (create_sm_chain_live raises without them).
    run("MERGE (dom:Wiki {n:'System'}) MERGE (sub:Wiki {n:'Sm_Branching'}) MERGE (pd:Wiki {n:'Cave'}) "
        "WITH dom, sub, pd MATCH (m:Wiki {n:$n}) "
        "MERGE (m)-[:HAS_DOMAIN]->(dom) MERGE (m)-[:HAS_SUBDOMAIN]->(sub) MERGE (m)-[:HAS_PERSONAL_DOMAIN]->(pd)",
        {"n": sm})


def _seed_multi_branch_case(run):
    """Case 1: a full 3-parallel-list multi-branch step (branch_to/branch_pattern/branch_weight
    all present, same length)."""
    gated, sm = f"{PFX}Gated1", f"{PFX}Sm1"
    step_a, step_x, step_y = f"{PFX}Step1_A", f"{PFX}Step1_X", f"{PFX}Step1_Y"
    _seed_sm(run, gated, sm)
    _seed_step(run, sm, step_a, required_pattern=None, text="Step A: branches",
               branch_to=[step_x, step_y], branch_pattern=["pattern_x", "pattern_y"],
               branch_weight=[2.0, 3.0])
    _seed_step(run, sm, step_x, required_pattern=None, text="Step X: terminal")
    _seed_step(run, sm, step_y, required_pattern=None, text="Step Y: terminal")
    return {"gated": gated, "sm": sm, "step_a": step_a, "step_x": step_x, "step_y": step_y}


def _seed_mismatched_case(run):
    """Case 2: branch_to has 3 targets; branch_pattern has only 1 (shorter); branch_weight is
    absent entirely. Must degrade every missing entry to None/1.0, never raise."""
    gated, sm = f"{PFX}Gated2", f"{PFX}Sm2"
    step_a = f"{PFX}Step2_A"
    step_x, step_y, step_z = f"{PFX}Step2_X", f"{PFX}Step2_Y", f"{PFX}Step2_Z"
    _seed_sm(run, gated, sm)
    _seed_step(run, sm, step_a, required_pattern=None, text="Step A: mismatched branches",
               branch_to=[step_x, step_y, step_z], branch_pattern=["pattern_x"])
    for st in (step_x, step_y, step_z):
        _seed_step(run, sm, st, required_pattern=None, text=st + ": terminal")
    return {"gated": gated, "sm": sm, "step_a": step_a, "step_x": step_x,
            "step_y": step_y, "step_z": step_z}


def _next_step_edge(run, a, b):
    rows = run(
        "MATCH (x:Wiki {n:$a})-[r:NEXT_STEP]->(y:Wiki {n:$b}) RETURN r.required_pattern AS rp, r.weight AS w",
        {"a": a, "b": b})
    return dict(rows[0]) if rows else None


def main():
    conn = _conn()
    if conn is None:
        print("FATAL: no neo4j", file=sys.stderr)
        sys.exit(1)
    run = _mk_run(conn)
    _cleanup(run)  # idempotent fresh start
    _ensure_types(run)

    results = {}
    try:
        # ---- Case 1: MULTI-BRANCH, all 3 parallel lists present + same length ----
        c1 = _seed_multi_branch_case(run)
        res1 = project_state_machine(c1["sm"], shared_connection=conn)
        results["1_returns_success"] = (
            isinstance(res1, str) and "error" not in res1.lower() and "skipped" not in res1.lower()
            and c1["gated"] in res1 and "gated=True" in res1
        )
        edge_x = _next_step_edge(run, c1["step_a"], c1["step_x"])
        edge_y = _next_step_edge(run, c1["step_a"], c1["step_y"])
        results["1_edges_exact"] = (
            edge_x is not None and edge_x.get("rp") == "pattern_x" and edge_x.get("w") == 2.0
            and edge_y is not None and edge_y.get("rp") == "pattern_y" and edge_y.get("w") == 3.0
        )

        # ---- Case 2: MISMATCHED LENGTHS — degrades to sane defaults, never raises ----
        c2 = _seed_mismatched_case(run)
        res2 = project_state_machine(c2["sm"], shared_connection=conn)
        results["2_returns_success_no_raise"] = (
            isinstance(res2, str) and "error" not in res2.lower() and "skipped" not in res2.lower()
            and c2["gated"] in res2 and "gated=True" in res2
        )
        e2x = _next_step_edge(run, c2["step_a"], c2["step_x"])   # has an explicit pattern
        e2y = _next_step_edge(run, c2["step_a"], c2["step_y"])   # missing pattern -> None
        e2z = _next_step_edge(run, c2["step_a"], c2["step_z"])   # missing pattern -> None
        results["2_degrades_to_defaults"] = (
            e2x is not None and e2x.get("rp") == "pattern_x" and e2x.get("w") == 1.0
            and e2y is not None and e2y.get("rp") is None and e2y.get("w") == 1.0
            and e2z is not None and e2z.get("rp") is None and e2z.get("w") == 1.0
        )
    finally:
        _cleanup(run)

    print("\n=== project_state_machine BRANCHING E2E (step 3: branch_to/branch_pattern/"
          "branch_weight -> real multi-branch NEXT_STEP edges) ===")
    ok = True
    for k in ["1_returns_success", "1_edges_exact", "2_returns_success_no_raise", "2_degrades_to_defaults"]:
        v = results.get(k)
        ok = ok and (v is True)
        print(f"  {k:<32} {'PASS' if v is True else 'FAIL ('+str(v)+')'}")
    print(f"\nE2E PROJECT_STATE_MACHINE-BRANCHING: {'PASS' if ok else 'FAIL'}  (test nodes removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
