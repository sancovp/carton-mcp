"""loops.py — the three-loop convenience SDK: gated SM × bandit × weights × GP.

The join Isaac named (2026-07-26): one machine, three learning loops over ONE
substrate — SM steps ≡ manifold edges ≡ neuromorphic wiring (a weighted,
gate-checked edge):

  INNER / routing      step(): the sm_gate mechanic — while an actor is at a
                       state, its call must match the state's
                       required_pattern; a NON-MATCH is REFUSED with the
                       exact pattern + instruction (the refusal IS the
                       next-move instruction, the CCC law); a MATCH advances
                       through a pluggable SELECTOR over the ADMISSIBLE
                       (warranted) transitions — argmax (sm_gate's
                       highest-weight auto-advance) or the softmax bandit
                       (P ∝ exp(weight·pressure), explore w/ mutation_rate).
  MIDDLE / plasticity  reward(): weight += delta on the actor's traversed
                       path — ONLY with warrant evidence, and a mock-tagged
                       outcome is REFUSED HARD (mock warrant must never move
                       real weights — the B5 law, in the update rule).
                       decay()/consolidate() ride the neuromorphic SDK.
  OUTER / neurogenesis evolve_topology(): lfpoop.gp over the machine's OWN
                       config (delta genomes rewiring states/transitions).
                       THE CATASTROPHE GUARD IS THE CONDUCTION LAW: a
                       programmed transition is born warranted (the program
                       is its witness); a GP-proposed transition enters COLD
                       and physically cannot be selected until
                       apply_champion() — which REFUSES without an external
                       handler acceptance — stamps its warrant. An ungated
                       self-reorganizing machine is unrepresentable here.

The whole machine is DATA (to_data/from_data round-trips), so it is
programmable in JSON like everything else in the family. Deps: the
neuromorphic SDK (this package) + lfpoop (public, github.com/sancovp/lfpoop).
"""
import os
import random
import re
import sys

from .computer import NeuromorphicComputer
from .substrate import InMemorySubstrate

_LFPOOP = os.path.expanduser("~/repo/lfpoop")
if os.path.isdir(_LFPOOP) and _LFPOOP not in sys.path:
    sys.path.insert(0, _LFPOOP)

from lfpoop import gp as GP  # noqa: E402
from lfpoop.codething import external_witnesses  # noqa: E402


class Refusal(PermissionError):
    """A gated call that did not match — carries pattern + instruction."""


class MockWarrantRefused(ValueError):
    """Mock-tagged evidence tried to move real weights — the B5 law."""


# ── selectors: the inner loop's policy, pluggable ───────────────────────────

def argmax_weight(admissible, rng=None):
    """sm_gate's auto-advance: the highest-weight next step."""
    return max(admissible, key=lambda e: e[3].get("weight", 1))


class SoftmaxBandit:
    """The canonical Boltzmann bandit (the manifold SoftmaxBanditSelector's
    textbook form): P(e) ∝ exp(weight·pressure); with prob mutation_rate,
    ignore weights and explore uniformly. Chooses ONLY among admissible."""

    def __init__(self, pressure=1.0, mutation_rate=0.0, rng=None):
        self.pressure, self.mutation_rate = pressure, mutation_rate
        self.rng = rng or random.Random(0)

    def __call__(self, admissible, rng=None):
        import math
        r = rng or self.rng
        if r.random() < self.mutation_rate:
            return r.choice(admissible)                 # EXPLORE
        betas = [math.exp(e[3].get("weight", 1) * self.pressure)
                 for e in admissible]
        pick, z = r.random() * sum(betas), 0.0
        for e, b in zip(admissible, betas):
            z += b
            if pick <= z:
                return e
        return admissible[-1]


# ── the machine ─────────────────────────────────────────────────────────────

