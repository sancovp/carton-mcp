#!/usr/bin/env python3
"""
CROSS-PACKAGE E2E for the equip_persona -> carton-SM-gate ACTOR wire (sub-step 1 of the equip_persona
wire, Isaac 2026-06-20 fork b: equipping a persona makes its carton_identity the gate's actor).

THE PROBLEM this proves solved: equip_persona runs in the skill-manager-mcp process; carton's
_sm_actor() reads the acting identity in the SEPARATE carton-mcp process. Runtime os.environ does NOT
cross processes — so the persona hands its carton_identity to the gate via a cross-process FILE
(exactly like sm_gate's own kill-switch/enable flag-files). This test proves the full handoff:

  (1) DEFAULT-OFF: no active-identity file => get_active_identity() is None AND _sm_actor() == 'Gnosys'
      (carton behaviour byte-identical until a persona is equipped).
  (2) sm_gate.set_active_identity('X') => file written; get_active_identity()=='X'; the LIVE server's
      _sm_actor() returns 'X' (the file overrides env/default).
  (3) THE REAL CROSS-PACKAGE WIRE: a real SkillManager.equip_persona(P) (skill-manager side) writes the
      file, and the carton server's _sm_actor() now returns P's carton_identity. report.carton_actor_set
      echoes it.
  (4) deactivate_persona() / clear_active_identity() removes the file => _sm_actor() back to 'Gnosys'.

Self-cleaning: a temp skills_dir (so the test persona never touches real _personas.json), a temp
active-identity file, all removed at the end. Run:
  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... python3 tests/test_equip_persona_actor_wire.py
"""
import os
import sys
import shutil
import tempfile

# _ACTIVE_IDENTITY_FILE is read at sm_gate MODULE LOAD — point it at a throwaway path BEFORE import.
_IDFILE = os.path.join(tempfile.gettempdir(), "zztest_actor_identity")
os.environ["CARTON_SM_ACTIVE_IDENTITY"] = _IDFILE
# deterministic default: drop any ambient actor env so the fallback resolves to 'Gnosys'
os.environ.pop("CARTON_SM_ACTOR", None)
os.environ.pop("AGENT_IDENTITY", None)
os.environ.setdefault("NEO4J_URI", "bolt://host.docker.internal:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "password")
os.environ.setdefault("HEAVEN_DATA_DIR", "/tmp/heaven_data")

if os.path.exists(_IDFILE):
    os.remove(_IDFILE)  # start with no active identity

from carton_mcp import sm_gate                      # noqa: E402  (env must be set first)
from carton_mcp import server_fastmcp as srv        # noqa: E402

WIRE_IDENTITY = "Zztest_Wire_Identity"
SET_IDENTITY = "Zztest_Set_Identity"


def main():
    results = {}
    tmp_skills = tempfile.mkdtemp(prefix="zztest_skills_")
    try:
        # (1) DEFAULT-OFF: no file => None + 'Gnosys'
        if os.path.exists(_IDFILE):
            os.remove(_IDFILE)
        results["1_default_off"] = (
            sm_gate.get_active_identity() is None and srv._sm_actor() == "Gnosys")

        # (2) set_active_identity => file written, read by both sm_gate and the live server _sm_actor
        sm_gate.set_active_identity(SET_IDENTITY)
        results["2_set_overrides"] = (
            sm_gate.get_active_identity() == SET_IDENTITY and srv._sm_actor() == SET_IDENTITY)

        # (3) THE REAL WIRE: a real SkillManager.equip_persona writes the file; carton _sm_actor sees it
        sm_gate.clear_active_identity()
        from skill_manager.core import SkillManager
        mgr = SkillManager(skills_dir=tmp_skills, agent_id="zztest")
        mgr.create_persona(
            name="Zztest_Wire_Persona", domain="test", description="throwaway test persona",
            frame="test frame", carton_identity=WIRE_IDENTITY)
        report = mgr.equip_persona("Zztest_Wire_Persona")
        results["3_equip_persona_wires_actor"] = (
            sm_gate.get_active_identity() == WIRE_IDENTITY
            and srv._sm_actor() == WIRE_IDENTITY
            and report.get("carton_actor_set") == WIRE_IDENTITY)

        # (4) deactivate_persona clears the actor => back to default
        mgr.deactivate_persona()
        results["4_deactivate_clears"] = (
            sm_gate.get_active_identity() is None and srv._sm_actor() == "Gnosys")
    finally:
        if os.path.exists(_IDFILE):
            os.remove(_IDFILE)
        shutil.rmtree(tmp_skills, ignore_errors=True)

    print("\n=== equip_persona -> carton-SM ACTOR wire E2E (cross-process file handoff) ===")
    ok = True
    for k in ["1_default_off", "2_set_overrides", "3_equip_persona_wires_actor", "4_deactivate_clears"]:
        v = results.get(k)
        ok = ok and (v is True)
        print(f"  {k:<30} {'PASS' if v is True else 'FAIL ('+str(v)+')'}")
    print(f"\nE2E EQUIP-PERSONA-ACTOR-WIRE: {'PASS' if ok else 'FAIL'}  (temp skills dir + id file removed)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
