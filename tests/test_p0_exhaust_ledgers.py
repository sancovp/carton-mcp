"""test_p0_exhaust_ledgers.py — gates for the P0 exhaust patches (Griess-Neural-Surrogate,
2026-07-06): Rejection_Ledger, Episode_Ledger, and the carton side of Verdict_Chain_Granularity.

Covers:
  1. REJECTION LEDGER — a Type-2 contradiction verdict is REJECTED (unchanged behavior) AND
     appends an oracle-labeled hard negative {concept, relationships, verdict_kind, reason,
     timestamp} to HEAVEN_DATA_DIR/soma_rejections.jsonl; a mereo_error verdict is SAVED as
     soup (unchanged) AND appends its record too.
  2. EPISODE LEDGER — sm_gate trajectory events land in HEAVEN_DATA_DIR/sm_episodes.jsonl:
     branch_chosen (the bandit_choices record, with full candidates + pick + call_text),
     refusal_pattern, refusal_no_branch, terminal_unlock, lock (sm_chain_visit).
  3. FIRED-CHAINS (carton consumer) — a verdict carrying the new fired_chains= block parses
     into queue_data["fired_chains"], appends to soma_fired_chains.jsonl, and does NOT
     pollute the soup/mereo/status parsers.

All offline: soma_validate is monkeypatched with canned verdicts; sm_gate gets a fake `run`;
HEAVEN_DATA_DIR points at a tmpdir so no real queue/ledger/daemon is touched.

Run (from a cwd OUTSIDE this repo — pytest's rootdir insertion makes the repo's stray
`carton_mcp/` subdir shadow the installed package when run from inside it):
    cd /tmp && python3 -m pytest /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/tests/test_p0_exhaust_ledgers.py -v
"""
import json
import os
import glob

import pytest


@pytest.fixture()
def tmp_heaven(tmp_path, monkeypatch):
    """Point HEAVEN_DATA_DIR at a tmpdir (ledgers + queue land there, never the real one)."""
    monkeypatch.setenv("HEAVEN_DATA_DIR", str(tmp_path))
    return tmp_path


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


# ────────────────────────────────────────────────────────────────────────────
# 1 + 3. REJECTION LEDGER + FIRED-CHAINS (add_concept_tool side)
# ────────────────────────────────────────────────────────────────────────────

CONTRA_VERDICT = (
    "event=evt_1 source=test observations=1 deduction_chains_fired=0 unmet=0 "
    "triples=10 missing_slots=0 compiled=0\n"
    "\n"
    "deduction_chains_fired=0 unmet=0\n"
    "status=p0_contra_probe:contradiction\n"
    "contradictions=1\n"
    "  - p0_contra_probe is_a both endurant and perdurant "
    "(disjoint DOLCE branches — cannot be both)"
)

MEREO_VERDICT = (
    "event=evt_2 source=test observations=1 deduction_chains_fired=0 unmet=0 "
    "triples=10 missing_slots=1 compiled=0\n"
    "\n"
    "deduction_chains_fired=0 unmet=0\n"
    "status=p0_mereo_probe:mereo_error\n"
    "mereo_errors=1\n"
    "  - p0_mereo_probe is_a florbostatic_widget (not a known/defined type)\n"
    "soup_gaps=1\n"
    "  - p0_mereo_probe claims to be florbostatic_widget. florbostatic_widget requires definition"
)

FIRED_VERDICT = (
    "event=evt_3 source=test observations=1 deduction_chains_fired=2 unmet=0 "
    "triples=10 missing_slots=0 compiled=0\n"
    "all_core_requirements_met\n"
    "deduction_chains_fired=2 unmet=0\n"
    "fired_chains=2\n"
    "  - chain: dchain_alpha_check\n"
    "  - chain: dchain_beta_project\n"
    "status=p0_fired_probe:code"
)


