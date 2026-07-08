"""Deterministic tests for aut_deducer (Griess-constructor phase 0). NO live daemons, NO neo4j,
NO OWL files: definitions are synthetic D(C) dicts built directly, and the one provenance test
uses a recording-fake `execute`. Covers the five specified fixtures:
  (a) 3 same-colored slots -> S3, order 6, one orbit
  (b) all-distinct colors  -> trivial group
  (c) 2+2 same-colored pairs -> S2 x S2, order 4, two orbits
  (d) provenance refinement: mocked evidence breaks one symmetry -> refined subgroup/orbit split
  (e) restriction_R present in every output
plus the M2 set_properties encoder preview (flat values only) and the fail-loud surfaces.
"""

import json

import pytest

from carton_mcp.aut_deducer import (
    RESTRICTION_R,
    deduce_aut_from_definition,
    encode_aut_properties,
    provenance_substitutability,
    read_definition,
    refine_orbits_with_evidence,
    slot_color,
    verify_order_brute_force,
)


def _slot(prop, target_type=None, cardinality=None, stage="owl_restriction", source="owl"):
    return {"prop": prop, "target_type": target_type, "cardinality": cardinality,
            "stage": stage, "source": source}


def test_a_three_same_colored_slots_give_s3():
    defn = {"class_name": "Fixture_A",
            "slots": [_slot("has_part", "Component", "min 1")] * 3}
    aut = deduce_aut_from_definition(defn)
    assert aut["order"] == 6                       # |S3|
    assert len(aut["orbits"]) == 1
    assert sorted(aut["orbits"][0]) == ["has_part#0", "has_part#1", "has_part#2"]
    assert len(aut["generators"]) == 2             # adjacent transpositions generate S3
    assert verify_order_brute_force(defn) == 6     # brute-force cross-check (n<=10 regime)


def test_b_all_distinct_colors_give_trivial_group():
    defn = {"class_name": "Fixture_B",
            "slots": [_slot("has_key", "Key", "exactly 1"),
                      _slot("has_value", "Value", "exactly 1"),
                      _slot("produced_by", "Source", "exactly 1")]}
    aut = deduce_aut_from_definition(defn)
    assert aut["order"] == 1
    assert aut["generators"] == []
    assert all(len(o) == 1 for o in aut["orbits"])
    assert verify_order_brute_force(defn) == 1


def test_c_two_plus_two_pairs_give_s2_x_s2():
    defn = {"class_name": "Fixture_C",
            "slots": [_slot("has_part", "Wheel", "min 1"), _slot("has_part", "Wheel", "min 1"),
                      _slot("has_port", "Port", "some"), _slot("has_port", "Port", "some")]}
    aut = deduce_aut_from_definition(defn)
    assert aut["order"] == 4                       # |S2 x S2|
    assert len(aut["orbits"]) == 2
    assert sorted(len(o) for o in aut["orbits"]) == [2, 2]
    assert verify_order_brute_force(defn) == 4


def test_d_mocked_provenance_evidence_refines_orbit():
    # 3 same-colored slots (S3); mocked FILLED_FROM-style evidence distinguishes slot #0
    # (filled by humans) from #1/#2 (filled by tools) -> the symmetry breaks, orbit splits.
    defn = {"class_name": "Fixture_D",
            "slots": [_slot("has_part", "Component", "min 1")] * 3}
    aut = deduce_aut_from_definition(defn)
    assert aut["order"] == 6
    evidence = {"has_part#0": frozenset({"human"}),
                "has_part#1": frozenset({"tool"}),
                "has_part#2": frozenset({"tool"})}
    refined = refine_orbits_with_evidence(aut, evidence)
    assert refined["order"] == 2                   # S1 x S2 — refined subgroup
    assert sorted(len(o) for o in refined["orbits"]) == [1, 2]
    assert refined["refined_from_order"] == 6
    assert ["has_part#1", "has_part#2"] in refined["orbits"]


def test_e_restriction_r_present_in_every_output():
    defn_a = {"class_name": "Fixture_A", "slots": [_slot("has_part", "Component")] * 3}
    aut = deduce_aut_from_definition(defn_a)
    refined = refine_orbits_with_evidence(aut, {"has_part#0": "x"})
    for out in (aut, refined):
        assert out["restriction_R"] == RESTRICTION_R
        assert "cannot distinguish what it cannot express" in out["restriction_R"]
        assert "computed_at" in out


def test_slot_color_is_the_full_four_tuple():
    s = _slot("has_part", "Wheel", "min 2", stage="owl_restriction")
    assert slot_color(s) == ("has_part", "Wheel", "min 2", "owl_restriction")
    # source is provenance, NOT color: two slots differing only in source share an orbit
    defn = {"class_name": "X", "slots": [_slot("p", "T", None, "s", source="graph"),
                                         _slot("p", "T", None, "s", source="owl")]}
    assert deduce_aut_from_definition(defn)["order"] == 2


