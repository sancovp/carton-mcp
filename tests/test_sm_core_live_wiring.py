#!/usr/bin/env python3
"""
LIVE-WIRING E2E for the Core require-next gate on the REAL get_concept MCP tool surface.

Verifies the wiring in server_fastmcp.py (the increment that makes the Core gate LIVE): get_concept
serves the concept's content as always, and — only when SM-gating is ON and the visited concept has a
Core — APPENDS a "⛓ REQUIRED NEXT" note and arms the require-next, with the next-move enforced by the
existing _sm_gate_check (routing-persistence). Proves:
  (1) DEFAULT-OFF: with the enable flag absent, get_concept(SUBJECT) is byte-identical (no require-next).
  (2) ON + Core: get_concept(SUBJECT) SERVES the content AND appends "⛓ REQUIRED NEXT" (not withheld).
  (3) ROUTING-PERSISTENCE on the live tool: while armed, get_concept(OTHER) is REFUSED (GateRefusal).
  (4) the REQUIRED move via the live tool: query_wiki_graph(matching) advances -> terminal -> UNLOCK.

Imports the real server module (which initializes the shared neo4j conn at load). Self-cleaning:
'Zztest_Lw_' nodes + the flag file are removed at the end. Run:
  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... python3 tests/test_sm_core_live_wiring.py
"""
import os
import sys
import tempfile

# The enable-flag path is read at MODULE LOAD, and _sm_actor reads CARTON_SM_ACTOR — set both BEFORE import.
_FLAG = os.path.join(tempfile.gettempdir(), "zztest_lw_sm_gate_enabled")
os.environ["CARTON_SM_GATE_ENABLED"] = _FLAG
os.environ["CARTON_SM_ACTOR"] = "Zztest_Lw_Actor"
os.environ.setdefault("NEO4J_URI", "bolt://host.docker.internal:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "password")
os.environ.setdefault("HEAVEN_DATA_DIR", "/tmp/heaven_data")

if os.path.exists(_FLAG):
    os.remove(_FLAG)   # start OFF

from carton_mcp import server_fastmcp as srv   # noqa: E402  (env must be set first)
from carton_mcp import sm_gate                  # noqa: E402

# srv._sm_actor() resolves get_active_identity() FIRST (the shared carton identity, e.g. 'gnosys'),
# which OVERRIDES CARTON_SM_ACTOR — so the live gate would lock a non-test actor whose Wiki node we
# don't control (and _lock_into_sm_chain MATCHes, never MERGEs, the actor node, so the lock would
# silently no-op for our seeded actor). Pin the live tool's actor to the hermetic test actor we seed
# and assert on. This still exercises the REAL gate path (gate_call / sm_chain_visit /
# _lock_into_sm_chain / get_active_step); only the identity lookup is stubbed.
srv._sm_actor = lambda: "Zztest_Lw_Actor"

SUBJECT = "Zztest_Lw_Subject"
OTHER = "Zztest_Lw_Other"
NODES = [SUBJECT, OTHER, "Zztest_Lw_Core", "Zztest_Lw_Sm", "Zztest_Lw_EntryStep",
         "Zztest_Lw_Show_Sm", "Zztest_Lw_Show_Step",
         "Zztest_Lw_Actor", "Zztest_Lw_Actor_Execution_State"]


def _run(q, p=None):
    return srv._sm_run(q, p or {})


def _program():
    for t in ("Sm_Chain", "State_Machine", "Traversal_Step", "Execution_State"):
        _run("MERGE (n:Wiki {n:$n})", {"n": t})
    _run("MERGE (o:Wiki {n:'Zztest_Lw_Other'}) SET o.d='another concept'", {})
    _run("MERGE (subj:Wiki {n:'Zztest_Lw_Subject'}) SET subj.d='THE SERVED BODY of the subject concept'", {})
    _run("MERGE (a:Wiki {n:'Zztest_Lw_Actor'})", {})
    # GATING Sm_Chain = a 2-SM stack (STACK-SIZE ACTIVATION rule, sm_gate.py:399, Isaac 2026-06-20 16:17:
    # a Sm_Chain is ON iff its stack holds >1 SM; a lone SM is the OFF show-SM). order-0 show-SM (no
    # required_pattern, serves only) + order-1 gating SM whose entry step requires query_wiki_graph.
    # Built via the proven create_sm_chain factory (the hand-MERGE it abstracts); sm_chain_name pins the
    # core node to 'Zztest_Lw_Core' for cleanup. A 1-SM seed would (correctly) NOT arm — the prior bug.
    sm_gate.create_sm_chain(
        "Zztest_Lw_Subject",
        [
            {"name": "Zztest_Lw_Show_Sm",
             "steps": [{"id": "Zztest_Lw_Show_Step", "required_pattern": None,
                        "text": "show the subject", "next": None}]},
            {"name": "Zztest_Lw_Sm",
             "steps": [{"id": "Zztest_Lw_EntryStep", "required_pattern": "query_wiki_graph",
                        "text": "run query_wiki_graph(...) next", "next": None}]},
        ],
        _run,
        sm_chain_name="Zztest_Lw_Core",
        domain="System", subdomain="Sm_Core_Live_Wiring", personal_domain="cave",
    )


def _cleanup():
    for n in NODES:
        _run("MATCH (n:Wiki {n:$n}) DETACH DELETE n", {"n": n})
    if os.path.exists(_FLAG):
        os.remove(_FLAG)


def _text(tc):
    return tc.text if hasattr(tc, "text") else str(tc)


def main():
    _cleanup()
    _program()
    results = {}
    try:
        # (1) DEFAULT-OFF (flag absent): no require-next appended
        out = _text(srv.get_concept(SUBJECT))
        results["1_default_off_no_require"] = (
            "THE SERVED BODY" in out and "REQUIRED NEXT" not in out)

        # turn the gate ON
        open(_FLAG, "w").close()

        # (2) ON + Core: content SERVED + require-next APPENDED (not withheld)
        out = _text(srv.get_concept(SUBJECT))
        results["2_on_serves_and_arms"] = (
            "THE SERVED BODY" in out and "⛓ REQUIRED NEXT" in out and "query_wiki_graph" in out)

        # (3) ROUTING-PERSISTENCE: armed -> a non-matching next move on the live tool is REFUSED
        try:
            srv.get_concept(OTHER)
            results["3_wrong_next_refused"] = False
        except sm_gate.GateRefusal:
            results["3_wrong_next_refused"] = True

        # (4) the REQUIRED move via the live query tool advances -> terminal -> UNLOCK
        try:
            srv.query_wiki_graph("MATCH (n:Wiki {n:'Zztest_Lw_Other'}) RETURN n.n")
            unlocked = (sm_gate.get_lifecycle("Zztest_Lw_Actor", _run) or {}).get("status") == "unlocked"
            results["4_required_next_unlocks"] = unlocked
        except Exception as e:
            results["4_required_next_unlocks"] = f"ERR {e}"
    finally:
        _cleanup()

    print("\n=== sm_gate CORE LIVE-WIRING E2E (require-next on the real get_concept tool) ===")
    ok = True
    for k in ["1_default_off_no_require", "2_on_serves_and_arms",
              "3_wrong_next_refused", "4_required_next_unlocks"]:
        v = results.get(k)
        ok = ok and (v is True)
        print(f"  {k:<26} {'PASS' if v is True else 'FAIL ('+str(v)+')'}")
    print(f"\nE2E SM-CORE-LIVE: {'PASS' if ok else 'FAIL'}  (test nodes + flag removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