@pytest.fixture()
def act(tmp_heaven, monkeypatch):
    """The add_concept_tool module wired for offline verdict-branch testing."""
    import carton_mcp.add_concept_tool as mod
    monkeypatch.setattr(mod, "SOMA_AVAILABLE", True)
    monkeypatch.setattr(mod, "CARTON_CB_STORE", False)  # no CB fan-out in tests
    return mod


def test_contradiction_rejected_and_ledgered(act, tmp_heaven, monkeypatch):
    monkeypatch.setattr(act, "soma_validate",
                        lambda source, observations, domain="default": {"result": CONTRA_VERDICT})
    rels = [{"relationship": "is_a", "related": ["Endurant_Thing", "Perdurant_Thing"]}]
    out = act.add_concept_tool_func(concept_name="P0_Contra_Probe", description="probe",
                                    relationships=rels)
    # Behavior unchanged: rejected, never queued.
    assert out.startswith("❌"), out
    assert "REJECTED" in out
    assert glob.glob(str(tmp_heaven / "carton_queue" / "*_concept.json")) == []
    # NEW: the hard negative landed in the rejection ledger.
    records = _read_jsonl(str(tmp_heaven / "soma_rejections.jsonl"))
    assert len(records) == 1, records
    r = records[0]
    assert r["concept"] == "P0_Contra_Probe"
    assert r["verdict_kind"] == "contradiction"
    assert "disjoint DOLCE branches" in r["reason"]
    assert r["relationships"][0]["relationship"] == "is_a"
    assert r["timestamp"]


def test_mereo_saved_as_soup_and_ledgered(act, tmp_heaven, monkeypatch):
    monkeypatch.setattr(act, "soma_validate",
                        lambda source, observations, domain="default": {"result": MEREO_VERDICT})
    rels = [{"relationship": "is_a", "related": ["Florbostatic_Widget"]}]
    out = act.add_concept_tool_func(concept_name="P0_Mereo_Probe", description="probe",
                                    relationships=rels)
    # Behavior unchanged: SAVED (fill signal, never a rejection) — queue write happened.
    assert out.startswith("✅"), out
    assert "MEREO" in out
    queued = glob.glob(str(tmp_heaven / "carton_queue" / "*_concept.json"))
    assert len(queued) == 1, queued
    # NEW: the mereo hard negative landed too.
    records = _read_jsonl(str(tmp_heaven / "soma_rejections.jsonl"))
    assert len(records) == 1, records
    assert records[0]["verdict_kind"] == "mereo_error"
    assert "not a known/defined type" in records[0]["reason"]


def test_fired_chains_parsed_queued_and_ledgered(act, tmp_heaven, monkeypatch):
    monkeypatch.setattr(act, "soma_validate",
                        lambda source, observations, domain="default": {"result": FIRED_VERDICT})
    rels = [{"relationship": "is_a", "related": ["Known_Fine_Type"]}]
    out = act.add_concept_tool_func(concept_name="P0_Fired_Probe", description="probe",
                                    relationships=rels)
    assert out.startswith("✅"), out
    # The queue payload carries the chain NAMES (not just a count).
    queued = glob.glob(str(tmp_heaven / "carton_queue" / "*_concept.json"))
    assert len(queued) == 1, queued
    with open(queued[0]) as f:
        qd = json.load(f)
    assert qd["fired_chains"] == ["dchain_alpha_check", "dchain_beta_project"]
    # The fired-chains exhaust ledger got the event record.
    records = _read_jsonl(str(tmp_heaven / "soma_fired_chains.jsonl"))
    assert len(records) == 1, records
    assert records[0]["concept"] == "P0_Fired_Probe"
    assert records[0]["fired_chains"] == ["dchain_alpha_check", "dchain_beta_project"]
    # Parser isolation: the chain lines did NOT leak into the soup parse, the status
    # verdict still resolved (code), and no rejection was recorded.
    assert qd["is_soup"] is False
    assert not _read_jsonl(str(tmp_heaven / "soma_rejections.jsonl"))
    assert "chain:" not in (qd.get("soup_reason") or "")


