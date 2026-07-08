#!/usr/bin/env python3
"""Unit tests for the SM-branching data model + pure decision logic (sm_gate.py, step 1 of the
SM-branching build, 2026-07-04): `_step_branches` (the backward-compat shim), `select_branch` (the
pure decision function), and `create_sm_chain`'s branches-aware edge-build loop.

Pure library-level tests — NO Neo4j, NO MCP, NO daemon. `select_branch` takes a list of branch dicts
+ a call-text string and returns a step id or None; it does no I/O, so this is the onion-architecture
INNER layer test (exactly like test_d2_coverage.py is for `_compute_d2_coverage`): it must pass
standing alone, before step 2 wires it into `auto_progress`/`gate_call`.

`create_sm_chain` itself takes an INJECTED `run` callable (query, params) -> rows, so its
backward-compat behavior (item (e) below) is also testable here with a fake `run` that just records
the calls made to it — no live neo4j connection needed for THAT check either. `reinforce_transition`
also takes an injected `run` and is checked the same way (it does one MATCH+SET write; we assert the
exact query shape + params it issues, since actually persisting a weight change requires a live graph
that is out of scope for a pure unit test — the E2E-through-real-neo4j proof is the dev-flow skill's
job, not this file's).
"""

from carton_mcp.sm_gate import (
    GateRefusal,
    _step_branches,
    auto_progress,
    create_sm_chain,
    reinforce_transition,
    select_branch,
)


class _FakeRun:
    """Records every (query, params) call made to it; never touches a real database."""

    def __init__(self):
        self.calls = []

    def __call__(self, query, params=None):
        self.calls.append((query, params or {}))
        return []


# --- select_branch ------------------------------------------------------------------------------

def test_select_branch_single_unconditional_branch():
    candidates = [{"to": "Step_B", "required_pattern": None, "weight": 1.0}]
    chosen = select_branch(candidates, "anything the agent says")
    assert chosen == "Step_B", f"expected 'Step_B', got {chosen}"
    print("✓ a single unconditional branch is always chosen")


def test_select_branch_multiple_unconditional_branches_weighted():
    candidates = [
        {"to": "Step_A", "required_pattern": None, "weight": 1.0},
        {"to": "Step_B", "required_pattern": None, "weight": 1.0},
        {"to": "Step_C", "required_pattern": None, "weight": 1.0},
    ]
    valid_ids = {"Step_A", "Step_B", "Step_C"}
    seen = set()
    for _ in range(50):
        chosen = select_branch(candidates, "some call text")
        assert chosen in valid_ids, f"select_branch returned an invalid id: {chosen!r}"
        seen.add(chosen)
    # not asserting a specific distribution (softmax sampling is stochastic without an injected rng) —
    # only that every draw is one of the declared candidates, every time.
    print(f"✓ multiple unconditional branches: every one of 50 draws was a valid candidate id ({seen})")


def test_select_branch_pattern_gated_only_one_matches():
    candidates = [
        {"to": "Step_Read", "required_pattern": "read_file", "weight": 1.0},
        {"to": "Step_Write", "required_pattern": "write_file", "weight": 1.0},
    ]
    chosen = select_branch(candidates, "I am about to write_file(x)")
    assert chosen == "Step_Write", f"expected 'Step_Write', got {chosen}"
    print("✓ pattern-gated branches: only the matching branch is eligible and is chosen")


def test_select_branch_pattern_gated_none_match_returns_none():
    candidates = [
        {"to": "Step_Read", "required_pattern": "read_file", "weight": 1.0},
        {"to": "Step_Write", "required_pattern": "write_file", "weight": 1.0},
    ]
    chosen = select_branch(candidates, "totally unrelated call text")
    assert chosen is None, f"expected None, got {chosen}"
    print("✓ pattern-gated branches: zero eligible -> None (never raises)")


def test_select_branch_empty_candidates_returns_none():
    chosen = select_branch([], "anything")
    assert chosen is None, f"expected None, got {chosen}"
    print("✓ empty candidates list -> None")


def test_select_branch_mixed_gated_and_ungated_eligibility():
    # An ungated branch (required_pattern=None) is ALWAYS eligible alongside a gated one that also matches.
    candidates = [
        {"to": "Step_Always", "required_pattern": None, "weight": 1.0},
        {"to": "Step_Gated", "required_pattern": "special_call", "weight": 1.0},
    ]
    chosen = select_branch(candidates, "special_call(1)")
    assert chosen in {"Step_Always", "Step_Gated"}, f"got {chosen}"
    # when the gate does NOT match, only the ungated branch is eligible -> deterministic
    chosen2 = select_branch(candidates, "nothing special here")
    assert chosen2 == "Step_Always", f"expected 'Step_Always', got {chosen2}"
    print("✓ an ungated branch stays eligible regardless of call text; a non-matching gate excludes its branch")


