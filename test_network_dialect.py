#!/usr/bin/env python3
"""THE get_concept_network DIALECT GATE — the network read works on BOTH engines.

    python3 knowledge/carton-mcp/test_network_dialect.py

Run as a SCRIPT, not through pytest-from-the-dir: the repo root IS the `carton_mcp` package, so
pytest's package inference breaks the flat imports. That is this repo's own convention
(test_carton_kv.py, test_carton_breaker.py, test_timeline_merge_live_path.py).

WHAT BROKE AND WHY IT IS TESTED HERE. `get_concept_network` was the last read facade that did not
work on kuzu, for two reasons that are NOT the same kind of problem:

  * `CALL { … }`  — kuzu has no subquery construct at all (a PARSER error). The wrapper was doing
    nothing a plain second MATCH does not do, so removing it is a pure simplification that is
    valid on both engines.
  * `[rel in r | type(rel)]` — kuzu has no list comprehension over a recursive-rel value (a
    BINDER error: "Variable rel is not in scope"). Unlike every other delta in this port there is
    NO form valid on both dialects, so the extraction moved into python.

The kuzu-shape assertions are CHARACTERISATION TESTS: they pin what kuzu returns today so that if
a future version changes it, we are told the constraint moved rather than silently depending on it.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from carton_utils import CartOnUtils  # noqa: E402

PASS, FAIL = [], []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  PASS  {name}")
    except AssertionError as exc:
        FAIL.append((name, str(exc)))
        print(f"  FAIL  {name}\n        {exc}")
    except Exception as exc:  # a broken test is a failure, not a skip
        import traceback
        FAIL.append((name, f"{type(exc).__name__}: {exc}"))
        print(f"  ERROR {name}\n{traceback.format_exc()}")


# ---------------------------------------------------------------- the extractor, both shapes

def test_the_NEO4J_shape_yields_its_types_in_hop_order():
    """A neo4j `r` arrives as a LIST already through `_serialize_relationship`."""
    value = [
        {"type": "Relationship", "relationship_type": "IS_A", "properties": {}},
        {"type": "Relationship", "relationship_type": "PART_OF", "properties": {"t": 1}},
    ]
    assert CartOnUtils._relationship_type_path(value) == ["IS_A", "PART_OF"], value


def test_the_KUZU_shape_yields_the_SAME_types_in_the_SAME_order():
    """A kuzu `r` arrives as ONE recursive-rel DICT whose `_rels` carry `_label`.

    Measured 2026-08-12 against kuzu 0.11.3 — this is the literal shape it returned.
    """
    value = {
        "_nodes": [{"_label": "Wiki", "n": "B"}],
        "_rels": [
            {"_src": {"offset": 0}, "_dst": {"offset": 1}, "_label": "IS_A"},
            {"_src": {"offset": 1}, "_dst": {"offset": 2}, "_label": "PART_OF"},
        ],
    }
    assert CartOnUtils._relationship_type_path(value) == ["IS_A", "PART_OF"], value


def test_BOTH_SHAPES_AGREE_which_is_the_whole_point():
    neo = [{"relationship_type": "HAS_PART"}, {"relationship_type": "IS_A"}]
    kuzu = {"_rels": [{"_label": "HAS_PART"}, {"_label": "IS_A"}]}
    assert CartOnUtils._relationship_type_path(neo) == CartOnUtils._relationship_type_path(kuzu)


def test_the_MILO_CONTRACT_holds_an_ordered_INDEXABLE_list_of_strings():
    """`milo/tool_rag.py:221` does `path[0] == rel_type`. A dict or a flattened string breaks it."""
    path = CartOnUtils._relationship_type_path({"_rels": [{"_label": "IS_A"}, {"_label": "PART_OF"}]})
    assert isinstance(path, list), type(path)
    assert all(isinstance(p, str) for p in path), path
    assert path[0] == "IS_A", path  # the FIRST hop, which is what milo filters on


def test_an_EMPTY_or_MISSING_value_is_an_empty_path_never_a_crash():
    for empty in (None, [], {}, {"_rels": []}, "", 0):
        assert CartOnUtils._relationship_type_path(empty) == [], repr(empty)


def test_a_GARBAGE_element_is_skipped_rather_than_poisoning_the_path():
    value = [{"relationship_type": "IS_A"}, "not-a-dict", {"no_type_key": 1}, {"_label": "PART_OF"}]
    assert CartOnUtils._relationship_type_path(value) == ["IS_A", "PART_OF"], value


# ---------------------------------------------------------------- the query shape itself

def test_the_query_carries_NEITHER_neo4j_ism():
    """Both are silent-failure shapes on kuzu, so a regression must be caught structurally."""
    q = CartOnUtils.__dict__["_build_network_query"](CartOnUtils.__new__(CartOnUtils), 2)
    assert "CALL" not in q, "the CALL{} subquery is back — kuzu cannot parse it"
    assert "rel in r" not in q, "the list comprehension is back — kuzu cannot bind it"
    assert "r as relationship_path" in q, "the raw relationship value must be returned"


def test_the_rel_type_FILTER_still_reaches_the_pattern():
    q = CartOnUtils.__dict__["_build_network_query"](CartOnUtils.__new__(CartOnUtils), 1, ["IS_A", "PART_OF"])
    assert "[r:IS_A|PART_OF*1..1]" in q, q


# ---------------------------------------------------------------- E2E through the real facade

def test_get_concept_network_RUNS_ON_KUZU_end_to_end():
    """The actual failing surface: the facade, on a real kuzu database, not a shape unit test."""
    try:
        import kuzu  # noqa: F401
    except ImportError:
        raise AssertionError("kuzu is not installed — this gate cannot verify the thing it exists for")

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "base", "heaven-framework"))
    tmp = tempfile.mkdtemp(prefix="kuzu_network_gate_")
    prev_backend = os.environ.get("GRAPH_BACKEND")
    prev_path = os.environ.get("KUZU_DB_PATH")
    os.environ["GRAPH_BACKEND"] = "kuzu"
    os.environ["KUZU_DB_PATH"] = os.path.join(tmp, "db")
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        g = KnowledgeGraphBuilder()
        g._ensure_connection()
        u = CartOnUtils(shared_connection=g)
        g.execute_query("MERGE (a:Wiki {n:'Gate_A'}) ON CREATE SET a.d='a'", {})
        g.execute_query("MERGE (b:Wiki {n:'Gate_B'}) ON CREATE SET b.d='b'", {})
        g.execute_query("MATCH (a:Wiki {n:'Gate_A'}),(b:Wiki {n:'Gate_B'}) MERGE (a)-[:IS_A]->(b)", {})

        res = u.get_concept_network("Gate_A", depth=1)
        assert res.get("success") is True, res.get("error")
        names = {i["connected_concept"] for i in res["network"]}
        assert "Gate_B" in names, names
        paths = [i["relationship_paths"] for i in res["network"] if i["connected_concept"] == "Gate_B"][0]
        assert paths == [["IS_A"]], paths

        filtered = u.get_concept_network("Gate_A", depth=1, rel_types=["IS_A"])
        assert filtered.get("success") is True, filtered.get("error")
        assert filtered["network"][0]["relationship_paths"][0][0] == "IS_A", filtered["network"]
        g.close()
    finally:
        for key, prev in (("GRAPH_BACKEND", prev_backend), ("KUZU_DB_PATH", prev_path)):
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    print("get_concept_network dialect gate\n")
    for name, fn in sorted(
        ((k, v) for k, v in list(globals().items()) if k.startswith("test_")),
        key=lambda kv: kv[0],
    ):
        check(name, fn)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    raise SystemExit(1 if FAIL else 0)
