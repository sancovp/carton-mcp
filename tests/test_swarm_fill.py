"""test_swarm_fill — the emergent-placement contract (2026-07-07).

Run from a cwd OUTSIDE the repo (the stray carton_mcp/ subdir shadows the installed
package under pytest's rootdir insertion):
    cd /tmp && python -m pytest /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/tests/test_swarm_fill.py -q

The contract (Isaac's ruling): NO filter, NO dedup — add_concept EVERY candidate.
Redundant siblings co-locate (both placed); a bad placement never aborts the fill.
"""
import json
from unittest import mock

from carton_mcp import swarm_fill


# ── fill_slot_via_brain: parse candidates over a stubbed HTTP ─────────

class _FakeResp:
    def __init__(self, body): self._b = body.encode()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_fill_parses_candidates_and_drops_labelless():
    body = json.dumps({"slot": "MilkType", "candidates": [
        {"label": "oat_milk", "rationale": "plant", "confidence": 8},
        {"label": "", "rationale": "blank", "confidence": 9},   # dropped
        {"label": "  soy_milk  ", "rationale": "legume", "confidence": 6},
    ]})
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp(body)):
        out = swarm_fill.fill_slot_via_brain("MilkType", siblings=["whole_milk"], n=3)
    assert [c["label"] for c in out] == ["oat_milk", "soy_milk"]  # blank dropped, trimmed


def test_fill_raises_on_missing_candidates_array():
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp(json.dumps({"slot": "x"}))):
        try:
            swarm_fill.fill_slot_via_brain("x")
            assert False, "expected RuntimeError on missing candidates"
        except RuntimeError:
            pass


# ── swarm_fill_and_place: EVERY candidate placed, no dedup ────────────

def _candidates(*labels):
    return [{"label": l, "rationale": "r", "confidence": 7} for l in labels]


def test_places_every_candidate_including_duplicates():
    calls = []
    def fake_add(name, description="", relationships=None, source="agent", shared_connection=None):
        calls.append({"name": name, "rels": relationships, "source": source})
        return f"✅ {name}"
    # duplicate label appears TWICE — both must be placed (emergent co-location, no dedup)
    with mock.patch.object(swarm_fill, "fill_slot_via_brain",
                           return_value=_candidates("almond_milk", "oat_milk", "almond_milk")):
        out = swarm_fill.swarm_fill_and_place(
            "MilkType", kernel_name="EspressoKernel", n=3, _add_concept=fake_add)
    # NO dedup: 3 candidates -> 3 add_concept calls (the two almond_milks BOTH placed)
    assert len(calls) == 3
    assert [c["name"] for c in calls] == ["almond_milk", "oat_milk", "almond_milk"]
    assert out["n_candidates"] == 3 and len(out["placements"]) == 3


def test_core_sentence_is_the_address():
    calls = []
    def fake_add(name, description="", relationships=None, source="agent", shared_connection=None):
        calls.append(relationships); return "✅"
    with mock.patch.object(swarm_fill, "fill_slot_via_brain", return_value=_candidates("oat_milk")):
        swarm_fill.swarm_fill_and_place("MilkType", kernel_name="EspressoKernel", _add_concept=fake_add)
    rels = calls[0]
    is_a = next(r for r in rels if r["relationship"] == "is_a")
    part_of = next(r for r in rels if r["relationship"] == "part_of")
    assert is_a["related"] == ["MilkType"]           # IS_A the slot (the dimension)
    assert part_of["related"] == ["EspressoKernel"]  # PART_OF the kernel (the space)


def test_bad_placement_does_not_abort_the_fill():
    def fake_add(name, description="", relationships=None, source="agent", shared_connection=None):
        if name == "boom":
            raise RuntimeError("neo4j exploded")
        return f"✅ {name}"
    with mock.patch.object(swarm_fill, "fill_slot_via_brain",
                           return_value=_candidates("ok1", "boom", "ok2")):
        out = swarm_fill.swarm_fill_and_place("Slot", _add_concept=fake_add)
    # all three recorded; the failing one carries an ERROR result, the rest succeed
    assert len(out["placements"]) == 3
    results = {p["label"]: str(p["result"]) for p in out["placements"]}
    assert "ERROR" in results["boom"] and results["ok1"].startswith("✅") and results["ok2"].startswith("✅")


def test_source_is_tagged():
    calls = []
    def fake_add(name, description="", relationships=None, source="agent", shared_connection=None):
        calls.append(source); return "✅"
    with mock.patch.object(swarm_fill, "fill_slot_via_brain", return_value=_candidates("x")):
        swarm_fill.swarm_fill_and_place("Slot", source="swarm_fill", _add_concept=fake_add)
    assert calls == ["swarm_fill"]
