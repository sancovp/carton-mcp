"""The neuromorphic computing SDK — carton's mechanisms, exposed AS a computer.

The 2026-07-25 rulings (transcript map, turns 500-546) made five mechanisms
explicit as neuroanatomy, "receipts already in the code, mislabeled as
features of a knowledge system." This SDK is those mechanisms as VERBS, over
the substrate port:

  wire_by_comention  add_concept's auto-linking = SYNAPSE FORMATION, Hebbian:
                     "co-mention wires together." A new concept's description
                     is scanned; every existing node it co-mentions gets a
                     wiring edge (born cold — warrant comes from use).
  growth cones       missing-concept tracking: a mention of a node that does
                     not exist yet is held as a growth_cone edge — a demand
                     the graph grows toward. When the node arrives, the cone
                     RESOLVES into real wiring.
  fire               the manifold's move+inject-payload = SPREADING
                     ACTIVATION: traversal, not querying. Activation spreads
                     ONLY over warranted wiring, gated by an INHIBITION
                     callback (SOMA's seat — "a spreading-activation system
                     without inhibitory circuits seizes; ungated association
                     is literally the hallucination failure mode"). The
                     accumulated payload along the path is "the membrane
                     potential of the thought."
  potentiate/decay   warrant IS the plasticity rule: "only warranted
                     co-activation potentiates." Potentiation requires
                     EVIDENCE (the warrant string is recorded, never
                     defaulted); unwarranted wiring decays toward pruning.
  consolidate        the working-memory-wipe/code-persists split =
                     hippocampal→cortical consolidation: session-buffer
                     writes move to the persistent substrate as one step;
                     the buffer wipes.
  grade              the computer grades ITSELF: unresolved growth cones,
                     regions with no afferents, wiring without warrant —
                     named gaps (the SOMA vault side re-derives these as
                     d-chains; foundation/computer.py).
  to_observations    the bridge that makes a tenant's computer organization
                     first-class SOMA ontology — the ruled "vault the
                     computer classes" payload, emitted in the /event wire
                     shape with per-value provenance.

Anatomy vocabulary (the ruled class set): stratum, region, kernel, wiring,
channel, selector, plasticity_rule, consolidation, activation_path. Regions
sit in strata ("gross anatomy — let experience wire the cortex"); kernels
are the one operation in a region ("parse, plan, validate, evolve — same
operation, different regions"); channels are the afferent/efferent surfaces
(seats and motor connectors).

Stdlib only. Substrate-independent by construction (see substrate.py).
"""
import re

from .substrate import Substrate

_WORD = re.compile(r"[a-z][a-z0-9_]{2,}")


class Inhibited(Exception):
    """The gate refused a spread — carries the named reason."""


