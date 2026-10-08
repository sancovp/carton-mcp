#!/usr/bin/env python3
"""Unit tests for carton_bounded_walk (issue #203) — the pure half of bounded activation.

Pure library-level tests — NO Neo4j, no MCP, no daemon (onion-architecture INNER layer, same
pattern as test_split_content.py). The Cypher executor (CartOnUtils.get_collection_concepts)
and the MCP tool (activate_collection) are thin wrappers verified by the integrator's live-test
script (live_test_bounded_activation.sh), not here.

The module is loaded DIRECTLY FROM THIS DIRECTORY by file path (importlib), never via the
installed `carton_mcp` package — the installed site-packages copy predates this module, and a
package import would silently test stale code (dev-dir-shadows-site-packages).

Synthetic rows simulate what the ONE Cypher execution returns (issue #203 ruling G8): each row
{name, description, boundary_type_hits, untyped, subtree_count, min_depth, has_children}.
Cases per the issue: hub member (untyped, over cap) · axis member (typed with a boundary IS_A) ·
depth stop · cap NOT applied to typed members (the DMN-ladder G4 requirement) · cycle/duplicate
rows · report-leads-payload key order · byte-compat of the zero-stop result.
"""
import importlib.util
import pathlib

_MOD_PATH = pathlib.Path(__file__).resolve().parent / "carton_bounded_walk.py"
_spec = importlib.util.spec_from_file_location("carton_bounded_walk_under_test", _MOD_PATH)
bw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bw)


def _row(name, description="a description", boundary_type_hits=None, untyped=False,
         subtree_count=0, min_depth=1, has_children=False):
    return {
        "name": name,
        "description": description,
        "boundary_type_hits": boundary_type_hits or [],
        "untyped": untyped,
        "subtree_count": subtree_count,
        "min_depth": min_depth,
        "has_children": has_children,
    }


# ---------------------------------------------------------------- plan builder

def test_plan_interpolates_depth_and_parameterizes_the_rest():
    plan = bw.build_walk_plan("My_Collection", max_depth=3)
    assert "[:HAS_PART*1..3]" in plan["cypher"], "depth must be LIVE (interpolated), not the dead param"
    assert "$collection_name" in plan["cypher"] and "$boundary_types" in plan["cypher"] and "$hub_cap" in plan["cypher"]
    assert plan["parameters"]["collection_name"] == "My_Collection"
    assert plan["parameters"]["hub_cap"] == 30
    assert plan["parameters"]["boundary_types"] == bw.DEFAULT_BOUNDARY_TYPES
    print("✓ plan: depth interpolated live, name/types/cap parameterized")


def test_plan_default_depth_is_1():
    plan = bw.build_walk_plan("X")
    assert "[:HAS_PART*1..1]" in plan["cypher"], (
        "default depth must be 1, only the concepts IN the collection (Isaac 2026-09-29)")
    print("✓ plan: default depth is 1 (the collection's own members)")


def test_plan_boundary_types_default_is_the_docmirror_collect_list():
    assert bw.DEFAULT_BOUNDARY_TYPES == [
        "Carton_Collection", "Local_Collection", "Identity_Collection", "Global_Collection",
        "Hypercluster", "Doc_Mirror_Repo", "Hwss_Domain", "Domain",
    ], ("the read-side type list is docmirror-collect's list (ruling G6): Domain the type of every domain "
        "node, the journal axis nodes included, and Hwss_Domain the type of the four roots (card 726)")
    print("✓ plan: boundary type list = docmirror-collect's list")


def test_plan_prunes_intermediates_not_the_terminal_member():
    plan = bw.build_walk_plan("X")
    assert "nodes(path)[1..-1]" in plan["cypher"], (
        "boundary predicate must apply to INTERMEDIATES only — include-but-do-not-descend (G7)")
    print("✓ plan: boundary pruned on intermediates only (member itself always included)")


def test_plan_rejects_bad_depth():
    for bad in (0, -1, 101, "10", 3.5, True):
        rejected = False
        try:
            bw.build_walk_plan("X", max_depth=bad)
        except ValueError as e:
            rejected = True
            assert "max_depth" in str(e), f"the rejection must name the bad param, got: {e}"
        assert rejected, f"max_depth={bad!r} must be rejected (depth is interpolated — must be a bounded int)"
    print("✓ plan: bad depths rejected (injection-safe interpolation)")