def test_no_fired_block_means_empty_list(act, tmp_heaven, monkeypatch):
    monkeypatch.setattr(act, "soma_validate",
                        lambda source, observations, domain="default": {"result": MEREO_VERDICT})
    act.add_concept_tool_func(concept_name="P0_Mereo_Probe", description="probe",
                              relationships=[{"relationship": "is_a",
                                              "related": ["Florbostatic_Widget"]}])
    queued = glob.glob(str(tmp_heaven / "carton_queue" / "*_concept.json"))
    with open(queued[0]) as f:
        qd = json.load(f)
    assert qd["fired_chains"] == []
    assert not os.path.exists(str(tmp_heaven / "soma_fired_chains.jsonl"))


# ────────────────────────────────────────────────────────────────────────────
# 2. EPISODE LEDGER (sm_gate side)
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def smg(tmp_heaven, monkeypatch, tmp_path):
    from carton_mcp import sm_gate
    # Ensure the kill switch cannot be tripped by a real file on this box.
    monkeypatch.setattr(sm_gate, "_DISABLE_FLAG", str(tmp_path / "no_such_flag"))
    return sm_gate


def _fake_run(active_rows, transition_rows):
    """A run() serving get_active_step + auto_progress's queries from canned rows."""
    def run(query, params=None):
        if "status = 'locked'" in query and "CURRENT_STEP" in query and "RETURN curr.n" in query:
            return list(active_rows)
        if "NEXT_STEP" in query and "RETURN nxt.n" in query:
            return list(transition_rows)
        if "RETURN n.text" in query:
            return [{"text": "next instruction"}]
        return []
    return run


ACTIVE = [{"id": "Step_One", "text": "do the thing", "required_pattern": "^do",
           "pattern_description": "", "state_id": "state-1"}]


def test_branch_chosen_recorded(smg, tmp_heaven):
    run = _fake_run(ACTIVE, [{"id": "Step_Two", "weight": 1.0, "required_pattern": None}])
    res = smg.gate_call("Test_Actor", "do something", run)
    assert res["allowed"] is True
    records = _read_jsonl(str(tmp_heaven / "sm_episodes.jsonl"))
    assert len(records) == 1, records
    r = records[0]
    assert r["event"] == "branch_chosen"
    assert r["actor"] == "Test_Actor"
    assert r["curr_step"] == "Step_One"
    assert r["chosen"] == "Step_Two"
    assert r["candidates"] == [{"to": "Step_Two", "required_pattern": None, "weight": 1.0}]
    assert r["call_text"] == "do something"
    assert r["timestamp"]


def test_refusal_pattern_recorded(smg, tmp_heaven):
    run = _fake_run(ACTIVE, [{"id": "Step_Two", "weight": 1.0, "required_pattern": None}])
    with pytest.raises(smg.GateRefusal):
        smg.gate_call("Test_Actor", "illegal move", run)
    records = _read_jsonl(str(tmp_heaven / "sm_episodes.jsonl"))
    assert len(records) == 1, records
    assert records[0]["event"] == "refusal_pattern"
    assert records[0]["required_pattern"] == "^do"
    assert records[0]["call_text"] == "illegal move"


def test_refusal_no_branch_recorded(smg, tmp_heaven):
    run = _fake_run(ACTIVE, [{"id": "Step_Two", "weight": 1.0, "required_pattern": "^xyz"}])
    with pytest.raises(smg.GateRefusal):
        smg.gate_call("Test_Actor", "do something", run)  # legal at the step, no eligible branch
    records = _read_jsonl(str(tmp_heaven / "sm_episodes.jsonl"))
    assert len(records) == 1, records
    assert records[0]["event"] == "refusal_no_branch"
    assert records[0]["candidates"][0]["required_pattern"] == "^xyz"


def test_terminal_unlock_recorded(smg, tmp_heaven):
    run = _fake_run(ACTIVE, [])  # zero transitions = terminal
    res = smg.gate_call("Test_Actor", "do final", run)
    assert res["allowed"] is True
    assert "UNLOCKED" in res["event"]
    records = _read_jsonl(str(tmp_heaven / "sm_episodes.jsonl"))
    assert len(records) == 1, records
    assert records[0]["event"] == "terminal_unlock"
    assert records[0]["curr_step"] == "Step_One"


