"""aut_deducer — deduce Aut_formal(C) for an ontology class C (Griess-constructor program, phase 0).

An ontology class C has a definition D(C) = its slots colored by (predicate, target type,
cardinality, stage), read from TWO surfaces:

  - the carton neo4j graph: HAS_REQUIRED_PART atomizations, REQUIRES_RELATIONSHIP edges
    (verified live 2026-07-05: the REQUIRES_RELATIONSHIP shape is
    (Template:Wiki)-[:REQUIRES_RELATIONSHIP {ts}]->(Predicate:Wiki) — the TARGET NODE NAME is the
    predicate, e.g. Has_Domain; the edge carries NO target-type/cardinality), and the core-sentence
    slot declarations (is_a / part_of / instantiates / produces — the four slots every carton
    concept carries).
  - the OWL world: class restrictions, loaded via THE SAME loading path server_fastmcp.youknow_sparql
    uses (owlready2.World over soma.owl + uarl.owl + starsystem.owl in SOMA_OWL_DIR) — here as a
    library call, never shelling to the MCP.

Aut_formal(C) = the group of slot permutations fixing every colored predicate = the colored-graph
automorphism group of D(C). D(C) is a star (class -> slots) with no slot-slot edges, so
Aut_formal(C) is exactly the direct product of symmetric groups on the color classes; definition
subgraphs are small (n <= 10 regime), so `verify_order_brute_force` cross-checks by explicit
permutation enumeration.

SOUNDNESS (structural, carried on every output as restriction_R): Aut_true SUBSET Aut_formal —
the ontology cannot distinguish what it cannot express. Any textual claim derived from these
outputs grades G4-G5 (formal-structural), never G1.

READ-ONLY: this module NEVER writes to neo4j and NEVER POSTs to SOMA. `encode_aut_properties` is
the M2 write-back ENCODER PREVIEW only — designed for carton set_properties' flat-property rules —
and is deliberately called nowhere in this phase.

V0 LIMITATION (honest, load-bearing): a slot's color includes its predicate, so orbit-mates always
share the same predicate — and FILLED_FROM provenance (soma_fillers.record_fill_provenance) is
keyed by prop, not by slot instance. Live provenance therefore measures SLOT-TYPE substitutability
(the orbit's prop filled interchangeably from multiple sources across concepts), not per-slot-mate
substitution; per-slot refinement (`refine_orbits_with_evidence`) is exercised only by synthetic /
mocked evidence in this phase.
"""

import itertools
import json
import logging
import math
import os
import re
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# The structural soundness restriction carried on EVERY output (never a G1 claim).
RESTRICTION_R = (
    "as expressible in the current ontology: Aut_formal(C) is computed over the slots the "
    "ontology can express; soundness Aut_true SUBSET Aut_formal (the ontology cannot distinguish "
    "what it cannot express). Textual claims derived from this grade G4-G5, never G1."
)

# The four core-sentence slots every carton concept declares (the carton core sentence).
CORE_SENTENCE_PREDICATES = ("is_a", "part_of", "instantiates", "produces")

# The >=3 distinct-concepts bar, mirroring soma_fillers.generalize_filling_strategies(threshold=3).
DEFAULT_THRESHOLD = 3

# owlready2 restriction type codes -> kind names (verified against owlready2 constants:
# SOME=24 ONLY=25 EXACTLY=26 MIN=27 MAX=28 VALUE=29).
_OWL_RESTRICTION_KINDS = {24: "some", 25: "only", 26: "exactly", 27: "min", 28: "max", 29: "value"}


# ---------------------------------------------------------------------------
# Read surfaces
# ---------------------------------------------------------------------------

def default_owl_dir() -> str:
    """SOMA's OWL directory — the same default server_fastmcp.youknow_sparql uses."""
    return os.environ.get(
        "SOMA_OWL_DIR",
        "/home/GOD/gnosys-plugin-v2/base/soma-prolog/soma_prolog",
    )


def load_owl_world(owl_dir: Optional[str] = None):
    """Load SOMA's three OWL files into one owlready2 world (youknow_sparql's loading path, as a
    library call). Returns (world, loaded_filenames). Fails LOUD (RuntimeError) if nothing loads."""
    import owlready2  # imported here so the pure group math stays importable without owlready2
    d = owl_dir or default_owl_dir()
    world = owlready2.World()
    loaded = []
    for fname in ("soma.owl", "uarl.owl", "starsystem.owl"):
        fpath = os.path.join(d, fname)
        if os.path.exists(fpath):
            world.get_ontology("file://" + fpath).load()
            loaded.append(fname)
    if not loaded:
        raise RuntimeError(
            f"No SOMA OWL files found in {d} (looked for soma.owl/uarl.owl/starsystem.owl); "
            "set SOMA_OWL_DIR"
        )
    return world, loaded