# ---------------------------------------------------------------- classifier

def test_hub_member_untyped_over_cap_is_stopped_with_reason():
    rows = [_row("Tag_Hub", untyped=True, subtree_count=45, has_children=True)]
    out = bw.classify_rows(rows, max_depth=10, hub_cap=30)
    assert [c["name"] for c in out["concepts"]] == ["Tag_Hub"], "boundary member still INCLUDED (G7)"
    assert len(out["stopped"]) == 1
    assert out["stopped"][0]["name"] == "Tag_Hub"
    assert "hub_cap" in out["stopped"][0]["reason"] and "45 > 30" in out["stopped"][0]["reason"]
    print("✓ hub member (untyped, subtree 45 > 30): included as leaf + stopped[hub_cap]")


def test_axis_member_typed_boundary_is_stopped_with_type_reason():
    rows = [_row("Some_Axis", boundary_type_hits=["Hwss_Domain"], subtree_count=500,
                 has_children=True)]
    out = bw.classify_rows(rows, max_depth=10, hub_cap=30)
    assert [c["name"] for c in out["concepts"]] == ["Some_Axis"]
    assert out["stopped"][0]["reason"] == "boundary_type: Hwss_Domain"
    print("✓ axis member (IS_A Hwss_Domain): included as leaf + stopped[boundary_type]")


def test_typed_hub_is_NOT_hub_capped_the_dmn_ladder_requirement():
    # G4: a live Conversation_<ts> measured HAS_PART*1..4 count 807 — typed (IS_A Conversation),
    # so the cap must NOT stop it, or every DMN ladder activation truncates.
    rows = [_row("Conversation_2026_08_26T20_36_08", untyped=False, subtree_count=807,
                 has_children=True, min_depth=1)]
    out = bw.classify_rows(rows, max_depth=10, hub_cap=30)
    assert out["stopped"] == [], "a TYPED member is never hub-capped (G4/G6 reconciliation)"
    print("✓ typed hub (Conversation, subtree 807): NOT capped — DMN ladders stay whole")


def test_depth_stop_reported_only_at_max_depth_with_children():
    rows = [
        _row("At_Max_With_Children", min_depth=4, has_children=True),
        _row("At_Max_Leaf", min_depth=4, has_children=False),
        _row("Shallow_With_Children", min_depth=2, has_children=True),
    ]
    out = bw.classify_rows(rows, max_depth=4, hub_cap=30)
    stopped_names = [s["name"] for s in out["stopped"]]
    assert stopped_names == ["At_Max_With_Children"], f"got {stopped_names}"
    assert "depth" in out["stopped"][0]["reason"] and "4" in out["stopped"][0]["reason"]
    print("✓ depth stop: only members AT max depth WITH children below are reported")


def test_cycle_duplicate_rows_dedupe_keeping_min_depth():
    # A cyclic graph cannot loop the Cypher (per-path relationship uniqueness), but the
    # classifier must stay correct if an executor ever hands it duplicate member rows.
    rows = [
        _row("Cycle_Node", min_depth=5, has_children=True),
        _row("Cycle_Node", min_depth=2, has_children=True),
        _row("Cycle_Node", min_depth=9, has_children=True),
    ]
    out = bw.classify_rows(rows, max_depth=9, hub_cap=30)
    assert len(out["concepts"]) == 1, "duplicates must collapse to one member"
    assert out["stopped"] == [], "min_depth 2 < max_depth 9 => not a depth stop"
    print("✓ cycle/duplicate rows: deduped to one member, min depth kept")


def test_reason_precedence_type_beats_cap():
    rows = [_row("Both", boundary_type_hits=["Carton_Collection"], untyped=False,
                 subtree_count=999, has_children=True)]
    out = bw.classify_rows(rows, max_depth=10, hub_cap=30)
    assert len(out["stopped"]) == 1
    assert out["stopped"][0]["reason"].startswith("boundary_type:")
    print("✓ reason precedence: boundary_type wins over hub_cap")


