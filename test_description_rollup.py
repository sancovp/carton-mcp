#!/usr/bin/env python3
"""Unit tests for _compute_description_rollup (D2 rollup, add_concept_tool.py).

Pure library-level test — NO Neo4j, no MCP, no daemon. _compute_description_rollup takes a
concept name + a relationship dict and returns a string; it does no I/O, so this is the
onion-architecture INNER layer test: it must pass standing alone, before anything wraps it.

Renders Isaac's exact template (verbatim, 2026-07-03): "{X} {is_a}, {part_of} in the {subdomain}
subdomain of {domain} domain. X has {has-part list}, which instantiates {instantiates}. {X}
instantiating that graph produces {produces}."
"""

from carton_mcp.add_concept_tool import _compute_description_rollup, _compute_d2_coverage


def test_empty_relationship_dict_returns_empty_string():
    result = _compute_description_rollup("Some_Concept", {})
    assert result == "", f"expected empty string, got {result!r}"
    print("✓ empty relationship_dict -> empty string")


def test_full_template_all_three_sentences():
    rels = {
        "is_a": ["Bug_Report"],
        "part_of": ["Launch_Strategy"],
        "has_domain": ["System"],
        "has_subdomain": ["Split_Content_Verification"],
        "has_step_1": ["Template_Method"],
        "instantiates": ["Process_Pattern"],
        "produces": ["Fix_Commit"],
    }
    result = _compute_description_rollup("Some_Concept", rels)
    expected = (
        "Some_Concept is_a Bug_Report, part_of Launch_Strategy in the "
        "Split_Content_Verification subdomain of System domain. "
        "Some_Concept has Template_Method, which instantiates Process_Pattern. "
        "Some_Concept instantiating that graph produces Fix_Commit."
    )
    assert result == expected, f"expected:\n{expected}\ngot:\n{result}"
    print("✓ full data -> all three sentences, exact template text")


def test_missing_produces_omits_third_sentence():
    rels = {"is_a": ["Bug_Report"], "part_of": ["Launch_Strategy"]}
    result = _compute_description_rollup("Some_Concept", rels)
    assert "produces" not in result, f"produces clause should be omitted, got {result!r}"
    assert result == "Some_Concept is_a Bug_Report, part_of Launch_Strategy."
    print("✓ no produces -> third sentence omitted, no domain/subdomain tail either")


def test_missing_has_parts_but_instantiates_present():
    rels = {"is_a": ["Bug_Report"], "instantiates": ["Process_Pattern"]}
    result = _compute_description_rollup("Some_Concept", rels)
    assert result == "Some_Concept is_a Bug_Report. Some_Concept instantiates Process_Pattern.", result
    print("✓ instantiates with no has-parts -> 'X instantiates Y' fallback phrasing")


def test_domain_without_subdomain():
    rels = {"is_a": ["Bug_Report"], "has_domain": ["System"]}
    result = _compute_description_rollup("Some_Concept", rels)
    assert result == "Some_Concept is_a Bug_Report in the System domain.", result
    print("✓ domain present, subdomain absent -> 'in the {domain} domain' only")


def test_administrative_keys_never_counted_as_has_parts():
    rels = {
        "is_a": ["Bug_Report"],
        "has_domain": ["System"],
        "has_subdomain": ["Sub"],
        "has_personal_domain": ["cave"],
    }
    result = _compute_description_rollup("Some_Concept", rels)
    # No genuine has_X part and no instantiates -> sentence 2 ("X has ...") must be entirely absent.
    assert " has " not in result, f"sentence 2 should be omitted (no real has-parts), got {result!r}"
    # has_personal_domain must never surface anywhere in the rendered text.
    assert "cave" not in result, f"has_personal_domain must never appear in the rollup, got {result!r}"
    # has_domain/has_subdomain DO surface, but only in their intended domain-tail role.
    assert result == "Some_Concept is_a Bug_Report in the Sub subdomain of System domain.", result
    print("✓ has_domain/has_subdomain/has_personal_domain never leak into the has-part-list clause")


def test_rollup_output_satisfies_full_d2_coverage():
    rels = {
        "is_a": ["Bug_Report"],
        "part_of": ["Launch_Strategy"],
        "has_domain": ["System"],
        "has_subdomain": ["Sub_Domain"],
        "instantiates": ["Process_Pattern"],
        "produces": ["Fix_Commit"],
    }
    rollup = _compute_description_rollup("Some_Concept", rels)
    coverage, unmatched = _compute_d2_coverage(rollup, rels)
    assert coverage == 100, f"rollup output must self-satisfy D2 100%, got {coverage}, unmatched={unmatched}"
    print("✓ the computed rollup, fed back through _compute_d2_coverage, scores 100%")


if __name__ == "__main__":
    print("Testing description rollup (_compute_description_rollup) — pure lib-level unit tests")
    print("=" * 70)
    test_empty_relationship_dict_returns_empty_string()
    test_full_template_all_three_sentences()
    test_missing_produces_omits_third_sentence()
    test_missing_has_parts_but_instantiates_present()
    test_domain_without_subdomain()
    test_administrative_keys_never_counted_as_has_parts()
    test_rollup_output_satisfies_full_d2_coverage()
    print("=" * 70)
    print("ALL DESCRIPTION ROLLUP UNIT TESTS PASSED")
