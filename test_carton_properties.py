"""
Lib-level tests for the Phase-1 PROPERTY SURFACE (carton programming model):
set_concept_properties (sync direct SET/REMOVE, reserved-key + value-type guards,
not-found refusal), query_concepts_by_properties (parameterized exact-match build),
and remove_concept_relationship (rel_type sanitization, sync DELETE).

Pure logic — uses a FakeGraph stub (no real neo4j), same pattern as
test_carton_kv_schema.py. Run: python3 test_carton_properties.py
"""
import os
import tempfile

os.environ["HEAVEN_DATA_DIR"] = tempfile.mkdtemp(prefix="kvprops_")
from carton_mcp.carton_utils import (  # noqa: E402
    set_concept_properties, query_concepts_by_properties, remove_concept_relationship,
    RESERVED_PROPERTY_KEYS,
)


class FakeGraph:
    """Stub KnowledgeGraphBuilder: an existence set + recorded write queries.
    `names` = the set of concept names that EXIST. `last` captures the final
    (query, params) so tests can assert the parameterized shape was built right."""
    def __init__(self, names, query_rows=None):
        self.names = set(names)
        self.calls = []                 # every (query, params) issued
        self.query_rows = query_rows or []   # rows returned for a match-by-property query

    def execute_query(self, query, params=None):
        params = params or {}
        self.calls.append((query, params))
        q = " ".join(query.split())     # collapse whitespace for matching
        # existence check used by set_concept_properties
        if "MATCH (c:Wiki {n: $n}) RETURN c.n AS n LIMIT 1" in q:
            return [{"n": params["n"]}] if params["n"] in self.names else []
        # SET c += $props  → record, no rows
        if "SET c += $props" in q:
            return []
        # REMOVE clauses → record, no rows
        if q.startswith("MATCH (c:Wiki {n: $n}) REMOVE"):
            return []
        # query_concepts_by_properties → return the canned rows
        if "RETURN c.n AS n" in q and "LIMIT $lim" in q:
            return list(self.query_rows)
        # remove_concept_relationship DELETE
        if "DELETE r RETURN count(r) AS deleted" in q:
            return [{"deleted": 1}]
        return []


# --------------------------------------------------------------------------- #
# set_concept_properties — merge
# --------------------------------------------------------------------------- #
def test_set_merge_basic_scalars():
    g = FakeGraph({"Task_1"})
    res = set_concept_properties("Task_1", {"status": "open", "order": 3, "done": False},
                                 shared_connection=g)
    assert res["success"] is True
    assert set(res["updated_keys"]) == {"status", "order", "done"}
    assert res["refused_keys"] == [] and res["removed_keys"] == []
    # the SET was a parameterized map (no value interpolation)
    set_calls = [(q, p) for q, p in g.calls if "SET c += $props" in " ".join(q.split())]
    assert len(set_calls) == 1
    assert set_calls[0][1]["props"] == {"status": "open", "order": 3, "done": False}


def test_set_merge_accepts_flat_list_of_scalars():
    g = FakeGraph({"Task_1"})
    res = set_concept_properties("Task_1", {"tags": ["a", "b", "c"]}, shared_connection=g)
    assert res["success"] is True
    assert res["updated_keys"] == ["tags"]


def test_set_refuses_reserved_keys():
    g = FakeGraph({"Task_1"})
    res = set_concept_properties("Task_1", {"status": "open", "d": "hi", "score": 5},
                                 shared_connection=g)
    assert res["success"] is True               # the non-reserved key still set
    assert res["updated_keys"] == ["status"]
    assert set(res["refused_keys"]) == {"d", "score"}
    # confirm reserved keys never reached the SET map
    set_calls = [(q, p) for q, p in g.calls if "SET c += $props" in " ".join(q.split())]
    assert "d" not in set_calls[0][1]["props"] and "score" not in set_calls[0][1]["props"]


def test_every_reserved_key_is_refused():
    g = FakeGraph({"Task_1"})
    props = {k: 1 for k in RESERVED_PROPERTY_KEYS}
    props["real_key"] = "v"
    res = set_concept_properties("Task_1", props, shared_connection=g)
    assert res["updated_keys"] == ["real_key"]
    assert set(res["refused_keys"]) == set(RESERVED_PROPERTY_KEYS)


