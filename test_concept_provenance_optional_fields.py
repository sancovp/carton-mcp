#!/usr/bin/env python3
"""Unit tests for merge_optional_domain_fields (add_concept_tool.py).

Pure library-level test — NO Neo4j, no MCP, no daemon. merge_optional_domain_fields takes the
RELATIONSHIPS LIST ([{"relationship":..., "related":...}, ...]) plus the four optional
domain/subdomain/personal_domain/produces values and returns a NEW list with them merged in; it
does no I/O, so this is the onion-architecture INNER layer test.

Covers the task-58 fix (Isaac 2026-07-04, verbatim): "it can move into add concept tool func
but as optionals because it cant change anything about how other code uses carton as lib unless
we wanna go thru literally all the code and check for these calls and adjust them." So
add_concept_tool_func gained domain/subdomain/personal_domain/produces as OPTIONAL params
(unlike the add_concept MCP tool, which requires them) — this module tests the pure merge logic
those params feed into.

IMPORTANT (why this operates on the LIST, not relationship_dict): add_concept_tool_func's queue
write persists `relationships` (the list) verbatim to the daemon queue — relationship_dict is a
derived view used only for SOMA/D2 validation. Merging only into relationship_dict would make
these fields validate correctly but never actually reach the graph (caught live during E2E
verification 2026-07-04, before this function's final shape was settled).
"""

from carton_mcp.add_concept_tool import (
    merge_optional_domain_fields,
    validate_personal_domain_value,
    PERSONAL_DOMAINS,
)


def test_all_none_returns_equivalent_list_unchanged():
    rels = [{"relationship": "is_a", "related": ["Bug_Report"]}]
    result = merge_optional_domain_fields(rels, None, None, None, None)
    assert result == rels, result
    print("✓ all-None optional args -> relationships list content unchanged (backward compat)")


def test_all_none_does_not_mutate_input_list():
    rels = [{"relationship": "is_a", "related": ["Bug_Report"]}]
    result = merge_optional_domain_fields(rels, "System", None, None, None)
    assert rels == [{"relationship": "is_a", "related": ["Bug_Report"]}], "input list must not be mutated"
    assert result is not rels, "must return a NEW list"
    print("✓ input relationships list is never mutated in place")


def test_all_four_fields_appear_as_new_entries():
    rels = [{"relationship": "is_a", "related": ["Bug_Report"]}]
    result = merge_optional_domain_fields(rels, "System", "Carton_Schema", "cave", ["Fix_Commit"])
    by_type = {r["relationship"]: r["related"] for r in result}
    assert by_type["has_domain"] == ["System"]
    assert by_type["has_subdomain"] == ["Carton_Schema"]
    assert by_type["has_personal_domain"] == ["cave"]
    assert by_type["produces"] == ["Fix_Commit"]
    assert by_type["is_a"] == ["Bug_Report"], "pre-existing entries must be untouched"
    print("✓ all four optional fields appear as correctly-typed new relationship entries")


def test_invalid_personal_domain_raises():
    try:
        merge_optional_domain_fields([], None, None, "not_a_real_domain", None)
        raise AssertionError("expected Exception for invalid personal_domain")
    except Exception as e:
        assert "not_a_real_domain" in str(e)
        for d in PERSONAL_DOMAINS:
            assert d in str(e), f"error message should list valid values, missing {d}"
    print("✓ invalid personal_domain raises with the valid-values list in the message")


def test_valid_personal_domain_does_not_raise():
    for d in PERSONAL_DOMAINS:
        result = merge_optional_domain_fields([], None, None, d, None)
        by_type = {r["relationship"]: r["related"] for r in result}
        assert by_type["has_personal_domain"] == [d]
    print("✓ every PERSONAL_DOMAINS enum value is accepted without raising")


def test_dedupes_against_value_already_present_via_generic_relationships():
    # Caller already hand-built a has_domain entry via the generic relationships list AND
    # passed domain="System" as the optional convenience param — must not duplicate the target.
    rels = [{"relationship": "has_domain", "related": ["System"]}]
    result = merge_optional_domain_fields(rels, "System", None, None, None)
    by_type = {r["relationship"]: r["related"] for r in result}
    assert by_type["has_domain"] == ["System"], f"expected no duplicate, got {by_type['has_domain']}"
    assert len([r for r in result if r["relationship"] == "has_domain"]) == 1, "must not create a second has_domain entry"
    print("✓ a domain value already present via generic relationships is not duplicated")


