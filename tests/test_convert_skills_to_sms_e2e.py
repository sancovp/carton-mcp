#!/usr/bin/env python3
"""
E2E for convert_skills_to_sms — the batch skill->SM converter (build-plan item 1 follow-through).

generate_system_prompt's "globally-available SMs from the graph" is only real once skill->SM nodes EXIST.
This batches skill_to_sm over a SET of skills to populate them, then proves the GENERATOR lists all of them
FROM THE GRAPH — the full carton-side loop end-to-end. Scope is explicit + capped (never blasts the corpus).
Proves:
  (1) BATCH: convert_skills_to_sms(run, skills=[A,B,C]) returns count==3 + the 3 Sm_<x> ids, and each
      skill now has its Sm_Chain in the graph (list_globally_available_sms finds all 3).
  (2) GENERATOR LISTS THEM: generate_system_prompt's sms section names all 3 skill SMs + their triggers.
  (3) IDEMPOTENT: a 2nd batch over the same skills does not duplicate (count stable, still exactly 3 SMs).
  (4) SAFE DEFAULT: convert_skills_to_sms(run) with NEITHER skills NOR limit converts NOTHING (count 0) —
      it can never blast the whole skill corpus by accident.

NOTE: the `limit=` path queries ALL `IS_A Skill` concepts (which include the real corpus), so it is NOT
exercised here to avoid persistent writes to real skills; it is a simple bounded query + the same
skill_to_sm calls covered by the explicit-skills path. Self-cleaning ('Zztest_Csts_' + derived names). Run:
  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... python3 tests/test_convert_skills_to_sms_e2e.py
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


SKILLS = ["Zztest_Csts_Alpha", "Zztest_Csts_Beta", "Zztest_Csts_Gamma"]
ACTOR = "Zztest_Csts_Actor"
DERIVED = [n for s in SKILLS for n in (f"Sm_Chain_{s}", f"Sm_{s}", f"Step_{s}_Show")]
NODES = SKILLS + [ACTOR] + DERIVED + [
    sm_gate.T_SM_CHAIN, sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP]


def _cleanup(run):
    for n in NODES:
        if n.startswith(("Zztest_Csts_", "Sm_Chain_Zztest", "Sm_Zztest", "Step_Zztest")):
            run("MATCH (n:Wiki {n:$n}) DETACH DELETE n", {"n": n})


def main():
    conn = _conn()
    if conn is None:
        print("FATAL: no neo4j", file=sys.stderr); sys.exit(1)
    run = _mk_run(conn)
    _cleanup(run)
    for t in (sm_gate.T_SM_CHAIN, sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP):
        run("MERGE (n:Wiki {n:$n})", {"n": t})
    run("MERGE (a:Wiki {n:$n})", {"n": ACTOR})
    for s in SKILLS:
        run("MERGE (sk:Wiki {n:$n}) MERGE (sk)-[:IS_A]->(:Wiki {n:'Skill'}) "
            "SET sk.has_when=$w", {"n": s, "w": f"when you need {s}"})

    results = {}
    try:
        # (1) batch converts exactly the 3 + each Sm_Chain exists (listing finds all 3)
        res = sm_gate.convert_skills_to_sms(run, skills=SKILLS)
        listed = {x.get("sm_id") for x in sm_gate.list_globally_available_sms(run)}
        results["1_batch_converts_set"] = (
            res.get("count") == 3
            and set(res.get("converted", [])) == {f"Sm_{s}" for s in SKILLS}
            and all(f"Sm_{s}" in listed for s in SKILLS))

        # (2) generator lists all 3 skill SMs + their triggers from the graph
        out = sm_gate.generate_system_prompt(ACTOR, run, persona_frame="frame")
        sms_section = out["sections"]["sms"]
        results["2_generator_lists_all"] = all(
            (f"Sm_{s}" in sms_section and f"when you need {s}" in sms_section) for s in SKILLS)

        # (3) idempotent: a 2nd batch does not duplicate (count stable; exactly 3 Sm_Chains, 3 SMs)
        res2 = sm_gate.convert_skills_to_sms(run, skills=SKILLS)
        dup = run("""MATCH (sk:Wiki)-[:HAS_SM_CHAIN]->(c:Wiki)-[r:SM_CHAIN_RUNS]->(sm:Wiki)
                     WHERE sk.n IN $names
                     RETURN count(DISTINCT c) AS chains, count(r) AS runs, count(DISTINCT sm) AS sms""",
                  {"names": SKILLS})
        d = dup[0] if dup else {}
        results["3_idempotent"] = (
            res2.get("count") == 3
            and d.get("chains") == 3 and d.get("runs") == 3 and d.get("sms") == 3)

        # (4) safe default: no skills + no limit => converts nothing
        res3 = sm_gate.convert_skills_to_sms(run)
        results["4_safe_default_zero"] = (res3.get("count") == 0 and res3.get("converted") == [])
    finally:
        _cleanup(run)

    print("\n=== convert_skills_to_sms E2E (batch skill->SM + generator lists from graph) ===")
    ok = True
    for k in ["1_batch_converts_set", "2_generator_lists_all", "3_idempotent", "4_safe_default_zero"]:
        v = results.get(k)
        ok = ok and (v is True)
        print(f"  {k:<24} {'PASS' if v is True else 'FAIL ('+str(v)+')'}")
    print(f"\nE2E CONVERT-SKILLS-TO-SMS: {'PASS' if ok else 'FAIL'}  (test nodes removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
