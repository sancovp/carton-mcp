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


import re as _re

_ATTR_KEY = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_KIND = _re.compile(r"^[a-z][a-z0-9_]*$")


class _LiveEdgeAttrs(dict):
    """Write-through edge attrs. The computer MUTATES the attrs dict that
    edges() returns (potentiate/decay do `attrs["weight"] = ...` in place —
    computer.py:198-211), and on InMemorySubstrate that persists because the
    dict IS the store. Here every __setitem__ writes through to the
    relationship property synchronously, so the same in-place mutation
    persists on neo4j. Reads are served from the dict contents fetched at
    edges() time."""

    def __init__(self, run, src, dst, reltype, contents):
        super().__init__(contents)
        self._run, self._src, self._dst, self._reltype = run, src, dst, reltype

    def __setitem__(self, key, value):
        if not _ATTR_KEY.match(key):
            raise ValueError(f"edge attr key {key!r} is not a safe property name")
        self._run(
            f"MATCH (a:Wiki {{n: $src}})-[r:{self._reltype}]->(b:Wiki {{n: $dst}}) "
            f"SET r.`{key}` = $value",
            {"src": self._src, "dst": self._dst, "value": value})
        super().__setitem__(key, value)


# carton-managed node properties: never settable as substrate attrs, and
# stripped from node() reads (the property-layer doctrine's reserved set +
# this adapter's own stub marker).
_MANAGED = {"n", "d", "t", "c", "linked", "score", "source", "timeline_linked",
            "odyssey_linked", "system_generated", "last_modified", "neuro_stub",
            "neuro"}


