"""
Lib-level tests for STEP 4 graph-bound logic: check_kv_refs (fuzzy did-you-mean),
register_kv_schemas (IS_A Carton_Kv_Schema + USES_KV_SCHEMA), validate_carton_obj
(schema bad-key + unresolved-ref), and the edit_carton_obj did-you-mean WRITE GUARD.

Uses a FakeGraph stub (no real neo4j). Run: python3 test_carton_kv_schema.py
"""
import json
import os
import tempfile

os.environ["HEAVEN_DATA_DIR"] = tempfile.mkdtemp(prefix="kvschema_")
from carton_mcp.carton_utils import (  # noqa: E402
    check_kv_refs, register_kv_schemas, validate_carton_obj, edit_carton_obj,
)
from carton_mcp.add_concept_tool import get_observation_queue_dir  # noqa: E402


def _drain_queue():
    qd = get_observation_queue_dir()
    files = sorted(qd.glob("*.json"))
    entries = [json.load(open(f)) for f in files]
    for f in files:
        f.unlink()
    return entries


class FakeGraph:
    """Stub KnowledgeGraphBuilder: a {name: description} store + recorded MERGE calls.
    description=None means the concept exists but has no n.d."""
    def __init__(self, store):
        self.store = dict(store)          # name -> description (or None)
        self.merges = []                  # recorded write queries

    def execute_query(self, query, params=None):
        params = params or {}
        q = " ".join(query.split())       # collapse whitespace for matching
        # existence check
        if "MATCH (c:Wiki {n: $n}) RETURN c.n AS n LIMIT 1" in q:
            return [{"n": params["n"]}] if params["n"] in self.store else []
        # read description (edit uses $name, validate uses $n)
        if "RETURN c.d AS d LIMIT 1" in q:
            d = self.store.get(params.get("n") or params.get("name"))
            return [{"d": d}] if d else []
        # fuzzy candidate scan
        if "toLower(c.n) CONTAINS $tok" in q:
            tok = params.get("tok", "")
            return [{"n": n} for n in self.store if tok in n.lower()]
        # any MERGE / write — record and succeed
        if "MERGE" in q:
            self.merges.append((q, params))
            return []
        return []


_SCHEMA_DESC = (
    "Schema for unit registry entries.\n"
    '<CartonObj name=reg_schema is_schema=true>'
    '{"type": "object", "properties": {"tier": {"type": "integer"}, "repo": {"type": "string"}}, '
    '"required": ["tier"]}'
    "</CartonObj>"
)


def _store(extra=None):
    s = {
        "Reg_Schema": _SCHEMA_DESC,
        "Cave_Repo": "the cave repo",
        "Free_Tier": "free tier",
        "A_Unit": "a", "B_Unit": "b",
    }
    if extra:
        s.update(extra)
    return s


# --------------------------------------------------------------------------- #
# check_kv_refs — fuzzy did-you-mean
# --------------------------------------------------------------------------- #
def test_check_refs_all_resolve():
    g = FakeGraph(_store())
    res = check_kv_refs(["Cave_Repo", "A_Unit"], g)
    assert res["ok"] is True and res["unresolved"] == {}


def test_check_refs_unresolved_with_suggestion():
    g = FakeGraph(_store())
    res = check_kv_refs(["Cave_Rep"], g)   # typo of Cave_Repo (does not exist)
    assert res["ok"] is False
    assert "Cave_Rep" in res["unresolved"]
    assert "Cave_Repo" in res["unresolved"]["Cave_Rep"]   # did-you-mean caught the real one


def test_check_refs_unresolved_no_match():
    g = FakeGraph(_store())
    res = check_kv_refs(["Zzz_Nonexistent"], g)
    assert res["ok"] is False
    assert res["unresolved"]["Zzz_Nonexistent"] == []      # no close matches


# --------------------------------------------------------------------------- #
# register_kv_schemas — auto-typing
# --------------------------------------------------------------------------- #
def test_register_is_schema_types_concept():
    g = FakeGraph(_store())
    out = register_kv_schemas("Reg_Schema", _SCHEMA_DESC, g)
    assert out["typed_schemas"] == ["reg_schema"]
    # an IS_A Carton_Kv_Schema MERGE was issued
    assert any("Carton_Kv_Schema" in q and "IS_A" in q for q, _ in g.merges)


def test_register_schema_reference_adds_uses_edge():
    desc = 'A unit. <CartonObj name=reg schema=Reg_Schema>{"tier": 2, "repo": Cave_Repo}</CartonObj>'
    g = FakeGraph(_store())
    out = register_kv_schemas("My_Unit", desc, g)
    assert out["uses_schemas"] == ["Reg_Schema"]
    assert any("USES_KV_SCHEMA" in q for q, _ in g.merges)


def test_register_no_fence_is_noop():
    g = FakeGraph(_store())
    out = register_kv_schemas("Plain", "just prose, no fences", g)
    assert out == {"typed_schemas": [], "uses_schemas": []}
    assert g.merges == []


# --------------------------------------------------------------------------- #
# validate_carton_obj — schema bad-key + unresolved-ref
# --------------------------------------------------------------------------- #
def test_validate_good_payload():
    desc = 'Unit. <CartonObj name=reg schema=Reg_Schema>{"tier": 2, "repo": Cave_Repo}</CartonObj>'
    g = FakeGraph(_store({"Good_Unit": desc}))
    res = validate_carton_obj("Good_Unit", "reg", g)
    assert res["success"] and res["valid"] is True
    assert res["errors"] == [] and res["unresolved_refs"] == {}


