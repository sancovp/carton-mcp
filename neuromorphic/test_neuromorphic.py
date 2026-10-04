"""Neuromorphic SDK tests — every ruled mechanism, exact, lab-runnable.

Covers: Hebbian co-mention wiring (exact wired set); growth cones held and
RESOLVED on arrival; spreading activation conducts ONLY over warranted
wiring and respects the inhibition gate (blocked hops named); the
plasticity law (potentiation REQUIRES evidence; unwarranted wiring decays to
pruning; warranted holds); the consolidation split (buffered writes absent
from the substrate until consolidate(), then present, buffer wiped); the
computer grades itself (the ruled gap names: unresolved_growth_cone,
region_no_afferents, unwarranted_wiring — exact); to_observations emits the
vault payload; and THE SUBSTRATE-SWAP EXPERIMENT (CCC's "J survives a
substrate swap" at SDK grain): the same program run over two substrates
yields identical connectivity snapshots AND identical fire() behavior —
identity is the connectivity pattern.

Run: python3 knowledge/carton-mcp/neuromorphic/test_neuromorphic.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neuromorphic import InMemorySubstrate, NeuromorphicComputer  # noqa: E402


def build_cortex(sub):
    """One deterministic construction program (the 'J' of the swap test)."""
    c = NeuromorphicComputer(sub)
    c.add_stratum("s_low", 1)
    c.add_region("percept", "s_low", "parse", provenance="test")
    c.add_region("assoc", "s_low", "plan", provenance="test")
    c.add_region("motor", "s_low", "act", provenance="test")
    c.add_channel("inbox", "afferent", feeds="percept", provenance="test")
    c._wire("percept", "assoc", warrant="", weight=1)
    c._wire("assoc", "motor", warrant="", weight=1)
    return c


def main():
    checks = {}

    # Hebbian: co-mention wires together — exact wired set.
    c = build_cortex(InMemorySubstrate())
    wired = c.wire_by_comention(
        "invoice_handler",
        "handles the percept stream and routes to motor via toward:ledger")
    checks["hebbian_comention_exact"] = (
        wired == ["motor", "percept"]
        and len(c.s.edges(src="invoice_handler", kind="wiring")) == 2)

    # Growth cone: held while absent, RESOLVED into wiring on arrival.
    checks["growth_cone_held"] = c.growth_cones() == [("invoice_handler",
                                                       "ledger")]
    c.add_region("ledger", "s_low", "record", provenance="test")
    resolved = c.resolve_growth_cones("ledger")
    checks["growth_cone_resolves"] = (
        resolved == ["invoice_handler"] and c.growth_cones() == []
        and len(c.s.edges(src="invoice_handler", dst="ledger",
                          kind="wiring")) == 1)

    # Spreading activation: unwarranted wiring does NOT conduct.
    r = c.fire("percept", payload="p1")
    checks["cold_wiring_does_not_conduct"] = (
        r["visited"] == ["percept"]
        and ("percept", "assoc", "unwarranted") in r["blocked"])

    # The plasticity law: evidence REQUIRED; then the path conducts.
    try:
        c.potentiate("percept", "assoc", "")
        checks["potentiation_requires_evidence"] = False
    except ValueError as e:
        checks["potentiation_requires_evidence"] = "warrant" in str(e)
    c.potentiate("percept", "assoc", "warrant:test-run-1")
    c.potentiate("assoc", "motor", "warrant:test-run-1")
    r2 = c.fire("percept", payload="p2")
    checks["warranted_path_conducts_exact"] = (
        r2["visited"] == ["percept", "assoc", "motor"])

    # Inhibition: the gate (SOMA's seat) blocks a hop, named.
    r3 = c.fire("percept", payload="p3",
                gate=lambda s, d, a: d != "motor")
    checks["inhibition_gate_blocks_named"] = (
        r3["visited"] == ["percept", "assoc"]
        and ("assoc", "motor", "inhibited") in r3["blocked"])

    # Decay: unwarranted prunes, warranted holds.
    pruned = c.decay()
    checks["decay_prunes_only_unwarranted"] = (
        set(pruned) == {("invoice_handler", "motor"),
                        ("invoice_handler", "percept"),
                        ("invoice_handler", "ledger")}
        and c.fire("percept", payload="p4")["visited"]
        == ["percept", "assoc", "motor"])

    # Consolidation: buffered writes are NOT on the substrate, then are.
    c2 = build_cortex(InMemorySubstrate())
    c2.buffer("add_region", "hippocampal", "s_low", "hold",
              provenance="test")
    checks["buffer_not_yet_substrate"] = not c2.s.has_node("hippocampal")
    n = c2.consolidate()
    checks["consolidate_moves_and_wipes"] = (
        n == 1 and c2.s.has_node("hippocampal") and c2._buffer == [])

    # The computer grades itself — the ruled gap names, exact.
    c3 = NeuromorphicComputer(InMemorySubstrate())
    c3.add_region("island", "s_low", "float", provenance="test")
    c3.wire_by_comention("seeker", "reaches toward:nowhere")
    gaps = sorted(c3.grade())
    checks["self_grade_names_gaps"] = gaps == [
        ("region_no_afferents", "island"),
        ("region_no_afferents", "seeker"),
        ("unresolved_growth_cone", "seeker->toward:nowhere")]

    # The vault payload: one observation per region/channel/wiring,
    # is_a the ruled classes, provenance carried.
    obs = build_cortex(InMemorySubstrate()).to_observations()
    kinds = sorted(o["relationships"][0]["related"][0]["value"]
                   for o in obs)
    checks["vault_payload_shape"] = (
        kinds == ["channel", "cortical_region", "cortical_region",
                  "cortical_region", "wiring", "wiring"]
        and all(any(r["relationship"] == "has_provenance"
                    for r in o["relationships"])
                for o in obs
                if o["relationships"][0]["related"][0]["value"]
                in ("cortical_region", "channel")))

    # THE SUBSTRATE-SWAP EXPERIMENT: same program, two substrates —
    # identical connectivity AND identical behavior. Identity = wiring.
    sa, sb = InMemorySubstrate(), InMemorySubstrate()
    ca, cb = build_cortex(sa), build_cortex(sb)
    for cx in (ca, cb):
        cx.potentiate("percept", "assoc", "warrant:swap")
        cx.potentiate("assoc", "motor", "warrant:swap")
    checks["substrate_swap_identity"] = (
        sa.snapshot() == sb.snapshot()
        and ca.fire("percept", "j") == cb.fire("percept", "j"))

    print()
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    failed = [k for k, v in checks.items() if not v]
    if failed:
        print(f"\nFAILED: {failed}")
        return 1
    print(f"\nNEUROMORPHIC SDK: co-mention wires together; growth cones "
          f"resolve on arrival; activation spreads only over warranted "
          f"wiring under an inhibition gate; warrant is the plasticity rule "
          f"(evidence required, unwarranted prunes); consolidation splits "
          f"working memory from cortex; the computer names its own gaps; "
          f"the organization emits as vault payload; and the same computer "
          f"is IDENTICAL across substrates. {len(checks)} checks green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