def test_select_branch_missing_weight_key_defaults_to_one():
    # A branch dict with no "weight" key at all must not raise (defaults to 1.0, per Edge.weight's default).
    candidates = [
        {"to": "Step_A", "required_pattern": None},
        {"to": "Step_B", "required_pattern": None},
    ]
    chosen = select_branch(candidates, "anything")
    assert chosen in {"Step_A", "Step_B"}, f"got {chosen}"
    print("✓ a branch dict with no 'weight' key defaults to 1.0 without raising")


# --- _step_branches (the backward-compat shim) ---------------------------------------------------

def test_step_branches_new_form_returned_as_is():
    step = {"id": "S1", "branches": [{"to": "S2", "required_pattern": "foo", "weight": 3.0}]}
    branches = _step_branches(step)
    assert branches == [{"to": "S2", "required_pattern": "foo", "weight": 3.0}], f"got {branches}"
    print("✓ a step already carrying 'branches' is returned unchanged")


def test_step_branches_new_form_empty_list():
    step = {"id": "S1", "branches": []}
    assert _step_branches(step) == [], "an explicit empty branches list must stay empty"
    print("✓ an explicit empty 'branches' list stays empty")


def test_step_branches_old_form_next_set():
    step = {"id": "S1", "required_pattern": None, "text": "t", "next": "S2"}
    branches = _step_branches(step)
    assert branches == [{"to": "S2", "required_pattern": None, "weight": 1.0}], f"got {branches}"
    print("✓ old-form step with 'next' set -> single-branch shorthand")


def test_step_branches_old_form_next_none():
    step = {"id": "S1", "required_pattern": None, "text": "t", "next": None}
    assert _step_branches(step) == [], "old-form step with next=None must produce zero branches"
    print("✓ old-form step with next=None -> no branches")


def test_step_branches_old_form_next_absent():
    step = {"id": "S1", "required_pattern": None, "text": "t"}
    assert _step_branches(step) == [], "old-form step with no 'next' key at all must produce zero branches"
    print("✓ old-form step with no 'next' key at all -> no branches")


# --- create_sm_chain: the backward-compat shorthand produces the same single-edge shape -----------

def test_create_sm_chain_backward_compat_next_only_single_edge():
    fake = _FakeRun()
    state_machines = [{
        "name": "Sm1",
        "steps": [
            {"id": "Step_A", "required_pattern": None, "text": "a", "next": "Step_B"},
            {"id": "Step_B", "required_pattern": None, "text": "b", "next": None},
        ],
    }]
    out = create_sm_chain("Zztest_Branching_Concept", state_machines, fake,
                          domain="System", subdomain="Sm_Branching", personal_domain="cave")

    assert out["sms"] == ["Sm1"]
    assert out["steps"] == ["Step_A", "Step_B"]
    assert out["gated"] is False  # single SM => the OFF show-SM case, unchanged by this task

    # exactly one NEXT_STEP edge write, from Step_A to Step_B, with the neutral defaults.
    edge_calls = [(q, p) for q, p in fake.calls if "NEXT_STEP" in q and "r.weight" in q]
    assert len(edge_calls) == 1, f"expected exactly 1 NEXT_STEP edge write, got {len(edge_calls)}"
    _, params = edge_calls[0]
    assert params["a"] == "Step_A", f"got {params}"
    assert params["b"] == "Step_B", f"got {params}"
    assert params["required_pattern"] is None, f"got {params}"
    assert params["weight"] == 1.0, f"got {params}"
    print("✓ a step-spec using only the old 'next' key still produces exactly one NEXT_STEP edge, "
          "same topology as before this change")


