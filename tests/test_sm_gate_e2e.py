#!/usr/bin/env python3
"""
E2E test for sm_gate.py — the carton-native State-Machine GATE — against the LIVE carton neo4j.

Proves the scientifically-exact CyberneticiRcus gate mechanic works on carton's :Wiki graph:
  (1) default-ungated: an actor with no locked Execution_State passes freely;
  (2) gate refusal: locked at a step whose required_pattern is 'add_concept', a 'get_concept(...)'
      call is REFUSED (GateRefusal carrying the regex);
  (3) legal move + auto-advance: an 'add_concept(...)' call passes AND advances the cursor;
  (4) terminal unlock: passing the final step UNLOCKS the Execution_State;
  (5) trigger: a result carrying trigger_traversal locks a fresh actor into the flow.

Self-cleaning: every node it creates is prefixed 'Zztest_Sm_' and DETACH-DELETEd at the end
(its own test artifacts — not the accumulation). Run:
  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... python3 tests/test_sm_gate_e2e.py
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
    """Adapt KnowledgeGraphBuilder.execute_query -> run(query, params) -> list[dict]."""
    def run(query, params=None):
        rows = conn.execute_query(query, params or {})
        out = []
        for r in (rows or []):
            out.append(dict(r) if not isinstance(r, dict) else r)
        return out
    return run


# ---- programming the SM through cypher that MIRRORS add_concept/set_properties output ----
# (State_Machine/Traversal_Step/Execution_State are :Wiki nodes typed by IS_A, exactly as
#  add_concept would store them; required_pattern/text/status are properties as set_properties
#  would set them; HAS_STEP/NEXT_STEP/CURRENT_STEP/HAS_LIFECYCLE are typed edges.)

ACTOR = "Zztest_Sm_Actor"
ACTOR2 = "Zztest_Sm_Actor2"
NODES = [ACTOR, ACTOR2, "Zztest_Sm_Machine",
         "Zztest_Sm_Step1", "Zztest_Sm_Step2", "Zztest_Sm_Step3",
         "Zztest_Sm_State", "Zztest_Sm_State2", "Zztest_Sm_TriggerNode",
         sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP, sm_gate.T_EXECUTION_STATE]


def _program_sm(run):
    # type nodes
    for t in (sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP, sm_gate.T_EXECUTION_STATE):
        run("MERGE (n:Wiki {n:$n})", {"n": t})
    # machine + 3 steps (step1 requires 'add_concept', step2 requires 'set_properties', step3 terminal)
    run("""
        MERGE (m:Wiki {n:'Zztest_Sm_Machine'}) MERGE (m)-[:IS_A]->(:Wiki {n:'State_Machine'})
        MERGE (s1:Wiki {n:'Zztest_Sm_Step1'}) MERGE (s1)-[:IS_A]->(:Wiki {n:'Traversal_Step'})
        SET s1.required_pattern='add_concept', s1.text='Step 1: you must add_concept.'
        MERGE (s2:Wiki {n:'Zztest_Sm_Step2'}) MERGE (s2)-[:IS_A]->(:Wiki {n:'Traversal_Step'})
        SET s2.required_pattern='set_properties', s2.text='Step 2: you must set_properties.'
        MERGE (s3:Wiki {n:'Zztest_Sm_Step3'}) MERGE (s3)-[:IS_A]->(:Wiki {n:'Traversal_Step'})
        SET s3.text='Step 3: terminal.'
        MERGE (m)-[:HAS_STEP]->(s1) MERGE (m)-[:HAS_STEP]->(s2) MERGE (m)-[:HAS_STEP]->(s3)
        MERGE (s1)-[r1:NEXT_STEP]->(s2) SET r1.weight=1.0
        MERGE (s2)-[r2:NEXT_STEP]->(s3) SET r2.weight=1.0
    """, {})
    # actor + locked Execution_State at step1
    run("""
        MERGE (a:Wiki {n:'Zztest_Sm_Actor'})
        MERGE (st:Wiki {n:'Zztest_Sm_State'}) MERGE (st)-[:IS_A]->(:Wiki {n:'Execution_State'})
        SET st.status='locked'
        MERGE (a)-[:HAS_LIFECYCLE]->(st)
        WITH st MATCH (s1:Wiki {n:'Zztest_Sm_Step1'})
        OPTIONAL MATCH (st)-[c:CURRENT_STEP]->() DELETE c
        MERGE (st)-[:CURRENT_STEP]->(s1)
    """, {})
    # actor2 + UNLOCKED Execution_State (for trigger test)
    run("""
        MERGE (a:Wiki {n:'Zztest_Sm_Actor2'})
        MERGE (st:Wiki {n:'Zztest_Sm_State2'}) MERGE (st)-[:IS_A]->(:Wiki {n:'Execution_State'})
        SET st.status='unlocked'
        MERGE (a)-[:HAS_LIFECYCLE]->(st)
    """, {})
    # a trigger node whose trigger_traversal points at step1
    run("MERGE (n:Wiki {n:'Zztest_Sm_TriggerNode'}) SET n.trigger_traversal='Zztest_Sm_Step1'", {})


def _cleanup(run):
    for n in NODES:
        if n.startswith("Zztest_Sm_"):
            run("MATCH (n:Wiki {n:$n}) DETACH DELETE n", {"n": n})


def main():
    conn = _conn()
    if conn is None:
        print("FATAL: no neo4j", file=sys.stderr); sys.exit(1)
    run = _mk_run(conn)
    _cleanup(run)  # idempotent fresh start
    _program_sm(run)
    results = {}
    try:
        # (1) default-ungated: unknown actor, no lock
        r = sm_gate.gate_call("Zztest_Sm_Nobody", "anything", run)
        results["1_default_ungated"] = (r["allowed"] is True)

        # (2) gate refusal: ACTOR locked at step1 (requires 'add_concept'); a get_concept call is illegal
        try:
            sm_gate.gate_call(ACTOR, "get_concept('Foo')", run)
            results["2_illegal_refused"] = False
        except sm_gate.GateRefusal as e:
            results["2_illegal_refused"] = ("required_pattern: add_concept" in str(e))

        # confirm the refusal did NOT advance the cursor (still at step1)
        act = sm_gate.get_active_step(ACTOR, run)
        results["2b_cursor_unchanged"] = (act is not None and act["id"] == "Zztest_Sm_Step1")

        # (3) legal move: an add_concept call passes AND advances to step2
        r = sm_gate.gate_call(ACTOR, "add_concept('Bar', is_a=['X'])", run)
        act = sm_gate.get_active_step(ACTOR, run)
        results["3_legal_advances"] = (r["allowed"] and act is not None and act["id"] == "Zztest_Sm_Step2")

        # (4) advance through step2 (set_properties) -> step3 (terminal) -> UNLOCK
        sm_gate.gate_call(ACTOR, "set_properties('Bar', {...})", run)  # step2 -> step3
        act_mid = sm_gate.get_active_step(ACTOR, run)
        # step3 has no required_pattern => any call passes + terminal unlock
        r = sm_gate.gate_call(ACTOR, "whatever", run)
        act_after = sm_gate.get_active_step(ACTOR, run)
        results["4_terminal_unlocks"] = (act_mid is not None and act_mid["id"] == "Zztest_Sm_Step3"
                                         and act_after is None)

        # (5) trigger: a result carrying trigger_traversal locks the UNLOCKED actor2 into the flow
        locked = sm_gate.scan_and_trigger(
            [{"n": "Zztest_Sm_TriggerNode", "trigger_traversal": "Zztest_Sm_Step1"}], ACTOR2, run)
        act2 = sm_gate.get_active_step(ACTOR2, run)
        results["5_trigger_locks"] = (locked == "Zztest_Sm_Step1"
                                      and act2 is not None and act2["id"] == "Zztest_Sm_Step1")
    finally:
        _cleanup(run)

    print("\n=== sm_gate E2E (carton-native CyberneticiRcus gate port) ===")
    ok = True
    for k in ["1_default_ungated", "2_illegal_refused", "2b_cursor_unchanged",
              "3_legal_advances", "4_terminal_unlocks", "5_trigger_locks"]:
        v = results.get(k)
        ok = ok and (v is True)
        print(f"  {k:<22} {'PASS' if v is True else 'FAIL ('+str(v)+')'}")
    print(f"\nE2E SM-GATE: {'PASS' if ok else 'FAIL'}  (test nodes removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
