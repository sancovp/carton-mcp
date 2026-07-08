"""Tests for the CartON manifold scientific graph-library — the gated state machine.

The load-bearing test is `test_gated_jump_proof`: it is the reproducible artifact for the claim
"a gated jump-flow IS a state machine" — a transition is structurally BLOCKED until its warrant
(all predecessor tails visited) is produced, then it fires and injects context.
"""
import importlib.util
import os
import sys

import pytest

# Load the pure module directly (avoid the carton_mcp package __init__, which pulls neo4j).
_PATH = os.path.join(os.path.dirname(__file__), "..", "manifold.py")
_spec = importlib.util.spec_from_file_location("manifold", _PATH)
manifold = importlib.util.module_from_spec(_spec)
sys.modules["manifold"] = manifold
_spec.loader.exec_module(manifold)

Node = manifold.Node
make_edge = manifold.make_edge
Manifold = manifold.Manifold
Traversal = manifold.Traversal
prove_gated_jump = manifold.prove_gated_jump
SoftmaxBanditSelector = manifold.SoftmaxBanditSelector
prove_bandit_learning = manifold.prove_bandit_learning
consolidate = manifold.consolidate
prove_consolidation_learning = manifold.prove_consolidation_learning
Organism = manifold.Organism
evolve_population = manifold.evolve_population
prove_evolution_selection = manifold.prove_evolution_selection
import random as _random


def test_node_requires_name():
    with pytest.raises(ValueError, match="non-empty"):
        Node("")


def test_edge_rejects_unknown_relation():
    with pytest.raises(ValueError, match="unknown relation"):
        make_edge("hyperlinks_to", "a", "b")


def test_tree_is_the_degenerate_case():
    """A plain `contains` tree traverses with no gating — the degenerate case."""
    m = Manifold()
    for n in ("root", "a", "b"):
        m.add_node(Node(n, f"payload-{n}"))
    m.add_edge(make_edge("contains", "root", "a"))
    m.add_edge(make_edge("contains", "root", "b"))
    t = Traversal(m, "root")
    adm = t.admissible_transitions()
    assert len(adm) == 2  # both children immediately admissible (no must_follow gate)
    inj = t.fire([e for e in adm if e.head == "a"][0])
    assert inj.head == "a" and t.current == "a"


def test_must_follow_gate_blocks_then_admits():
    """The warrant gate: a must_follow transition is blocked until ALL its tails are visited."""
    m = Manifold()
    for n in ("start", "key", "room"):
        m.add_node(Node(n, n))
    gated = m.add_edge(make_edge("must_follow", ["start", "key"], "room"))
    m.add_edge(make_edge("contains", "start", "key"))
    t = Traversal(m, "start")
    # gated jump blocked: 'key' not yet visited
    assert t.is_blocked(gated) is True
    with pytest.raises(PermissionError):
        t.fire(gated)
    # produce the warrant
    t.fire([e for e in t.admissible_transitions() if e.head == "key"][0])
    # now admissible
    assert t.is_blocked(gated) is False
    inj = t.fire(gated)
    assert inj.head == "room" and t.current == "room"


def test_fire_injects_context_in_order():
    """Firing accumulates the head payloads — the flow controls what enters context."""
    m = Manifold()
    for n in ("a", "b", "c"):
        m.add_node(Node(n, f"ctx-{n}"))
    m.add_edge(make_edge("contains", "a", "b"))
    m.add_edge(make_edge("contains", "b", "c"))
    t = Traversal(m, "a")
    t.step()  # a -> b
    t.step()  # b -> c
    assert t.working_set == "ctx-a\nctx-b\nctx-c"
    assert t.current == "c"


