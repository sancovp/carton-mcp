"""The substrate port — carton's substrate-independence, made a seam.

The 2026-07-25 reframe's thesis (transcript map, categories-youknow-
neuromorphic-reframe): carton is "a substrate-independent neuromorphic
computer" — "the same computer already runs over neo4j AND markdown
simultaneously; identity = the connectivity pattern." This module makes that
claim an INTERFACE: the computer core (computer.py) talks only to this port.

Adapters:
  * InMemorySubstrate — a third substrate (dict-backed). Running the
    computer over it in the lab is a REAL run of the computer, not a mock:
    the computer IS the connectivity + operations, per the thesis. Also the
    vehicle for the substrate-swap experiment (CCC's "J survives a substrate
    swap") at SDK grain.
  * CartonSubstrate — the neo4j/carton adapter (HOST-ONLY: carton_mcp and
    the production graph are barred from the lab — Isaac's hard rule,
    memory feedback_lab_never_host_neo4j). Import is lazy and refuses
    loudly outside a carton-equipped host.

Stdlib only in this module and in computer.py.
"""


class Substrate:
    """What a substrate must provide. Nodes are named; edges are typed and
    attributed. No query language — the computer computes by traversal."""

    def add_node(self, name, **attrs):
        raise NotImplementedError

    def has_node(self, name):
        raise NotImplementedError

    def node(self, name):
        """Attr dict (live reference)."""
        raise NotImplementedError

    def nodes(self):
        raise NotImplementedError

    def add_edge(self, src, dst, kind, **attrs):
        raise NotImplementedError

    def edges(self, src=None, dst=None, kind=None):
        """[(src, dst, kind, attrs)] filtered by any of the three."""
        raise NotImplementedError


class InMemorySubstrate(Substrate):
    def __init__(self):
        self._nodes = {}
        self._edges = []

    def add_node(self, name, **attrs):
        self._nodes.setdefault(name, {}).update(attrs)

    def has_node(self, name):
        return name in self._nodes

    def node(self, name):
        return self._nodes[name]

    def nodes(self):
        return list(self._nodes)

    def add_edge(self, src, dst, kind, **attrs):
        self._edges.append((src, dst, kind, dict(attrs)))

    def edges(self, src=None, dst=None, kind=None):
        return [(s, d, k, a) for (s, d, k, a) in self._edges
                if (src is None or s == src)
                and (dst is None or d == dst)
                and (kind is None or k == kind)]

    def snapshot(self):
        """The connectivity pattern — identity, per the thesis."""
        return (sorted((n, tuple(sorted(a.items())))
                       for n, a in self._nodes.items()),
                sorted((s, d, k, tuple(sorted(a.items())))
                       for (s, d, k, a) in self._edges))


class CartonSubstrate(Substrate):
    """HOST-ONLY adapter over carton's real graph. The lab never
    instantiates this (no carton_mcp in the lab env; production neo4j is
    off-limits by hard rule)."""

    def __init__(self):
        try:
            import carton_mcp  # noqa: F401  (host-side only)
        except ImportError as e:
            raise RuntimeError(
                "CartonSubstrate is host-only: carton_mcp is not present "
                "in this environment (and the lab must never reach the "
                "production graph). Use InMemorySubstrate here.") from e
        raise NotImplementedError(
            "host-side wiring pending — see the SDK spec: maps add_node -> "
            "add_concept, add_edge -> relationship, edges -> cypher "
            "traversal; runs where carton runs")