class NeuromorphicComputer:
    def __init__(self, substrate: Substrate, plasticity_threshold=2):
        self.s = substrate
        self.plasticity_threshold = plasticity_threshold
        self._buffer = []
        self._aliases = {}                      # surface word -> node name                       # working memory (pre-consolidation)

    # ── anatomy ──
    def add_stratum(self, name, level):
        self.s.add_node(name, kind="stratum", level=level)

    def add_region(self, name, stratum, function, provenance="",
                   aliases=()):
        """aliases: surface words the thing's own speech uses for this
        region (docs say "research", the node is dept_research) — the
        Hebbian scan resolves mentions through them."""
        self.s.add_node(name, kind="region", stratum=stratum,
                        function=function, provenance=provenance)
        for a in aliases:
            self._aliases[a.lower()] = name

    def add_kernel(self, name, region, operation):
        self.s.add_node(name, kind="kernel", operation=operation)
        self.s.add_edge(name, region, "kernel_of")

    def add_channel(self, name, direction, feeds, provenance=""):
        if direction not in ("afferent", "efferent"):
            raise ValueError(f"channel direction {direction!r} — a channel "
                             f"is a percept seat (afferent) or a motor "
                             f"connector (efferent)")
        self.s.add_node(name, kind="channel", direction=direction,
                        provenance=provenance)
        self.s.add_edge(name, feeds, "feeds" if direction == "afferent"
                        else "driven_by")

    # ── synapse formation: co-mention wires together ──
    def wire_by_comention(self, name, description, provenance=""):
        """Add a concept node; Hebbian-wire it to every EXISTING node its
        description co-mentions; hold GROWTH CONES toward the missing ones
        it names with the cone marker `toward:<name>`."""
        self.s.add_node(name, kind="region", stratum="", function="",
                        provenance=provenance)
        mentioned = set(_WORD.findall(description.lower())) - {name}
        for m in sorted(mentioned):
            if (self.s.has_node(m)
                    and self.s.node(m).get("kind") == "region"):
                self._wire(name, m, warrant="", weight=1)   # born cold
            elif m.startswith("toward:") or ("toward:" + m) in description:
                pass
        for m in sorted(set(re.findall(r"toward:([a-z0-9_]+)",
                                       description))):
            if not self.s.has_node(m):
                self.s.add_edge(name, m, "growth_cone")
        return sorted(m for m in mentioned if self.s.has_node(m))

    def _wire(self, src, dst, warrant, weight):
        self.s.add_edge(src, dst, "wiring", warrant=warrant, weight=weight)

    def describe(self, region, text):
        """Hebbian wiring for an EXISTING node from the thing's own text:
        scan `text`, wire region -> every existing co-mentioned node (born
        cold — association is not operation), hold growth cones toward
        `toward:<name>` demands that don't exist yet. Returns (wired,
        cones)."""
        if not self.s.has_node(region):
            raise KeyError(f"describe: no such node {region!r}")
        mentioned = set(_WORD.findall(text.lower())) - {region}
        wired = []
        for m in sorted(mentioned):
            target = m if self.s.has_node(m) else self._aliases.get(m)
            # synapses connect FUNCTIONAL AREAS only — a co-mention of a
            # stratum/channel label is not a synapse (category error caught
            # live: CEO.md's word "org" wired a region to the stratum node)
            if (target and target != region
                    and self.s.node(target).get("kind") == "region"
                    and not self.s.edges(src=region, dst=target,
                                         kind="wiring")):
                self._wire(region, target, warrant="", weight=1)
                wired.append(target)
        cones = []
        for m in sorted(set(re.findall(r"toward:([a-z0-9_]+)", text))):
            if not self.s.has_node(m):
                self.s.add_edge(region, m, "growth_cone")
                cones.append(m)
        return wired, cones

    def resolve_growth_cones(self, arrived):
        """The graph grew toward a demand and it ARRIVED: cones pointing at
        `arrived` become real (cold) wiring. Returns the resolved sources."""
        resolved = []
        for (src, dst, _, _) in self.s.edges(dst=arrived, kind="growth_cone"):
            self._wire(src, dst, warrant="", weight=1)
            resolved.append(src)
        return resolved

    def growth_cones(self):
        return [(s, d) for (s, d, _, _) in self.s.edges(kind="growth_cone")
                if not self.s.has_node(d)]

    # ── spreading activation, gated ──
    def fire(self, start, payload, gate=None, max_hops=6):
        """Spread from `start` over WARRANTED wiring only, accumulating the
        payload trace. `gate(src, dst, attrs)` is the inhibition seat — it
        may raise Inhibited or return False to block a hop. Returns the
        activation path as data: {visited (order), trace, blocked}."""
        if not self.s.has_node(start):
            raise KeyError(f"fire: no such node {start!r}")
        visited, trace, blocked = [start], [(start, payload)], []
        frontier = [start]
        for _ in range(max_hops):
            nxt = []
            for node in frontier:
                for (src, dst, _, attrs) in self.s.edges(src=node,
                                                         kind="wiring"):
                    if dst in visited:
                        continue
                    if not attrs.get("warrant"):
                        blocked.append((src, dst, "unwarranted"))
                        continue                 # only warranted wiring conducts
                    if gate is not None and not gate(src, dst, attrs):
                        blocked.append((src, dst, "inhibited"))
                        continue
                    visited.append(dst)
                    trace.append((dst, payload))
                    nxt.append(dst)
            if not nxt:
                break
            frontier = nxt
        return {"visited": visited, "trace": trace, "blocked": blocked}

    # ── plasticity: warrant is the learning rule ──
    def potentiate(self, src, dst, warrant_evidence):
        """Only warranted co-activation potentiates — the evidence string is
        REQUIRED and recorded verbatim (no evidence, no potentiation)."""
        if not warrant_evidence:
            raise ValueError("potentiation requires warrant evidence — "
                             "unwarranted co-activation must not potentiate")
        for (s, d, k, attrs) in self.s.edges(src=src, dst=dst, kind="wiring"):
            attrs["weight"] = attrs.get("weight", 1) + 1
            attrs["warrant"] = warrant_evidence
            return attrs["weight"]
        raise KeyError(f"potentiate: no wiring {src}->{dst}")

    def decay(self):
        """Unwarranted wiring decays toward pruning; warranted holds."""
        pruned = []
        for (s, d, k, attrs) in list(self.s.edges(kind="wiring")):
            if not attrs.get("warrant"):
                attrs["weight"] = attrs.get("weight", 1) - 1
                if attrs["weight"] <= 0:
                    pruned.append((s, d))
        return pruned

    # ── consolidation: the wipe/persist split ──
    def buffer(self, fn, *args, **kwargs):
        """Stage a write in working memory (not yet on the substrate)."""
        self._buffer.append((fn, args, kwargs))

    def consolidate(self):
        """Working memory → cortex, one step; the buffer wipes. Returns how
        many writes consolidated."""
        n = len(self._buffer)
        for fn, args, kwargs in self._buffer:
            getattr(self, fn)(*args, **kwargs)
        self._buffer = []
        return n

    # ── the computer grades itself ──
    def grade(self):
        """Named gaps, the ruled examples verbatim: unresolved growth cones;
        a region with no afferents (neither wiring in nor a channel feeding
        it); wiring without warrant (cold synapses awaiting use)."""
        gaps = []
        for (src, dst) in self.growth_cones():
            gaps.append(("unresolved_growth_cone", f"{src}->toward:{dst}"))
        for n in self.s.nodes():
            if self.s.node(n).get("kind") != "region":
                continue
            afferent = (self.s.edges(dst=n, kind="wiring")
                        or self.s.edges(dst=n, kind="feeds"))
            if not afferent:
                gaps.append(("region_no_afferents", n))
        for (s, d, _, attrs) in self.s.edges(kind="wiring"):
            if not attrs.get("warrant"):
                gaps.append(("unwarranted_wiring", f"{s}->{d}"))
        return gaps

    # ── the SOMA bridge: the organization as first-class ontology ──
    def to_observations(self, source="neuromorphic_sdk"):
        """The computer's organization in the /event wire shape (one node
        per region/kernel/channel/wiring, is_a the vaulted computer classes,
        provenance carried) — foundation/computer.py's vault payload."""
        def node_obs(name, rels):
            by = {}
            for (p, v, t) in rels:
                by.setdefault(p, []).append({"value": v, "type": t})
            return {"source": source, "name": name, "description": name,
                    "relationships": [{"relationship": p, "related": vs}
                                      for p, vs in by.items()]}
        obs = []
        # ORDER MATTERS: the engine checks concepts sequentially within an
        # event, so a region's afferent grade must see its wiring/channel
        # triples already asserted — connectivity FIRST, regions LAST
        # (found empirically 2026-07-26: regions-first made every wired
        # region grade afferent-less at its own check time).
        for i, (src, dst, _, attrs) in enumerate(self.s.edges(kind="wiring")):
            obs.append(node_obs(f"wiring_{src}__{dst}", [
                ("is_a", "wiring", "concept_ref"),
                ("has_name", f"wiring_{src}__{dst}", "string_value"),
                ("has_from_region", src, "concept_ref"),
                ("has_to_region", dst, "concept_ref"),
                ("has_warrant", attrs.get("warrant") or "cold",
                 "string_value")]))
        for n in sorted(self.s.nodes()):
            a = self.s.node(n)
            kind = a.get("kind")
            if kind == "region":  # SDK-internal kind; vaults as cortical_region
                obs.append(node_obs(n, [
                    ("is_a", "cortical_region", "concept_ref"),
                    ("has_name", n, "string_value"),
                    ("has_stratum", a.get("stratum") or "unassigned",
                     "string_value"),
                    ("has_function", a.get("function") or "unassigned",
                     "string_value"),
                    ("has_provenance", a.get("provenance") or "in_memory",
                     "string_value")]))
            elif kind == "channel":
                feeds = ([d for (_, d, k2, _) in self.s.edges(src=n)
                          if k2 in ("feeds", "driven_by")] or [""])[0]
                obs.append(node_obs(n, [
                    ("is_a", "channel", "concept_ref"),
                    ("has_name", n, "string_value"),
                    ("has_direction", a["direction"], "string_value"),
                    ("has_feeds", feeds, "concept_ref"),
                    ("has_provenance", a.get("provenance") or "in_memory",
                     "string_value")]))
            elif kind == "kernel":
                obs.append(node_obs(n, [
                    ("is_a", "kernel", "concept_ref"),
                    ("has_name", n, "string_value"),
                    ("has_operation", a["operation"], "string_value")]))
        return obs
