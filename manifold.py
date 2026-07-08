"""The CartON manifold — the scientific graph-library: a gated state machine over a typed hypergraph.

This is the generalized, scientifically-named substrate (Isaac 2026-06-19: "separate the primitives
out of CCC and put them in carton... abstractly represented in scientific layers"). It is the carton
package's give-away graph-library — the same object three systems instantiate:

  * the SSRI paper's "edge is a state transition that injects context" (Flat-versus-Tree §9;
    graph-skills-experimental: Node+payload, typed hyperedges, must_follow gate, fire=inject-context);
  * CybernetiCircus's gated TraversalStep state machine (required_pattern warrant + auto-advance);
  * a future gated TreeShell jump-flow (a jump-flow IS a gated state machine over the navigation tree).

The vocabulary is the SOMA-vaulted scientific layer (gnosys_vault.state_machine): State_Machine,
Traversal_Step, State_Transition, Execution_State. THIS module is the runnable form of it.

TWO LAYERS (the metalanguage, code-grounded from CCC):
  TOPOLOGICAL (here, v0): Node(payload) · typed hyperedge Edge (specializes/delegates_to/must_follow/
    contains) · the must_follow GATE (a transition is admissible only once ALL its predecessor tails
    are visited = the warrant) · fire = move + INJECT the head's payload into an accumulating context.
  DYNAMICAL (CCC, deferred — pluggable selector hook below): weighted-softmax policy (prob ∝
    exp(weight·selection_pressure)) · bandit reinforcement · day/night consolidation · evolutionary
    lifetime · identity-invariant. Added as a Selector; the topological gate stands without it.

NO carton/neo4j I/O in this core — it is pure + fully testable. The carton adapter (`from_carton`,
read-only: carton concepts -> Nodes, typed edges -> Edges) is added separately so the core stays pure.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

# The closed, small relation vocabulary — the typed edges meaning is actually made of
# (graph-skills-experimental model). A `must_follow` edge is the GATE; `contains`/`specializes`
# give the tree as the degenerate case.
RELATIONS = ("specializes", "delegates_to", "must_follow", "contains")


@dataclass(frozen=True)
class Node:
    """A Traversal_Step: an identity plus the context payload it injects when entered."""
    name: str
    payload: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Node.name must be non-empty")


@dataclass(frozen=True)
class Edge:
    """A State_Transition: a typed, directed HYPEREDGE ``tails`` --relation--> ``head``.

    ``tails`` is the set of source nodes (one for a binary edge; several for a multi-predecessor
    ``must_follow`` gate). ``head`` is the single node whose payload is injected when the edge fires.
    ``weight`` is the DYNAMICAL-layer tuning parameter (CCC softmax policy); ignored by the pure
    topological gate, used only by a Selector.
    """
    relation: str
    tails: frozenset[str]
    head: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.relation not in RELATIONS:
            raise ValueError(f"unknown relation {self.relation!r}; must be one of {RELATIONS}")
        if not self.tails:
            raise ValueError("Edge.tails must be non-empty")
        if not self.head:
            raise ValueError("Edge.head must be non-empty")

    @property
    def is_binary(self) -> bool:
        return len(self.tails) == 1

    def __str__(self) -> str:
        return f"({', '.join(sorted(self.tails))}) --{self.relation}--> {self.head}"


def make_edge(relation: str, tails: "str | Iterable[str]", head: str, weight: float = 1.0) -> Edge:
    """Construct an Edge from a single tail name or an iterable of them."""
    if isinstance(tails, str):
        tails = [tails]
    return Edge(relation=relation, tails=frozenset(tails), head=head, weight=weight)


class Manifold:
    """A typed hypergraph of Nodes + Edges — the State_Machine substrate (in-memory core)."""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []

    def add_node(self, node: Node) -> Node:
        self._nodes[node.name] = node
        return node

    def add_edge(self, edge: Edge) -> Edge:
        for t in edge.tails:
            if t not in self._nodes:
                raise ValueError(f"edge tail {t!r} is not a node")
        if edge.head not in self._nodes:
            raise ValueError(f"edge head {edge.head!r} is not a node")
        self._edges.append(edge)
        return edge

    def reinforce(self, edge: Edge, delta: float = 0.1) -> Edge:
        """Bandit reinforcement (CCC Night consolidation: ``r.weight += delta`` on the chosen arm).

        ``Edge`` is frozen, so this REPLACES it in place with a heavier copy and returns the new edge.
        The topological gate is unaffected (weight is a DYNAMICAL-layer param); only a Selector reads it.
        """
        try:
            i = self._edges.index(edge)
        except ValueError:
            raise KeyError(f"edge {edge} is not in this manifold")
        heavier = Edge(edge.relation, edge.tails, edge.head, edge.weight + delta)
        self._edges[i] = heavier
        return heavier

    def get_node(self, name: str) -> Node:
        if name not in self._nodes:
            raise KeyError(f"no node {name!r}")
        return self._nodes[name]

    def out_edges(self, name: str) -> list[Edge]:
        """Edges whose tail-set CONTAINS ``name`` (the moves that depart from being-at ``name``)."""
        return [e for e in self._edges if name in e.tails]

    @property
    def nodes(self) -> list[Node]:
        return list(self._nodes.values())

    @property
    def edges(self) -> list[Edge]:
        return list(self._edges)


@dataclass
class Injection:
    """The observable record of one transition firing: which edge, what context it injected."""
    edge: Edge
    head: str
    payload: str

    def __str__(self) -> str:
        return f"[{self.edge.relation}] entered {self.head!r}, injected: {self.payload!r}"


# A Selector chooses among admissible transitions (the DYNAMICAL layer hook). Default = first
# admissible (deterministic). A CCC-style softmax-bandit selector plugs in here later without
# touching the gate.
Selector = Callable[[list[Edge], "Traversal"], Edge]


def first_selector(admissible: list[Edge], _t: "Traversal") -> Edge:
    return admissible[0]


@dataclass
class SoftmaxBanditSelector:
    """The DYNAMICAL layer (CCC's weighted policy, in its canonical scientific form): a softmax /
    Boltzmann bandit over the admissible transitions.

        P(e)  ∝  exp( weight(e) · selection_pressure )           # EXPLOIT
        with probability ``mutation_rate``: uniform-random pick   # EXPLORE

    ``selection_pressure`` is the inverse temperature β: 0 → uniform (pure explore), large → greedy
    argmax. This is the textbook scientific form CCC instantiates with weighted ``NEXT_STEP`` edges +
    ``adjust_transition_weight``/Night-consolidation reinforcement (``weight += delta`` on the chosen
    arm). It is a drop-in ``Selector`` — it touches only ``Edge.weight``, never the warrant gate, so the
    topological soundness layer stands underneath it unchanged.

    Deterministic given the injected ``rng`` — seed it (``random.Random(seed)``) for a reproducible
    artifact trail; the gate's admissibility is computed first, so the bandit only ever chooses among
    transitions whose warrant already holds.
    """
    selection_pressure: float = 1.0
    mutation_rate: float = 0.0
    rng: random.Random = field(default_factory=random.Random)

    def probabilities(self, admissible: list[Edge]) -> list[float]:
        """The exploit distribution over ``admissible`` — observable, for the artifact trail.

        Numerically stable softmax (shift by the max β before exp). Returns one probability per edge,
        in the order given; an empty input returns ``[]``.
        """
        if not admissible:
            return []
        betas = [e.weight * self.selection_pressure for e in admissible]
        mx = max(betas)
        exps = [math.exp(b - mx) for b in betas]
        total = sum(exps) or 1.0
        return [w / total for w in exps]

    def __call__(self, admissible: list[Edge], _t: "Traversal") -> Edge:
        if not admissible:
            raise ValueError("no admissible transitions to select from")
        # EXPLORE: with prob mutation_rate, ignore the weights and pick uniformly.
        if self.mutation_rate > 0.0 and self.rng.random() < self.mutation_rate:
            return self.rng.choice(admissible)
        # EXPLOIT: sample from the softmax distribution.
        probs = self.probabilities(admissible)
        r = self.rng.random()
        acc = 0.0
        for edge, p in zip(admissible, probs):
            acc += p
            if r <= acc:
                return edge
        return admissible[-1]  # float-rounding fallthrough


class Traversal:
    """An Execution_State: a position on the Manifold with an accumulating context buffer.

    THE GATE (the warrant): ``admissible_transitions`` returns only the out-edges whose ENTIRE
    tail-set has already been visited — a ``must_follow`` transition CANNOT fire until all its
    predecessors hold. ``fire`` moves to the head and INJECTS its payload. This is what makes a
    jump-flow a gated state machine: you cannot advance until the warrant is produced.
    """

    def __init__(self, manifold: Manifold, start: str, selector: Selector = first_selector) -> None:
        manifold.get_node(start)  # validate
        self.manifold = manifold
        self.current = start
        self.selector = selector
        self.visited: list[str] = [start]
        self.context: list[str] = [manifold.get_node(start).payload]
        self.history: list[Injection] = []

    def admissible_transitions(self) -> list[Edge]:
        """The warrant gate: out-edges from ``current`` whose every tail is already visited."""
        visited = set(self.visited) | {self.current}
        return [e for e in self.manifold.out_edges(self.current) if e.tails <= visited]

    def is_blocked(self, edge: Edge) -> bool:
        """A transition is BLOCKED iff its warrant (all predecessor tails visited) is not yet met."""
        return edge not in self.admissible_transitions()

    def fire(self, edge: Edge) -> Injection:
        """Fire a transition (warrant must hold): move to ``edge.head`` and inject its payload."""
        if self.is_blocked(edge):
            unmet = sorted(set(edge.tails) - (set(self.visited) | {self.current}))
            raise PermissionError(
                f"transition BLOCKED: {edge} — warrant not produced "
                f"(unvisited predecessor(s): {unmet or 'not departing from current'})")
        head_node = self.manifold.get_node(edge.head)
        inj = Injection(edge=edge, head=edge.head, payload=head_node.payload)
        self.current = edge.head
        if edge.head not in self.visited:
            self.visited.append(edge.head)
        self.context.append(head_node.payload)
        self.history.append(inj)
        return inj

    def step(self) -> Optional[Injection]:
        """Fire ONE selected admissible transition (or None if the flow is at a leaf/blocked)."""
        adm = self.admissible_transitions()
        if not adm:
            return None
        return self.fire(self.selector(adm, self))

    @property
    def working_set(self) -> str:
        """The full accumulated context, in injection order — what the flow let into context."""
        return "\n".join(self.context)


def consolidate(traversal: "Traversal", manifold: Manifold, delta: float = 0.1) -> dict:
    """DAY/NIGHT CONSOLIDATION (CCC Night close-out, scientific form): at a run's terminal, REINFORCE
    every transition the run actually took — the bandit LEARNS ACROSS RUNS.

    ``traversal.history`` IS the day-record (each Injection holds the Edge that fired). Night reinforces
    each distinct arm by ``delta`` per occurrence (an arm taken twice gets ``2·delta``), reading the
    CURRENT edge in the manifold so it composes with prior consolidations. Pure — it mutates only edge
    weights (the dynamical layer), never the warrant gate. (CCC also webs a ``:Consolidation`` node here;
    that graph-write is the deferred carton-WRITE adapter — this pure core returns the record instead.)
    """
    from collections import Counter
    taken = Counter((inj.edge.relation, inj.edge.tails, inj.edge.head) for inj in traversal.history)
    reinforced = []
    for (relation, tails, head), n in taken.items():
        current = next((e for e in manifold.edges
                        if e.relation == relation and e.tails == tails and e.head == head), None)
        if current is None:  # edge gone (graph mutated mid-run) — skip, don't fabricate
            continue
        new_edge = manifold.reinforce(current, delta * n)
        reinforced.append({"edge": str(new_edge), "times_taken": n, "new_weight": new_edge.weight})
    return {"reinforced": len(reinforced), "delta": delta, "arms": reinforced}


# ── evolutionary lifetime (CCC Reap/Survive/Reproduce, scientific form) ─────────────────────────────
# CCC selects over a POPULATION of beings at each lifetime terminal by fitness (lib/evolution.py).
# In this PURE layer a "being" is a heritable Selector GENOME — the bandit hyperparameters
# (selection_pressure, mutation_rate); fitness is supplied by the caller (it measures the genome's
# runs — the pure layer never invents a task). The LLM-runner genes (temperature/top_p) are out of
# scope here. Thresholds are CCC's verbatim.
REAP_THRESHOLD = 0.4
REPRODUCE_THRESHOLD = 0.8


@dataclass
class Organism:
    """A heritable Selector genome + its measured fitness — the unit of the evolutionary lifetime."""
    selection_pressure: float = 1.0
    mutation_rate: float = 0.1
    fitness: float = 1.0
    name: str = "org"

    def selector(self, rng: Optional[random.Random] = None) -> SoftmaxBanditSelector:
        """Express the genome as a runnable bandit selector."""
        return SoftmaxBanditSelector(self.selection_pressure, self.mutation_rate,
                                     rng or random.Random())


def _mutate_organism(org: Organism, rng: random.Random) -> Organism:
    """Mutate a genome for a reproduced child (CCC ``_mutate_status``, the manifold-relevant genes)."""
    return Organism(
        selection_pressure=max(0.1, round(org.selection_pressure + rng.uniform(-0.1, 0.1), 2)),
        mutation_rate=max(0.01, min(1.0, round(org.mutation_rate + rng.uniform(-0.02, 0.02), 2))),
        fitness=1.0,
        name=f"{org.name}_V{rng.randint(2, 99)}",
    )


def evolve_population(population: list, rng: random.Random,
                      reap: float = REAP_THRESHOLD, reproduce: float = REPRODUCE_THRESHOLD) -> tuple:
    """One evolutionary generation (CCC Reap/Survive/Reproduce, scientific form). Each organism's
    fitness selects: ``< reap`` → REAPED (dropped); ``>= reproduce`` → SURVIVES and spawns a MUTATED
    child; in between → SURVIVES unchanged. Returns ``(next_population, events)``. Pure given ``rng``.
    """
    survivors: list = []
    events: list = []
    for org in population:
        if org.fitness < reap:
            events.append({"name": org.name, "fitness": org.fitness, "action": "reap"})
            continue
        survivors.append(org)
        if org.fitness >= reproduce:
            child = _mutate_organism(org, rng)
            survivors.append(child)
            events.append({"name": org.name, "fitness": org.fitness,
                           "action": "reproduce", "child": child.name})
        else:
            events.append({"name": org.name, "fitness": org.fitness, "action": "survive"})
    return survivors, events


# ── carton adapter (READ-ONLY): load a carton subgraph into the manifold model ─────────────────────
# Maps carton's relationship types onto the closed scientific vocabulary. IS_A => specializes
# (B is_a A: B is a more specific A); HAS_PART/CONTAINS/HAS_STEP => contains (A contains B);
# PART_OF => contains (inverse, recorded head=container); DEPENDS_ON/MUST_FOLLOW/NEXT_STEP =>
# must_follow (the GATE); DELEGATES_TO/PRODUCES/INSTANTIATES => delegates_to. Unmapped rels are skipped.
_CARTON_REL = {
    "IS_A": ("specializes", False), "HAS_PART": ("contains", False),
    "CONTAINS": ("contains", False), "HAS_STEP": ("contains", False),
    "PART_OF": ("contains", True),   # inverse: child PART_OF parent => parent contains child
    "DEPENDS_ON": ("must_follow", False), "MUST_FOLLOW": ("must_follow", False),
    "NEXT_STEP": ("must_follow", False),
    "DELEGATES_TO": ("delegates_to", False), "PRODUCES": ("delegates_to", False),
    "INSTANTIATES": ("delegates_to", False),
}


def from_carton(root: str, depth: int = 2, query_fn: Optional[Callable] = None) -> Manifold:
    """Load a carton subgraph (the manifold's neighborhood of ``root``) into a Manifold — READ-ONLY.

    carton :Wiki concepts -> Nodes (payload = the concept description); typed carton edges within the
    neighborhood -> scientific Edges via ``_CARTON_REL``. This is the "ON carton" adapter: it reads the
    live manifold and lifts a region into the runnable gated-state-machine model — NO writes.

    ``query_fn`` is the neo4j reader (``carton_mcp.carton_utils.CartOnUtils().query_wiki_graph`` by
    default); injectable so the adapter is unit-testable WITHOUT a live graph. It must return a dict
    ``{"success": bool, "data": [{"name", "desc", "rel", "target"}, ...]}`` (rel/target null for
    isolated nodes).
    """
    if query_fn is None:  # pragma: no cover - live carton path
        from carton_mcp.carton_utils import CartOnUtils
        query_fn = CartOnUtils().query_wiki_graph
    d = max(1, int(depth))
    r = query_fn(
        f"MATCH (root:Wiki {{n:$root}}) "
        f"OPTIONAL MATCH (root)-[*1..{d}]-(nbr:Wiki) "
        f"WITH collect(DISTINCT root) + collect(DISTINCT nbr) AS ns "
        f"UNWIND ns AS n WITH DISTINCT n, ns "
        f"OPTIONAL MATCH (n)-[e]->(t:Wiki) WHERE t IN ns "
        f"RETURN n.n AS name, n.d AS desc, type(e) AS rel, t.n AS target",
        {"root": root})
    m = Manifold()
    if not (r and r.get("success") and r.get("data")):
        return m
    rows = r["data"]
    # pass 1: nodes (every distinct name, with its description payload)
    for row in rows:
        name = row.get("name")
        if name and name not in m._nodes:
            m.add_node(Node(name, (row.get("desc") or "")[:2000]))
    # pass 2: edges (mapped relations whose head is also in the loaded node-set)
    seen_edges: set = set()
    for row in rows:
        src, rel, tgt = row.get("name"), row.get("rel"), row.get("target")
        if not (src and rel and tgt) or tgt not in m._nodes:
            continue
        mapped = _CARTON_REL.get(rel.upper())
        if not mapped:
            continue
        relation, inverse = mapped
        tail, head = (tgt, src) if inverse else (src, tgt)
        key = (relation, tail, head)
        if key in seen_edges or tail not in m._nodes or head not in m._nodes:
            continue
        seen_edges.add(key)
        m.add_edge(make_edge(relation, tail, head))
    return m


def prove_gated_jump() -> dict:
    """THE GATED-JUMP PROOF — the smallest running demonstration that a jump-flow is a gated state
    machine: a transition is structurally BLOCKED until its warrant is produced, then fires.

    Builds: START --must_follow{requires GATE_KEY}--> LOCKED_ROOM, where GATE_KEY is a separate node.
    The jump to LOCKED_ROOM is gated on having visited GATE_KEY (the warrant). Returns a reproducible
    artifact trail: the blocked attempt, the warrant production, the now-admissible fire, the injected
    context. (Reproducible: pure, deterministic — same input → same trail.)
    """
    m = Manifold()
    m.add_node(Node("start", "you are at START"))
    m.add_node(Node("gate_key", "you picked up the GATE KEY (the warrant)"))
    m.add_node(Node("locked_room", "you ENTERED the locked room — context injected"))
    # the gated jump: locked_room requires BOTH start and gate_key visited (multi-tail must_follow gate)
    gated_jump = m.add_edge(make_edge("must_follow", ["start", "gate_key"], "locked_room"))
    # the warrant-producing jump: start --contains--> gate_key (free to take)
    fetch_key = m.add_edge(make_edge("contains", "start", "gate_key"))

    t = Traversal(m, start="start")
    trail = []

    # 1) attempt the gated jump BEFORE producing the warrant -> must be BLOCKED
    blocked = t.is_blocked(gated_jump)
    block_msg = None
    try:
        t.fire(gated_jump)
    except PermissionError as e:
        block_msg = str(e)
    trail.append({"step": "attempt_gated_jump_before_warrant",
                  "blocked": blocked, "error": block_msg, "current": t.current})

    # 2) produce the warrant: take the free jump to gate_key (visit the predecessor)
    inj_key = t.fire(fetch_key)
    trail.append({"step": "produce_warrant(visit gate_key)",
                  "injected": inj_key.payload, "visited": list(t.visited)})

    # 3) now the gated jump is admissible (warrant produced) -> fire it
    now_blocked = t.is_blocked(gated_jump)
    # the gated jump departs from gate_key's tail-set; current is gate_key, tails {start,gate_key} all visited
    inj_room = t.fire(gated_jump)
    trail.append({"step": "fire_gated_jump_after_warrant",
                  "blocked_now": now_blocked, "injected": inj_room.payload, "current": t.current})

    return {
        "proven": (blocked is True and block_msg is not None and now_blocked is False
                   and t.current == "locked_room"),
        "trail": trail,
        "working_set": t.working_set,
        "history": [str(h) for h in t.history],
    }


def prove_bandit_learning(seed: int = 7) -> dict:
    """THE BANDIT-LEARNING PROOF — the smallest running demonstration that the DYNAMICAL layer LEARNS:
    a softmax bandit over two equally-weighted admissible jumps starts ~50/50, and REINFORCING the
    chosen arm (CCC consolidation, ``weight += delta``) raises that arm's selection probability and
    makes it empirically dominate. Seeded ⇒ a reproducible artifact trail (same seed → same trail).

    Builds HUB --contains--> {arm_a, arm_b} (both admissible, equal weight). selection_pressure=2.0.
    """
    m = Manifold()
    m.add_node(Node("hub", "at the HUB"))
    m.add_node(Node("arm_a", "took ARM A"))
    m.add_node(Node("arm_b", "took ARM B"))
    arm_a = m.add_edge(make_edge("contains", "hub", "arm_a", weight=1.0))
    m.add_edge(make_edge("contains", "hub", "arm_b", weight=1.0))

    sel = SoftmaxBanditSelector(selection_pressure=2.0, mutation_rate=0.0, rng=random.Random(seed))
    trail = []

    # 1) equal weights -> ~50/50 exploit distribution
    adm = Traversal(m, "hub").admissible_transitions()
    p_before = {e.head: round(p, 4) for e, p in zip(adm, sel.probabilities(adm))}
    trail.append({"step": "initial_equal_weights", "probs": p_before})

    # 2) reinforce arm_a five times (the bandit learns arm_a is the good arm)
    for _ in range(5):
        arm_a = m.reinforce(arm_a, delta=0.3)
    adm = Traversal(m, "hub").admissible_transitions()
    p_after = {e.head: round(p, 4) for e, p in zip(adm, sel.probabilities(adm))}
    trail.append({"step": "after_reinforce_arm_a_x5(+0.3)", "probs": p_after,
                  "arm_a_weight": arm_a.weight})

    # 3) empirically the learned arm dominates selection (one shared seeded rng ⇒ reproducible)
    counts = {"arm_a": 0, "arm_b": 0}
    for _ in range(200):
        chosen = sel(Traversal(m, "hub").admissible_transitions(), None)
        counts[chosen.head] += 1
    trail.append({"step": "empirical_200_selections", "counts": counts})

    return {
        "proven": (abs(p_before["arm_a"] - 0.5) < 0.05            # started fair
                   and p_after["arm_a"] > p_before["arm_a"]        # learning RAISED arm_a's probability
                   and counts["arm_a"] > counts["arm_b"]),         # and it now dominates empirically
        "trail": trail,
    }


def prove_consolidation_learning(seed: int = 11) -> dict:
    """THE CONSOLIDATION PROOF — the day/night loop creates LEARNING ACROSS RUNS (rich-get-richer):
    over repeated runs where each bandit pick is reinforced at the run terminal, one arm comes to
    dominate both the selection counts AND the final weights. Seeded ⇒ a reproducible artifact trail.

    HUB --contains--> {a, b}, both starting equal. Each of 15 runs: the softmax bandit picks one arm,
    then ``consolidate`` reinforces the arm it took (+0.4). The feedback loop amplifies an early lead.
    """
    m = Manifold()
    for n in ("hub", "a", "b"):
        m.add_node(Node(n, n))
    m.add_edge(make_edge("contains", "hub", "a", weight=1.0))
    m.add_edge(make_edge("contains", "hub", "b", weight=1.0))
    sel = SoftmaxBanditSelector(selection_pressure=2.0, mutation_rate=0.1, rng=random.Random(seed))

    counts = {"a": 0, "b": 0}
    for _ in range(15):
        t = Traversal(m, "hub", selector=sel)
        inj = t.step()                       # the bandit picks an arm (gate-admissible)
        counts[inj.head] += 1
        consolidate(t, m, delta=0.4)         # night: reinforce the arm this run took

    weights = {e.head: e.weight for e in m.edges}
    dominant = max(counts, key=counts.get)
    other = "b" if dominant == "a" else "a"
    return {
        "proven": (counts[dominant] > 15 * 0.6           # one arm took the majority of runs
                   and weights[dominant] > weights[other]),  # and its weight grew past the other's
        "dominant_arm": dominant,
        "trail": [{"step": "15_runs_pick_then_consolidate", "counts": counts, "final_weights": weights}],
    }


def prove_evolution_selection(seed: int = 5) -> dict:
    """THE EVOLUTION PROOF — Reap/Survive/Reproduce selects a population by fitness (CCC lifetime,
    scientific form). A weak (0.2), a middling (0.6), and a strong (0.95) genome ⇒ after one
    generation the weak is REAPED, the middling SURVIVES unchanged, the strong SURVIVES + spawns a
    MUTATED child. Seeded ⇒ a reproducible artifact (same seed → same mutated child genome).
    """
    rng = random.Random(seed)
    population = [
        Organism(1.0, 0.10, fitness=0.20, name="weak"),
        Organism(1.5, 0.10, fitness=0.60, name="mid"),
        Organism(2.0, 0.10, fitness=0.95, name="strong"),
    ]
    nxt, events = evolve_population(population, rng)
    names = [o.name for o in nxt]
    actions = {e["name"]: e["action"] for e in events}
    child = next((o for o in nxt if o.name.startswith("strong_V")), None)
    return {
        "proven": (actions["weak"] == "reap" and actions["mid"] == "survive"
                   and actions["strong"] == "reproduce"
                   and "weak" not in names and "mid" in names and "strong" in names
                   and child is not None and len(nxt) == 3),
        "events": events,
        "next_population": names,
        "child_genome": ({"selection_pressure": child.selection_pressure,
                          "mutation_rate": child.mutation_rate} if child else None),
    }


if __name__ == "__main__":  # pragma: no cover - manual proof run
    import json
    print(json.dumps({"gated_jump": prove_gated_jump(),
                      "bandit_learning": prove_bandit_learning(),
                      "consolidation_learning": prove_consolidation_learning(),
                      "evolution_selection": prove_evolution_selection()}, indent=2))
