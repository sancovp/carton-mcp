#!/usr/bin/env python3
"""
LIVE E2E test for the step-2 SM-branching wiring (sm_gate.py `auto_progress`/`gate_call` now calling
`select_branch`/`reinforce_transition`) against the REAL carton neo4j — the actual proof the wiring
works, not just that the pure functions work in isolation (that proof is `test_sm_branching.py`).

Builds a single Machine (via `create_sm_chain_live`, the SELF-CONTAINED factory external callers use —
no connection passed) with an entry step `Step_A` (no required_pattern of its own — the branching lives
on its OUTGOING NEXT_STEP edges) carrying 2 branches:
  - Step_Gated  (required_pattern='trigger_case', weight=1000.0)  — the PATTERN-GATED branch
  - Step_Other  (required_pattern=None,           weight=0.001)   — the UNGATED branch ("one not")
The weights are deliberately skewed by 6 orders of magnitude so that, when a call matches Step_Gated's
pattern (making BOTH branches eligible — an ungated branch is always eligible per `select_branch`), the
softmax-over-weight selection picks Step_Gated with probability indistinguishable from 1.0
(`exp(0.001-1000)` underflows to 0.0 in double precision) — i.e. deterministic FOR TEST PURPOSES without
needing to seed `select_branch`'s (unseeded, module-level `random`) RNG.

Proves, against the LIVE graph:
  (1) locking ACTOR at Step_A and calling `gate_call` with input matching the gated branch's pattern
      advances to Step_Gated, NOT Step_Other (query the cursor back after the call).
  (2) the taken edge's `weight` property in neo4j has ACTUALLY increased by exactly the default
      `reinforce_delta` (0.1) — read the raw weight before and after via `query_wiki_graph`-style direct
      Cypher (never trust that `reinforce_transition` was merely "called").
  (3) repeating the SAME branch-take (re-locking the actor back at Step_A each time) increases the
      weight AGAIN each time — 3 consecutive takes, 3 consecutive weight increases, exact numbers
      captured and printed (not just "it worked").
  (4) a call that matches NEITHER branch's pattern... is not applicable here since Step_Other is
      unconditional (always eligible) — so this file's refusal-path coverage lives in the unit tests
      (`test_auto_progress_no_eligible_branch_refuses_naming_all_patterns`, where every candidate IS
      pattern-gated). This file focuses on what only a LIVE graph can prove: the weight actually persists.

Self-cleaning: every node it creates is prefixed 'Zztest_Branch_' and DETACH-DELETEd at the end. Run:
  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... python3 tests/test_sm_branching_live_e2e.py
"""
import os
import sys

from carton_mcp import sm_gate