class CartonSubstrate(Substrate):
    """HOST-side adapter over carton's real graph (the lab never
    instantiates this: no carton_mcp in the lab env; production neo4j is
    off-limits there by hard rule).

    THE LANE (design of record, Neuromorphic_Core_Collection 2026-08-09):
    DIRECT synchronous cypher — the sm_gate scratch lane (`_open_live_run`
    shape: MERGE/SET through a `run(query, params)->rows` closure) — NOT the
    observation queue. The Substrate port assumes synchronous add_node and
    live attr references; the queue drain latency breaks read-after-write.
    `to_observations` remains the separate SOMA vault pass.

    THE MAPPING:
      node            a :Wiki node, `n.n` = the substrate name, attrs as
                      plain node properties (scratch lane — these nodes
                      carry no IS_A; carton-managed keys are refused).
      edge            ONE relationship per (src, kind, dst), MERGEd — kind
                      `wiring` -> type `WIRING`. Every substrate edge is
                      stamped `r.neuro = true`; edges() matches ONLY stamped
                      relationships, so the computer never sees (or mutates)
                      carton's own IS_A/PART_OF web. Deliberate deviation
                      from InMemorySubstrate: repeated add_edge updates the
                      one synapse instead of appending a duplicate.
      growth cone     an edge toward a name that doesn't exist. Neo4j needs
                      both endpoints, so the missing target is MERGEd with
                      `neuro_stub: true`; has_node()/nodes() treat stubs as
                      NONEXISTENT, and add_node on that name clears the
                      marker — which IS the cone's "arrival". (The graph
                      analogue of carton's own auto-stubs, which the SDK
                      maps growth cones to.)
      nodes()         only substrate-authored nodes (`neuro: true`, stamped
                      by add_node — the computer's own anatomy), never the
                      whole concept graph. has_node()/node() DO see real
                      concepts (co-mention and cone-arrival against the
                      real graph are features).

    ⚠ Names land in the SHARED :Wiki namespace. add_node MERGEs on exact
    `n.n`, so a name colliding with a real concept would decorate that
    concept. Callers use distinctive names; tests use unique prefixes and
    clean up after themselves."""

    def __init__(self, run=None):
        try:
            import carton_mcp  # noqa: F401  (host-side only)
        except ImportError as e:
            raise RuntimeError(
                "CartonSubstrate is host-only: carton_mcp is not present "
                "in this environment (and the lab must never reach the "
                "production graph). Use InMemorySubstrate here.") from e
        if run is None:
            from carton_mcp.sm_gate import _open_live_run
            run = _open_live_run()
        self._run = run

    # ── helpers ──
    @staticmethod
    def _reltype(kind):
        if not _KIND.match(kind or ""):
            raise ValueError(f"edge kind {kind!r} — kinds are lowercase words")
        return kind.upper()

    @staticmethod
    def _check_attrs(attrs):
        for k in attrs:
            if k in _MANAGED:
                raise ValueError(f"attr {k!r} is a carton-managed property")
            if not _ATTR_KEY.match(k):
                raise ValueError(f"attr key {k!r} is not a safe property name")

    # ── the Substrate port ──
    def add_node(self, name, **attrs):
        self._check_attrs(attrs)
        # `neuro: true` marks a substrate-authored node — nodes() scopes to it
        # (a real concept may coincidentally carry `kind`; measured 2026-08-09:
        # three did, and an attr-based scope leaked them into the anatomy).
        self._run(
            "MERGE (x:Wiki {n: $name}) SET x += $attrs, x.neuro = true "
            "REMOVE x.neuro_stub",
            {"name": name, "attrs": attrs})

    def has_node(self, name):
        rows = self._run(
            "MATCH (x:Wiki {n: $name}) "
            "WHERE coalesce(x.neuro_stub, false) = false "
            "RETURN count(x) AS c", {"name": name})
        return bool(rows and rows[0].get("c"))

    def node(self, name):
        rows = self._run(
            "MATCH (x:Wiki {n: $name}) "
            "WHERE coalesce(x.neuro_stub, false) = false "
            "RETURN properties(x) AS p", {"name": name})
        if not rows:
            raise KeyError(name)
        return {k: v for k, v in (rows[0].get("p") or {}).items()
                if k not in _MANAGED}

    def nodes(self):
        rows = self._run(
            "MATCH (x:Wiki) WHERE x.neuro = true "
            "AND coalesce(x.neuro_stub, false) = false RETURN x.n AS n", {})
        return [r["n"] for r in rows]

    def add_edge(self, src, dst, kind, **attrs):
        self._check_attrs(attrs)
        rt = self._reltype(kind)
        # endpoints must exist for a relationship; a missing target becomes
        # a stub the port treats as nonexistent (the growth-cone case).
        self._run("MERGE (a:Wiki {n: $src})", {"src": src})
        self._run(
            "OPTIONAL MATCH (b:Wiki {n: $dst}) WITH b WHERE b IS NULL "
            "CREATE (:Wiki {n: $dst, neuro_stub: true})", {"dst": dst})
        self._run(
            f"MATCH (a:Wiki {{n: $src}}), (b:Wiki {{n: $dst}}) "
            f"MERGE (a)-[r:{rt}]->(b) SET r.neuro = true, r += $attrs",
            {"src": src, "dst": dst, "attrs": attrs})

    def edges(self, src=None, dst=None, kind=None):
        where = ["r.neuro = true"]
        params = {}
        if src is not None:
            where.append("a.n = $src"); params["src"] = src
        if dst is not None:
            where.append("b.n = $dst"); params["dst"] = dst
        rel = f":{self._reltype(kind)}" if kind is not None else ""
        rows = self._run(
            f"MATCH (a:Wiki)-[r{rel}]->(b:Wiki) WHERE {' AND '.join(where)} "
            f"RETURN a.n AS src, b.n AS dst, type(r) AS rt, "
            f"properties(r) AS p ORDER BY src, dst", params)
        out = []
        for r in rows:
            k = r["rt"].lower()
            contents = {a: v for a, v in (r.get("p") or {}).items()
                        if a != "neuro"}
            out.append((r["src"], r["dst"], k,
                        _LiveEdgeAttrs(self._run, r["src"], r["dst"],
                                       r["rt"], contents)))
        return out