def test_create_sm_chain_new_branches_multiple_edges():
    fake = _FakeRun()
    state_machines = [{
        "name": "Sm1",
        "steps": [
            {"id": "Step_A", "required_pattern": None, "text": "a",
             "branches": [
                 {"to": "Step_B", "required_pattern": "read_file", "weight": 2.0},
                 {"to": "Step_C", "required_pattern": "write_file", "weight": 1.0},
             ]},
            {"id": "Step_B", "required_pattern": None, "text": "b"},
            {"id": "Step_C", "required_pattern": None, "text": "c"},
        ],
    }]
    create_sm_chain("Zztest_Branching_Concept2", state_machines, fake,
                    domain="System", subdomain="Sm_Branching", personal_domain="cave")

    edge_calls = [(q, p) for q, p in fake.calls if "NEXT_STEP" in q and "r.weight" in q]
    assert len(edge_calls) == 2, f"expected exactly 2 NEXT_STEP edge writes, got {len(edge_calls)}"
    by_target = {p["b"]: p for _, p in edge_calls}
    assert by_target["Step_B"]["required_pattern"] == "read_file"
    assert by_target["Step_B"]["weight"] == 2.0
    assert by_target["Step_C"]["required_pattern"] == "write_file"
    assert by_target["Step_C"]["weight"] == 1.0
    print("✓ a step-spec using the new 'branches' key produces one NEXT_STEP edge per branch, "
          "each carrying its own required_pattern + weight")


# --- reinforce_transition -------------------------------------------------------------------------

def test_reinforce_transition_issues_the_expected_write():
    fake = _FakeRun()
    reinforce_transition("Step_A", "Step_B", 0.5, fake)
    assert len(fake.calls) == 1, f"expected exactly 1 write, got {len(fake.calls)}"
    query, params = fake.calls[0]
    assert "NEXT_STEP" in query, f"query does not mention NEXT_STEP: {query}"
    assert "SET r.weight" in query, f"query does not update r.weight: {query}"
    assert params == {"curr_id": "Step_A", "next_id": "Step_B", "delta": 0.5}, f"got {params}"
    print("✓ reinforce_transition issues exactly one MATCH+SET write with the expected params")


# --- auto_progress: step 2's wiring of select_branch/reinforce_transition into the live traversal ---
# These use a FakeRun (never a live database) and a hand-built `active_step` dict — the exact shape
# `get_active_step` returns (state_id, id, transitions=[{"id","weight","required_pattern"}, ...]), per
# the wired step-2 query. This is the onion-architecture INNER-layer proof that the rewrite in
# `auto_progress` actually calls `select_branch`/`reinforce_transition` correctly; the live E2E proof
# that this also holds against a REAL neo4j graph (weight-before/weight-after, actually observed) is
# `tests/test_sm_branching_live_e2e.py`.

def test_auto_progress_matches_pattern_gated_branch_not_highest_weight():
    fake = _FakeRun()
    active_step = {
        "state_id": "Zzfake_State1", "id": "Step_A",
        "transitions": [
            # Step_High has the highest weight but its pattern does NOT match the call -> excluded.
            {"id": "Step_High", "weight": 100.0, "required_pattern": "totally_different_call"},
            # Step_Match has a much lower weight but its pattern DOES match -> the only eligible one.
            {"id": "Step_Match", "weight": 1.0, "required_pattern": "read_file"},
        ],
    }
    msg = auto_progress(active_step, fake, call_text="please read_file(x) now")
    assert "Step_Match" in msg, f"expected advance to 'Step_Match', got: {msg}"
    assert "Step_High" not in msg, f"must NOT have advanced to the higher-weight non-matching branch: {msg}"
    # the CURRENT_STEP move actually targeted Step_Match
    move_calls = [(q, p) for q, p in fake.calls if "CREATE (s)-[:CURRENT_STEP]->(nxt)" in q]
    assert len(move_calls) == 1 and move_calls[0][1]["next_id"] == "Step_Match", f"got {move_calls}"
    # reinforce_transition was called on the edge ACTUALLY taken (Step_A -> Step_Match), default delta 0.1
    reinforce_calls = [(q, p) for q, p in fake.calls if "SET r.weight = coalesce" in q]
    assert len(reinforce_calls) == 1, f"expected exactly 1 reinforce write, got {len(reinforce_calls)}"
    assert reinforce_calls[0][1] == {"curr_id": "Step_A", "next_id": "Step_Match", "delta": 0.1}, \
        f"got {reinforce_calls[0][1]}"
    print("✓ auto_progress: a call matching only the low-weight pattern-gated branch advances there "
          "(not the higher-weight non-matching branch), and reinforces the edge actually taken")


