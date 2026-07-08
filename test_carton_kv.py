"""
Unit tests for carton_kv (STEP 1 parser/normalizer). PURE — no neo4j / no MCP.

Run standalone:  python3 test_carton_kv.py     (prints PASS/FAIL summary)
Or via pytest:   pytest test_carton_kv.py

Covers the commander's required edge cases:
  - multiple FLAT fences in one string
  - deeply-nested JSON
  - bare refs as dict-VALUES and as array-ELEMENTS
  - quoted literals NOT treated as refs
  - a literal </CartonObj> inside a quoted string value (harmless via span scan)
plus: ref-grammar, attr parsing, object round-trip, minimal-diff splice, malformed handling.
"""
import json

from carton_kv import (
    is_title_underscore,
    scan_json_span,
    refs_to_strict_json,
    body_from_obj,
    parse_fence_body,
    parse_attrs,
    find_carton_objs,
    get_carton_obj,
    serialize_carton_obj,
    replace_carton_obj_body,
    split_key_path,
    apply_carton_obj_op,
    extract_refs,
    deref_for_validation,
    validate_against_schema,
    remove_carton_obj,
    carry_forward_fences,
    expand_refs_in_description,
)

REF = lambda name: {"$ref": name}  # noqa: E731 — terse ref literal for tests


# --------------------------------------------------------------------------- #
# ref grammar
# --------------------------------------------------------------------------- #
def test_is_title_underscore():
    assert is_title_underscore("Reality")
    assert is_title_underscore("Foo_Bar")
    assert is_title_underscore("OVP_Ova_2")
    assert is_title_underscore("A1_B2")
    assert not is_title_underscore("foo_bar")     # lowercase start
    assert not is_title_underscore("Foo_")        # trailing underscore
    assert not is_title_underscore("Foo__Bar")    # double underscore
    assert not is_title_underscore("_Foo")        # leading underscore
    assert not is_title_underscore("true")        # json literal
    assert not is_title_underscore("123")         # number


# --------------------------------------------------------------------------- #
# span scanner
# --------------------------------------------------------------------------- #
def test_scan_json_span_object():
    s = '{"a": 1}TAIL'
    assert scan_json_span(s, 0) == len('{"a": 1}')


def test_scan_json_span_array():
    s = "[1, 2, [3, 4]]rest"
    assert scan_json_span(s, 0) == len("[1, 2, [3, 4]]")


def test_scan_json_span_braces_inside_string_ignored():
    s = '{"x": "a } ] { string"}AFTER'
    end = scan_json_span(s, 0)
    assert s[:end] == '{"x": "a } ] { string"}'


def test_scan_json_span_close_fence_inside_string_ignored():
    # The crux: a literal </CartonObj> inside a string must NOT end the body.
    s = '{"x": "text </CartonObj> more"}</CartonObj>'
    end = scan_json_span(s, 0)
    assert s[:end] == '{"x": "text </CartonObj> more"}'


def test_scan_json_span_escaped_quote():
    s = r'{"x": "a \" } brace"}Z'
    end = scan_json_span(s, 0)
    assert s[:end] == r'{"x": "a \" } brace"}'


def test_scan_json_span_unterminated_raises():
    try:
        scan_json_span('{"a": 1', 0)
        assert False, "expected ValueError"
    except ValueError:
        pass


# --------------------------------------------------------------------------- #
# converters
# --------------------------------------------------------------------------- #
def test_refs_to_strict_json_value_and_array():
    raw = '{"k": Foo_Bar, "list": [Baz, Qux_2], "lit": "Not_A_Ref"}'
    strict = refs_to_strict_json(raw)
    obj = json.loads(strict)  # must be valid strict JSON
    assert obj == {
        "k": REF("Foo_Bar"),
        "list": [REF("Baz"), REF("Qux_2")],
        "lit": "Not_A_Ref",       # quoted literal stays a plain string
    }


def test_refs_to_strict_json_leaves_json_literals():
    raw = '{"a": true, "b": false, "c": null, "n": -3.5}'
    assert json.loads(refs_to_strict_json(raw)) == {"a": True, "b": False, "c": None, "n": -3.5}


