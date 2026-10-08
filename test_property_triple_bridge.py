#!/usr/bin/env python3
"""test_property_triple_bridge — proof of the Content-Skyladder step-2 property->triple bridge.

Run as a SCRIPT (repo root IS the carton_mcp package):  python3 test_property_triple_bridge.py

Proves add_concept_tool_func's SOMA-validation payload includes a concept's `has_`-prefixed
STRING properties as string_value triples (so a vaulted type's required str field, stored as a
scratch-lane property, reaches SOMA and lets the concept climb SOUP->CODE) WITHOUT adding any
neo4j relationship (the neo4j write is untouched — no node pollution). Composes with the isolated
-daemon proof (2026-08-01, :8095): a framework carrying the 5 required fields as SOMA string
triples grades code and fires dchain_framework_write_journeycore — so bridging the properties
into those triples is exactly what makes the genesis framework climb + the content rung fire.

No live daemon / no live carton: soma_validate is monkeypatched to CAPTURE the payload; the
breaker/quota/CartOnUtils deps are stubbed; the queue write goes to a throwaway HEAVEN_DATA_DIR.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types


def _install_stubs(neo4j_props: dict):
    """Stub the carton deps add_concept_tool_func imports lazily so the function runs with no
    live neo4j: breaker CLOSED (None), quota no-op, and CartOnUtils.query_wiki_graph serving the
    ACCUMULATE relationship read (empty) AND the bridge's properties(c) read (neo4j_props)."""
    br = types.ModuleType("carton_mcp.carton_breaker")
    br.check_breaker = lambda shared_connection=None: None
    sys.modules["carton_mcp.carton_breaker"] = br

    # No quota stub: metering is not in this package. It is enforced at the box's
    # query endpoint, where the operator runs it.

    cu = types.ModuleType("carton_mcp.carton_utils")

    class _FakeUtils:
        def __init__(self, shared_connection=None):
            pass

        def query_wiki_graph(self, cypher, parameters=None):
            if "properties(c)" in cypher:            # the BRIDGE read
                return {"success": True, "data": [{"p": dict(neo4j_props)}]}
            return {"success": True, "data": []}     # the ACCUMULATE relationship read
    cu.CartOnUtils = _FakeUtils
    sys.modules["carton_mcp.carton_utils"] = cu


def _run(properties: dict, neo4j_props: dict, relationships=None):
    """Call add_concept_tool_func with soma_validate captured; return the SOMA relationships dict
    {rel_type: [(value, type), ...]} the payload carried."""
    _install_stubs(neo4j_props)
    import add_concept_tool as act

    captured = {}

    def _fake_soma_validate(source, observations):
        captured["obs"] = observations
        return {"result": "status=x:code\nall_core_requirements_met\ndeduction_chains_fired=0 unmet=0"}

    act._soma_up = lambda: True
    act.soma_validate = _fake_soma_validate

    with tempfile.TemporaryDirectory() as td:
        os.environ["HEAVEN_DATA_DIR"] = td
        act.add_concept_tool_func(
            concept_name="Test_Framework_Bridge",
            description="",
            relationships=relationships or [{"relationship": "is_a", "related": ["Framework"]}],
            properties=properties,
            hide_youknow=False,
        )
    obs = captured.get("obs") or []
    rels = {}
    for r in (obs[0].get("relationships") if obs else []):
        rels[r["relationship"]] = [(x["value"], x["type"]) for x in r["related"]]
    return rels


def test_param_has_props_bridge_to_string_triples():
    rels = _run(
        properties={
            "has_obstacle": "You cannot arbitrarily make a grand argument.",
            "has_overcome": "Collapse instead of compose.",
            "has_dream": "frameworks that prove themselves",
            "has_name": "Grand Argument Synthesis (GAS)",
            "has_definition": "GAS certifies the shape of an argument.",
            "status": "open",          # scratch-lane, MUST NOT bridge
            "blessed": True,           # non-str, MUST NOT bridge
        },
        neo4j_props={},
    )
    for k in ("has_obstacle", "has_overcome", "has_dream", "has_name", "has_definition"):
        assert k in rels, f"{k} not bridged into the SOMA payload: {list(rels)}"
        assert rels[k] == [(rels[k][0][0], "string_value")], f"{k} not string_value: {rels[k]}"
        assert rels[k][0][0], f"{k} bridged empty"
    assert "status" not in rels, "scratch-lane 'status' was wrongly bridged"
    assert "blessed" not in rels, "non-str 'blessed' was wrongly bridged"


def test_neo4j_existing_props_bridge():
    # empty properties param -> the bridge must read the EXISTING neo4j node properties
    rels = _run(
        properties=None,
        neo4j_props={"has_obstacle": "GAS_Obstacle", "has_dream": "GAS_Dream", "status": "done"},
    )
    assert rels.get("has_obstacle") == [("GAS_Obstacle", "string_value")], rels.get("has_obstacle")
    assert rels.get("has_dream") == [("GAS_Dream", "string_value")], rels.get("has_dream")
    assert "status" not in rels, "scratch-lane 'status' from neo4j was wrongly bridged"


def test_has_key_already_a_relationship_is_not_double_bridged():
    # has_argument_shape is a REAL relationship on the framework; a same-named property must NOT
    # shadow/duplicate the edge (the edge value stays; the property is not appended).
    rels = _run(
        properties={"has_argument_shape": "some-string"},
        neo4j_props={},
        relationships=[
            {"relationship": "is_a", "related": ["Framework"]},
            {"relationship": "has_argument_shape", "related": ["Premise"]},
        ],
    )
    vals = rels.get("has_argument_shape", [])
    assert ("some-string", "string_value") not in vals, f"property shadowed the real edge: {vals}"
    assert any(v[0] == "Premise" for v in vals), f"real edge lost: {vals}"


def main() -> int:
    test_param_has_props_bridge_to_string_triples()
    test_neo4j_existing_props_bridge()
    test_has_key_already_a_relationship_is_not_double_bridged()
    print("ALL PASS (3/3) — property->triple bridge verified (has_* string props -> SOMA string_value triples; scratch-lane + non-str + already-edge excluded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