def test_missing_description_preserved_verbatim():
    rows = [_row("Ghost", description=None), _row("Empty", description="")]
    out = bw.classify_rows(rows, max_depth=10, hub_cap=30)
    assert all(c["description"] == "[MISSING CONCEPT - NOT YET DEFINED]" for c in out["concepts"])
    assert out["missing"] == ["Empty", "Ghost"]
    print("✓ missing-description members flagged with the legacy verbatim marker")


# ---------------------------------------------------------------- result shape

def test_report_leads_the_payload_key_order():
    rows = [_row("Tag_Hub", untyped=True, subtree_count=45, has_children=True), _row("Leaf")]
    result = bw.build_activation_result("Coll", rows, max_depth=10, hub_cap=30)
    keys = list(result.keys())
    assert keys.index("truncation_report") < keys.index("concepts"), keys
    assert keys.index("stopped") < keys.index("concepts"), keys
    assert result["truncation_report"].startswith("BOUNDED-WALK TRUNCATION: 1 member(s)")
    assert "max_depth=10" in result["truncation_report"] and "hub_cap=30" in result["truncation_report"]
    print("✓ result: truncation_report + stopped INSERTED BEFORE concepts (G10 — _fmt truncates at 10k)")


def test_zero_stops_result_is_byte_compatible_with_legacy_shape():
    # G4: when nothing stops, the rendered payload must be byte-identical to pre-#203.
    # _fmt drops None/[]/{} fields, so truncation_report must be None and stopped must be [].
    rows = [_row("A"), _row("B", description=None)]
    result = bw.build_activation_result("Coll", rows, max_depth=10, hub_cap=30)
    assert result["truncation_report"] is None, "must be None so _fmt drops it"
    assert result["stopped"] == [], "must be [] so _fmt drops it"
    rendered_keys = [k for k, v in result.items() if v is not None and v != [] and v != {}]
    assert rendered_keys == ["success", "collection_name", "concepts", "total_count", "warning"], rendered_keys
    assert result["warning"] == ("⚠️ Warnings: [B] are in Coll but are not defined, themselves.")
    assert result["total_count"] == 2
    print("✓ result: zero stops => rendered fields identical to the pre-#203 shape (byte-compat)")


def test_empty_collection_result_matches_legacy_exactly():
    result = bw.build_activation_result("Nope", [], max_depth=10, hub_cap=30)
    assert result == {
        "success": True,
        "collection_name": "Nope",
        "concepts": [],
        "total_count": 0,
        "warning": None,
        "message": "Collection 'Nope' is empty or does not exist",
    }
    print("✓ result: empty collection reproduces the legacy shape exactly")


def test_stop_report_elision_is_itself_reported():
    stopped = [{"name": f"N{i}", "reason": "boundary_type: Hypercluster"} for i in range(50)]
    report = bw.build_stop_report(stopped, max_depth=10, hub_cap=30, inline_limit=40)
    assert "50 member(s)" in report
    assert "and 10 more" in report, "the report's own inline cap must not be silent (G2)"
    print("✓ report: inline elision is itself reported (no silent caps, even in the report)")


if __name__ == "__main__":
    print("Testing carton_bounded_walk — pure plan-builder + row-classifier unit tests (issue #203)")
    print("=" * 78)
    test_plan_interpolates_depth_and_parameterizes_the_rest()
    test_plan_default_depth_is_1()
    test_plan_boundary_types_default_is_the_docmirror_collect_list()
    test_plan_prunes_intermediates_not_the_terminal_member()
    test_plan_rejects_bad_depth()
    test_hub_member_untyped_over_cap_is_stopped_with_reason()
    test_axis_member_typed_boundary_is_stopped_with_type_reason()
    test_typed_hub_is_NOT_hub_capped_the_dmn_ladder_requirement()
    test_depth_stop_reported_only_at_max_depth_with_children()
    test_cycle_duplicate_rows_dedupe_keeping_min_depth()
    test_reason_precedence_type_beats_cap()
    test_missing_description_preserved_verbatim()
    test_report_leads_the_payload_key_order()
    test_zero_stops_result_is_byte_compatible_with_legacy_shape()
    test_empty_collection_result_matches_legacy_exactly()
    test_stop_report_elision_is_itself_reported()
    print("=" * 78)
    print("ALL BOUNDED-WALK UNIT TESTS PASSED")
