"""
Lib-level tests for the manifest-as-render path in substrate_projector:
hydrate_template_content (collects children one level deep with their properties,
reserved keys excluded via _build_template_content) and the PublishManifest
RenderablePiece (reconstructs nested readme + renders valid, stable JSON).

Pure logic — uses a FakeGraph stub (no real neo4j), same pattern as
test_carton_properties.py. Run: python3 test_publish_manifest_render.py
"""
import json
import os
import tempfile

os.environ["HEAVEN_DATA_DIR"] = tempfile.mkdtemp(prefix="pubman_")
from carton_mcp.substrate_projector import (  # noqa: E402
    hydrate_template_content, PublishManifest,
)


class FakeUtils:
    """Stub for CartOnUtils: answers the parent-row query and the children query.

    `nodes` maps concept name -> {description, props, relationships}.
    `edges` maps (parent, edge_type) -> [child names] (graph order).
    """
    def __init__(self, nodes, edges):
        self.nodes = nodes
        self.edges = edges

    def query_wiki_graph(self, cypher, params=None):
        params = params or {}
        q = " ".join(cypher.split())
        # children-by-edge query
        if "type(r) = $edge_type" in q:
            kids = self.edges.get((params["name"], params["edge_type"]), [])
            return {"success": True, "data": [{"name": k} for k in kids]}
        # parent/node row query
        name = params.get("name")
        node = self.nodes.get(name)
        if not node:
            return {"success": False, "data": []}
        return {"success": True, "data": [{
            "name": name,
            "description": node.get("description", ""),
            "props": node.get("props", {}),
            "relationships": node.get("relationships", []),
        }]}


def _patch_utils(monkey_nodes, monkey_edges):
    """Install a FakeUtils as the CartOnUtils that hydrate_template_content imports."""
    import carton_mcp.carton_utils as cu
    orig = cu.CartOnUtils
    cu.CartOnUtils = lambda shared_connection=None: FakeUtils(monkey_nodes, monkey_edges)
    return orig, cu


def test_hydrator_collects_children_with_properties():
    nodes = {
        "Registry": {"description": "The registry.", "props": {
            "n": "Registry", "d": "raw", "t": "2026", "linked": True,  # reserved -> excluded
        }},
        "Unit_A": {"description": "Unit A.", "props": {
            "n": "Unit_A", "d": "raw", "name": "a", "subdir": "x/a", "pypi": True,
        }},
        "Unit_B": {"description": "Unit B.", "props": {
            "n": "Unit_B", "name": "b", "subdir": "x/b", "pypi": False,
        }},
    }
    edges = {("Registry", "HAS_UNIT"): ["Unit_A", "Unit_B"]}
    orig, cu = _patch_utils(nodes, edges)
    try:
        content = hydrate_template_content("Registry", edge_type="HAS_UNIT",
                                           children_key="units")
    finally:
        cu.CartOnUtils = orig

    assert "units" in content and len(content["units"]) == 2
    a, b = content["units"]
    # child scalar properties are present
    assert a["name"] == "a" and a["subdir"] == "x/a" and a["pypi"] is True
    assert b["name"] == "b" and b["pypi"] is False
    # reserved managed fields excluded from EVERY level
    for d in (content, a, b):
        assert "d" not in d and "t" not in d and "linked" not in d


def test_hydrator_no_edge_returns_no_children_key():
    # No `name` property -> content["name"] is the concept name.
    nodes = {"Solo": {"description": "Just me.", "props": {"order": 1}}}
    orig, cu = _patch_utils(nodes, {})
    try:
        content = hydrate_template_content("Solo")  # no edge_type
    finally:
        cu.CartOnUtils = orig
    assert "units" not in content and "children" not in content
    assert content["name"] == "Solo"


def test_hydrator_name_property_wins_over_concept_name():
    # A `name` PROPERTY (the data identity) overrides the concept-name default.
    nodes = {"Publishing_Unit_Doc_Mirror": {"description": "", "props": {"name": "doc-mirror"}}}
    orig, cu = _patch_utils(nodes, {})
    try:
        content = hydrate_template_content("Publishing_Unit_Doc_Mirror")
    finally:
        cu.CartOnUtils = orig
    assert content["name"] == "doc-mirror"


def test_hydrator_missing_concept_raises():
    orig, cu = _patch_utils({}, {})
    try:
        raised = False
        try:
            hydrate_template_content("Nope")
        except ValueError:
            raised = True
    finally:
        cu.CartOnUtils = orig
    assert raised


def test_publish_manifest_renders_valid_json_with_nested_readme():
    units = [
        {
            "name": "doc-mirror", "subdir": "doc-mirror-system/plugin",
            "public_repo": "sancovp/doc-mirror", "pypi": False,
            "readme_description": "doc-mirror plugin.",
            "readme_links": json.dumps({"Docs": "https://x"}, sort_keys=True),
            "readme_badges": json.dumps({"license": True, "stars": True}, sort_keys=True),
        },
    ]
    pm = PublishManifest(units=units, manifest_comment="hello")
    out = pm.render()
    parsed = json.loads(out)  # must be valid JSON
    assert parsed["_comment"] == "hello"
    u = parsed["units"][0]
    assert u["name"] == "doc-mirror" and u["pypi"] is False
    # nested readme reconstructed from flat json-string props
    assert u["readme"]["description"] == "doc-mirror plugin."
    assert u["readme"]["links"] == {"Docs": "https://x"}
    assert u["readme"]["badges"] == {"license": True, "stars": True}


def test_publish_manifest_no_comment_omits_key():
    pm = PublishManifest(units=[])
    parsed = json.loads(pm.render())
    assert "_comment" not in parsed
    assert parsed["units"] == []


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