class LearningMachine:
    """states: {name: {pattern, instruction, terminal}}; transitions:
    [{from, to, weight, warrant}]; start: name. Programmed transitions are
    born warranted BY THE PROGRAM (warrant='programmed:<source>')."""

    def __init__(self, config, source="program", selector=None):
        # transitions accepted as list OR dict; canonical form is DICT-keyed
        # (t0, t1, ...) so the delta algebra (GP genomes) can walk it
        trs = config["transitions"]
        if isinstance(trs, dict):
            trs = [dict(v) for _, v in sorted(trs.items())]
        else:
            trs = [dict(t) for t in trs]
        self.config = {"states": dict(config["states"]),
                       "transitions": trs,
                       "start": config["start"]}
        self.selector = selector or argmax_weight
        self.c = NeuromorphicComputer(InMemorySubstrate())
        self.c.add_stratum("machine", 1)
        for name, st in self.config["states"].items():
            self.c.add_region(name, "machine", st.get("instruction", ""),
                              provenance=source)
            self.c.s.node(name).update(pattern=st.get("pattern", ""),
                                       terminal=bool(st.get("terminal")))
        for t in self.config["transitions"]:
            self.c._wire(t["from"], t["to"],
                         warrant=t.get("warrant", f"programmed:{source}"),
                         weight=t.get("weight", 1))
        self._cursor = {}         # actor -> state
        self._path = {}           # actor -> [(src, dst)] traversed

    # ── inner loop: the gate + the selector ──
    def lock(self, actor):
        self._cursor[actor] = self.config["start"]
        self._path[actor] = []

    def step(self, actor, call_text, rng=None):
        state = self._cursor.get(actor)
        if state is None:
            return {"status": "unlocked"}                # default-ungated
        node = self.c.s.node(state)
        pattern = node.get("pattern", "")
        if pattern and not re.search(pattern, call_text):
            raise Refusal(
                f"at {state}: call does not match required_pattern "
                f"/{pattern}/ — instruction: {node.get('function', '')}")
        if node.get("terminal"):
            self._cursor.pop(actor)                      # UNLOCK
            return {"status": "unlocked", "at": state}
        admissible = [e for e in self.c.s.edges(src=state, kind="wiring")
                      if e[3].get("warrant")]            # COLD cannot conduct
        if not admissible:
            return {"status": "stuck", "at": state}
        chosen = self.selector(admissible, rng=rng)
        self._cursor[actor] = chosen[1]
        self._path[actor].append((chosen[0], chosen[1]))
        return {"status": "advanced", "from": state, "to": chosen[1]}

    # ── middle loop: warranted reinforcement only ──
    def reward(self, actor, warrant_evidence, delta=1):
        if not warrant_evidence:
            raise ValueError("reward requires warrant evidence")
        if str(warrant_evidence).strip().lower().startswith("mock"):
            raise MockWarrantRefused(
                f"evidence {warrant_evidence!r} is mock-tagged — mock "
                f"warrant must never move real weights (the testbed law)")
        out = []
        for (src, dst) in self._path.get(actor, []):
            for (s, d, k, attrs) in self.c.s.edges(src=src, dst=dst,
                                                   kind="wiring"):
                attrs["weight"] = attrs.get("weight", 1) + delta
                attrs["warrant"] = warrant_evidence
                out.append((src, dst, attrs["weight"]))
        return out

    def consolidate(self):
        return self.c.consolidate()

    # ── data: the machine is programmable ──
    def to_data(self):
        return {"states": {n: dict(self.config["states"][n])
                           for n in self.config["states"]},
                "transitions": {
                    f"t{i}": {"from": s, "to": d,
                              "weight": a.get("weight", 1),
                              "warrant": a.get("warrant", "")}
                    for i, (s, d, k, a)
                    in enumerate(self.c.s.edges(kind="wiring"))},
                "start": self.config["start"]}

    # ── outer loop: GP over the machine's own config, handler-gated ──
    def evolve_topology(self, mutators, eval_fn, train_view, **kw):
        """lfpoop.gp.evolve over to_data(). GP-added transitions in any
        phenotype are COLD (no warrant) — they cannot conduct in a live
        machine until apply_champion() stamps them after handler acceptance."""
        evaluator = GP.Evaluator(self.to_data(), eval_fn)
        return GP.evolve(self.to_data(), mutators, evaluator, train_view,
                         **kw)

    def apply_champion(self, champion, store, selector=None):
        """REFUSES without an external handler acceptance of this genome id;
        on acceptance, builds the NEW machine — transitions the genome added
        get their warrant stamped from the promotion itself."""
        ext = external_witnesses(store, champion["id"])
        if not ext:
            raise PermissionError(
                f"apply_champion: genome {champion['id']} has no external "
                f"handler acceptance (accept_witness) — the machine cannot "
                f"crown its own rewiring")
        cfg = GP.phenotype(champion, self.to_data())
        for t in cfg["transitions"].values():
            if not t.get("warrant"):
                t["warrant"] = (f"promoted:{champion['id']}:"
                                f"by:{ext[-1]['witness_id']}")
        return LearningMachine(cfg, source=f"promoted:{champion['id']}",
                               selector=selector or self.selector)