def test_body_from_obj_renders_refs_bare():
    obj = {"k": REF("Foo_Bar"), "list": [REF("Baz"), 1], "s": "lit"}
    body = body_from_obj(obj)
    assert "Foo_Bar" in body and '{"$ref"' not in body
    # round-trips back to the same object
    assert parse_fence_body(body) == obj


def test_parse_fence_body_malformed_raises():
    try:
        parse_fence_body('{"a": Foo_Bar,,}')
        assert False, "expected ValueError"
    except ValueError:
        pass


# --------------------------------------------------------------------------- #
# attributes
# --------------------------------------------------------------------------- #
def test_parse_attrs_bare_and_quoted():
    attrs = parse_attrs('name=Unit_Registry schema=Some_Schema is_schema=true desc="hi there"')
    assert attrs == {
        "name": "Unit_Registry",
        "schema": "Some_Schema",
        "is_schema": "true",
        "desc": "hi there",
    }


# --------------------------------------------------------------------------- #
# find_carton_objs — the integration of the above
# --------------------------------------------------------------------------- #
def test_find_single_fence_full_record():
    text = 'prose <CartonObj name=Reg schema=Reg_Schema>{"v": Foo_Bar, "n": 3}</CartonObj> tail'
    fences = find_carton_objs(text)
    assert len(fences) == 1
    f = fences[0]
    assert f.name == "Reg"
    assert f.schema == "Reg_Schema"
    assert f.is_schema is False
    assert f.obj == {"v": REF("Foo_Bar"), "n": 3}
    # spans are exact
    assert text[f.span[0]:f.span[1]].startswith("<CartonObj name=Reg")
    assert text[f.span[0]:f.span[1]].endswith("</CartonObj>")
    assert text[f.body_span[0]:f.body_span[1]] == '{"v": Foo_Bar, "n": 3}'


def test_find_multiple_flat_fences():
    text = (
        "intro\n"
        '<CartonObj name=A>{"x": One_Ref}</CartonObj>\n'
        "middle prose\n"
        '<CartonObj name=B>{"y": [Two_Ref, Three_Ref]}</CartonObj>\n'
        "outro"
    )
    fences = find_carton_objs(text)
    assert [f.name for f in fences] == ["A", "B"]
    assert fences[0].obj == {"x": REF("One_Ref")}
    assert fences[1].obj == {"y": [REF("Two_Ref"), REF("Three_Ref")]}


def test_find_deeply_nested_json():
    text = '<CartonObj name=Deep>{"a": {"b": {"c": [1, {"d": Leaf_Ref}]}}}</CartonObj>'
    f = find_carton_objs(text)[0]
    assert f.obj == {"a": {"b": {"c": [1, {"d": REF("Leaf_Ref")}]}}}


def test_find_refs_as_dict_values_and_array_elements():
    text = '<CartonObj name=Mix>{"val": Dict_Val_Ref, "arr": [Elem_A, Elem_B, "lit"]}</CartonObj>'
    f = find_carton_objs(text)[0]
    assert f.obj == {"val": REF("Dict_Val_Ref"), "arr": [REF("Elem_A"), REF("Elem_B"), "lit"]}


def test_find_quoted_literal_not_ref():
    text = '<CartonObj name=Q>{"bare": Real_Ref, "quoted": "Looks_Like_Ref"}</CartonObj>'
    f = find_carton_objs(text)[0]
    assert f.obj["bare"] == REF("Real_Ref")
    assert f.obj["quoted"] == "Looks_Like_Ref"   # stays a literal string


def test_find_literal_close_fence_inside_string():
    # The headline edge case: </CartonObj> inside a quoted value must not end the fence.
    text = '<CartonObj name=Tricky>{"note": "use </CartonObj> literally", "r": Safe_Ref}</CartonObj>AFTER'
    fences = find_carton_objs(text)
    assert len(fences) == 1
    f = fences[0]
    assert f.obj == {"note": "use </CartonObj> literally", "r": REF("Safe_Ref")}
    # the fence ends at the REAL close tag, leaving AFTER untouched
    assert text[f.span[1]:] == "AFTER"