def test_set_refuses_dict_value():
    g = FakeGraph({"Task_1"})
    res = set_concept_properties("Task_1", {"meta": {"nested": 1}}, shared_connection=g)
    assert res["success"] is False
    assert "meta" in res["error"]
    # NOTHING was written (no SET issued)
    assert not any("SET c += $props" in " ".join(q.split()) for q, _ in g.calls)


def test_set_refuses_list_with_nonscalar():
    g = FakeGraph({"Task_1"})
    res = set_concept_properties("Task_1", {"tags": ["ok", {"bad": 1}]}, shared_connection=g)
    assert res["success"] is False
    assert "tags" in res["error"]
    assert not any("SET c += $props" in " ".join(q.split()) for q, _ in g.calls)


def test_set_not_found_concept_refuses():
    g = FakeGraph(set())                 # Task_1 does NOT exist
    res = set_concept_properties("Task_1", {"status": "open"}, shared_connection=g)
    assert res["success"] is False
    assert "not found" in res["error"]
    assert not any("SET c += $props" in " ".join(q.split()) for q, _ in g.calls)


def test_set_unknown_mode_refused():
    g = FakeGraph({"Task_1"})
    res = set_concept_properties("Task_1", {"status": "open"}, mode="upsert",
                                 shared_connection=g)
    assert res["success"] is False
    assert "mode" in res["error"]


def test_set_empty_properties_refused():
    g = FakeGraph({"Task_1"})
    res = set_concept_properties("Task_1", {}, shared_connection=g)
    assert res["success"] is False
    assert "non-empty" in res["error"]


def test_set_no_connection_refused():
    # Force the no-connection branch deterministically (don't depend on a reachable neo4j):
    # the lib falls back to add_concept_tool._get_module_connection when shared_connection is None.
    import carton_mcp.add_concept_tool as _act
    orig = _act._get_module_connection
    _act._get_module_connection = lambda: None
    try:
        res = set_concept_properties("Task_1", {"status": "open"}, shared_connection=None)
    finally:
        _act._get_module_connection = orig
    assert res["success"] is False
    assert "connection" in res["error"]


# --------------------------------------------------------------------------- #
# set_concept_properties — remove
# --------------------------------------------------------------------------- #
def test_remove_mode_removes_keys():
    g = FakeGraph({"Task_1"})
    res = set_concept_properties("Task_1", {"status": True, "order": True},
                                 mode="remove", shared_connection=g)
    assert res["success"] is True
    assert set(res["removed_keys"]) == {"status", "order"}
    assert res["updated_keys"] == []
    # a REMOVE clause was issued with backtick-quoted keys
    rem = [(q, p) for q, p in g.calls if "REMOVE" in q]
    assert len(rem) == 1
    assert "c.`status`" in rem[0][0] and "c.`order`" in rem[0][0]


def test_remove_mode_refuses_reserved():
    g = FakeGraph({"Task_1"})
    res = set_concept_properties("Task_1", {"d": True, "status": True},
                                 mode="remove", shared_connection=g)
    assert res["removed_keys"] == ["status"]
    assert res["refused_keys"] == ["d"]


# --------------------------------------------------------------------------- #
# query_concepts_by_properties — parameterized exact-match build
# --------------------------------------------------------------------------- #
def test_query_builds_parameterized_where():
    g = FakeGraph({"Task_1"}, query_rows=[{"n": "Task_1", "status": "open"}])
    res = query_concepts_by_properties({"status": "open"}, shared_connection=g)
    assert res["success"] is True
    assert res["results"] == [{"n": "Task_1", "status": "open"}]
    q, p = g.calls[-1]
    qn = " ".join(q.split())
    # value is a $param, NOT interpolated; key is backtick-quoted
    assert "c.`status` = $w_0" in qn
    assert p["w_0"] == "open"
    assert p["lim"] == 25


