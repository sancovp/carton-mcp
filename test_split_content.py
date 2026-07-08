#!/usr/bin/env python3
"""Unit tests for build_split_spec (carton_split_content.py).

Pure library-level test — NO Neo4j, no MCP, no daemon. build_split_spec takes a concept name +
raw content string and returns a dict; it does no I/O, so this is the onion-architecture INNER
layer test: it must pass standing alone, before the thin wrapper (split_content_concept, in the
same module) or its MCP exposure (server_fastmcp.py's split_content_concept tool) are trusted.
"""

from carton_mcp.carton_split_content import build_split_spec


def test_content_node_name_derivation():
    spec = build_split_spec("My_Concept", "some raw content")
    assert spec["content_node_name"] == "My_Concept_Desc_Content", f"got {spec['content_node_name']}"
    print("✓ content_node_name = {concept_name}_Desc_Content")


def test_content_node_is_a_and_part_of():
    spec = build_split_spec("My_Concept", "some raw content")
    assert spec["content_node_is_a"] == ["Desc_Content"], f"got {spec['content_node_is_a']}"
    assert spec["content_node_part_of"] == ["My_Concept"], f"got {spec['content_node_part_of']}"
    print("✓ is_a=[Desc_Content], part_of=[concept_name]")


def test_relationship_name():
    spec = build_split_spec("My_Concept", "some raw content")
    assert spec["relationship_name"] == "has_desc_content", f"got {spec['relationship_name']}"
    print("✓ relationship_name = has_desc_content")


def test_content_passed_through_byte_identical():
    raw = "Line one.\nLine two with special chars: <CartonObj>{}</CartonObj> and unicode: ☃\nTrailing whitespace   "
    spec = build_split_spec("My_Concept", raw)
    assert spec["content_node_description"] == raw, "raw content must be byte-identical, never modified"
    print("✓ raw content passed through byte-identical (never truncated/modified)")


def test_never_modifies_input_content_string():
    raw = "the exact original string, byte for byte"
    build_split_spec("My_Concept", raw)
    assert raw == "the exact original string, byte for byte", "input string must never be mutated"
    print("✓ input raw_content is never touched/modified by build_split_spec")


def test_empty_content_preserved_as_empty():
    spec = build_split_spec("My_Concept", "")
    assert spec["content_node_description"] == "", f"got {spec['content_node_description']!r}"
    print("✓ empty raw_content preserved as empty string (not defaulted/replaced)")


if __name__ == "__main__":
    print("Testing content split (build_split_spec) — pure lib-level unit tests")
    print("=" * 70)
    test_content_node_name_derivation()
    test_content_node_is_a_and_part_of()
    test_relationship_name()
    test_content_passed_through_byte_identical()
    test_never_modifies_input_content_string()
    test_empty_content_preserved_as_empty()
    print("=" * 70)
    print("ALL CONTENT SPLIT UNIT TESTS PASSED")
