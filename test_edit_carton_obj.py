"""
Lib-level test for the edit_carton_obj WRAPPER (carton_mcp.carton_utils.edit_carton_obj).

Tests the neo4j-bound glue WITHOUT a real neo4j or the daemon: a stub graph supplies
n.d, and a temp HEAVEN_DATA_DIR captures the queued raw_concept replace entry. The PURE
op logic is covered separately by test_carton_kv.py (42 tests). The real end-to-end
(daemon applies the replace, n.d actually changes) is the commander's MCP-surface gate.

Run: python3 test_edit_carton_obj.py
"""
import json
import os
import tempfile

# Use the INSTALLED package (edit_carton_obj uses relative imports → needs package context).
# FORCE an isolated HEAVEN_DATA_DIR so test queue entries never reach the REAL daemon/neo4j.
os.environ["HEAVEN_DATA_DIR"] = tempfile.mkdtemp(prefix="kvtest_")
from carton_mcp.carton_utils import edit_carton_obj  # noqa: E402
from carton_mcp.add_concept_tool import get_observation_queue_dir  # noqa: E402

_DESC = (
    "Prose about the registry.\n"
    '<CartonObj name=Unit_Registry schema=Reg_Schema>'
    '{"units": {"cave": {"repo": Cave_Repo, "tier": 2}}, "order": [A_Unit, B_Unit]}'
    "</CartonObj>\n"
    'sibling <CartonObj name=Other>{"k": 1}</CartonObj> end'
)


class FakeGraph:
    """Minimal stand-in for KnowledgeGraphBuilder: returns a fixed n.d for the read query."""
    def __init__(self, description):
        self.description = description
        self.queries = []

    def execute_query(self, query, params=None):
        self.queries.append((query, params))
        # STEP 4 ref-guard: existence check — pretend every queried ref exists so the
        # guard passes (these STEP-2 tests are not about the did-you-mean guard).
        if "RETURN c.n AS n LIMIT 1" in query:
            return [{"n": (params or {}).get("n")}]
        if "RETURN c.d AS d" in query:
            return [{"d": self.description}] if self.description is not None else []
        return []


def _drain_queue():
    qd = get_observation_queue_dir()
    files = sorted(qd.glob("*.json"))
    entries = [json.load(open(f)) for f in files]
    for f in files:
        f.unlink()
    return entries


def test_get_no_write():
    _drain_queue()
    g = FakeGraph(_DESC)
    res = edit_carton_obj("My_Concept", "Unit_Registry", "units.cave.tier", "get", shared_connection=g)
    assert res["success"] and res["op"] == "get"
    assert res["value"] == 2
    assert _drain_queue() == []          # get NEVER queues a write
    # the raw read query was issued
    assert any("RETURN c.d AS d" in q for q, _ in g.queries)


def test_set_queues_replace_with_spliced_description():
    _drain_queue()
    g = FakeGraph(_DESC)
    res = edit_carton_obj("My_Concept", "Unit_Registry", "units.cave.tier", "set", 5, shared_connection=g)
    assert res["success"] and res["op"] == "set" and res["value"] == 5
    entries = _drain_queue()
    assert len(entries) == 1
    e = entries[0]
    assert e["raw_concept"] is True
    assert e["concept_name"] == "My_Concept"
    assert e["desc_update_mode"] == "replace"        # the sanctioned replace mode
    assert e["relationships"] == []                  # existing rels untouched
    # the queued description is the spliced n.d: tier=5, prose + sibling byte-identical
    assert '"tier": 5' in e["description"]
    assert '"tier": 2' not in e["description"]
    assert e["description"].startswith("Prose about the registry.\n")
    assert '<CartonObj name=Other>{"k": 1}</CartonObj> end' in e["description"]
    assert "Cave_Repo" in e["description"]           # ref preserved bare


def test_set_ref_value_via_dict():
    _drain_queue()
    g = FakeGraph(_DESC)
    res = edit_carton_obj("My_Concept", "Unit_Registry", "units.cave.owner", "set",
                          {"$ref": "Owner_X"}, shared_connection=g)
    assert res["success"]
    e = _drain_queue()[0]
    assert "Owner_X" in e["description"] and "$ref" not in e["description"]


def test_remove_queues_replace():
    _drain_queue()
    g = FakeGraph(_DESC)
    res = edit_carton_obj("My_Concept", "Unit_Registry", "units.cave.tier", "remove", shared_connection=g)
    assert res["success"]
    e = _drain_queue()[0]
    assert e["desc_update_mode"] == "replace"
    assert '"tier"' not in e["description"]
    assert "Cave_Repo" in e["description"]            # sibling leaf preserved


def test_append_queues_replace():
    _drain_queue()
    g = FakeGraph(_DESC)
    res = edit_carton_obj("My_Concept", "Unit_Registry", "order", "append",
                          {"$ref": "C_Unit"}, shared_connection=g)
    assert res["success"]
    e = _drain_queue()[0]
    assert "C_Unit" in e["description"]


def test_missing_concept_returns_error_no_write():
    _drain_queue()
    g = FakeGraph(None)   # read returns no rows
    res = edit_carton_obj("Nope", "Unit_Registry", "units", "get", shared_connection=g)
    assert res["success"] is False and "not found" in res["error"]
    assert _drain_queue() == []


def test_missing_fence_returns_error_no_write():
    _drain_queue()
    g = FakeGraph(_DESC)
    res = edit_carton_obj("My_Concept", "No_Such_Fence", "a", "set", 1, shared_connection=g)
    assert res["success"] is False
    assert _drain_queue() == []


def test_bad_path_returns_error_no_write():
    _drain_queue()
    g = FakeGraph(_DESC)
    res = edit_carton_obj("My_Concept", "Unit_Registry", "units.nope.deep", "get", shared_connection=g)
    assert res["success"] is False
    assert _drain_queue() == []


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