def test_produces_merges_alongside_existing_produces_targets():
    rels = [{"relationship": "produces", "related": ["Existing_Output"]}]
    result = merge_optional_domain_fields(rels, None, None, None, ["New_Output", "Existing_Output"])
    by_type = {r["relationship"]: r["related"] for r in result}
    assert by_type["produces"] == ["Existing_Output", "New_Output"], by_type["produces"]
    print("✓ produces extends existing targets, deduped, order-preserving")


def test_empty_produces_list_is_a_noop_not_an_error():
    rels = [{"relationship": "is_a", "related": ["X"]}]
    result = merge_optional_domain_fields(rels, None, None, None, [])
    by_type = {r["relationship"]: r["related"] for r in result}
    assert "produces" not in by_type, "an empty produces list must not create the entry at all"
    print("✓ empty produces list -> no-op (matches falsy-value skip, not a crash)")


def test_illegal_personal_domain_via_relationships_list_raises():
    """THE HOLE (measured 2026-08-26, closed the same day).

    The enum was 'documented and enforced' while 640 illegal has_personal_domain edges sat in
    the graph across 7 non-enum values (Frameworks 606, _Unnamed 19, Discord 5,
    Potential_Offers 3, Starsystem 3, Gnosys 3, Testing 1). They got in because the gate only
    ever read the personal_domain PARAM — a caller stating the same fact through the raw
    relationships list walked straight past it. A gate on one of two doors is not a gate.
    """
    rels = [
        {"relationship": "is_a", "related": ["Bug_Report"]},
        {"relationship": "has_personal_domain", "related": ["Frameworks"]},
    ]
    try:
        merge_optional_domain_fields(rels, None, None, None, None)
        raise AssertionError(
            "expected Exception: 'Frameworks' is not in the personal_domain enum and must be "
            "refused when supplied via the relationships list, exactly as via the param"
        )
    except AssertionError:
        raise
    except Exception as e:
        assert "Frameworks" in str(e), str(e)
        assert "relationships list" in str(e), f"error must name WHICH door it came through: {e}"
    print("✓ illegal has_personal_domain via the relationships list raises (the 640-edge hole)")


def test_titlecase_personal_domain_is_accepted_via_both_doors():
    """CartON normalizes relationship targets to Title_Case, so the graph holds `Cave`, not
    `cave`. A case-SENSITIVE gate would refuse 604 legal, already-stored values — and a
    migration that 'corrected' them would flatten all 604 to misc. Both doors must accept it.
    """
    result = merge_optional_domain_fields([], None, None, "Cave", None)
    by_type = {r["relationship"]: r["related"] for r in result}
    assert by_type["has_personal_domain"] == ["Cave"], by_type
    rels = [{"relationship": "has_personal_domain", "related": ["Paiab", "Sanctum"]}]
    result = merge_optional_domain_fields(rels, None, None, None, None)
    by_type = {r["relationship"]: r["related"] for r in result}
    assert by_type["has_personal_domain"] == ["Paiab", "Sanctum"], by_type
    print("✓ Title_Case personal_domain accepted via BOTH the param and the relationships list")


def test_validate_personal_domain_value_directly():
    for legal in ("cave", "Cave", "CAVE", "misc", "Personal"):
        validate_personal_domain_value(legal, "a test")
    for illegal in ("Frameworks", "", "sanctuary", "Misc_Ideas"):
        try:
            validate_personal_domain_value(illegal, "a test")
            raise AssertionError(f"expected Exception for {illegal!r}")
        except AssertionError:
            raise
        except Exception as e:
            assert "a test" in str(e), f"error must name its source: {e}"
    print("✓ validate_personal_domain_value: case-insensitive accept, names its source on raise")


if __name__ == "__main__":
    print("Testing merge_optional_domain_fields — pure lib-level unit tests")
    print("=" * 70)
    test_all_none_returns_equivalent_list_unchanged()
    test_all_none_does_not_mutate_input_list()
    test_all_four_fields_appear_as_new_entries()
    test_invalid_personal_domain_raises()
    test_valid_personal_domain_does_not_raise()
    test_dedupes_against_value_already_present_via_generic_relationships()
    test_produces_merges_alongside_existing_produces_targets()
    test_empty_produces_list_is_a_noop_not_an_error()
    test_illegal_personal_domain_via_relationships_list_raises()
    test_titlecase_personal_domain_is_accepted_via_both_doors()
    test_validate_personal_domain_value_directly()
    print("=" * 70)
    print("ALL CONCEPT-PROVENANCE OPTIONAL-FIELDS UNIT TESTS PASSED")
