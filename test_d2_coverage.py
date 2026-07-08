#!/usr/bin/env python3
"""Unit tests for _compute_d2_coverage (D2, add_concept_tool.py).

Pure library-level test — NO Neo4j, no MCP, no daemon. _compute_d2_coverage
takes a description string + a relationship dict and returns a tuple; it does
no I/O, so this is the onion-architecture INNER layer test: it must pass
standing alone, before anything wraps it (add_concept_tool_func) or exposes
it over MCP (server_fastmcp.py's add_concept).
"""

from carton_mcp.add_concept_tool import _compute_d2_coverage


def test_empty_relationship_dict_returns_none_coverage():
    coverage, unmatched = _compute_d2_coverage("some description", {})
    assert coverage is None, f"expected None coverage, got {coverage}"
    assert unmatched == [], f"expected no unmatched, got {unmatched}"
    print("✓ empty relationship_dict -> (None, [])")


def test_relationship_dict_with_no_targets_returns_none_coverage():
    coverage, unmatched = _compute_d2_coverage("some description", {"is_a": [], "part_of": []})
    assert coverage is None, f"expected None coverage, got {coverage}"
    assert unmatched == [], f"expected no unmatched, got {unmatched}"
    print("✓ relationships present but all-empty target lists -> (None, [])")


def test_full_coverage_underscored_form():
    rels = {"is_a": ["Bug_Report"], "part_of": ["Launch_Strategy"]}
    desc = "This is a Bug_Report that is part_of the Launch_Strategy effort."
    coverage, unmatched = _compute_d2_coverage(desc, rels)
    assert coverage == 100, f"expected 100, got {coverage}"
    assert unmatched == [], f"expected no unmatched, got {unmatched}"
    print("✓ every target mentioned in underscored form -> 100%, no unmatched")


def test_full_coverage_spaced_form():
    rels = {"is_a": ["Bug_Report"], "part_of": ["Launch_Strategy"]}
    desc = "This is a bug report that is part of the launch strategy effort."
    coverage, unmatched = _compute_d2_coverage(desc, rels)
    assert coverage == 100, f"expected 100, got {coverage}"
    assert unmatched == [], f"expected no unmatched, got {unmatched}"
    print("✓ every target mentioned in spaced form -> 100%, no unmatched")


def test_partial_coverage_reports_correct_unmatched():
    rels = {"is_a": ["Bug_Report"], "part_of": ["Launch_Strategy"], "produces": ["Fix_Commit"]}
    desc = "This is a Bug_Report about something."
    coverage, unmatched = _compute_d2_coverage(desc, rels)
    assert coverage == 33, f"expected 33 (1/3), got {coverage}"
    assert set(unmatched) == {"Launch_Strategy", "Fix_Commit"}, f"got {unmatched}"
    print("✓ partial match -> correct percentage and correct unmatched set")


def test_zero_coverage_when_nothing_mentioned():
    rels = {"is_a": ["Alpha_Concept"], "part_of": ["Beta_Concept"]}
    coverage, unmatched = _compute_d2_coverage("totally unrelated text", rels)
    assert coverage == 0, f"expected 0, got {coverage}"
    assert set(unmatched) == {"Alpha_Concept", "Beta_Concept"}, f"got {unmatched}"
    print("✓ nothing mentioned -> 0%, everything unmatched")


def test_never_modifies_description():
    rels = {"is_a": ["Alpha_Concept"]}
    desc = "the exact original string, byte for byte"
    _compute_d2_coverage(desc, rels)
    assert desc == "the exact original string, byte for byte", "description must never be mutated"
    print("✓ description is never touched/modified by the coverage check")


if __name__ == "__main__":
    print("Testing D2 coverage (_compute_d2_coverage) — pure lib-level unit tests")
    print("=" * 70)
    test_empty_relationship_dict_returns_none_coverage()
    test_relationship_dict_with_no_targets_returns_none_coverage()
    test_full_coverage_underscored_form()
    test_full_coverage_spaced_form()
    test_partial_coverage_reports_correct_unmatched()
    test_zero_coverage_when_nothing_mentioned()
    test_never_modifies_description()
    print("=" * 70)
    print("ALL D2 COVERAGE UNIT TESTS PASSED")
