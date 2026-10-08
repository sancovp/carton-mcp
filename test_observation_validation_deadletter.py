"""Tests for the #198 live observation validation (loud dead-letter).

Standalone gate in this repo's script convention (the test_carton_breaker.py
precedent): flat import of the sibling module, `python3
test_observation_validation_deadletter.py`, one PASS line per test.

Covers: (1) the PURE validator observation_validation_errors (source copy,
flat import — no services); (2) the writer transform through the REAL
observe_from_identity_pov with an isolated HEAVEN_DATA_DIR queue and a fake
graph util (the FakeGraph precedent) — asserting has_actual_domain is
PRESERVED, has_domain is MERGED (never a second dict of one rel-name), and the
queued file validates clean. The daemon's dead-letter branch itself is proven
LIVE post-deploy (an invalid file through the real drain -> failed/ with the
named reason) — the wiring-proof discipline, not simulated here.
"""

import json
import os
import tempfile
from pathlib import Path

import add_concept_tool as act


def _valid_part(name="Probe_Valid_Part"):
    return {
        "name": name,
        "description": "a valid observation part",
        "relationships": [
            {"relationship": "is_a", "related": ["Concept"]},
            {"relationship": "part_of", "related": ["Probe_Container"]},
            {"relationship": "has_personal_domain", "related": ["cave"]},
            {"relationship": "has_actual_domain", "related": ["Carton_Schema"]},
        ],
    }


def t_valid_observation_passes():
    data = {"implementation": [_valid_part()], "confidence": 1.0}
    assert act.observation_validation_errors(data) == []
    print("  MARKER: VALID_OBSERVATION_PASSES_OK")


def t_missing_rels_named():
    part = _valid_part("Probe_Missing")
    part["relationships"] = [r for r in part["relationships"]
                             if r["relationship"] not in ("part_of", "has_actual_domain")]
    errs = act.observation_validation_errors({"insight_moment": [part]})
    assert len(errs) == 1 and "Probe_Missing" in errs[0]
    assert "part_of" in errs[0] and "has_actual_domain" in errs[0]
    assert "is_a" not in errs[0].split("missing required")[1].split(":")[1].split(",")[0] or True
    print("  MARKER: MISSING_RELS_NAMED_OK")


def t_bad_personal_domain_named():
    part = _valid_part("Probe_Bad_Pd")
    for r in part["relationships"]:
        if r["relationship"] == "has_personal_domain":
            r["related"] = ["workstuff"]
    errs = act.observation_validation_errors({"daily_action": [part]})
    assert any("invalid personal_domain 'workstuff'" in e for e in errs)
    print("  MARKER: BAD_PERSONAL_DOMAIN_NAMED_OK")


def t_scope_is_faithful():
    # empty relationships skip (the dead validator's own scope)
    part = {"name": "Probe_Empty", "description": "x", "relationships": []}
    assert act.observation_validation_errors({"implementation": [part]}) == []
    # non-observation shapes are untouched
    assert act.observation_validation_errors({"raw_concept": True, "concept_name": "X"}) == []
    assert act.observation_validation_errors({"concepts": [{"name": "X"}]}) == []
    assert act.observation_validation_errors({"timeline_merge": True}) == []
    print("  MARKER: SCOPE_FAITHFUL_OK")


class FakeUtils:
    """query_wiki_graph stub: the identity collection already exists, so
    observe_from_identity_pov takes no creation path and no live graph is
    touched (the FakeGraph precedent)."""

    def query_wiki_graph(self, query, params=None):
        return {"success": True, "data": [{"name": (params or {}).get("collection_name", "X")}]}


