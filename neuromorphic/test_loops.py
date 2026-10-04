"""Three-loop machine tests — the joined SDK's laws, exact; seeded rng.

Covers: the machine as data (round trip); the GATE (non-match refused with
the exact pattern + instruction — the refusal is the next-move instruction;
match advances; terminal unlocks; default-ungated when no cursor); selection
(argmax = sm_gate auto-advance; the softmax bandit explores under
mutation_rate, seeded); THE CONDUCTION LAW AS CATASTROPHE GUARD (a cold
GP-style transition is never selected, whatever its weight); the middle loop
(reward requires warrant evidence, potentiates exactly the traversed path,
and REFUSES mock-tagged evidence hard); the outer loop end-to-end (GP over
the machine's own config; apply_champion refuses without the handler seat;
after acceptance the promoted transition carries the promotion warrant and
CONDUCTS).

Run: python3 knowledge/carton-mcp/neuromorphic/test_loops.py
"""
import os
import random
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.expanduser("~/repo/lfpoop"))

from neuromorphic.loops import (LearningMachine, Refusal,  # noqa: E402
                                MockWarrantRefused, SoftmaxBandit)
from lfpoop import gp as GP  # noqa: E402
from lfpoop import deltas as DL  # noqa: E402
from lfpoop.codething import Store, accept_witness  # noqa: E402

MACHINE = {
    "start": "draft",
    "states": {
        "draft": {"pattern": r"write\(", "instruction": "write the draft",
                  "terminal": False},
        "review": {"pattern": r"review\(", "instruction": "review it",
                   "terminal": False},
        "polish": {"pattern": r"polish\(", "instruction": "polish it",
                   "terminal": False},
        "done": {"pattern": "", "instruction": "", "terminal": True},
    },
    "transitions": [
        {"from": "draft", "to": "review", "weight": 2},
        {"from": "draft", "to": "polish", "weight": 1},
        {"from": "review", "to": "done", "weight": 1},
        {"from": "polish", "to": "done", "weight": 1},
    ],
}


def main():
    checks = {}

    m = LearningMachine(MACHINE, source="test_program")
    d = m.to_data()
    checks["machine_is_data_roundtrip"] = (
        d["start"] == "draft" and len(d["transitions"]) == 4
        and all(t["warrant"].startswith("programmed:")
                for t in d["transitions"].values()))

    # default-ungated; the gate refuses with pattern + instruction.
    checks["default_ungated"] = m.step("ghost", "anything")["status"] == "unlocked"
    m.lock("alice")
    try:
        m.step("alice", "delete(everything)")
        checks["gate_refusal_is_instruction"] = False
    except Refusal as e:
        checks["gate_refusal_is_instruction"] = (
            "write\\(" in str(e) and "write the draft" in str(e))

    # match advances via argmax (sm_gate auto-advance: heavier wins).
    r = m.step("alice", "write(the draft)")
    checks["argmax_advance"] = (r == {"status": "advanced", "from": "draft",
                                      "to": "review"})
    r2 = m.step("alice", "review(the draft)")
    r3 = m.step("alice", "anything")           # terminal: unlocks
    checks["terminal_unlocks"] = (r2["to"] == "done"
                                  and r3 == {"status": "unlocked",
                                             "at": "done"}
                                  and m.step("alice", "x")["status"]
                                  == "unlocked")

    # the softmax bandit explores: under mutation_rate=1.0 the lighter arm
    # gets picked sometimes across seeds; at pressure with rate 0, heavy wins.
    picks = set()
    for seed in range(8):
        mb = LearningMachine(MACHINE, selector=SoftmaxBandit(
            pressure=3.0, mutation_rate=1.0, rng=random.Random(seed)))
        mb.lock("bob")
        picks.add(mb.step("bob", "write(x)")["to"])
    checks["bandit_explores"] = picks == {"review", "polish"}
    mh = LearningMachine(MACHINE, selector=SoftmaxBandit(
        pressure=50.0, mutation_rate=0.0, rng=random.Random(1)))
    mh.lock("carol")
    checks["bandit_exploits_at_pressure"] = (
        mh.step("carol", "write(x)")["to"] == "review")

    # THE CONDUCTION LAW: a cold transition never conducts, whatever weight.
    cold_cfg = {**MACHINE, "transitions": MACHINE["transitions"] + [
        {"from": "draft", "to": "done", "weight": 999, "warrant": ""}]}
    mc = LearningMachine(cold_cfg)
    mc.lock("dave")
    checks["cold_transition_cannot_conduct"] = (
        mc.step("dave", "write(x)")["to"] == "review")

    # middle loop: reward potentiates EXACTLY the traversed path; mock
    # evidence refused hard.
    m2 = LearningMachine(MACHINE)
    m2.lock("eve")
    m2.step("eve", "write(x)")
    m2.step("eve", "review(x)")
    out = m2.reward("eve", "warrant:shipped-artifact-123")
    checks["reward_potentiates_traversed_path"] = (
        out == [("draft", "review", 3), ("review", "done", 2)])
    try:
        m2.reward("eve", "mock:simulated-customer")
        checks["mock_warrant_refused_hard"] = False
    except MockWarrantRefused as e:
        checks["mock_warrant_refused_hard"] = "never move real weights" in str(e)

    # outer loop: GP proposes a draft->done shortcut; the champion cannot
    # apply without the handler; after acceptance it conducts, warranted.
    def shortcut_mutator(train_view, rng, registry):
        return [GP.genome([DL.delta("add", ("transitions", "shortcut"),
                                    {"from": "draft", "to": "done",
                                     "weight": 5})], "m_shortcut")]

    def eval_fn(phen):
        has = any(t.get("from") == "draft" and t.get("to") == "done"
                  for t in phen["transitions"].values())
        return {"primary": {"k": 9 if has else 5, "n": 10}}

    m3 = LearningMachine(MACHINE)
    run = m3.evolve_topology([shortcut_mutator], eval_fn, train_view=[],
                             generations=1, mu=1, rng=random.Random(4))
    champ, fit = run["survivors"][0]
    checks["outer_loop_finds_champion"] = fit["primary"]["k"] == 9

    with tempfile.TemporaryDirectory() as td:
        store = Store(os.path.join(td, "store.jsonl"))
        try:
            m3.apply_champion(champ, store)
            checks["apply_refuses_without_handler"] = False
        except PermissionError as e:
            checks["apply_refuses_without_handler"] = (
                "cannot crown its own rewiring" in str(e))
        accept_witness(store, champ["id"], "external:governor:accept=yes")
        promoted = m3.apply_champion(champ, store)
        pd = promoted.to_data()
        shortcut = [t for t in pd["transitions"].values()
                    if t["from"] == "draft" and t["to"] == "done"]
        promoted.lock("frank")
        checks["promoted_transition_conducts_warranted"] = (
            len(shortcut) == 1
            and shortcut[0]["warrant"].startswith(
                f"promoted:{champ['id']}:by:external:governor")
            and promoted.step("frank", "write(x)")["to"] == "done")

    print()
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    failed = [k for k, v in checks.items() if not v]
    if failed:
        print(f"\nFAILED: {failed}")
        return 1
    print(f"\nTHREE-LOOP MACHINE: the machine is data; the gate refuses with "
          f"the instruction; argmax = sm_gate auto-advance and the softmax "
          f"bandit explores; COLD transitions cannot conduct (the "
          f"catastrophe guard is the physics); reward potentiates only the "
          f"warranted traversed path and mock warrant is refused hard; GP "
          f"rewires the topology only through the handler seat. "
          f"{len(checks)} checks green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
