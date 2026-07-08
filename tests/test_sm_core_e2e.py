#!/usr/bin/env python3
"""
E2E test for the CORE layer of sm_gate.py — the per-concept SM stack + the REQUIRE-NEXT visit gate —
against the LIVE carton neo4j, under the STACK-SIZE ACTIVATION rule.

Proves Isaac's 2026-06-20 16:17 decision: a Sm_Chain is ON (gated) iff its SM stack holds MORE THAN 1
SM. A single SM (the show-SM) = OFF even if its entry carries a required_pattern; adding any further SM
turns gating on. A Core does NOT withhold the visited concept's content — it REQUIRES that the actor's
NEXT move is a specific traversal/cypher. The cases:
  (1) DEFAULT OFF: a concept with NO Core -> sm_chain_visit arms nothing (require_next is None).
  (2) STACK-SIZE RULE: a SINGLE-SM Core (even with a required_pattern entry) is OFF -> arms nothing,
      never locks the actor.
  (3) >1 SM => GATED: visiting a 2-SM concept (show-SM order-0 + gating-SM order-1) ARMS a require-next
      and LOCKS the actor into the GATING SM's entry step (content is served by the caller).
  (4) the lock is real + targets the gating SM (order-1), not the show-SM.
  (5) ROUTING-PERSISTENCE: while locked, a NON-matching next move is REFUSED by the normal gate_call.
  (6) the REQUIRED move satisfies it: running the required query advances -> terminal -> UNLOCK.

Self-cleaning: every node it creates is prefixed 'Zztest_Core_' and DETACH-DELETEd at the end (its own
artifacts only). Run:
  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... python3 tests/test_sm_core_e2e.py
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


ACTOR = "Zztest_Core_Actor"
SUBJECT = "Zztest_Core_Subject"   # a 2-SM stack => GATED (show-SM order-0 + gating-SM order-1)
SINGLE = "Zztest_Core_Single"     # a 1-SM stack WITH a pattern entry => OFF (the stack-size rule)
PLAIN = "Zztest_Core_Plain"       # a concept with NO Core => off
NODES = [ACTOR, SUBJECT, SINGLE, PLAIN,
         "Zztest_Core_Core", "Zztest_Core_Sm", "Zztest_Core_EntryStep",      # SUBJECT order-0 show-SM
         "Zztest_Core_Sm2", "Zztest_Core_EntryStep2",                        # SUBJECT order-1 gating-SM
         "Zztest_Core_Single_Core", "Zztest_Core_Single_Sm", "Zztest_Core_Single_Step",
         f"{ACTOR}_Execution_State",
         sm_gate.T_SM_CHAIN, sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP, sm_gate.T_EXECUTION_STATE]


def _program(run):
    for t in (sm_gate.T_SM_CHAIN, sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP, sm_gate.T_EXECUTION_STATE):
        run("MERGE (n:Wiki {n:$n})", {"n": t})
    run("MERGE (a:Wiki {n:'Zztest_Core_Actor'})", {})
    # PLAIN: no Core at all.
    run("MERGE (p:Wiki {n:'Zztest_Core_Plain'}) SET p.d='plain content, no gate'", {})
    # SINGLE: a Core holding ONE SM whose entry HAS a required_pattern. Under the stack-size rule this is
    # still OFF (stack size == 1) — proving a single show-SM is ungated even with a pattern.
    run("""
        MERGE (s:Wiki {n:'Zztest_Core_Single'}) SET s.d='single-SM concept (OFF: stack size 1)'
        MERGE (core:Wiki {n:'Zztest_Core_Single_Core'}) MERGE (core)-[:IS_A]->(:Wiki {n:'Sm_Chain'})
        MERGE (sm:Wiki {n:'Zztest_Core_Single_Sm'}) MERGE (sm)-[:IS_A]->(:Wiki {n:'State_Machine'})
        MERGE (es:Wiki {n:'Zztest_Core_Single_Step'}) MERGE (es)-[:IS_A]->(:Wiki {n:'Traversal_Step'})
        SET es.required_pattern='query_wiki_graph', es.text='(would require, but stack size 1 => off)'
        MERGE (s)-[:HAS_SM_CHAIN]->(core)
        MERGE (core)-[r:SM_CHAIN_RUNS]->(sm) SET r.order=0
        MERGE (sm)-[:HAS_STEP]->(es)
    """, {})
    # SUBJECT: a Core holding TWO SMs => GATED. order-0 = show-SM (no required_pattern, serves content);
    # order-1 = gating-SM whose entry REQUIRES the next move be query_wiki_graph.
    run("""
        MERGE (subj:Wiki {n:'Zztest_Core_Subject'}) SET subj.d='served content (a Core does not withhold)'
        MERGE (core:Wiki {n:'Zztest_Core_Core'}) MERGE (core)-[:IS_A]->(:Wiki {n:'Sm_Chain'})
        MERGE (sm0:Wiki {n:'Zztest_Core_Sm'}) MERGE (sm0)-[:IS_A]->(:Wiki {n:'State_Machine'})
        MERGE (es0:Wiki {n:'Zztest_Core_EntryStep'}) MERGE (es0)-[:IS_A]->(:Wiki {n:'Traversal_Step'})
        SET es0.text='show step (no requirement)'
        MERGE (sm0)-[:HAS_STEP]->(es0)
        MERGE (sm1:Wiki {n:'Zztest_Core_Sm2'}) MERGE (sm1)-[:IS_A]->(:Wiki {n:'State_Machine'})
        MERGE (es1:Wiki {n:'Zztest_Core_EntryStep2'}) MERGE (es1)-[:IS_A]->(:Wiki {n:'Traversal_Step'})
        SET es1.required_pattern='query_wiki_graph',
            es1.text='REQUIRED NEXT after Zztest_Core_Subject: run query_wiki_graph(...) to continue.'
        MERGE (sm1)-[:HAS_STEP]->(es1)
        MERGE (subj)-[:HAS_SM_CHAIN]->(core)
        MERGE (core)-[r0:SM_CHAIN_RUNS]->(sm0) SET r0.order=0
        MERGE (core)-[r1:SM_CHAIN_RUNS]->(sm1) SET r1.order=1
    """, {})


def _cleanup(run):
    for n in NODES:
        if n.startswith("Zztest_Core_"):
            run("MATCH (n:Wiki {n:$n}) DETACH DELETE n", {"n": n})


def main():
    conn = _conn()
    if conn is None:
        print("FATAL: no neo4j", file=sys.stderr); sys.exit(1)
    run = _mk_run(conn)
    _cleanup(run)   # idempotent fresh start
    _program(run)
    results = {}
    try:
        # (1) DEFAULT OFF: a concept with no Core arms nothing
        r = sm_gate.sm_chain_visit(ACTOR, PLAIN, run)
        results["1_no_core_off"] = (r["require_next"] is None)

        # (2) STACK-SIZE RULE: a single-SM Core (even WITH a pattern entry) is OFF + never locks
        r = sm_gate.sm_chain_visit(ACTOR, SINGLE, run)
        results["2_single_sm_off"] = (r["require_next"] is None
                                      and sm_gate.get_active_step(ACTOR, run) is None)

        # (3) >1 SM => GATED: visiting the 2-SM concept ARMS a require-next (does NOT withhold content)
        r = sm_gate.sm_chain_visit(ACTOR, SUBJECT, run)
        results["3_multi_sm_arms"] = (bool(r["require_next"]) and "query_wiki_graph" in r["require_next"])

        # (4) the actor is LOCKED at the GATING SM's entry step (order-1), not the show-SM
        act = sm_gate.get_active_step(ACTOR, run)
        results["4_locked_at_gating"] = (act is not None and act["id"] == "Zztest_Core_EntryStep2")

        # (5) ROUTING-PERSISTENCE: a NON-matching next move is REFUSED by the normal gate_call
        try:
            sm_gate.gate_call(ACTOR, "get_concept('Something_Else')", run)
            results["5_wrong_next_refused"] = False
        except sm_gate.GateRefusal as e:
            results["5_wrong_next_refused"] = ("query_wiki_graph" in str(e))

        # (6) the REQUIRED next move satisfies it -> advance -> terminal -> UNLOCK
        gr = sm_gate.gate_call(ACTOR, "query_wiki_graph(MATCH (n) RETURN n)", run)
        life = sm_gate.get_lifecycle(ACTOR, run)
        results["6_required_next_unlocks"] = (gr["allowed"] is True and life is not None
                                              and life["status"] == "unlocked")
    finally:
        _cleanup(run)

    print("\n=== sm_gate CORE E2E (stack-size activation + REQUIRE-NEXT) ===")
    ok = True
    for k in ["1_no_core_off", "2_single_sm_off", "3_multi_sm_arms",
              "4_locked_at_gating", "5_wrong_next_refused", "6_required_next_unlocks"]:
        v = results.get(k)
        ok = ok and (v is True)
        print(f"  {k:<26} {'PASS' if v is True else 'FAIL ('+str(v)+')'}")
    print(f"\nE2E SM-CORE: {'PASS' if ok else 'FAIL'}  (test nodes removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
