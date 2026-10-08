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

⚠ THIS RUNS AGAINST WHATEVER `NEO4J_URI` NAMES, AND ITS DEFAULT IS PRODUCTION —
`bolt://host.docker.internal:7687` is the identical default the live daemon uses
(observation_worker_daemon.py:1302). Run bare, it writes to the real graph. That is deliberate
(this is a live-graph E2E), but it means every node this file creates must be cleanable, which is
what the bound-type discipline in `_program_sm` protects.

Self-cleaning: every node it creates is named `Zztest_Sm_*` and DETACH-DELETEd at the end (its own
test artifacts — not the accumulation). This is TRUE ONLY BECAUSE the type nodes are bound rather
than inlined: until 2026-08-22 the relationship MERGEs inlined their `:Wiki` targets, so each run
ALSO minted fresh `State_Machine` / `Traversal_Step` / `Execution_State` nodes — which carry no
`Zztest_Sm_` prefix, so `_cleanup` could not see them and they leaked into the graph permanently.
The docstring claimed self-cleaning throughout; the claim was false, and being false is exactly why
the leak stayed invisible. Keep the types bound and this line stays true.

Run:
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
    # THE TYPE NODES ARE BOUND, NEVER INLINE. An anonymous inline `:Wiki {n:'X'}` sitting as the
    # TARGET of a relationship MERGE matches the WHOLE PATH -- for a new source that path has never
    # existed, so Cypher creates the entire pattern INCLUDING A FRESH TYPE NODE, once per run,
    # forever. Merging the type by name up-front does NOT save you: the inline form never looks at
    # it. (Anonymous_Inline_Type_Merge_Defect; .claude/rules/wiki-type-shattering-repair.md.)
    #
    # Every MERGE on a type name is collapsed with `WITH ... LIMIT 1` because these names are STILL
    # shattered in the live graph -- an uncollapsed MERGE matches all N copies and every downstream
    # clause then runs once per row (Merge_Amplification_On_Shattered_Graph). The collapse is
    # correct both before and after the dedupe lands.
    for t in (sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP, sm_gate.T_EXECUTION_STATE):
        run("MERGE (n:Wiki {n:$n})", {"n": t})
    # machine + 3 steps (step1 requires 'add_concept', step2 requires 'set_properties', step3 terminal)
    run("""
        MERGE (t_m:Wiki {n:'State_Machine'})
        WITH t_m LIMIT 1
        MERGE (t_s:Wiki {n:'Traversal_Step'})
        WITH t_m, t_s LIMIT 1
        MERGE (m:Wiki {n:'Zztest_Sm_Machine'}) MERGE (m)-[:IS_A]->(t_m)
        MERGE (s1:Wiki {n:'Zztest_Sm_Step1'}) MERGE (s1)-[:IS_A]->(t_s)
        SET s1.required_pattern='add_concept', s1.text='Step 1: you must add_concept.'
        MERGE (s2:Wiki {n:'Zztest_Sm_Step2'}) MERGE (s2)-[:IS_A]->(t_s)
        SET s2.required_pattern='set_properties', s2.text='Step 2: you must set_properties.'
        MERGE (s3:Wiki {n:'Zztest_Sm_Step3'}) MERGE (s3)-[:IS_A]->(t_s)
        SET s3.text='Step 3: terminal.'
        MERGE (m)-[:HAS_STEP]->(s1) MERGE (m)-[:HAS_STEP]->(s2) MERGE (m)-[:HAS_STEP]->(s3)
        MERGE (s1)-[r1:NEXT_STEP]->(s2) SET r1.weight=1.0
        MERGE (s2)-[r2:NEXT_STEP]->(s3) SET r2.weight=1.0
    """, {})
    # actor + locked Execution_State at step1
    run("""
        MERGE (t_e:Wiki {n:'Execution_State'})
        WITH t_e LIMIT 1
        MERGE (a:Wiki {n:'Zztest_Sm_Actor'})
        MERGE (st:Wiki {n:'Zztest_Sm_State'}) MERGE (st)-[:IS_A]->(t_e)
        SET st.status='locked'
        MERGE (a)-[:HAS_LIFECYCLE]->(st)
        WITH st MATCH (s1:Wiki {n:'Zztest_Sm_Step1'})
        OPTIONAL MATCH (st)-[c:CURRENT_STEP]->() DELETE c
        MERGE (st)-[:CURRENT_STEP]->(s1)
    """, {})
    # actor2 + UNLOCKED Execution_State (for trigger test)
    run("""
        MERGE (t_e:Wiki {n:'Execution_State'})
        WITH t_e LIMIT 1
        MERGE (a:Wiki {n:'Zztest_Sm_Actor2'})
        MERGE (st:Wiki {n:'Zztest_Sm_State2'}) MERGE (st)-[:IS_A]->(t_e)
        SET st.status='unlocked'
        MERGE (a)-[:HAS_LIFECYCLE]->(st)
    """, {})
    # a trigger node whose trigger_traversal points at step1
    run("MERGE (n:Wiki {n:'Zztest_Sm_TriggerNode'}) SET n.trigger_traversal='Zztest_Sm_Step1'", {})


def _cleanup(run):
    # ⚠ THE PREFIX GUARD IS LOAD-BEARING, NOT AN OVERSIGHT. `NODES` also lists the three real type
    # names (sm_gate.T_*) so the test can reason about them, and this guard is what stops the
    # cleanup from DETACH-DELETING the production universals every other concept in the graph is
    # `IS_A` into. Never "fix" it by dropping the check.
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