def test_is_schema_flag_parsed():
    text = '<CartonObj name=My_Schema is_schema=true>{"type": "object"}</CartonObj>'
    f = find_carton_objs(text)[0]
    assert f.is_schema is True
    assert f.obj == {"type": "object"}


def test_malformed_fence_skipped_by_default():
    text = 'ok <CartonObj name=Bad>{"a": 1  NO CLOSE  and <CartonObj name=Good>{"b": Good_Ref}</CartonObj>'
    fences = find_carton_objs(text)
    # the Bad open tag has no valid body+close; scanner recovers and finds Good
    assert [f.name for f in fences] == ["Good"]
    assert fences[0].obj == {"b": REF("Good_Ref")}


def test_get_carton_obj_by_name():
    text = '<CartonObj name=A>{"x": 1}</CartonObj><CartonObj name=B>{"y": 2}</CartonObj>'
    assert get_carton_obj(text, "B").obj == {"y": 2}
    assert get_carton_obj(text, "Nope") is None


# --------------------------------------------------------------------------- #
# serialize + splice (minimal-diff write basis)
# --------------------------------------------------------------------------- #
def test_serialize_carton_obj_round_trips():
    fence_text = serialize_carton_obj("Reg", {"v": REF("Foo_Bar"), "n": 3}, schema="Reg_Schema")
    assert fence_text.startswith("<CartonObj name=Reg schema=Reg_Schema>")
    f = find_carton_objs(fence_text)[0]
    assert f.name == "Reg" and f.schema == "Reg_Schema"
    assert f.obj == {"v": REF("Foo_Bar"), "n": 3}


def test_serialize_is_schema_attr():
    fence_text = serialize_carton_obj("S", {"type": "object"}, is_schema=True)
    assert "is_schema=true" in fence_text
    assert find_carton_objs(fence_text)[0].is_schema is True


def test_replace_body_is_minimal_diff():
    text = (
        "PROSE BEFORE "
        '<CartonObj name=A>{"x": Old_Ref}</CartonObj>'
        " MIDDLE "
        '<CartonObj name=B>{"y": 2}</CartonObj>'
        " PROSE AFTER"
    )
    out = replace_carton_obj_body(text, "A", {"x": New_Ref_obj(), "z": 9})
    # A's body changed; everything else byte-identical
    assert get_carton_obj(out, "A").obj == {"x": REF("New_Ref"), "z": 9}
    assert "PROSE BEFORE " in out and " MIDDLE " in out and " PROSE AFTER" in out
    # B fence untouched, byte-identical
    b_src = '<CartonObj name=B>{"y": 2}</CartonObj>'
    assert b_src in out
    # open + close tags of A preserved exactly
    assert "<CartonObj name=A>" in out and out.count("</CartonObj>") == 2


def New_Ref_obj():
    return {"$ref": "New_Ref"}


def test_replace_body_missing_name_raises():
    try:
        replace_carton_obj_body('<CartonObj name=A>{"x": 1}</CartonObj>', "Z", {"x": 2})
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_full_round_trip_parse_serialize_parse():
    original_obj = {
        "title": "literal text",
        "owner": REF("Owner_Concept"),
        "deps": [REF("Dep_One"), REF("Dep_Two")],
        "meta": {"nested": REF("Nested_Ref"), "count": 7, "flag": True},
    }
    body = body_from_obj(original_obj)
    reparsed = parse_fence_body(body)
    assert reparsed == original_obj
    # and through a full fence
    fence = serialize_carton_obj("Round", original_obj)
    assert find_carton_objs(fence)[0].obj == original_obj


# --------------------------------------------------------------------------- #
# STEP 2 — pure op-applier
# --------------------------------------------------------------------------- #
def test_split_key_path():
    assert split_key_path("") == []
    assert split_key_path("a.b.c") == ["a", "b", "c"]
    assert split_key_path("a.0.b") == ["a", 0, "b"]
    assert split_key_path("0") == [0]
    assert split_key_path("-1") == [-1]