def test_validate_bad_key_reported():
    desc = 'Unit. <CartonObj name=reg schema=Reg_Schema>{"tier": "free", "repo": Cave_Repo}</CartonObj>'
    g = FakeGraph(_store({"Bad_Unit": desc}))
    res = validate_carton_obj("Bad_Unit", "reg", g)
    assert res["valid"] is False
    assert any(e["path"] == "tier" for e in res["errors"])


def test_validate_unknown_ref_did_you_mean():
    desc = 'Unit. <CartonObj name=reg schema=Reg_Schema>{"tier": 2, "repo": Cave_Rep}</CartonObj>'
    g = FakeGraph(_store({"Typo_Unit": desc}))
    res = validate_carton_obj("Typo_Unit", "reg", g)
    assert res["valid"] is False
    assert "Cave_Rep" in res["unresolved_refs"]
    assert "Cave_Repo" in res["unresolved_refs"]["Cave_Rep"]


# --------------------------------------------------------------------------- #
# edit_carton_obj — the WRITE GUARD (refuse a write that introduces an unknown ref)
# --------------------------------------------------------------------------- #
def test_edit_guard_refuses_unknown_ref():
    desc = 'Unit. <CartonObj name=reg>{"tier": 2, "repo": Cave_Repo}</CartonObj>'
    g = FakeGraph(_store({"Guard_Unit": desc}))
    res = edit_carton_obj("Guard_Unit", "reg", "owner", "set", {"$ref": "Nonexist_Owner"},
                          shared_connection=g)
    assert res["success"] is False
    assert "unresolved" in res["error"]
    assert "Nonexist_Owner" in res["did_you_mean"]
    assert g.merges == []   # NOTHING written


def test_edit_guard_allows_known_ref():
    desc = 'Unit. <CartonObj name=reg>{"tier": 2, "repo": Cave_Repo}</CartonObj>'
    g = FakeGraph(_store({"Guard_Unit": desc}))
    res = edit_carton_obj("Guard_Unit", "reg", "owner", "set", {"$ref": "A_Unit"}, shared_connection=g)
    assert res["success"] is True   # A_Unit exists → write proceeds (queued)


def test_edit_guard_allows_literal_value():
    desc = 'Unit. <CartonObj name=reg>{"tier": 2, "repo": Cave_Repo}</CartonObj>'
    g = FakeGraph(_store({"Guard_Unit": desc}))
    res = edit_carton_obj("Guard_Unit", "reg", "tier", "set", 9, shared_connection=g)
    assert res["success"] is True   # literal int, no ref → no guard trip


# --------------------------------------------------------------------------- #
# STEP 4B — remove_fence op (explicit whole-fence deletion via edit_carton_obj)
# --------------------------------------------------------------------------- #
def test_remove_fence_op_queues_replace_with_removed_fences():
    _drain_queue()
    desc = ('Prose. <CartonObj name=reg>{"tier": 2, "repo": Cave_Repo}</CartonObj>'
            ' more <CartonObj name=other>{"k": 1}</CartonObj>')
    g = FakeGraph(_store({"Rm_Unit": desc}))
    res = edit_carton_obj("Rm_Unit", "reg", "", "remove_fence", shared_connection=g)
    assert res["success"] is True
    entries = _drain_queue()
    assert len(entries) == 1
    e = entries[0]
    assert e["desc_update_mode"] == "replace"
    assert e["removed_fences"] == ["reg"]              # tells the daemon guard NOT to carry it back
    assert "name=reg" not in e["description"]          # reg fence removed from the new desc
    assert "name=other" in e["description"]            # sibling fence preserved


def test_remove_fence_missing_fence_errors_no_write():
    _drain_queue()
    desc = 'Prose. <CartonObj name=reg>{"tier": 2}</CartonObj>'
    g = FakeGraph(_store({"Rm_Unit": desc}))
    res = edit_carton_obj("Rm_Unit", "no_such", "", "remove_fence", shared_connection=g)
    assert res["success"] is False
    assert _drain_queue() == []                        # nothing queued on a bad remove


def test_normal_edit_has_empty_removed_fences():
    _drain_queue()
    desc = 'Prose. <CartonObj name=reg>{"tier": 2}</CartonObj>'
    g = FakeGraph(_store({"Rm_Unit": desc}))
    res = edit_carton_obj("Rm_Unit", "reg", "tier", "set", 7, shared_connection=g)
    assert res["success"] is True
    e = _drain_queue()[0]
    assert e["removed_fences"] == []                   # a normal edit removes no fences


# --------------------------------------------------------------------------- #
# STEP 4B daemon-path regression: parse_queue_file_to_concepts must FORWARD removed_fences.
# (The runtime bug: the MAIN worker loop parses raw_concept files via this fn — which dropped
# removed_fences — so the guard saw [] and carried a removed fence back. This test guards it.)
# --------------------------------------------------------------------------- #
def test_parse_queue_file_forwards_removed_fences():
    from pathlib import Path
    from carton_mcp.observation_worker_daemon import parse_queue_file_to_concepts
    qf = Path(os.environ["HEAVEN_DATA_DIR"]) / "x_concept.json"
    qf.write_text(json.dumps({
        "raw_concept": True,
        "concept_name": "Rm_Unit",
        "description": 'Prose. <CartonObj name=first>{"a": 1}</CartonObj>',
        "relationships": [],
        "desc_update_mode": "replace",
        "removed_fences": ["second"],
    }))
    concepts = parse_queue_file_to_concepts(qf)
    qf.unlink()
    assert len(concepts) == 1
    assert concepts[0]["removed_fences"] == ["second"]   # MUST reach batch_create's guard
    assert concepts[0]["desc_update_mode"] == "replace"


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