def test_sm_chain_visit_lock_recorded(smg, tmp_heaven):
    def run(query, params=None):
        if "HAS_SM_CHAIN" in query and "SM_CHAIN_RUNS" in query and "RETURN sm.n" in query:
            return [{"sm_id": "Sm_Show", "order": 0}, {"sm_id": "Sm_Gate", "order": 1}]
        if "HAS_STEP" in query and "RETURN s.n" in query:
            if (params or {}).get("sm") == "Sm_Gate":
                return [{"id": "Step_Gate_Entry", "text": "your next move must be X",
                         "required_pattern": "^X", "pattern_description": ""}]
            return [{"id": "Step_Show", "text": "show", "required_pattern": None,
                     "pattern_description": ""}]
        if "equipped_sm_id" in query:
            return []
        return []
    out = smg.sm_chain_visit("Test_Actor", "Gated_Concept", run)
    assert out["require_next"] == "your next move must be X"
    records = _read_jsonl(str(tmp_heaven / "sm_episodes.jsonl"))
    assert len(records) == 1, records
    r = records[0]
    assert r["event"] == "lock"
    assert r["concept"] == "Gated_Concept"
    assert r["sm_id"] == "Sm_Gate"
    assert r["entry_step"] == "Step_Gate_Entry"


def test_records_validate_against_canonical_models(act, smg, tmp_heaven, monkeypatch):
    """DRIFT PIN: every ledger record the writers emit must validate against the canonical
    Pydantic shapes in exhaust_records.py (what gnosys-vault vault()s into SOMA). A writer
    key change without a model change fails HERE."""
    from carton_mcp.exhaust_records import (SomaRejectionRecord, SmEpisodeRecord,
                                            FiredChainsRecord)
    # Rejection + fired-chains records via the real branches:
    monkeypatch.setattr(act, "soma_validate",
                        lambda source, observations, domain="default": {"result": CONTRA_VERDICT})
    act.add_concept_tool_func(concept_name="P0_Contra_Probe", description="probe",
                              relationships=[{"relationship": "is_a",
                                              "related": ["Endurant_Thing", "Perdurant_Thing"]}])
    monkeypatch.setattr(act, "soma_validate",
                        lambda source, observations, domain="default": {"result": FIRED_VERDICT})
    act.add_concept_tool_func(concept_name="P0_Fired_Probe", description="probe",
                              relationships=[{"relationship": "is_a", "related": ["Known_Fine_Type"]}])
    for rec in _read_jsonl(str(tmp_heaven / "soma_rejections.jsonl")):
        SomaRejectionRecord(**rec)
    for rec in _read_jsonl(str(tmp_heaven / "soma_fired_chains.jsonl")):
        FiredChainsRecord(**rec)
    # Episode records via the real gate paths (advance + refusal + lock):
    run = _fake_run(ACTIVE, [{"id": "Step_Two", "weight": 1.0, "required_pattern": None}])
    smg.gate_call("Test_Actor", "do something", run)
    with pytest.raises(smg.GateRefusal):
        smg.gate_call("Test_Actor", "illegal move", run)
    episodes = _read_jsonl(str(tmp_heaven / "sm_episodes.jsonl"))
    assert episodes, "no episode records written"
    for rec in episodes:
        SmEpisodeRecord(**rec)


def test_ledger_fault_never_breaks_the_gate(smg, tmp_heaven, monkeypatch):
    # Point the ledger at an unwritable path — the gate must still work (best-effort law).
    monkeypatch.setattr(smg, "episode_ledger_path",
                        lambda: "/proc/definitely/not/writable.jsonl")
    run = _fake_run(ACTIVE, [{"id": "Step_Two", "weight": 1.0, "required_pattern": None}])
    res = smg.gate_call("Test_Actor", "do something", run)
    assert res["allowed"] is True  # advance succeeded despite the ledger fault
