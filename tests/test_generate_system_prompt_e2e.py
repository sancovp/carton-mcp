#!/usr/bin/env python3
"""
E2E for generate_system_prompt — the graph->system-prompt GENERATOR (build-plan item 2).

Isaac 2026-06-20 (Claude_P_And_Build_Plan): claude -p controls the system prompt, so it is REBUILT FROM
CARTON each turn; "globally-available SMs go in the system prompt exactly like skills now BUT listed FROM
THE GRAPH." This generator assembles the prompt from graph reads. The persona_frame (the persona's role /
system-prompt text) is INJECTED (it lives in skill-manager's Persona.frame, not carton — frame-in-carton is
deferred). Proves:
  (1) PERSONA: an injected persona_frame string appears verbatim in the persona section + the prompt.
  (2) GLOBALLY-AVAILABLE SMs: after skill_to_sm builds a skill->SM, the generator LISTS it FROM THE GRAPH
      (the Sm_<skill> id + the backing skill's trigger appear in the sms section); a legacy IS_A
      State_Machine node with NO backing Core is EXCLUDED.
  (3) CURRENT-LOCATION SM: with the actor locked at a step with a required_pattern, the location section
      names the step + says the next move is REQUIRED; with no lock, it says "not in any flow".
  (4) WORK/DEV MODE: Execution_State.region=self => mode DEV; an external region => WORK; the `mode`/
      `region` params override the graph read.
  (5) FAILS SOFT: an unknown actor + empty injected ghost still returns a non-empty prompt (default markers),
      never raising.

Self-cleaning ('Zztest_Gsp_' prefix + derived Sm_Chain_/Sm_/Step_/Execution_State names). Run:
  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... python3 tests/test_generate_system_prompt_e2e.py
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


SKILL = "Zztest_Gsp_Skill"
LEGACY_SM = "Zztest_Gsp_Legacy_Sm"        # IS_A State_Machine but NO backing Core -> must be excluded
ACTOR = "Zztest_Gsp_Actor"
NODES = [SKILL, LEGACY_SM, ACTOR, f"{ACTOR}_Execution_State",
         f"Sm_Chain_{SKILL}", f"Sm_{SKILL}", f"Step_{SKILL}_Show",
         sm_gate.T_SM_CHAIN, sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP, sm_gate.T_EXECUTION_STATE]


def _cleanup(run):
    for n in NODES:
        if n.startswith("Zztest_Gsp_") or n.startswith(("Sm_Chain_Zztest", "Sm_Zztest", "Step_Zztest")):
            run("MATCH (n:Wiki {n:$n}) DETACH DELETE n", {"n": n})


def main():
    conn = _conn()
    if conn is None:
        print("FATAL: no neo4j", file=sys.stderr); sys.exit(1)
    run = _mk_run(conn)
    _cleanup(run)
    for t in (sm_gate.T_SM_CHAIN, sm_gate.T_STATE_MACHINE, sm_gate.T_TRAVERSAL_STEP, sm_gate.T_EXECUTION_STATE):
        run("MERGE (n:Wiki {n:$n})", {"n": t})
    # the ACTOR node MUST exist (the gate's actor = a real identity concept; _lock_into_sm_chain's leading
    # MATCH (a) no-ops without it). A skill concept with a when-trigger, + a LEGACY bare State_Machine
    # (no Core) that must be excluded from the globally-available listing.
    run("MERGE (a:Wiki {n:$n})", {"n": ACTOR})
    run("MERGE (s:Wiki {n:$n}) SET s.d='a test skill', s.has_when='when you need the Gsp test thing'", {"n": SKILL})
    run(f"MERGE (m:Wiki {{n:$n}}) MERGE (m)-[:IS_A]->(:Wiki {{n:'{sm_gate.T_STATE_MACHINE}'}})", {"n": LEGACY_SM})

    results = {}
    try:
        # (1) PERSONA frame injected verbatim
        out = sm_gate.generate_system_prompt(ACTOR, run, persona_frame="I am the GSP test persona.")
        results["1_persona_frame_injected"] = (
            "I am the GSP test persona." in out["sections"]["persona"]
            and "I am the GSP test persona." in out["prompt"])

        # (2) globally-available SMs listed from the graph; legacy bare SM excluded
        sm_gate.skill_to_sm(SKILL, run)
        sms = sm_gate.list_globally_available_sms(run)
        sm_ids = [s.get("sm_id") for s in sms]
        out2 = sm_gate.generate_system_prompt(ACTOR, run, persona_frame="g")
        results["2_sms_listed_from_graph"] = (
            f"Sm_{SKILL}" in sm_ids and LEGACY_SM not in sm_ids
            and f"Sm_{SKILL}" in out2["sections"]["sms"]
            and "when you need the Gsp test thing" in out2["sections"]["sms"])

        # (3) current-location: lock the actor at a required-pattern step, then unlocked
        step = f"Step_{SKILL}_Show"
        run("MATCH (st:Wiki {n:$s}) SET st.required_pattern='get_concept.*Target', st.text='go to Target'",
            {"s": step})
        sm_gate._lock_into_sm_chain(ACTOR, f"Sm_{SKILL}", step, run)
        out3 = sm_gate.generate_system_prompt(ACTOR, run, persona_frame="g")
        locked_ok = (step in out3["sections"]["location"]
                     and "REQUIRED" in out3["sections"]["location"]
                     and "get_concept.*Target" in out3["sections"]["location"])
        # unlock -> "not in any flow"
        run("MATCH (a:Wiki {n:$a})-[:HAS_LIFECYCLE]->(s:Wiki) SET s.status='unlocked'", {"a": ACTOR})
        out3b = sm_gate.generate_system_prompt(ACTOR, run, persona_frame="g")
        results["3_current_location"] = locked_ok and "not in any flow" in out3b["sections"]["location"]

        # (4) WORK/DEV mode: region=self => dev; external => work; param override
        run("MATCH (a:Wiki {n:$a})-[:HAS_LIFECYCLE]->(s:Wiki) SET s.region='self'", {"a": ACTOR})
        dev = sm_gate.generate_system_prompt(ACTOR, run, persona_frame="g")
        run("MATCH (a:Wiki {n:$a})-[:HAS_LIFECYCLE]->(s:Wiki) SET s.region='Some_External_Domain'", {"a": ACTOR})
        work = sm_gate.generate_system_prompt(ACTOR, run, persona_frame="g")
        override = sm_gate.generate_system_prompt(ACTOR, run, persona_frame="g", mode="dev")
        results["4_work_dev_mode"] = (
            dev["mode"] == "dev" and "DEV" in dev["sections"]["mode"]
            and work["mode"] == "work" and "Some_External_Domain" in work["sections"]["mode"]
            and override["mode"] == "dev")

        # (5) fails soft on unknown actor + no frame -> non-empty prompt, default markers, no raise
        soft = sm_gate.generate_system_prompt("Zztest_Gsp_Nobody", run)
        results["5_fails_soft"] = (
            isinstance(soft.get("prompt"), str) and len(soft["prompt"]) > 0
            and "MODE:" in soft["prompt"] and "not in any flow" in soft["sections"]["location"])
    finally:
        _cleanup(run)

    print("\n=== generate_system_prompt E2E (graph->system-prompt generator, item 2) ===")
    ok = True
    for k in ["1_persona_frame_injected", "2_sms_listed_from_graph", "3_current_location",
              "4_work_dev_mode", "5_fails_soft"]:
        v = results.get(k)
        ok = ok and (v is True)
        print(f"  {k:<26} {'PASS' if v is True else 'FAIL ('+str(v)+')'}")
    print(f"\nE2E GENERATE-SYSTEM-PROMPT: {'PASS' if ok else 'FAIL'}  (test nodes removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