def test_provenance_substitutability_with_recording_fake():
    calls = []

    def fake_execute(query, params):
        calls.append((query, params))
        # 3 distinct concepts, same source_type, 2 distinct sources -> ONE substitution hit
        return [
            {"concept": "C1", "prop": "has_part", "source_type": "tool", "source": "S1"},
            {"concept": "C2", "prop": "has_part", "source_type": "tool", "source": "S2"},
            {"concept": "C3", "prop": "has_part", "source_type": "tool", "source": "S1"},
            # a sparse group (1 concept) must NOT count, even with 2 sources
            {"concept": "C1", "prop": "has_part", "source_type": "human", "source": "H1"},
        ]

    orbits = [["has_part#0", "has_part#1"]]
    out = provenance_substitutability("Fixture_P", orbits, fake_execute, threshold=3)
    assert len(out) == 1
    row = out[0]
    assert row["substitution_hits"] == 1
    assert row["observation_count"] == 4
    assert row["distinct_fill_sources"] == 3       # S1, S2, H1
    assert calls and calls[0][1]["props"] == ["has_part"]
    assert "FILLED_FROM" in calls[0][0]            # reads the real substrate's edge type


def test_provenance_substitutability_empty_graph_is_thin():
    out = provenance_substitutability("Fixture_Q", [["has_part#0", "has_part#1"]],
                                      lambda q, p: [])
    assert out[0]["substitution_hits"] == 0
    assert out[0]["observation_count"] == 0
    assert out[0]["distinct_fill_sources"] == 0


def test_read_definition_fails_loud_on_neither_surface():
    # graph says "no node"; no OWL surface passed -> LookupError, never a silent empty dict
    with pytest.raises(LookupError) as exc:
        read_definition("Nope_Class", execute=lambda q, p: [])
    assert "resolves on NEITHER surface" in str(exc.value)
    # no surface at all is a programming error
    with pytest.raises(ValueError) as exc2:
        read_definition("Nope_Class")
    assert "needs at least one surface" in str(exc2.value)


def test_read_definition_graph_surface_shapes_slots():
    def fake_execute(query, params):
        if "REQUIRES_RELATIONSHIP" in query:
            return [{"prop": "Has_Domain"}, {"prop": "Has_What"}]
        if "HAS_REQUIRED_PART" in query:
            return [{"part": "Engine_Block", "types": ["Engine"]}]
        return [{"n": params["n"]}]   # the existence probe

    defn = read_definition("Fixture_G", execute=fake_execute)
    stages = [s["stage"] for s in defn["slots"]]
    assert stages.count("required_relationship") == 2
    assert stages.count("required_part") == 1
    assert stages.count("core_sentence") == 4      # is_a / part_of / instantiates / produces
    part_slot = next(s for s in defn["slots"] if s["stage"] == "required_part")
    assert part_slot["target_type"] == "Engine"    # the part's IS_A type colors the slot
    assert defn["surfaces"] == {"graph": True, "owl": False}


def test_encode_aut_properties_is_flat_for_set_properties():
    defn = {"class_name": "Fixture_C",
            "slots": [_slot("has_part", "Wheel")] * 2 + [_slot("has_port", "Port")] * 2}
    aut = deduce_aut_from_definition(defn)
    enc = encode_aut_properties(aut)
    assert enc["aut_order"] == 4 and isinstance(enc["aut_order"], int)
    assert enc["aut_orbit_count"] == 2
    # flat list of comma-joined slot ids — NO nested dicts (set_properties refuses them)
    assert isinstance(enc["aut_orbits"], list)
    assert all(isinstance(x, str) for x in enc["aut_orbits"])
    assert "has_part#0,has_part#1" in enc["aut_orbits"]
    assert json.loads(enc["aut_generators"]) == aut["generators"]   # json round-trip
    assert isinstance(enc["aut_computed_at"], str)
    assert enc["aut_restriction_r"] == RESTRICTION_R
    for v in enc.values():
        assert isinstance(v, (str, int)) or (isinstance(v, list) and all(isinstance(i, str) for i in v))


if __name__ == "__main__":
    # Script-style runner (this repo's convention: pytest collection inside the repo tree trips over
    # the repo-root __init__.py, which pytest 8 imports as a top-level Package init — a pre-existing
    # repo-wide condition. Run either `python3 tests/test_aut_deducer.py` here, or pytest on this
    # file from any directory OUTSIDE the repo's package ancestry.)
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if failures else 0)