def test_from_carton_adapter_builds_model():
    """The read-only carton adapter lifts a carton subgraph into the manifold model (injected data)."""
    fake = {"success": True, "data": [
        {"name": "Quest_Start", "desc": "start", "rel": "CONTAINS", "target": "Quest_Key"},
        {"name": "Quest_Key", "desc": "key", "rel": "NEXT_STEP", "target": "Quest_Room"},
        {"name": "Quest_Room", "desc": "room", "rel": None, "target": None},
    ]}
    m = manifold.from_carton("Quest_Start", query_fn=lambda *a, **k: fake)
    assert {n.name for n in m.nodes} == {"Quest_Start", "Quest_Key", "Quest_Room"}
    assert m.get_node("Quest_Key").payload == "key"
    rels = {(e.relation, tuple(sorted(e.tails)), e.head) for e in m.edges}
    assert ("contains", ("Quest_Start",), "Quest_Key") in rels   # CONTAINS -> contains
    assert ("must_follow", ("Quest_Key",), "Quest_Room") in rels  # NEXT_STEP -> must_follow
    # gated sequence on the loaded graph: Start -> Key -> Room (cannot reach Room without Key)
    t = manifold.Traversal(m, "Quest_Start")
    assert t.step().head == "Quest_Key"
    assert t.step().head == "Quest_Room"
    assert t.current == "Quest_Room"


def test_from_carton_part_of_inverts():
    """PART_OF inverts: child PART_OF parent => parent contains child."""
    fake = {"success": True, "data": [
        {"name": "Child", "desc": "c", "rel": "PART_OF", "target": "Parent"},
        {"name": "Parent", "desc": "p", "rel": None, "target": None},
    ]}
    m = manifold.from_carton("Parent", query_fn=lambda *a, **k: fake)
    rels = {(e.relation, tuple(sorted(e.tails)), e.head) for e in m.edges}
    assert ("contains", ("Parent",), "Child") in rels


def test_from_carton_empty_on_failed_query():
    m = manifold.from_carton("X", query_fn=lambda *a, **k: {"success": False})
    assert m.nodes == []


def test_gated_jump_proof():
    """THE reproducible artifact: blocked-before-warrant, fires-after-warrant, ends in locked_room."""
    r = prove_gated_jump()
    assert r["proven"] is True
    t = r["trail"]
    assert t[0]["step"] == "attempt_gated_jump_before_warrant" and t[0]["blocked"] is True
    assert t[0]["error"] is not None and t[0]["current"] == "start"
    assert t[2]["step"] == "fire_gated_jump_after_warrant" and t[2]["blocked_now"] is False
    assert t[2]["current"] == "locked_room"


# ── DYNAMICAL layer (increment 3): the softmax-bandit Selector + reinforcement ──────────────────────

def _two_arm_manifold():
    m = Manifold()
    for n in ("hub", "a", "b"):
        m.add_node(Node(n, n))
    ea = m.add_edge(make_edge("contains", "hub", "a", weight=1.0))
    eb = m.add_edge(make_edge("contains", "hub", "b", weight=1.0))
    return m, ea, eb


def test_softmax_equal_weights_is_fair():
    """Equal weights => ~uniform exploit distribution (the unbiased prior)."""
    m, ea, eb = _two_arm_manifold()
    sel = SoftmaxBanditSelector(selection_pressure=2.0)
    probs = sel.probabilities([ea, eb])
    assert abs(probs[0] - 0.5) < 1e-9 and abs(probs[1] - 0.5) < 1e-9


def test_softmax_heavier_arm_is_more_likely():
    """A heavier-weighted edge gets a strictly higher selection probability (prob ∝ exp(w·β))."""
    m, ea, eb = _two_arm_manifold()
    ea = m.reinforce(ea, delta=1.0)  # a now weight 2.0 vs b 1.0
    sel = SoftmaxBanditSelector(selection_pressure=2.0)
    p_a, p_b = sel.probabilities([ea, eb])
    assert p_a > p_b
    # exact softmax value: exp(2·2)/(exp(2·2)+exp(1·2)) = exp(4)/(exp(4)+exp(2))
    import math
    assert abs(p_a - math.exp(4) / (math.exp(4) + math.exp(2))) < 1e-9