_DESC = (
    "Some prose about the registry.\n"
    '<CartonObj name=Unit_Registry schema=Reg_Schema>'
    '{"units": {"cave": {"repo": Cave_Repo, "tier": 2}}, "order": [A_Unit, B_Unit]}'
    "</CartonObj>\n"
    "trailing prose <CartonObj name=Other>{\"k\": 1}</CartonObj> end"
)


def test_op_get_leaf():
    new, val = apply_carton_obj_op(_DESC, "Unit_Registry", "units.cave.tier", "get")
    assert val == 2
    assert new == _DESC  # get never mutates


def test_op_get_ref_value():
    _, val = apply_carton_obj_op(_DESC, "Unit_Registry", "units.cave.repo", "get")
    assert val == {"$ref": "Cave_Repo"}


def test_op_set_leaf_minimal_diff():
    new, val = apply_carton_obj_op(_DESC, "Unit_Registry", "units.cave.tier", "set", 5)
    assert val == 5
    assert get_carton_obj(new, "Unit_Registry").obj["units"]["cave"]["tier"] == 5
    # prose + sibling fence byte-identical
    assert new.startswith("Some prose about the registry.\n")
    assert '<CartonObj name=Other>{"k": 1}</CartonObj> end' in new
    # only the tier leaf changed: cave repo ref untouched
    assert get_carton_obj(new, "Unit_Registry").obj["units"]["cave"]["repo"] == {"$ref": "Cave_Repo"}


def test_op_set_new_key_on_dict():
    new, _ = apply_carton_obj_op(_DESC, "Unit_Registry", "units.cave.lang", "set", "python")
    assert get_carton_obj(new, "Unit_Registry").obj["units"]["cave"]["lang"] == "python"


def test_op_set_ref_value():
    new, _ = apply_carton_obj_op(_DESC, "Unit_Registry", "units.cave.owner", "set", {"$ref": "Owner_X"})
    # round-trips to a BARE ref in the stored body
    assert "Owner_X" in get_carton_obj(new, "Unit_Registry").raw_body
    assert "$ref" not in get_carton_obj(new, "Unit_Registry").raw_body
    assert get_carton_obj(new, "Unit_Registry").obj["units"]["cave"]["owner"] == {"$ref": "Owner_X"}


def test_op_set_list_index():
    new, _ = apply_carton_obj_op(_DESC, "Unit_Registry", "order.1", "set", {"$ref": "New_Unit"})
    assert get_carton_obj(new, "Unit_Registry").obj["order"] == [{"$ref": "A_Unit"}, {"$ref": "New_Unit"}]


def test_op_append_to_list():
    new, target = apply_carton_obj_op(_DESC, "Unit_Registry", "order", "append", {"$ref": "C_Unit"})
    assert get_carton_obj(new, "Unit_Registry").obj["order"] == [
        {"$ref": "A_Unit"}, {"$ref": "B_Unit"}, {"$ref": "C_Unit"}
    ]


def test_op_append_non_list_raises():
    try:
        apply_carton_obj_op(_DESC, "Unit_Registry", "units.cave.tier", "append", 1)
        assert False, "expected TypeError"
    except TypeError:
        pass


def test_op_remove_dict_key():
    new, _ = apply_carton_obj_op(_DESC, "Unit_Registry", "units.cave.tier", "remove")
    cave = get_carton_obj(new, "Unit_Registry").obj["units"]["cave"]
    assert "tier" not in cave and cave["repo"] == {"$ref": "Cave_Repo"}


def test_op_remove_list_index():
    new, _ = apply_carton_obj_op(_DESC, "Unit_Registry", "order.0", "remove")
    assert get_carton_obj(new, "Unit_Registry").obj["order"] == [{"$ref": "B_Unit"}]


def test_op_set_whole_body():
    new, _ = apply_carton_obj_op(_DESC, "Unit_Registry", "", "set", {"fresh": True})
    assert get_carton_obj(new, "Unit_Registry").obj == {"fresh": True}
    # sibling fence still intact
    assert get_carton_obj(new, "Other").obj == {"k": 1}


