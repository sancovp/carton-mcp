"""The crown of card 858 / issue 1424: the property trail rides the one SOMA switch.

Gnosys_System.soma_validator reads off by Isaac 2026-10-01, verbatim: "lets go disable soma while
the main agent is rehydrating; its in carton add concept thats the only thing that ever calls it".
The property trail (carton_utils._emit_property_trail) is a second carton caller of SOMA, and the
drain (observation_worker_daemon.batch_create_concepts_neo4j) reaches it for every concept that
carries properties, waiting up to its 10 s bound per concept on one thread.

Pure logic: a FakeGraph stub and a recorded urlopen, no neo4j, no SOMA.
Run: python3 test_property_trail_soma_off.py (the repo root IS the carton_mcp package, so the
INSTALLED module is the one under test: pip install --no-deps . first).
"""
import logging
import os
import tempfile
import urllib.request

os.environ["HEAVEN_DATA_DIR"] = tempfile.mkdtemp(prefix="trail858_")
import carton_mcp.carton_utils as cu  # noqa: E402

ONTOLOGY_TYPES = ["Doc_Mirror_Journal_Finding", "Idea"]


class FakeGraph:
    """An existence set, an is_a map and every query and property write recorded."""

    def __init__(self, names, types):
        self.names = set(names)
        self.types = types
        self.calls = []
        self.props = {}

    def execute_query(self, query, params=None):
        params = params or {}
        self.calls.append((query, params))
        q = " ".join(query.split())
        if "RETURN c.n AS n LIMIT 1" in q:
            return [{"n": params["n"]}] if params["n"] in self.names else []
        if "collect(t.n) AS types" in q:
            return [{"types": list(self.types.get(params["n"], []))}]
        return []

    def set_properties(self, name, props):
        self.props.setdefault(name, {}).update(props)

    def remove_properties(self, name, keys):
        for k in keys:
            self.props.get(name, {}).pop(k, None)


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getcode(self):
        return 200


class Recorder:
    """Stands in for urllib.request.urlopen and records every POST it is asked to make."""

    def __init__(self):
        self.posts = []

    def __call__(self, req, timeout=None):
        self.posts.append({"url": req.full_url, "timeout": timeout})
        return _Response()


class Warnings(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _patched(switch=None):
    """Swap urlopen for a recorder and, when given, the trail switch; return the restorer."""
    rec, orig_open, orig_switch = Recorder(), urllib.request.urlopen, cu.PROPERTY_TRAIL_TO_SOMA
    urllib.request.urlopen = rec
    if switch is not None:
        cu.PROPERTY_TRAIL_TO_SOMA = switch

    def restore():
        urllib.request.urlopen = orig_open
        cu.PROPERTY_TRAIL_TO_SOMA = orig_switch
    return rec, restore


def test_the_trail_switch_reads_off_while_soma_is_off():
    got = cu.soma_trail_on()
    assert got is False, (
        "INVARIANT: no property write POSTs its trail to SOMA while Gnosys_System.soma_validator "
        "is off (Isaac 2026-10-01 disabled SOMA in carton); FIX: soma_trail_on returns "
        f"PROPERTY_TRAIL_TO_SOMA, which is False. got {got!r}")


def test_a_property_write_on_an_ontology_node_posts_nothing_while_off():
    g = FakeGraph({"J"}, {"J": ONTOLOGY_TYPES})
    rec, restore = _patched()
    try:
        status = cu._emit_property_trail("J", {"status": "open"}, g)
    finally:
        restore()
    queried = [q for q, _ in g.calls if "collect(t.n) AS types" in " ".join(q.split())]
    assert status == "soma-off" and rec.posts == [] and queried == [], (
        "INVARIANT: while the switch is off the trail asks nothing of the graph and POSTs nothing "
        "to SOMA, and says soma-off; FIX: _emit_property_trail returns soma-off before the is_a "
        f"query when soma_trail_on is False. got status {status!r}, posts {rec.posts}, "
        f"is_a queries {len(queried)}")


def test_switched_on_the_trail_posts_once_within_its_bound():
    g = FakeGraph({"J"}, {"J": ONTOLOGY_TYPES})
    rec, restore = _patched(switch=True)
    try:
        status = cu._emit_property_trail("J", {"status": "open"}, g)
    finally:
        restore()
    assert status == "emitted" and len(rec.posts) == 1 and rec.posts[0]["timeout"] == 10, (
        "INVARIANT: switched back on, the trail posts exactly as before, one POST to the SOMA "
        "route within its 10 s bound, so the restore is one switch; FIX: soma_trail_on reads "
        f"PROPERTY_TRAIL_TO_SOMA at call time. got status {status!r}, posts {rec.posts}")


def test_set_properties_reports_the_trail_as_soma_off():
    g = FakeGraph({"J"}, {"J": ONTOLOGY_TYPES})
    rec, restore = _patched()
    try:
        res = cu.set_concept_properties("J", {"status": "open"}, shared_connection=g)
    finally:
        restore()
    assert res.get("success") and res.get("trail") == "soma-off" and rec.posts == [], (
        "INVARIANT: the set_properties report says the trail is off, never soma-unreachable, so a "
        "reader can tell a switched-off SOMA from a dead one; FIX: _emit_property_trail returns "
        f"soma-off and set_concept_properties passes it through. got {res}, posts {rec.posts}")


def test_the_drain_lands_properties_without_waiting_on_soma():
    from carton_mcp.observation_worker_daemon import batch_create_concepts_neo4j
    name = "Knowledge_Carton_Mcp_Test_858_2026_10_08T00_00_00"
    g = FakeGraph({name}, {name: ONTOLOGY_TYPES})
    concept = {"name": name, "description": "a drained journal entry",
               "relationships": {"is_a": ONTOLOGY_TYPES},
               "properties": {"status": "open", "webbing": "owed"}}
    handler = Warnings()
    log = logging.getLogger("carton_mcp.carton_utils")
    log.addHandler(handler)
    rec, restore = _patched()
    try:
        out = batch_create_concepts_neo4j([concept], g)
    finally:
        restore()
        log.removeHandler(handler)
    trail_lines = [w for w in handler.lines if "property-trail" in w]
    assert out["properties_set"] == 2 and g.props.get(name) == concept["properties"] \
        and rec.posts == [] and trail_lines == [], (
        "INVARIANT: the drain lands a concept and its properties without one SOMA POST while the "
        "switch is off, so no batch waits a trail timeout; FIX: the trail returns soma-off before "
        f"any POST. got properties_set {out['properties_set']}, props {g.props.get(name)}, posts "
        f"{rec.posts}, trail warnings {trail_lines}")


if __name__ == "__main__":
    import sys
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{passed + failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