def test_high_selection_pressure_is_greedy_argmax():
    """selection_pressure → large drives the policy to the argmax (pure exploit)."""
    m, ea, eb = _two_arm_manifold()
    ea = m.reinforce(ea, delta=0.5)  # a heavier
    sel = SoftmaxBanditSelector(selection_pressure=50.0, mutation_rate=0.0, rng=_random.Random(1))
    picks = [sel([ea, eb], None).head for _ in range(20)]
    assert set(picks) == {"a"}  # always the heavy arm


def test_mutation_rate_one_is_pure_explore():
    """mutation_rate=1.0 => always uniform-random (ignores weights entirely)."""
    m, ea, eb = _two_arm_manifold()
    ea = m.reinforce(ea, delta=10.0)  # massively heavier — but explore ignores it
    sel = SoftmaxBanditSelector(selection_pressure=5.0, mutation_rate=1.0, rng=_random.Random(3))
    picks = [sel([ea, eb], None).head for _ in range(100)]
    assert "a" in picks and "b" in picks  # both appear despite the weight skew


def test_selection_is_deterministic_under_seed():
    """Same seed => identical selection sequence (reproducible artifact trail)."""
    m, ea, eb = _two_arm_manifold()
    s1 = SoftmaxBanditSelector(selection_pressure=1.5, mutation_rate=0.3, rng=_random.Random(42))
    s2 = SoftmaxBanditSelector(selection_pressure=1.5, mutation_rate=0.3, rng=_random.Random(42))
    seq1 = [s1([ea, eb], None).head for _ in range(50)]
    seq2 = [s2([ea, eb], None).head for _ in range(50)]
    assert seq1 == seq2


def test_reinforce_replaces_edge_with_heavier_copy():
    """reinforce bumps weight by delta in place; the gate is unaffected (still admissible)."""
    m, ea, eb = _two_arm_manifold()
    heavier = m.reinforce(ea, delta=0.3)
    assert heavier.weight == 1.3 and heavier in m.edges and ea not in m.edges
    # gate intact: both arms still admissible from hub
    assert len(Traversal(m, "hub").admissible_transitions()) == 2


def test_bandit_learning_proof():
    """THE reproducible artifact for the dynamical layer: fair start → reinforce → learned arm dominates."""
    r = prove_bandit_learning(seed=7)
    assert r["proven"] is True
    before, after, emp = r["trail"]
    assert abs(before["probs"]["arm_a"] - 0.5) < 0.05          # started fair
    assert after["probs"]["arm_a"] > before["probs"]["arm_a"]  # learning raised arm_a
    assert emp["counts"]["arm_a"] > emp["counts"]["arm_b"]     # and it empirically dominates


# ── consolidation (increment 4): the day/night loop = learning across runs ──────────────────────────

def test_consolidate_reinforces_taken_arms_per_occurrence():
    """consolidate reinforces every arm the run TOOK, +delta per occurrence; untaken arms unchanged."""
    m, ea, eb = _two_arm_manifold()  # hub->a, hub->b
    # a run that takes hub->a (only) — history holds that one injection
    t = Traversal(m, "hub", selector=lambda adm, _t: [e for e in adm if e.head == "a"][0])
    t.step()  # fires hub->a
    rec = consolidate(t, m, delta=0.5)
    weights = {e.head: e.weight for e in m.edges}
    assert weights["a"] == 1.5 and weights["b"] == 1.0   # only the taken arm reinforced
    assert rec["reinforced"] == 1 and rec["arms"][0]["times_taken"] == 1