def test_op_missing_fence_raises():
    try:
        apply_carton_obj_op(_DESC, "Nope", "a", "get")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_op_bad_op_raises():
    try:
        apply_carton_obj_op(_DESC, "Unit_Registry", "units", "frobnicate", 1)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_op_bad_path_raises():
    try:
        apply_carton_obj_op(_DESC, "Unit_Registry", "units.nonexistent.deep", "get")
        assert False, "expected KeyError"
    except (KeyError, IndexError, TypeError):
        pass


def test_op_only_target_fence_changes_other_byte_identical():
    new, _ = apply_carton_obj_op(_DESC, "Other", "k", "set", 99)
    # Unit_Registry fence is byte-identical
    ur_src = _DESC[_DESC.index("<CartonObj name=Unit_Registry"):_DESC.index("</CartonObj>") + len("</CartonObj>")]
    assert ur_src in new
    assert get_carton_obj(new, "Other").obj == {"k": 99}


# --------------------------------------------------------------------------- #
# STEP 4 — pure ref-extraction + schema validation
# --------------------------------------------------------------------------- #
def test_extract_refs_nested():
    obj = {"a": REF("R1"), "b": [REF("R2"), 1, "lit"], "c": {"d": REF("R3")}, "n": 5}
    assert extract_refs(obj) == ["R1", "R2", "R3"]


def test_extract_refs_none():
    assert extract_refs({"a": 1, "b": ["x", "y"], "c": {"d": True}}) == []


def test_deref_for_validation():
    obj = {"repo": REF("Cave_Repo"), "arr": [REF("A"), 2], "lit": "keep"}
    assert deref_for_validation(obj) == {"repo": "Cave_Repo", "arr": ["A", 2], "lit": "keep"}


_SCHEMA = {
    "type": "object",
    "properties": {"tier": {"type": "integer"}, "repo": {"type": "string"}},
    "required": ["tier"],
}


def test_validate_good_payload():
    body = {"tier": 2, "repo": REF("Cave_Repo")}     # ref dereffed to the string "Cave_Repo"
    assert validate_against_schema(body, _SCHEMA) == []


def test_validate_bad_type_reports_key():
    body = {"tier": "free", "repo": REF("Cave_Repo")}
    errs = validate_against_schema(body, _SCHEMA)
    assert len(errs) == 1
    assert errs[0]["path"] == "tier"
    assert "integer" in errs[0]["message"]


def test_validate_missing_required_reports():
    body = {"repo": REF("Cave_Repo")}                # missing required 'tier'
    errs = validate_against_schema(body, _SCHEMA)
    assert len(errs) == 1
    assert "tier" in errs[0]["message"]


# --------------------------------------------------------------------------- #
# STEP 4B — fence removal + fence-preservation guard core
# --------------------------------------------------------------------------- #
def test_remove_carton_obj():
    text = 'A <CartonObj name=X>{"k": 1}</CartonObj> B <CartonObj name=Y>{"m": 2}</CartonObj> C'
    out = remove_carton_obj(text, "X")
    assert get_carton_obj(out, "X") is None
    assert get_carton_obj(out, "Y").obj == {"m": 2}   # sibling preserved
    assert "A " in out and " C" in out


def test_remove_carton_obj_missing_raises():
    try:
        remove_carton_obj('<CartonObj name=X>{"k":1}</CartonObj>', "Z")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_carry_forward_replace_preserves_fence():
    old = 'Prose. <CartonObj name=Reg>{"tier": 2, "repo": Cave_Repo}</CartonObj>'
    incoming = "New re-derived prose with NO fence."     # the dangerous case
    out = carry_forward_fences(old, incoming)
    assert '<CartonObj name=Reg>{"tier": 2, "repo": Cave_Repo}</CartonObj>' in out
    assert out.startswith("New re-derived prose")        # incoming prose kept, fence appended