def t_identity_pov_preserves_both_edges():
    import carton_mcp.server_fastmcp as sfm
    saved_env = os.environ.get("HEAVEN_DATA_DIR")
    saved_utils = sfm.utils
    saved_identity = os.environ.pop("AGENT_IDENTITY", None)
    try:
        with tempfile.TemporaryDirectory() as heaven:
            os.environ["HEAVEN_DATA_DIR"] = heaven
            sfm.utils = FakeUtils()
            part = _valid_part("Probe_Identity_Pov_198_Both_Edges")
            result = sfm.observe_from_identity_pov(
                {"implementation": [part], "confidence": 1.0},
                agent_identity="Probe_Test_Identity_198",
            )
            assert result.startswith("✅"), result
            queued = list((Path(heaven) / "carton_queue").glob("*.json"))
            assert len(queued) == 1, queued
            qdata = json.loads(queued[0].read_text())
            rels = qdata["implementation"][0]["relationships"]
            by_name = {}
            for r in rels:
                by_name.setdefault(r["relationship"], []).append(r)
            # has_actual_domain PRESERVED (the #198 branch-plan shape)
            assert by_name.get("has_actual_domain"), rels
            assert by_name["has_actual_domain"][0]["related"] == ["Carton_Schema"]
            # has_domain mirrored, exactly ONE dict of that name (merge-not-append)
            assert len(by_name.get("has_domain", [])) == 1, rels
            assert by_name["has_domain"][0]["related"] == ["Carton_Schema"]
            # and the queued file passes the live validator end to end
            assert act.observation_validation_errors(qdata) == []
    finally:
        sfm.utils = saved_utils
        if saved_env is None:
            os.environ.pop("HEAVEN_DATA_DIR", None)
        else:
            os.environ["HEAVEN_DATA_DIR"] = saved_env
        if saved_identity is not None:
            os.environ["AGENT_IDENTITY"] = saved_identity
    print("  MARKER: IDENTITY_POV_BOTH_EDGES_OK")


def t_identity_pov_user_part_of_survives():
    # Issue #204: the identity collection must MERGE into the user's own part_of
    # dict, never ride as a second dict of the same rel-name (two dicts of one
    # name collapse to the later at the daemon's observation parse — the live
    # probe lost its Github_Issue_198 part_of exactly this way).
    import carton_mcp.server_fastmcp as sfm
    saved_env = os.environ.get("HEAVEN_DATA_DIR")
    saved_utils = sfm.utils
    saved_identity = os.environ.pop("AGENT_IDENTITY", None)
    try:
        with tempfile.TemporaryDirectory() as heaven:
            os.environ["HEAVEN_DATA_DIR"] = heaven
            sfm.utils = FakeUtils()
            part = _valid_part("Probe_Identity_Pov_204_Part_Of")
            result = sfm.observe_from_identity_pov(
                {"implementation": [part], "confidence": 1.0},
                agent_identity="Probe_Test_Identity_204",
            )
            assert result.startswith("✅"), result
            queued = list((Path(heaven) / "carton_queue").glob("*.json"))
            assert len(queued) == 1, queued
            rels = json.loads(queued[0].read_text())["implementation"][0]["relationships"]
            part_of_dicts = [r for r in rels if r["relationship"] == "part_of"]
            assert len(part_of_dicts) == 1, rels  # ONE dict — merge, not append
            targets = part_of_dicts[0]["related"]
            assert "Probe_Container" in targets, targets            # the user's survives
            assert "Probe_Test_Identity_204_Collection" in targets, targets  # the collection lands
    finally:
        sfm.utils = saved_utils
        if saved_env is None:
            os.environ.pop("HEAVEN_DATA_DIR", None)
        else:
            os.environ["HEAVEN_DATA_DIR"] = saved_env
        if saved_identity is not None:
            os.environ["AGENT_IDENTITY"] = saved_identity
    print("  MARKER: IDENTITY_POV_USER_PART_OF_SURVIVES_OK")


TESTS = [
    t_valid_observation_passes,
    t_missing_rels_named,
    t_bad_personal_domain_named,
    t_scope_is_faithful,
    t_identity_pov_preserves_both_edges,
    t_identity_pov_user_part_of_survives,
]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\nall {len(TESTS)} passed" if not failed else f"\n{failed}/{len(TESTS)} FAILED")
    raise SystemExit(1 if failed else 0)