def make_executor():
    """A read-only neo4j `execute(query, params) -> rows` bound to the repo's established connection
    pattern (heaven_base KnowledgeGraphBuilder — the same class observation_worker_daemon uses).
    Fails LOUD if the connection cannot be established."""
    from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
    conn = KnowledgeGraphBuilder(
        uri=os.getenv("NEO4J_URI", "bolt://host.docker.internal:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )
    conn._ensure_connection()
    return conn.execute_query


def _camel_to_title_underscore(name: str) -> str:
    """OWL CamelCase -> carton Title_Case_With_Underscores (OntologyEngineer -> Ontology_Engineer)."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    return "_".join(p.capitalize() for p in s.split("_"))


def owl_class_index(world) -> Dict[str, object]:
    """Index the world's classes under BOTH their raw OWL name and the carton Title_Case_With_
    Underscores form, so a graph-named class resolves against the OWL surface."""
    index: Dict[str, object] = {}
    for c in world.classes():
        index.setdefault(c.name, c)
        index.setdefault(_camel_to_title_underscore(c.name), c)
    return index


def _owl_restriction_slots(owl_class) -> List[dict]:
    """Slots from a class's DIRECT owlready2 Restrictions (is_a + equivalent_to, direct only —
    inherited/nested constructs are out of scope for v0)."""
    import owlready2
    slots = []
    constructs = list(owl_class.is_a) + list(getattr(owl_class, "equivalent_to", []) or [])
    for r in constructs:
        if not isinstance(r, owlready2.Restriction):
            continue
        prop = getattr(r.property, "name", None) or str(r.property)
        kind = _OWL_RESTRICTION_KINDS.get(r.type, f"type_{r.type}")
        card = getattr(r, "cardinality", None)
        cardinality = f"{kind} {card}" if card is not None else kind
        value = getattr(r, "value", None)
        target_type = getattr(value, "name", None) or (str(value) if value is not None else None)
        slots.append({
            "prop": prop,
            "target_type": target_type,
            "cardinality": cardinality,
            "stage": "owl_restriction",
            "source": "owl",
        })
    return slots


def _graph_definition_slots(class_name: str, execute: Callable[[str, dict], list],
                            include_core_sentence: bool) -> Tuple[bool, List[dict]]:
    """The carton-graph half of read_definition: (node_exists, slots). Slots come from
    REQUIRES_RELATIONSHIP edges (target node name IS the required predicate), HAS_REQUIRED_PART
    atomizations (the part's IS_A type is the slot's target type; falls back to the part's own name
    when untyped), and the four core-sentence slot declarations."""
    rows = execute("MATCH (c:Wiki {n: $n}) RETURN c.n AS n", {"n": class_name}) or []
    if not rows:
        return False, []
    slots: List[dict] = []
    req = execute(
        "MATCH (c:Wiki {n: $n})-[:REQUIRES_RELATIONSHIP]->(p:Wiki) "
        "RETURN p.n AS prop ORDER BY p.n",
        {"n": class_name}) or []
    for r in req:
        slots.append({"prop": r["prop"], "target_type": None, "cardinality": None,
                      "stage": "required_relationship", "source": "graph"})
    parts = execute(
        "MATCH (c:Wiki {n: $n})-[:HAS_REQUIRED_PART]->(p:Wiki) "
        "OPTIONAL MATCH (p)-[:IS_A]->(t:Wiki) "
        "RETURN p.n AS part, collect(t.n) AS types ORDER BY p.n",
        {"n": class_name}) or []
    for r in parts:
        types = [t for t in (r.get("types") or []) if t]
        slots.append({"prop": "has_required_part",
                      "target_type": (sorted(types)[0] if types else r["part"]),
                      "cardinality": None,
                      "stage": "required_part", "source": "graph"})
    if include_core_sentence:
        for pred in CORE_SENTENCE_PREDICATES:
            slots.append({"prop": pred, "target_type": None, "cardinality": None,
                          "stage": "core_sentence", "source": "graph"})
    return True, slots


def read_definition(class_name: str,
                    execute: Optional[Callable[[str, dict], list]] = None,
                    world=None,
                    owl_index: Optional[Dict[str, object]] = None,
                    include_core_sentence: bool = True) -> dict:
    """Read D(C) from BOTH surfaces. Returns {class_name, slots, surfaces}.

    Fails LOUD (LookupError) if the class resolves on NEITHER surface (no graph node AND no OWL
    class). A class that resolves but declares no slots returns slots=[] — that emptiness is a
    finding, not an error. Passing neither `execute` nor `world` is a programming error (ValueError).
    """
    if execute is None and world is None and owl_index is None:
        raise ValueError("read_definition needs at least one surface: execute (graph) or world/owl_index (OWL)")

    slots: List[dict] = []
    graph_found = False
    owl_found = False

    if execute is not None:
        graph_found, graph_slots = _graph_definition_slots(class_name, execute, include_core_sentence)
        slots.extend(graph_slots)

    if world is not None or owl_index is not None:
        index = owl_index if owl_index is not None else owl_class_index(world)
        owl_class = index.get(class_name)
        owl_found = owl_class is not None
        if owl_found:
            slots.extend(_owl_restriction_slots(owl_class))

    if not graph_found and not owl_found:
        raise LookupError(
            f"class '{class_name}' resolves on NEITHER surface (no :Wiki node in the carton graph, "
            "no class in the SOMA OWL world)"
        )
    logger.info("aut_deducer: read_definition(%s) -> %d slots (graph=%s, owl=%s)",
                class_name, len(slots), graph_found, owl_found)
    return {"class_name": class_name, "slots": slots,
            "surfaces": {"graph": graph_found, "owl": owl_found}}


# ---------------------------------------------------------------------------
# Aut_formal — colored-slot automorphism group
# ---------------------------------------------------------------------------

def slot_color(slot: dict) -> Tuple:
    """The FULL color of a slot: (predicate, target type, cardinality, stage)."""
    return (slot.get("prop"), slot.get("target_type"), slot.get("cardinality"), slot.get("stage"))


def _assign_slot_ids(slots: List[dict]) -> List[dict]:
    """Give each slot a stable unique id `prop#k` (k = per-prop occurrence index, declaration order)."""
    counts: Dict[str, int] = {}
    out = []
    for s in slots:
        prop = str(s.get("prop"))
        k = counts.get(prop, 0)
        counts[prop] = k + 1
        s2 = dict(s)
        s2["id"] = f"{prop}#{k}"
        out.append(s2)
    return out


def _orbits_from_groups(groups: Dict[Tuple, List[str]]) -> Tuple[List[List[str]], List[List[str]], int]:
    """From color(-or refined-signature) groups -> (orbits, generators, order).
    generators = adjacent transpositions inside each orbit of size >= 2 (they generate S_n there);
    order = product of factorials of orbit sizes."""
    orbits = sorted((sorted(ids) for ids in groups.values()), key=lambda o: (o[0], len(o)))
    generators = []
    order = 1
    for orbit in orbits:
        order *= math.factorial(len(orbit))
        for a, b in zip(orbit, orbit[1:]):
            generators.append([a, b])
    return orbits, generators, order


def deduce_aut_from_definition(defn: dict) -> dict:
    """Pure: D(C) -> Aut_formal(C). Slots with the SAME full color are interchangeable; D(C) is a
    star (no slot-slot edges), so Aut_formal = direct product of symmetric groups on color classes."""
    slots = _assign_slot_ids(list(defn.get("slots") or []))
    groups: Dict[Tuple, List[str]] = {}
    for s in slots:
        groups.setdefault(slot_color(s), []).append(s["id"])
    orbits, generators, order = _orbits_from_groups(groups)
    return {
        "class_name": defn.get("class_name"),
        "slots": slots,
        "generators": generators,
        "orbits": orbits,
        "order": order,
        "restriction_R": RESTRICTION_R,
        "computed_at": datetime.now().isoformat(),
    }


def deduce_aut(class_name: str,
               execute: Optional[Callable[[str, dict], list]] = None,
               world=None,
               owl_index: Optional[Dict[str, object]] = None) -> dict:
    """Read D(C) from the live surfaces and deduce Aut_formal(C). Fail-loud inherits from
    read_definition (LookupError when the class resolves on neither surface)."""
    return deduce_aut_from_definition(
        read_definition(class_name, execute=execute, world=world, owl_index=owl_index))


def verify_order_brute_force(defn: dict, max_n: int = 8) -> int:
    """Brute-force cross-check (the n<=10 regime): count the permutations of the slot list that map
    every slot onto a slot of the SAME full color. Raises ValueError above max_n (guard, not a fallback)."""
    slots = list(defn.get("slots") or [])
    n = len(slots)
    if n > max_n:
        raise ValueError(f"brute force guarded at n<={max_n}, got {n}")
    colors = [slot_color(s) for s in slots]
    return sum(
        1 for perm in itertools.permutations(range(n))
        if all(colors[i] == colors[perm[i]] for i in range(n))
    )


def refine_orbits_with_evidence(aut: dict, slot_evidence: Dict[str, object]) -> dict:
    """Refine Aut_formal's orbits by PER-SLOT evidence signatures: orbit-mates whose observed
    evidence differs are no longer interchangeable (the evidence breaks the formal symmetry), so the
    orbit splits and the group order drops to the product over the refined cells.

    `slot_evidence` maps slot id -> any hashable signature (e.g. frozenset of observed source_types);
    slots absent from the map get the signature None. V0 honesty: LIVE FILLED_FROM provenance is
    prop-keyed and orbit-mates share their prop, so live data cannot key this map per-slot — this
    refinement is exercised by synthetic/mocked evidence in phase 0 (see module docstring).
    Returns a new aut dict (orbits/generators/order refined; restriction_R carried)."""
    slots = list(aut.get("slots") or [])
    by_id = {s["id"]: s for s in slots}
    groups: Dict[Tuple, List[str]] = {}
    for orbit_idx, orbit in enumerate(aut.get("orbits") or []):
        for sid in orbit:
            sig = slot_evidence.get(sid)
            groups.setdefault((orbit_idx, sig), []).append(sid)
    orbits, generators, order = _orbits_from_groups(groups)
    return {
        "class_name": aut.get("class_name"),
        "slots": slots,
        "generators": generators,
        "orbits": orbits,
        "order": order,
        "restriction_R": RESTRICTION_R,
        "computed_at": datetime.now().isoformat(),
        "refined_from_order": aut.get("order"),
    }


# ---------------------------------------------------------------------------
# Provenance substitutability — Cypher over FILLED_FROM (read-only)
# ---------------------------------------------------------------------------

def provenance_substitutability(class_name: str, orbits: List[List[str]],
                                execute: Callable[[str, dict], list],
                                threshold: int = DEFAULT_THRESHOLD) -> List[dict]:
    """Per-orbit provenance evidence from the FILLED_FROM substrate (read-only Cypher).

    FILLED_FROM shape (soma_fillers.record_fill_provenance, verified):
      (Concept:Wiki)-[:FILLED_FROM {prop, source_type, ts}]->(Source:Wiki)
    Fills attach to concept INSTANCES, so we join instances of the class ((i)-[:IS_A]->(class))
    plus the class node itself, restricted to the orbit's props.

    Substitution signal (v0, prop-keyed — see module docstring): within an orbit, a source_type
    group whose fills span >= 2 DISTINCT sources, supported by >= `threshold` distinct concepts
    (mirroring generalize_filling_strategies' >=3 discipline), counts as one substitution hit —
    the orbit's slot-type is being filled interchangeably. Absence of hits is WEAK evidence.
    Returns [{orbit, distinct_fill_sources, substitution_hits, observation_count}] per orbit."""
    results = []
    for orbit in orbits:
        props = sorted({sid.rsplit("#", 1)[0] for sid in orbit})
        rows = execute(
            "MATCH (i:Wiki)-[:IS_A]->(c:Wiki {n: $class}) "
            "MATCH (i)-[fp:FILLED_FROM]->(src:Wiki) WHERE fp.prop IN $props "
            "RETURN i.n AS concept, fp.prop AS prop, fp.source_type AS source_type, src.n AS source "
            "UNION "
            "MATCH (c:Wiki {n: $class})-[fp:FILLED_FROM]->(src:Wiki) WHERE fp.prop IN $props "
            "RETURN c.n AS concept, fp.prop AS prop, fp.source_type AS source_type, src.n AS source",
            {"class": class_name, "props": props}) or []
        rows = [r if isinstance(r, dict) else dict(r) for r in rows]
        by_source_type: Dict[str, List[dict]] = {}
        for r in rows:
            by_source_type.setdefault(str(r.get("source_type")), []).append(r)
        hits = 0
        for st_rows in by_source_type.values():
            distinct_sources = {r.get("source") for r in st_rows}
            distinct_concepts = {r.get("concept") for r in st_rows}
            if len(distinct_sources) >= 2 and len(distinct_concepts) >= threshold:
                hits += 1
        results.append({
            "orbit": list(orbit),
            "distinct_fill_sources": len({r.get("source") for r in rows}),
            "substitution_hits": hits,
            "observation_count": len(rows),
        })
    return results


# ---------------------------------------------------------------------------
# M2 PREVIEW ONLY — the set_properties flat-property encoder (called NOWHERE in phase 0)
# ---------------------------------------------------------------------------

def encode_aut_properties(aut: dict) -> dict:
    """ENCODER PREVIEW for the eventual M2 write-back via carton set_properties (Isaac's ruling:
    flat properties on the class node). set_properties REFUSES nested dicts, so everything here is
    a scalar or a flat list of scalars: aut_order int, aut_orbit_count int, aut_orbits = flat list
    of comma-joined slot ids (one string per orbit), aut_generators json.dumps'd, plus
    aut_computed_at / aut_restriction_r strings. Phase 0 calls this NOWHERE — no writes."""
    return {
        "aut_order": int(aut["order"]),
        "aut_orbit_count": len(aut.get("orbits") or []),
        "aut_orbits": [",".join(orbit) for orbit in (aut.get("orbits") or [])],
        "aut_generators": json.dumps(aut.get("generators") or []),
        "aut_computed_at": str(aut.get("computed_at")),
        "aut_restriction_r": str(aut.get("restriction_R")),
    }