def test_carry_forward_no_double_add_when_present():
    old = 'Old. <CartonObj name=Reg>{"tier": 2}</CartonObj>'
    incoming = 'New. <CartonObj name=Reg>{"tier": 5}</CartonObj>'   # edited fence, present by name
    out = carry_forward_fences(old, incoming)
    assert out == incoming                                # not carried — incoming's edit wins
    assert out.count("name=Reg") == 1


def test_carry_forward_honors_removed_fences():
    old = 'Old. <CartonObj name=Reg>{"tier": 2}</CartonObj>'
    incoming = "New prose only."
    out = carry_forward_fences(old, incoming, removed_fences=["Reg"])
    assert out == incoming                                # explicitly removed → not carried


def test_carry_forward_partial_multiple():
    old = '<CartonObj name=A>{"a": 1}</CartonObj> mid <CartonObj name=B>{"b": 2}</CartonObj>'
    incoming = 'kept <CartonObj name=A>{"a": 9}</CartonObj> only'
    out = carry_forward_fences(old, incoming)
    assert get_carton_obj(out, "A").obj == {"a": 9}       # A present in incoming → not carried
    assert get_carton_obj(out, "B").obj == {"b": 2}       # B absent → carried verbatim


def test_carry_forward_noop_when_no_old_fences():
    assert carry_forward_fences("just prose", "new prose") == "new prose"


# --------------------------------------------------------------------------- #
# STEP 5 — ref-expansion (read-time projection, depth + cycle)
# --------------------------------------------------------------------------- #
# A fake graph: name -> {"description": str, "relationships": [(rel,target)]}
_GRAPH = {
    "Cave_Repo": {"description": 'A repo. <CartonObj name=inner>{"owner": Olivus}</CartonObj>',
                  "relationships": [("is_a", "Repo"), ("part_of", "Monorepo")]},
    "Olivus": {"description": "all of us", "relationships": [("is_a", "Identity")]},
    # cycle: A -> B -> A
    "A_Node": {"description": '<CartonObj name=an>{"next": B_Node}</CartonObj>', "relationships": []},
    "B_Node": {"description": '<CartonObj name=bn>{"next": A_Node}</CartonObj>', "relationships": []},
}


def _fetch(name):
    return _GRAPH.get(name)


_EXP_DESC = 'Reg. <CartonObj name=reg>{"repo": Cave_Repo, "tier": 2}</CartonObj>'


def test_expand_depth0_is_raw():
    assert expand_refs_in_description(_EXP_DESC, _fetch, 0) == _EXP_DESC   # unchanged


def test_expand_depth1_one_hop():
    out = expand_refs_in_description(_EXP_DESC, _fetch, 1)
    assert "Cave_Repo⟨" in out                       # ref expanded inline
    assert "A repo." in out                           # its description shown
    assert "is_a Repo" in out                         # its relationships shown
    # one hop only: Cave_Repo's OWN inner ref (Olivus) is NOT expanded at depth 1
    assert "Olivus⟨" not in out
    assert "tier" in out                              # non-ref data preserved


def test_expand_depth2_recurses():
    out = expand_refs_in_description(_EXP_DESC, _fetch, 2)
    assert "Cave_Repo⟨" in out
    assert "Olivus⟨" in out                           # second hop expanded
    assert "all of us" in out                          # Olivus's description


def test_expand_cycle_terminates():
    desc = '<CartonObj name=c>{"start": A_Node}</CartonObj>'
    out = expand_refs_in_description(desc, _fetch, 5)   # deep depth + a cycle
    assert "A_Node⟨" in out
    assert "cycle" in out                               # cycle marker, no infinite loop


def test_expand_unresolved_ref_marked():
    desc = '<CartonObj name=u>{"x": No_Such_Concept}</CartonObj>'
    out = expand_refs_in_description(desc, _fetch, 1)
    assert "No_Such_Concept⟨…unresolved⟩" in out


def test_expand_no_fence_unchanged():
    assert expand_refs_in_description("just prose with Cave_Repo word", _fetch, 2) == "just prose with Cave_Repo word"


# --------------------------------------------------------------------------- #
# standalone runner
# --------------------------------------------------------------------------- #
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