def test_consolidate_is_per_occurrence_count():
    """An arm taken N times in a run gets N·delta (matches CCC per-choice reinforcement)."""
    m = Manifold()
    for n in ("x", "y", "z"):
        m.add_node(Node(n, n))
    m.add_edge(make_edge("contains", "x", "y"))
    m.add_edge(make_edge("contains", "y", "z"))
    m.add_edge(make_edge("contains", "z", "x"))  # cycle so an edge can recur
    # walk x->y->z->x->y : hub edge x->y taken twice
    t = Traversal(m, "x", selector=manifold.first_selector)
    for _ in range(4):
        t.step()
    counts = {}
    for inj in t.history:
        counts[inj.head] = counts.get(inj.head, 0) + 1
    rec = consolidate(t, m, delta=0.1)
    # the x->y edge was fired twice -> +0.2
    xy = [e for e in m.edges if e.tails == frozenset({"x"}) and e.head == "y"][0]
    assert abs(xy.weight - 1.2) < 1e-9


def test_consolidation_learning_proof():
    """THE reproducible artifact for cross-run learning: 15 pick-then-consolidate runs → one arm dominates."""
    r = prove_consolidation_learning(seed=11)
    assert r["proven"] is True
    counts = r["trail"][0]["counts"]
    weights = r["trail"][0]["final_weights"]
    dom = r["dominant_arm"]
    other = "b" if dom == "a" else "a"
    assert counts[dom] > 9                       # majority of the 15 runs
    assert weights[dom] > weights[other]         # rich-get-richer: dominant arm grew heavier


def test_consolidation_proof_is_reproducible():
    """Same seed → identical consolidation outcome (deterministic artifact)."""
    assert prove_consolidation_learning(seed=11) == prove_consolidation_learning(seed=11)


# ── evolutionary lifetime (increment 5): Reap / Survive / Reproduce ─────────────────────────────────

def test_evolve_reaps_survives_reproduces_by_fitness():
    """The three selection branches: <0.4 reap, [0.4,0.8) survive, >=0.8 reproduce (mutated child)."""
    rng = _random.Random(1)
    pop = [Organism(1.0, 0.1, fitness=0.30, name="dies"),
           Organism(1.0, 0.1, fitness=0.50, name="lives"),
           Organism(1.0, 0.1, fitness=0.90, name="breeds")]
    nxt, events = evolve_population(pop, rng)
    actions = {e["name"]: e["action"] for e in events}
    assert actions == {"dies": "reap", "lives": "survive", "breeds": "reproduce"}
    names = [o.name for o in nxt]
    assert "dies" not in names and "lives" in names and "breeds" in names
    assert any(n.startswith("breeds_V") for n in names)  # the mutated child
    assert len(nxt) == 3  # lives + breeds + child


def test_evolve_child_genome_is_mutated_and_bounded():
    """A reproduced child's genome is mutated within CCC bounds (selection_pressure>=0.1, mutation_rate in [0.01,1])."""
    rng = _random.Random(2)
    nxt, _ = evolve_population([Organism(0.15, 0.02, fitness=1.0, name="p")], rng)
    child = [o for o in nxt if o.name.startswith("p_V")][0]
    assert child.selection_pressure >= 0.1 and 0.01 <= child.mutation_rate <= 1.0
    assert child.fitness == 1.0  # child starts fresh


def test_organism_expresses_a_selector():
    """An Organism's genome expresses as a runnable softmax bandit selector with its hyperparams."""
    org = Organism(selection_pressure=3.0, mutation_rate=0.2)
    sel = org.selector(_random.Random(0))
    assert isinstance(sel, SoftmaxBanditSelector)
    assert sel.selection_pressure == 3.0 and sel.mutation_rate == 0.2


def test_evolution_selection_proof():
    """THE reproducible artifact for the evolutionary lifetime: weak reaped, mid survives, strong breeds."""
    r = prove_evolution_selection(seed=5)
    assert r["proven"] is True
    assert "weak" not in r["next_population"] and "strong" in r["next_population"]
    assert r["child_genome"] is not None
    # reproducible: same seed → same mutated child genome
    assert prove_evolution_selection(seed=5) == prove_evolution_selection(seed=5)