def test_query_multi_key_anded():
    g = FakeGraph({"Task_1"}, query_rows=[])
    query_concepts_by_properties({"status": "open", "order": 2}, limit=5, shared_connection=g)
    q, p = g.calls[-1]
    qn = " ".join(q.split())
    assert "c.`status` = $w_0 AND c.`order` = $w_1" in qn
    assert p["w_0"] == "open" and p["w_1"] == 2
    assert p["lim"] == 5


def test_query_empty_where_refused():
    g = FakeGraph({"Task_1"})
    res = query_concepts_by_properties({}, shared_connection=g)
    assert res["success"] is False
    assert "non-empty" in res["error"]
    assert g.calls == []                 # never queried


def test_query_bad_limit_defaults():
    g = FakeGraph({"Task_1"}, query_rows=[])
    query_concepts_by_properties({"status": "open"}, limit="oops", shared_connection=g)
    _, p = g.calls[-1]
    assert p["lim"] == 25                 # non-int limit → default


# --------------------------------------------------------------------------- #
# remove_concept_relationship — rel_type sanitization + sync DELETE
# --------------------------------------------------------------------------- #
def test_remove_rel_valid_type_deletes():
    g = FakeGraph({"A", "B"})
    res = remove_concept_relationship("A", "PART_OF", "B", shared_connection=g)
    assert res["success"] is True
    assert res["deleted_count"] == 1
    q, p = g.calls[-1]
    assert "[r:PART_OF]" in q
    assert p["s"] == "A" and p["t"] == "B"


def test_remove_rel_sanitizes_injection_attempt():
    g = FakeGraph({"A", "B"})
    # a rel_type with non-alpha/underscore chars must be REFUSED (cannot be a param)
    res = remove_concept_relationship("A", "PART_OF]->() DETACH DELETE n //", "B",
                                      shared_connection=g)
    assert res["success"] is False
    assert "invalid rel_type" in res["error"]
    # no DELETE was issued
    assert not any("DELETE r" in q for q, _ in g.calls)


def test_remove_rel_empty_type_refused():
    g = FakeGraph({"A", "B"})
    res = remove_concept_relationship("A", "", "B", shared_connection=g)
    assert res["success"] is False
    assert "invalid rel_type" in res["error"]


def test_remove_rel_no_connection_refused():
    import carton_mcp.add_concept_tool as _act
    orig = _act._get_module_connection
    _act._get_module_connection = lambda: None
    try:
        res = remove_concept_relationship("A", "PART_OF", "B", shared_connection=None)
    finally:
        _act._get_module_connection = orig
    assert res["success"] is False
    assert "connection" in res["error"]


# --------------------------------------------------------------------------- #
# substrate_projector._build_template_content — node-property merge
# --------------------------------------------------------------------------- #
def test_template_content_merges_props_excluding_reserved():
    from carton_mcp.substrate_projector import _build_template_content
    concept_data = {
        "name": "Task_1",
        "description": "An essence paragraph.\n\nAn essence sentence.",
        "relationships": [{"type": "IS_A", "target": "Task"}],
        # properties(c) from neo4j: reserved managed fields + user properties,
        # plus a collision with an explicit concept-data key ("name")
        "props": {
            "n": "Task_1", "d": "raw desc", "t": "2026-06-10", "linked": True,
            "status": "open", "order": 3,
            "name": "PROP_SHOULD_NOT_WIN",
        },
    }
    content = _build_template_content(concept_data, "Task_1")
    # non-reserved properties fill keys not already present
    assert content["status"] == "open" and content["order"] == 3
    # reserved managed fields are excluded entirely
    for reserved in RESERVED_PROPERTY_KEYS:
        if reserved == "n":
            continue  # "n" is reserved AND never a template key; nothing to check beyond absence
        assert reserved not in content
    assert "n" not in content and "d" not in content and "t" not in content
    # explicit concept-data keys win over properties
    assert content["name"] == "Task_1"
    assert content["essence_paragraph"] == "An essence paragraph."
    assert content["essence_sentence"] == "An essence sentence."
    assert content["relationships"] == [{"type": "IS_A", "related": "Task"}]


if __name__ == "__main__":
    import sys
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
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
