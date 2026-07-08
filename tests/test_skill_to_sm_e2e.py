#!/usr/bin/env python3
"""
E2E for skill_to_sm — the skill->SM converter v0 (build-plan item 1: "SKILLS ARE JUST SMs").

Isaac 2026-06-20: the SM IS the skill; globally-available SMs get listed in the system prompt FROM THE
GRAPH. v0 gives a skill concept a DEGENERATE show-Core (one show-SM, entry has NO required_pattern), so
it is OFF by default (sm_chain_visit serves it, requires nothing) — the "1 step = show = off" default.
ACTIVATION (a Core with >1 SM in its stack is ON) rides the deferred multi-SM advance increment. Proves:
  (1) skill_to_sm builds <skill> -HAS_SM_CHAIN-> Core -SM_CHAIN_RUNS{0}-> Sm -HAS_STEP-> ShowStep (get_sm_chain = 1 SM).
  (2) the show step has NO required_pattern (it is a pure "show").
  (3) sm_chain_visit on the converted skill is OFF: require_next is None (served, not gated) AND the actor
      is NOT locked (no Execution_State written).
  (4) idempotent: converting twice leaves exactly ONE Core / ONE SM_CHAIN_RUNS edge / ONE SM (MERGE).

Self-cleaning ('Zztest_S2sm_' + the derived Sm_Chain_/Sm_/Step_ names). Run:
  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... python3 tests/test_skill_to_sm_e2e.py
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


SKILL = "Zztest_S2sm_Skill"
ACTOR = "Zztest_S2sm_Actor"
NODES = [SKILL, ACTOR, f"{ACTOR}_Execution_State",
         f"Sm_Chain_{SKILL}", f"Sm_{SKILL}", f"Step_{SKILL}_Show",
         sm_gate.T_SM_CHAIN, sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP, sm_gate.T_EXECUTION_STATE]


def _cleanup(run):
    for n in NODES:
        if n.startswith("Zztest_S2sm_") or n.startswith(("Sm_Chain_Zztest", "Sm_Zztest", "Step_Zztest")):
            run("MATCH (n:Wiki {n:$n}) DETACH DELETE n", {"n": n})


def main():
    conn = _conn()
    if conn is None:
        print("FATAL: no neo4j", file=sys.stderr); sys.exit(1)
    run = _mk_run(conn)
    _cleanup(run)
    for t in (sm_gate.T_SM_CHAIN, sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP, sm_gate.T_EXECUTION_STATE):
        run("MERGE (n:Wiki {n:$n})", {"n": t})
    run("MERGE (s:Wiki {n:$n}) SET s.d='a test skill concept'", {"n": SKILL})
    results = {}
    try:
        # (1) convert: builds the show-Core; get_sm_chain returns exactly 1 SM
        info = sm_gate.skill_to_sm(SKILL, run)
        core = sm_gate.get_sm_chain(SKILL, run)
        results["1_core_has_one_sm"] = (
            len(core) == 1 and core[0]["sm_id"] == f"Sm_{SKILL}" and info["sm_id"] == f"Sm_{SKILL}")

        # (2) the show step exists and has NO required_pattern
        entry = sm_gate._entry_step(f"Sm_{SKILL}", run)
        results["2_show_step_no_pattern"] = (
            entry is not None and entry["id"] == f"Step_{SKILL}_Show"
            and not entry.get("required_pattern"))

        # (3) sm_chain_visit is OFF: require_next None AND actor not locked
        cv = sm_gate.sm_chain_visit(ACTOR, SKILL, run)
        life = sm_gate.get_lifecycle(ACTOR, run)
        results["3_off_no_require_no_lock"] = (
            cv.get("require_next") is None
            and (life is None or life.get("status") != "locked"))

        # (4) idempotent: a 2nd conversion does not duplicate Core / SM_CHAIN_RUNS / SM
        sm_gate.skill_to_sm(SKILL, run)
        core2 = sm_gate.get_sm_chain(SKILL, run)
        dup = run("""MATCH (sk:Wiki {n:$n})-[h:HAS_SM_CHAIN]->(c:Wiki)-[r:SM_CHAIN_RUNS]->(sm:Wiki)
                     RETURN count(DISTINCT c) AS cores, count(r) AS runs, count(DISTINCT sm) AS sms""",
                  {"n": SKILL})
        d = dup[0] if dup else {}
        results["4_idempotent"] = (
            len(core2) == 1 and d.get("cores") == 1 and d.get("runs") == 1 and d.get("sms") == 1)
    finally:
        _cleanup(run)

    print("\n=== skill_to_sm E2E (skill->SM converter v0, off-by-default show-Core) ===")
    ok = True
    for k in ["1_core_has_one_sm", "2_show_step_no_pattern", "3_off_no_require_no_lock", "4_idempotent"]:
        v = results.get(k)
        ok = ok and (v is True)
        print(f"  {k:<26} {'PASS' if v is True else 'FAIL ('+str(v)+')'}")
    print(f"\nE2E SKILL-TO-SM: {'PASS' if ok else 'FAIL'}  (test nodes removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
