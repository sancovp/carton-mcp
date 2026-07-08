#!/usr/bin/env python3
"""
E2E test for create_sm_chain_live in sm_gate.py — the SELF-CONTAINED factory entry external callers
(dragonbones) use — against the LIVE carton neo4j. Proves that create_sm_chain_live, called with NO
run/connection passed (it opens its own from env), builds the EXACT proven SM structure AND that the
live-built SM actually GATES.

The cases:
  (1) STRUCTURE: create_sm_chain_live (no connection passed) builds the 2-SM stack; query it back with
      our OWN connection and assert the HAS_SM_CHAIN / SM_CHAIN_RUNS{order} / HAS_STEP /
      Traversal_Step{required_pattern} structure exists.
  (2) GATES: sm_chain_visit ARMS a require_next on the live-built 2-SM concept (proves the self-contained
      factory produces a WORKING gate, not just nodes) — and locks at the gating SM's entry step.

Self-cleaning: every node it creates is prefixed 'Zztest_FactoryLive_' and DETACH-DELETEd at the end (its
own artifacts only). Run:
  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... python3 tests/test_sm_factory_live_e2e.py
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


ACTOR = "Zztest_FactoryLive_Actor"
SUBJECT = "Zztest_FactoryLive_Subject"  # gets a 2-SM stack => GATED
# the factory-built nodes (deterministic from the spec below)
SM_CHAIN = f"{SUBJECT}_Sm_Chain"
SHOW_SM = "Zztest_FactoryLive_Show_Sm"
SHOW_STEP = "Zztest_FactoryLive_Show_Step"
GATE_SM = "Zztest_FactoryLive_Gate_Sm"
GATE_STEP = "Zztest_FactoryLive_Gate_Step"
NODES = [ACTOR, SUBJECT, SM_CHAIN, SHOW_SM, SHOW_STEP, GATE_SM, GATE_STEP,
         f"{ACTOR}_Execution_State"]

# The 2-SM stack: order-0 show-SM (no required_pattern => serves content) + order-1 gating-SM whose entry
# REQUIRES the next move be query_wiki_graph (the stack-size rule makes a >1-SM stack GATED).
STATE_MACHINES = [
    {"name": SHOW_SM,
     "steps": [{"id": SHOW_STEP, "required_pattern": None,
                "text": "show step (no requirement)", "next": None}]},
    {"name": GATE_SM,
     "steps": [{"id": GATE_STEP, "required_pattern": "query_wiki_graph",
                "text": "REQUIRED NEXT after Zztest_FactoryLive_Subject: run query_wiki_graph(...) to continue.",
                "next": None}]},
]


def _ensure_types(run):
    for t in (sm_gate.T_SM_CHAIN, sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP, sm_gate.T_EXECUTION_STATE):
        run("MERGE (n:Wiki {n:$n})", {"n": t})
    run("MERGE (a:Wiki {n:$a})", {"a": ACTOR})


def _cleanup(run):
    for n in NODES:
        if n.startswith("Zztest_FactoryLive_"):
            run("MATCH (n:Wiki {n:$n}) DETACH DELETE n", {"n": n})


def _structure_counts(run):
    """Count the structural edges/nodes the factory should have produced for SUBJECT."""
    rows = run("""
        MATCH (c:Wiki {n:$subject})-[:HAS_SM_CHAIN]->(core:Wiki)-[:IS_A]->(:Wiki {n:'Sm_Chain'})
        OPTIONAL MATCH (core)-[r:SM_CHAIN_RUNS]->(sm:Wiki)-[:IS_A]->(:Wiki {n:'State_Machine'})
        OPTIONAL MATCH (sm)-[:HAS_STEP]->(st:Wiki)-[:IS_A]->(:Wiki {n:'Traversal_Step'})
        RETURN count(DISTINCT core) AS chains,
               count(DISTINCT sm) AS sms,
               count(DISTINCT st) AS steps,
               count(DISTINCT r) AS runs_edges
    """, {"subject": SUBJECT})
    return dict(rows[0]) if rows else {}


def main():
    conn = _conn()
    if conn is None:
        print("FATAL: no neo4j", file=sys.stderr); sys.exit(1)
    run = _mk_run(conn)   # the test's OWN connection (assertions + cleanup)
    _cleanup(run)   # idempotent fresh start
    _ensure_types(run)
    results = {}
    try:
        # --- Build the 2-SM stack via the SELF-CONTAINED factory: NO run/connection passed ---
        out = sm_gate.create_sm_chain_live(SUBJECT, STATE_MACHINES,
                                          domain="System", subdomain="Sm_Factory_Live_E2e",
                                          personal_domain="cave")

        # (1) STRUCTURE: the self-contained factory produced the proven structure (query it back with OUR conn).
        c = _structure_counts(run)
        order_rows = run("""
            MATCH (c:Wiki {n:$subject})-[:HAS_SM_CHAIN]->(:Wiki)-[r:SM_CHAIN_RUNS]->(sm:Wiki)
            RETURN sm.n AS sm, r.order AS order ORDER BY r.order
        """, {"subject": SUBJECT})
        orders = {row["sm"]: row["order"] for row in order_rows}
        pat_rows = run("""
            MATCH (st:Wiki {n:$gate_step})-[:IS_A]->(:Wiki {n:'Traversal_Step'})
            RETURN st.required_pattern AS rp, st.text AS text
        """, {"gate_step": GATE_STEP})
        gate_pat = pat_rows[0]["rp"] if pat_rows else None
        results["1_structure"] = (
            out.get("sm_chain") == SM_CHAIN
            and out.get("gated") is True
            and out.get("sms") == [SHOW_SM, GATE_SM]
            and out.get("steps") == [SHOW_STEP, GATE_STEP]
            and c.get("chains") == 1 and c.get("sms") == 2
            and c.get("steps") == 2 and c.get("runs_edges") == 2
            and orders.get(SHOW_SM) == 0 and orders.get(GATE_SM) == 1
            and gate_pat == "query_wiki_graph"
        )

        # (2) GATES: the live-built 2-SM concept actually arms a require-next + locks at the gating SM.
        r = sm_gate.sm_chain_visit(ACTOR, SUBJECT, run)
        act = sm_gate.get_active_step(ACTOR, run)
        results["2_live_built_sm_gates"] = (
            bool(r["require_next"]) and "query_wiki_graph" in r["require_next"]
            and act is not None and act["id"] == GATE_STEP
        )
        # release the lock so it doesn't leak
        sm_gate.gate_call(ACTOR, "query_wiki_graph(MATCH (n) RETURN n)", run)
    finally:
        _cleanup(run)

    print("\n=== create_sm_chain_live FACTORY E2E (self-contained: structure + gating) ===")
    ok = True
    for k in ["1_structure", "2_live_built_sm_gates"]:
        v = results.get(k)
        ok = ok and (v is True)
        print(f"  {k:<28} {'PASS' if v is True else 'FAIL ('+str(v)+')'}")
    print(f"\nE2E SM-FACTORY-LIVE: {'PASS' if ok else 'FAIL'}  (test nodes removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
