"""The DTO interface — "the interface to all of the carton conveniences,
neuromorphically designing a brain FOR a thing" (Isaac, 2026-07-26).

NOT a model OF the thing (the market's log-mirror twins). A design surface
that aims the SDK's developmental machinery AT a subject:

    brain = design_brain(reading)

where `reading` is a THING READING (a body scan — produced by a reader like
soma_prolog.extractor.read_thing, every value provenance-traced, absence
left absent):

    {"name": str,
     "strata":  [(name, level), ...],
     "regions": [{"name","stratum","function","provenance"}, ...],
     "io":      [{"name","direction","feeds","provenance"}, ...],
     "speech":  [{"region","text","provenance"}, ...],
     "apex":    {part: provenance-or-None for the 7 hyper_agent parts}}

design_brain adds NO machinery — it composes the organs that already exist:
  1. LAY ANATOMY  — strata + regions from the thing's structure.
  2. ATTACH CHANNELS — the thing's I/O surfaces become afferents (seats)
     and motor connectors.
  3. LET EXPERIENCE WIRE — describe() grows Hebbian synapses from the
     thing's OWN speech/documents (born cold: association is not
     operation; only the thing's lived operation potentiates — warrant),
     growth cones held toward what the docs demand but the thing lacks.

The Brain wraps the computer with the apex reading:
  .apex()     — the hyper_agent completeness condition, filled IFF read
  .checkup()  — the brain check-up, named off reality ("perceives, acts;
                cannot reside / ratchet / govern")
  .to_observations() — computer organization + the apex instance as the
                SOMA vault payload (the tenant's brain, first-class
                ontology; the engine re-derives the same gaps)

Instantiation IS neurodevelopment: a tenant = a brain grown from the same
anatomy plan; the moat is the wiring only that tenant's operation could
have grown. Stdlib only.
"""
from .computer import NeuromorphicComputer
from .substrate import InMemorySubstrate

APEX_PARTS = ["graph_residence", "gate", "percept_channel",
              "motor_connector", "heartbeat", "ratchet", "governor_seat"]

_CHECKUP_VERBS = {
    "percept_channel": ("perceives", "cannot perceive"),
    "motor_connector": ("acts", "cannot act"),
    "heartbeat": ("beats", "has no heartbeat"),
    "gate": ("is gated", "is ungated"),
    "graph_residence": ("resides in a graph", "cannot reside (no graph "
                        "runtime)"),
    "ratchet": ("ratchets", "cannot ratchet (no review trail)"),
    "governor_seat": ("is governed", "is ungoverned (no seated governor)"),
}


class Brain:
    def __init__(self, computer, reading):
        self.computer = computer
        self.reading = reading

    def grade(self):
        return self.computer.grade()

    def apex(self):
        """The hyper_agent completeness condition, read — never staged."""
        surfaces = self.reading.get("apex", {})
        present = {p: surfaces[p] for p in APEX_PARTS if surfaces.get(p)}
        missing = sorted(p for p in APEX_PARTS if not surfaces.get(p))
        return {"present": present, "missing": missing}

    def checkup(self):
        """The brain check-up as a sentence, generated from the apex read."""
        a = self.apex()
        can = [_CHECKUP_VERBS[p][0] for p in APEX_PARTS if p in a["present"]]
        cannot = [_CHECKUP_VERBS[p][1] for p in a["missing"]]
        cold = sum(1 for g in self.grade() if g[0] == "unwarranted_wiring")
        temp = (f"; cortex is COLD ({cold} unwarranted synapses — no lived "
                f"operation has potentiated it yet)" if cold else
                "; cortex carries warranted wiring")
        return (f"{self.reading['name']}'s brain: "
                + ", ".join(can) + "; " + "; ".join(cannot) + temp + ".")

    def to_observations(self, source="dto_brain"):
        """The whole brain as vault payload: the computer's organization
        plus the apex instance (parts filled iff read, provenance carried;
        the engine re-derives the missing set)."""
        obs = self.computer.to_observations(source=source)
        a = self.apex()
        rels = [("is_a", "hyper_agent", "concept_ref"),
                ("has_name", f"{self.reading['name']}_twin", "string_value"),
                ("has_provenance",
                 self.reading.get("provenance", "reading"), "string_value")]
        for part, prov in a["present"].items():
            part_node = f"{self.reading['name']}_{part}"
            by = {}
            for (p, v, t) in [("is_a", part, "concept_ref"),
                              ("has_name", part_node, "string_value"),
                              ("has_provenance", prov, "string_value")]:
                by.setdefault(p, []).append({"value": v, "type": t})
            obs.append({"source": source, "name": part_node,
                        "description": part_node,
                        "relationships": [{"relationship": p, "related": vs}
                                          for p, vs in by.items()]})
            rels.append((f"has_{part}", part_node, "concept_ref"))
        by = {}
        for (p, v, t) in rels:
            by.setdefault(p, []).append({"value": v, "type": t})
        obs.append({"source": source,
                    "name": f"{self.reading['name']}_twin",
                    "description": f"{self.reading['name']}_twin",
                    "relationships": [{"relationship": p, "related": vs}
                                      for p, vs in by.items()]})
        return obs


def design_brain(reading, substrate=None):
    """READ → LAY ANATOMY → ATTACH CHANNELS → LET EXPERIENCE WIRE."""
    c = NeuromorphicComputer(substrate or InMemorySubstrate())
    for (name, level) in reading.get("strata", []):
        c.add_stratum(name, level)
    for r in reading.get("regions", []):
        c.add_region(r["name"], r["stratum"], r["function"],
                     provenance=r["provenance"],
                     aliases=r.get("aliases", ()))
    for ch in reading.get("io", []):
        c.add_channel(ch["name"], ch["direction"], feeds=ch["feeds"],
                      provenance=ch["provenance"])
    for sp in reading.get("speech", []):
        c.describe(sp["region"], sp["text"])
    return Brain(c, reading)
