"""DTO interface tests — design_brain on the REAL b6 instance (pure lab).

D1  anatomy is a READING: the brain's regions == the union of the two real
    structure artifacts (config.json departments + agents/*.md personas),
    provenance carried on every region node.
D2  experience wires the cortex from the thing's OWN docs: the Hebbian
    synapse set equals an INDEPENDENT re-derivation (re-scan of the same
    real docs against the alias map) — and every synapse is COLD (born of
    association; b6 has no lived operation to warrant anything: the event
    stream is empty).
D3  the apex check-up is read, never staged: present == {gate, heartbeat,
    motor_connector, percept_channel}; missing == [governor_seat,
    graph_residence, ratchet] — the same facts the 09-right engine run
    derived; checkup() names them.

Run: PYTHONPATH=base/soma-prolog python3 knowledge/carton-mcp/neuromorphic/test_dto.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "repo", "sra-git",
                                "base", "soma-prolog"))

from neuromorphic.dto import design_brain  # noqa: E402
from soma_prolog.extractor import read_thing  # noqa: E402

_WORD = re.compile(r"[a-z][a-z0-9_]{2,}")


def main():
    checks = {}
    reading = read_thing()
    brain = design_brain(reading)
    c = brain.computer

    # D1 — anatomy == the two real artifacts' union, provenance carried.
    cfg = json.load(open("/jobworld_data/b6-outreach/config.json"))
    expected = {"dept_" + d["id"].replace("-", "_")
                for d in cfg["departments"]}
    agents = "/jobworld_data/b6-outreach/agents"
    expected |= {"dept_" + os.path.splitext(f)[0].lower()
                 for f in os.listdir(agents)
                 if f.endswith(".md") and f != "README.md"}
    got = {n for n in c.s.nodes() if c.s.node(n).get("kind") == "region"}
    checks["D1_anatomy_is_the_reading"] = (
        got == expected
        and all(c.s.node(n).get("provenance") for n in got))

    # D2 — Hebbian wiring == independent re-derivation from the same docs;
    # all synapses COLD (no lived operation yet — the honest newborn state).
    alias = {}
    for r in reading["regions"]:
        for a in r.get("aliases", []):
            alias[a.lower()] = r["name"]
    expected_wiring = set()
    for sp in reading["speech"]:
        words = set(_WORD.findall(sp["text"].lower()))
        for w in words:
            tgt = sp["region"] if False else alias.get(w)
            if tgt is None and w in expected:
                tgt = w
            if tgt and tgt != sp["region"]:
                expected_wiring.add((sp["region"], tgt))
    got_wiring = {(s, d) for (s, d, _, _) in c.s.edges(kind="wiring")}
    checks["D2_cortex_wired_from_own_docs_exact"] = (
        got_wiring == expected_wiring and len(got_wiring) > 0)
    if not checks["D2_cortex_wired_from_own_docs_exact"]:
        print("  [D2] got-expected:", sorted(got_wiring - expected_wiring))
        print("  [D2] expected-got:", sorted(expected_wiring - got_wiring))
    cold = {(s.split("->")[0]) for (k, s) in c.grade()
            if k == "unwarranted_wiring"}
    checks["D2b_all_synapses_cold"] = (
        sum(1 for g in c.grade() if g[0] == "unwarranted_wiring")
        == len(got_wiring))

    # D3 — the apex check-up, read off reality.
    a = brain.apex()
    checks["D3_apex_read_not_staged"] = (
        sorted(a["present"]) == ["gate", "heartbeat", "motor_connector",
                                 "percept_channel"]
        and a["missing"] == ["governor_seat", "graph_residence", "ratchet"])
    cu = brain.checkup()
    checks["D3b_checkup_names_the_facts"] = (
        "perceives" in cu and "acts" in cu
        and "cannot reside" in cu and "cannot ratchet" in cu
        and "ungoverned" in cu and "COLD" in cu)
    print("  CHECKUP:", cu)

    print()
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    failed = [k for k, v in checks.items() if not v]
    if failed:
        print(f"\nFAILED: {failed}")
        return 1
    print(f"\nDTO: a brain designed FOR b6 from its own body — anatomy read "
          f"from two real artifacts, cortex wired by its own documents "
          f"({len(got_wiring)} cold synapses awaiting lived operation), apex "
          f"graded off reality. The interface added no machinery. "
          f"{len(checks)} checks green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