def _conn():
    from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
    c = KnowledgeGraphBuilder(
        uri=os.getenv("NEO4J_URI", "bolt://host.docker.internal:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )
    c._ensure_connection()
    return c


def _mk_run(conn):
    def run(query, params=None):
        rows = conn.execute_query(query, params or {})
        return [dict(r) if not isinstance(r, dict) else r for r in (rows or [])]
    return run


ACTOR = "Zztest_Branch_Actor"
SUBJECT = "Zztest_Branch_Subject"      # the concept create_sm_chain_live hangs the Sm_Chain off of
SM = "Zztest_Branch_Sm"
STEP_A = "Zztest_Branch_Step_A"
STEP_GATED = "Zztest_Branch_Step_Gated"
STEP_OTHER = "Zztest_Branch_Step_Other"
STATE = f"{ACTOR}_Execution_State"
NODES = [ACTOR, SUBJECT, SM, STEP_A, STEP_GATED, STEP_OTHER, STATE,
         f"{SUBJECT}_Sm_Chain",
         sm_gate.T_SM_CHAIN, sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP, sm_gate.T_EXECUTION_STATE]

# The 2-branch spec: Step_A has NO required_pattern of its own (gate_call's own-step check passes it
# straight through to auto_progress -> select_branch decides among the OUTGOING branches). Weights are
# skewed 1000.0 : 0.001 so the softmax pick of the matching gated branch is ~1.0 in double precision.
STATE_MACHINES = [{
    "name": SM,
    "steps": [
        {"id": STEP_A, "required_pattern": None, "text": "Step A: branches on call_text.",
         "branches": [
             {"to": STEP_GATED, "required_pattern": "trigger_case", "weight": 1000.0},
             {"to": STEP_OTHER, "required_pattern": None, "weight": 0.001},
         ]},
        {"id": STEP_GATED, "required_pattern": None, "text": "Step Gated: terminal."},
        {"id": STEP_OTHER, "required_pattern": None, "text": "Step Other: terminal."},
    ],
}]


def _lock_actor_at_step_a(run):
    """Directly lock (or re-lock) ACTOR's Execution_State at STEP_A — same idiom as
    tests/test_sm_gate_e2e.py's `_program_sm` actor-locking cypher."""
    run(f"""
        MERGE (a:Wiki {{n: $actor}})
        MERGE (st:Wiki {{n: $state}}) MERGE (st)-[:IS_A]->(:Wiki {{n: 'Execution_State'}})
        SET st.status = 'locked'
        MERGE (a)-[:HAS_LIFECYCLE]->(st)
        WITH st MATCH (s:Wiki {{n: $step_a}})
        OPTIONAL MATCH (st)-[c:CURRENT_STEP]->() DELETE c
        MERGE (st)-[:CURRENT_STEP]->(s)
    """, {"actor": ACTOR, "state": STATE, "step_a": STEP_A})


def _edge_weight(run, a, b):
    rows = run("""
        MATCH (x:Wiki {n:$a})-[r:NEXT_STEP]->(y:Wiki {n:$b}) RETURN r.weight AS w
    """, {"a": a, "b": b})
    return rows[0]["w"] if rows else None


def _cleanup(run):
    for n in NODES:
        if n.startswith("Zztest_Branch_") or n.endswith("_Execution_State") and n.startswith("Zztest_Branch_"):
            run("MATCH (n:Wiki {n:$n}) DETACH DELETE n", {"n": n})


def main():
    conn = _conn()
    if conn is None:
        print("FATAL: no neo4j", file=sys.stderr); sys.exit(1)
    run = _mk_run(conn)
    _cleanup(run)  # idempotent fresh start
    results = {}
    weight_trail = []
    try:
        # --- build the 2-branch SM via the SELF-CONTAINED factory (no connection passed) ---
        out = sm_gate.create_sm_chain_live(SUBJECT, STATE_MACHINES,
                                          domain="System", subdomain="Sm_Branching_Live_E2e",
                                          personal_domain="cave")
        results["setup_gated"] = (out.get("sms") == [SM] and out.get("steps") == [STEP_A, STEP_GATED, STEP_OTHER])

        weight_before_1 = _edge_weight(run, STEP_A, STEP_GATED)
        weight_trail.append({"take": 1, "weight_before": weight_before_1})

        # (1)+(2) lock ACTOR at Step_A; a call matching the gated branch's pattern advances there,
        # NOT Step_Other; the taken edge's weight increased by exactly reinforce_delta (0.1 default).
        _lock_actor_at_step_a(run)
        r1 = sm_gate.gate_call(ACTOR, "I am about to trigger_case(x)", run)
        act1 = sm_gate.get_active_step(ACTOR, run)
        weight_after_1 = _edge_weight(run, STEP_A, STEP_GATED)
        weight_trail[-1]["weight_after"] = weight_after_1
        results["1_advanced_to_gated_not_other"] = (act1 is not None and act1["id"] == STEP_GATED)
        results["2_weight_increased_take1"] = (
            weight_before_1 is not None and weight_after_1 is not None
            and abs((weight_after_1 - weight_before_1) - 0.1) < 1e-9
        )

        # (3) repeat the SAME branch-take twice more (re-lock at Step_A each time) — the weight must
        # increase AGAIN each time. Capture the actual before/after numbers, not just "it worked".
        ok_repeat = True
        for i in (2, 3):
            wb = _edge_weight(run, STEP_A, STEP_GATED)
            _lock_actor_at_step_a(run)
            sm_gate.gate_call(ACTOR, "I am about to trigger_case(x) again", run)
            wa = _edge_weight(run, STEP_A, STEP_GATED)
            weight_trail.append({"take": i, "weight_before": wb, "weight_after": wa})
            ok_repeat = ok_repeat and (wb is not None and wa is not None and abs((wa - wb) - 0.1) < 1e-9)
        results["3_repeated_takes_each_increase_weight"] = ok_repeat
    finally:
        _cleanup(run)

    print("\n=== SM-BRANCHING LIVE E2E (step 2: auto_progress/gate_call wired to select_branch + "
          "reinforce_transition) ===")
    print("  weight trail (actual numbers observed, per take):")
    for row in weight_trail:
        print(f"    take {row.get('take')}: weight_before={row.get('weight_before')} "
              f"weight_after={row.get('weight_after')}")
    ok = True
    for k in ["setup_gated", "1_advanced_to_gated_not_other", "2_weight_increased_take1",
              "3_repeated_takes_each_increase_weight"]:
        v = results.get(k)
        ok = ok and (v is True)
        print(f"  {k:<38} {'PASS' if v is True else 'FAIL ('+str(v)+')'}")
    print(f"\nE2E SM-BRANCHING-LIVE: {'PASS' if ok else 'FAIL'}  (test nodes removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
