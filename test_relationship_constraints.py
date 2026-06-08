#!/usr/bin/env python3
"""Test relationship constraint validation in Carton."""

import os
import sys

# Set environment variables for testing
os.environ['GITHUB_PAT'] = 'test_token'
os.environ['REPO_URL'] = 'test_repo'
os.environ['BASE_PATH'] = '/tmp/carton_constraint_test'
# TRIGGERS: Neo4j database via Bolt protocol on localhost:7687
os.environ['NEO4J_URI'] = 'bolt://localhost:7687'
os.environ['NEO4J_USER'] = 'neo4j'
os.environ['NEO4J_PASSWORD'] = 'password'

from carton_mcp.add_concept_tool import add_concept_tool_func

def test_part_of_cycle():
    """Test that adding part_of with cycle is rejected."""
    print("\n=== Test 1: part_of Cycle Detection ===")

    try:
        # Create A part_of B
        result1 = add_concept_tool_func(
            concept_name="ConceptA",
            description="Concept A",
            relationships=[{"relationship": "is_a", "related": ["TestConcept"]},
                          {"relationship": "part_of", "related": ["ConceptB"]}]
        )
        print(f"✓ Created ConceptA part_of ConceptB: {result1}")
    except Exception as e:
        print(f"✗ Failed to create ConceptA: {e}")
        return

    try:
        # Create B part_of C
        result2 = add_concept_tool_func(
            concept_name="ConceptB",
            description="Concept B",
            relationships=[{"relationship": "is_a", "related": ["TestConcept"]},
                          {"relationship": "part_of", "related": ["ConceptC"]}]
        )
        print(f"✓ Created ConceptB part_of ConceptC: {result2}")
    except Exception as e:
        print(f"✗ Failed to create ConceptB: {e}")
        return

    try:
        # Try to create C part_of A (should fail - creates cycle)
        result3 = add_concept_tool_func(
            concept_name="ConceptC",
            description="Concept C",
            relationships=[{"relationship": "is_a", "related": ["TestConcept"]},
                          {"relationship": "part_of", "related": ["ConceptA"]}]
        )
        print(f"✗ FAILED: Should have rejected cycle, but created: {result3}")
    except Exception as e:
        if "Cycle detected" in str(e):
            print(f"✓ Correctly rejected cycle: {e}")
        else:
            print(f"✗ Failed with unexpected error: {e}")

def test_instantiates_empty_pattern():
    """Test that instantiating empty pattern is rejected."""
    print("\n=== Test 2: Instantiates Empty Pattern ===")

    try:
        # Try to instantiate EmptyPattern (which has no parts)
        result = add_concept_tool_func(
            concept_name="InstanceOfEmpty",
            description="Instance of empty pattern",
            relationships=[{"relationship": "is_a", "related": ["TestInstance"]},
                          {"relationship": "instantiates", "related": ["EmptyPattern"]}]
        )
        print(f"✗ FAILED: Should have rejected empty pattern, but created: {result}")
    except Exception as e:
        if "pattern has no parts" in str(e):
            print(f"✓ Correctly rejected empty pattern: {e}")
        else:
            print(f"✗ Failed with unexpected error: {e}")

def test_part_of_instantiated():
    """Test that adding part_of to instantiated concept triggers versioning."""
    print("\n=== Test 3: part_of to Instantiated Concept ===")

    try:
        # Create Pattern with a part
        result1 = add_concept_tool_func(
            concept_name="PartX",
            description="Part X",
            relationships=[{"relationship": "is_a", "related": ["Part"]},
                          {"relationship": "part_of", "related": ["PatternY"]}]
        )
        print(f"✓ Created PartX part_of PatternY: {result1}")
    except Exception as e:
        print(f"✗ Failed to create PartX: {e}")
        return

    try:
        # Create instance that instantiates PatternY
        result2 = add_concept_tool_func(
            concept_name="InstanceY",
            description="Instance of Pattern Y",
            relationships=[{"relationship": "is_a", "related": ["Instance"]},
                          {"relationship": "instantiates", "related": ["PatternY"]}]
        )
        print(f"✓ Created InstanceY instantiates PatternY: {result2}")
    except Exception as e:
        print(f"✗ Failed to create InstanceY: {e}")
        return

    try:
        # Try to add another part to PatternY (should fail - instantiated)
        result3 = add_concept_tool_func(
            concept_name="PartZ",
            description="Part Z",
            relationships=[{"relationship": "is_a", "related": ["Part"]},
                          {"relationship": "part_of", "related": ["PatternY"]}]
        )
        print(f"✗ FAILED: Should have rejected part_of to instantiated, but created: {result3}")
    except Exception as e:
        if "immutable" in str(e) and "_v" in str(e):
            print(f"✓ Correctly rejected with version suggestion: {e}")
        else:
            print(f"✗ Failed with unexpected error: {e}")

if __name__ == "__main__":
    print("Testing Carton Relationship Constraints")
    print("=" * 50)

    # Note: These tests require a running Neo4j instance
    # and will create test data in /tmp/carton_constraint_test

    test_part_of_cycle()
    test_instantiates_empty_pattern()
    test_part_of_instantiated()

    print("\n" + "=" * 50)
    print("Tests complete")