def test_auto_progress_no_eligible_branch_refuses_naming_all_patterns():
    fake = _FakeRun()
    active_step = {
        "state_id": "Zzfake_State1", "id": "Step_A",
        "transitions": [
            {"id": "Step_Read", "weight": 1.0, "required_pattern": "read_file"},
            {"id": "Step_Write", "weight": 1.0, "required_pattern": "write_file"},
        ],
    }
    try:
        auto_progress(active_step, fake, call_text="totally unrelated call text")
        raise AssertionError("expected GateRefusal, none was raised")
    except GateRefusal as e:
        msg = str(e)
        assert "no eligible branch" in msg.lower(), f"refusal must name the situation: {msg}"
        assert "Step_Read" in msg and "read_file" in msg, f"refusal must name Step_Read's pattern: {msg}"
        assert "Step_Write" in msg and "write_file" in msg, f"refusal must name Step_Write's pattern: {msg}"
    # a refusal must NOT move the cursor and must NOT reinforce anything
    assert not any("CREATE (s)-[:CURRENT_STEP]->(nxt)" in q for q, _ in fake.calls), \
        "a refused call must not move CURRENT_STEP"
    assert not any("SET r.weight = coalesce" in q for q, _ in fake.calls), \
        "a refused call must not reinforce any edge"
    print("✓ auto_progress: zero eligible branches -> GateRefusal naming every branch's required_pattern "
          "(the eligible-vs-ineligible list), no cursor move, no reinforcement")


def test_auto_progress_explicit_target_step_id_bypasses_branching_unchanged():
    fake = _FakeRun()
    active_step = {
        "state_id": "Zzfake_State1", "id": "Step_A",
        "transitions": [
            # a branch whose pattern would NEVER match the given call_text, and whose presence must NOT
            # matter at all — the explicit target_step_id bypasses select_branch entirely.
            {"id": "Step_X", "weight": 1.0, "required_pattern": "never_matches_this_call_text"},
        ],
    }
    msg = auto_progress(active_step, fake, target_step_id="Step_Explicit", call_text="irrelevant text")
    assert "Step_Explicit" in msg, f"expected the explicit target to be used verbatim, got: {msg}"
    move_calls = [(q, p) for q, p in fake.calls if "CREATE (s)-[:CURRENT_STEP]->(nxt)" in q]
    assert len(move_calls) == 1 and move_calls[0][1]["next_id"] == "Step_Explicit", f"got {move_calls}"
    # an explicit override must NEVER reinforce (no branch decision was made)
    assert not any("SET r.weight = coalesce" in q for q, _ in fake.calls), \
        "an explicit target_step_id override must not reinforce anything"
    print("✓ auto_progress: an explicit target_step_id bypasses select_branch/reinforcement entirely, "
          "exactly as before this build")


def test_auto_progress_zero_transitions_is_still_the_terminal_unlock_case():
    fake = _FakeRun()
    active_step = {"state_id": "Zzfake_State1", "id": "Step_Terminal", "transitions": []}
    msg = auto_progress(active_step, fake, call_text="anything at all")
    assert "UNLOCKED" in msg, f"expected the terminal unlock message, got: {msg}"
    unlock_calls = [(q, p) for q, p in fake.calls if "SET s.status = 'unlocked'" in q]
    assert len(unlock_calls) == 1, f"expected exactly 1 unlock write, got {len(unlock_calls)}"
    assert not any("SET r.weight = coalesce" in q for q, _ in fake.calls), \
        "a terminal (zero-outgoing) step must not reinforce anything"
    print("✓ auto_progress: zero outgoing transitions is unchanged — still the terminal UNLOCK case")


if __name__ == "__main__":
    print("Testing SM branching (sm_gate.py: _step_branches / select_branch / create_sm_chain / "
          "reinforce_transition / auto_progress) — pure lib-level unit tests")
    print("=" * 70)
    test_select_branch_single_unconditional_branch()
    test_select_branch_multiple_unconditional_branches_weighted()
    test_select_branch_pattern_gated_only_one_matches()
    test_select_branch_pattern_gated_none_match_returns_none()
    test_select_branch_empty_candidates_returns_none()
    test_select_branch_mixed_gated_and_ungated_eligibility()
    test_select_branch_missing_weight_key_defaults_to_one()
    test_step_branches_new_form_returned_as_is()
    test_step_branches_new_form_empty_list()
    test_step_branches_old_form_next_set()
    test_step_branches_old_form_next_none()
    test_step_branches_old_form_next_absent()
    test_create_sm_chain_backward_compat_next_only_single_edge()
    test_create_sm_chain_new_branches_multiple_edges()
    test_reinforce_transition_issues_the_expected_write()
    test_auto_progress_matches_pattern_gated_branch_not_highest_weight()
    test_auto_progress_no_eligible_branch_refuses_naming_all_patterns()
    test_auto_progress_explicit_target_step_id_bypasses_branching_unchanged()
    test_auto_progress_zero_transitions_is_still_the_terminal_unlock_case()
    print("=" * 70)
    print("ALL SM BRANCHING UNIT TESTS PASSED")
