"""Tests for carton_vault_payload — the lane a vault registration takes INTO CartON.

Run as a SCRIPT (the repo root IS the `carton_mcp` package, so pytest-from-the-dir breaks on
package inference — the convention test_carton_quota.py / test_carton_breaker.py use):

    python3 test_carton_vault_payload.py

No daemon, no neo4j, no queue: both carton seams are INJECTED (the carton_breaker precedent).
The ONE thing these exist to pin is the invariant the module was built around — a registration
reaches SOMA as ONE event, never one-per-observation — because a per-observation loop silently
loses every `required_restriction` the type was supposed to get (measured on an isolated
daemon, 2026-08-18; see the module header).
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

os.environ["HEAVEN_DATA_DIR"] = tempfile.mkdtemp(prefix="carton_vault_flags_")

import carton_vault_payload as V


# ── fixtures ────────────────────────────────────────────────────────────────────────
def _obs(name, rels=None):
    return {"source": "vault", "name": name, "description": f"desc {name}",
            "relationships": rels if rels is not None else [
                {"relationship": "is_a", "related": [{"value": "system_type", "type": "concept_ref"}]}]}


def _payload():
    """A vault()-shaped registration: the type node plus its two arg part-nodes."""
    return [
        _obs("thing", [
            {"relationship": "is_a", "related": [{"value": "system_type", "type": "concept_ref"}]},
            {"relationship": "has_required_part",
             "related": [{"value": "thing__arg__a", "type": "concept_ref"},
                         {"value": "thing__arg__b", "type": "concept_ref"}]}]),
        _obs("thing__arg__a", [
            {"relationship": "is_a", "related": [{"value": "code_arg", "type": "concept_ref"}]},
            {"relationship": "has_arg_property", "related": [{"value": "has_a", "type": "string_value"}]}]),
        _obs("thing__arg__b", [
            {"relationship": "is_a", "related": [{"value": "code_arg", "type": "concept_ref"}]},
            {"relationship": "has_arg_property", "related": [{"value": "has_b", "type": "string_value"}]}]),
    ]


class Spy:
    """Records how the two injected carton seams were called."""

    def __init__(self, verdict="all_core_requirements_met", raise_on=None):
        self.soma_calls, self.writes, self.order = [], [], []
        self.verdict, self.raise_on = verdict, raise_on

    def soma(self, source, observations, domain="default"):
        self.soma_calls.append(list(observations))
        self.order.append("soma")
        return {"result": self.verdict}

    def write(self, concept_name, **kw):
        if self.raise_on and concept_name == self.raise_on:
            raise RuntimeError("neo4j is down")
        self.writes.append((concept_name, kw))
        self.order.append("write")
        return "queued"

    def run(self, payload=None, **kw):
        return V.add_vault_payload(payload if payload is not None else _payload(),
                                   soma_fn=self.soma, write_fn=self.write, **kw)


def reset_flags():
    try:
        os.remove(V.flag_path())
    except FileNotFoundError:
        pass


# ── the invariant this module exists for ────────────────────────────────────────────
def test_the_whole_payload_reaches_soma_as_ONE_event():
    """⭐ THE ONE THAT MATTERS. Three observations, ONE SOMA event carrying all three.

    A per-observation loop would make three events, and `register_one_system_type` — which
    fires ONCE PER TYPE PER PROCESS — would derive the type's restrictions before its arg
    nodes existed, then latch. Measured: the type graded `code` with ZERO restrictions, and
    an instance missing every required field graded `code` instead of `soup`, silently."""
    reset_flags()
    s = Spy()
    s.run()
    assert len(s.soma_calls) == 1, f"SOMA was hit {len(s.soma_calls)} times, not once"
    assert [o["name"] for o in s.soma_calls[0]] == ["thing", "thing__arg__a", "thing__arg__b"], \
        "the single event did not carry every observation"
    assert [n for n, _ in s.writes] == ["thing", "thing__arg__a", "thing__arg__b"], \
        "not every concept reached the record"


def test_the_record_writes_DO_call_soma_so_it_comes_back_a_system_type():
    """⭐ STEP 2 OF ISAAC'S ORDER. `hide_youknow=False` so each CartON write calls SOMA and
    SOMA validates it — that is what makes the concept land in the record AS a system type,
    with its region, its is_system_type flag and its release-effects.

    An earlier version passed True here on the reasoning that SOMA had already seen the
    observations. That reasoning is wrong once step 1 has run — step 1 latches
    `system_type_registered`, so the per-concept calls cannot re-derive anything — and it
    cost exactly the thing the design is for: measured queue entries carrying
    is_soup/is_code/is_system_type all False and no release-effects."""
    reset_flags()
    s = Spy()
    s.run()
    assert all(kw.get("hide_youknow") is False for _, kw in s.writes), \
        "a record write skipped SOMA, so the concept never comes back graded"


def test_soma_runs_BEFORE_the_record_so_its_verdict_can_gate():
    reset_flags()
    s = Spy()
    s.run()
    assert s.order[0] == "soma", f"the record was written before validation: {s.order[:2]}"


def test_a_CONTRADICTION_refuses_the_write():
    """The one verdict CartON refuses to store — accepting it decoheres the graph even as
    soup. Everything else, mereo fill signals included, is SAVED."""
    reset_flags()
    s = Spy(verdict="contradictions=1\n  - thing reaches two disjoint branches")
    out = s.run()
    assert s.writes == [], "a contradiction was written to the record"
    assert "REFUSED" in out, out


def test_a_MEREO_fill_signal_is_still_written():
    """A fill signal names what is missing; it is not a rejection."""
    reset_flags()
    s = Spy(verdict="mereo_errors=1\n  - thing requires has_a. Provide it.")
    s.run()
    assert len(s.writes) == 3, "a fill signal was mistaken for a rejection"


# ── the flag (Isaac's pieces 2 and 3) ───────────────────────────────────────────────
# A flag is trustworthy only when BOTH stores hold the payload, so every skip-path test must
# say what the REFLECTION (SOMA's quadstore) holds. These fixture names are in neither real
# store, so without an injected reflection_fn the real one correctly reports them absent and
# the write proceeds — which is the 2026-09-18 fix working, not a test failure.
REFLECTED = staticmethod(lambda names: True)      # the quadstore has them
NOT_REFLECTED = staticmethod(lambda names: False)  # the quadstore does NOT


def test_a_second_call_SKIPS_the_write():
    reset_flags()
    Spy().run(reflection_fn=lambda names: True)
    s2 = Spy()
    out = s2.run(reflection_fn=lambda names: True)
    assert s2.writes == [] and s2.soma_calls == [], "the redundant re-write was not skipped"
    assert "skipped" in out and "already present" in out, out


def test_force_overrides_the_flag():
    reset_flags()
    Spy().run()
    s = Spy()
    s.run(force=True)
    assert len(s.writes) == 3, "force=True did not rewrite"


def _age_the_flag(payload, days_over=1, value=None):
    flags = V._load_flags()
    key = V.payload_key(payload)
    flags[key]["last_checked"] = value if value is not None else (
        datetime.now(timezone.utc) - timedelta(days=V.FLAG_TTL_DAYS + days_over)).isoformat()
    V._save_flags(flags)
    return key


def test_a_STALE_flag_is_VERIFIED_and_kept_when_carton_really_holds_them():
    """Past the TTL the function CHECKS rather than trusts — and a truthful flag survives,
    with its check-time refreshed so the next call is cheap again."""
    reset_flags()
    payload = _payload()
    Spy().run(payload)
    key = _age_the_flag(payload)
    old = V._load_flags()[key]["last_checked"]

    s = Spy()
    s.run(payload, present_fn=lambda names, shared_connection=None: True,
          reflection_fn=lambda names: True)
    assert s.writes == [], "a verified-truthful flag still triggered a rewrite"
    assert V._load_flags()[key]["last_checked"] != old, "the check-time was not refreshed"


def test_a_flag_TRUTHFUL_about_carton_but_LYING_about_the_reflection_REWRITES():
    """⭐ THE OTHER HALF OF AN HONEST FLAG (2026-09-18). CartON really holds them; SOMA's
    quadstore does not. That is not a hypothetical: the 2026-09-16 quadstore rebuild left
    CartON untouched, so the CartON-only check passed on every boot, every registration was
    skipped, and the reflection sat missing its declarations for two days while each boot
    reported success.

    A FRESH flag must fail this too, which is why the reflection gates both branches — a fresh
    flag is exactly as blind to a quadstore rebuild as a stale one, and trusting it for
    FLAG_TTL_DAYS is trusting the half of the claim nobody checked."""
    reset_flags()
    payload = _payload()
    Spy().run(payload, reflection_fn=lambda names: True)

    s = Spy()   # flag is FRESH; carton says present; the reflection does not have them
    s.run(payload, present_fn=lambda names, shared_connection=None: True,
          reflection_fn=lambda names: False)
    assert s.writes, "a flag lying about the REFLECTION was trusted — the quadstore stays stale"
    assert s.soma_calls, "the rewrite never reached SOMA, so the reflection cannot be repaired"


def test_no_flag_but_BOTH_stores_hold_it_SKIPS_and_flags():
    """⭐ ISSUE 798. Isaac: SOMA only has to feed itself one time and if those things exist
    then it doesnt do that again. Existence decides; a missing flag is written, not obeyed."""
    reset_flags()
    payload = _payload()
    s = Spy()
    out = s.run(payload, present_fn=lambda names, shared_connection=None: True,
                reflection_fn=lambda observations: True)
    assert s.writes == [] and s.soma_calls == [], "an existing registration was fed again"
    assert "already present" in out, out
    assert V.payload_key(payload) in V._load_flags(), "the verified existence was not flagged"


def _store_with(rows):
    import sqlite3
    path = os.path.join(tempfile.mkdtemp(prefix="soma_store_"), "q.sqlite3")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE soma_triples (subject TEXT, predicate TEXT, object TEXT, status TEXT)")
    con.executemany("INSERT INTO soma_triples VALUES (?,?,?,?)", rows)
    con.commit()
    con.close()
    return path


_STORED = [("thing", "is_a", "system_type", "system_type"),
           ("thing", "has_required_part", "thing_arg_a", "system_type"),
           ("thing", "has_required_part", "thing_arg_b", "system_type"),
           ("thing_arg_a", "is_a", "code_arg", "code"),
           ("thing_arg_a", "has_arg_property", "has_a", "code"),
           ("thing_arg_b", "is_a", "code_arg", "code"),
           ("thing_arg_b", "has_arg_property", "has_b", "code")]


def test_the_reflection_is_read_under_SOMAs_names():
    """⭐ ISSUE 798. SOMA stores thing__arg__a as thing_arg_a (prolog_interop normalizes every
    name), so a lookup under any other mapping reads a vaulted registration as missing."""
    assert V._reflection_state(_payload(), store_path=_store_with(_STORED)) == (V.CODE, [])


def test_present_but_not_code_is_NOT_CODE_and_named():
    """⭐ ISSUE 799, Isaac: vaulted things must be graded code or they are not vaulted right.
    A registration present only as soup is not skipped as done; it is named."""
    rows = [r[:3] + ("soup",) if r[0] == "thing_arg_a" else r for r in _STORED]
    assert V._reflection_state(_payload(), store_path=_store_with(rows)) == (V.NOT_CODE, ["thing_arg_a"])


def test_a_missing_typing_triple_means_ABSENT():
    """A changed signature must rewrite: the check reads every relationship, not only names."""
    rows = [r for r in _STORED if r[:2] != ("thing_arg_b", "has_arg_property")]
    assert V._reflection_state(_payload(), store_path=_store_with(rows)) == (V.ABSENT, [])


def _dchain(premise):
    return [_obs("dchain_x", [
        {"relationship": "is_a", "related": [{"value": "deduction_chain", "type": "concept_ref"}]},
        {"relationship": "has_type_target", "related": [{"value": "thing", "type": "concept_ref"}]},
        {"relationship": "has_deduction_premise", "related": [{"value": premise, "type": "string_value"}]},
        {"relationship": "has_deduction_conclusion",
         "related": [{"value": "assertz(release_effect(\\'m:f\\', C))", "type": "string_value"}]}])]


_DCHAIN_STORED = [("dchain_x", "is_a", "deduction_chain", "code"),
                  ("dchain_x", "has_type_target", "thing", "code"),
                  ("dchain_x", "has_deduction_premise", "checking(C), triple(C, has_a, _)", "code"),
                  ("dchain_x", "has_deduction_conclusion", "assertz(release_effect('m:f', C))", "code")]


def test_a_dchain_is_compared_on_its_premise_string_as_SOMA_stores_it():
    """A premise and conclusion are compared as the atom text SOMA stores: the escaped quote
    the source sends is the plain quote the store holds."""
    payload = _dchain("checking(C), triple(C, has_a, _)")
    assert V._reflection_state(payload, store_path=_store_with(_DCHAIN_STORED)) == (V.CODE, [])


def test_an_edited_dchain_premise_string_is_ABSENT_so_it_is_resent():
    """⭐ ISSUE 799. Measured on the prod store: two d-chains whose conclusion was edited in
    source were skipped by the 798 check as present, so the edit never reached SOMA."""
    payload = _dchain("checking(C), triple(C, has_b, _)")
    assert V._reflection_state(payload, store_path=_store_with(_DCHAIN_STORED)) == (V.ABSENT, [])


def test_present_but_not_code_is_resent_ONCE_then_named_never_refed():
    """⭐ ISSUE 799. Neither skipped silently nor re-fed forever: the first boot re-sends it so a
    fix can take effect, and while this exact content stays not code it is named, not sent."""
    reset_flags()
    payload = _payload()
    s = Spy()
    state = lambda observations: (V.NOT_CODE, ["thing_arg_a"])
    first = s.run(payload, reflection_fn=state)
    assert len(s.soma_calls) == 1 and V.NOT_CODE_TAG + "thing_arg_a" in first, first
    second = s.run(payload, reflection_fn=state)
    assert len(s.soma_calls) == 1, "identical not-code content was fed again"
    assert second.startswith("carton_vault: posted nothing") and "thing_arg_a" in second, second


def test_a_LYING_flag_is_caught_and_the_payload_is_REWRITTEN():
    """⭐ The half that makes the flag honest. The store was rebuilt / the box reprovisioned;
    the flag says written, CartON does not have them. The flag loses."""
    reset_flags()
    payload = _payload()
    Spy().run(payload)
    _age_the_flag(payload)

    s = Spy()
    s.run(payload, present_fn=lambda names, shared_connection=None: False)
    assert len(s.writes) == 3, "a lying flag was trusted"
    assert len(s.soma_calls) == 1, "the rewrite did not re-validate"


def test_an_unanswerable_check_time_is_treated_as_stale_not_fresh():
    """A corrupt flag must trigger re-verification, never silent trust."""
    reset_flags()
    payload = _payload()
    Spy().run(payload)
    _age_the_flag(payload, value="not-a-timestamp")

    s = Spy()
    s.run(payload, present_fn=lambda names, shared_connection=None: False)
    assert len(s.writes) == 3, "a corrupt check-time was treated as fresh"


def test_an_unanswerable_presence_query_rewrites_rather_than_assuming():
    """The carton_quota lesson, applied: a check that cannot run must never report
    'all present'. `_concepts_present` returns False on any failure."""
    assert V._concepts_present(["anything"], shared_connection=object()) is False, \
        "an unanswerable presence check reported success"


def test_a_FAILED_write_is_NOT_flagged_so_the_next_call_retries():
    """The failure direction that matters: never record a success we did not have."""
    reset_flags()
    payload = _payload()
    s = Spy(raise_on="thing__arg__b")
    out = s.run(payload)
    assert "FAILED" in out, out
    assert V.payload_key(payload) not in V._load_flags(), "a partial write was flagged as done"


def test_a_signature_CHANGE_gets_a_new_key_but_a_description_edit_does_not():
    """The flag keys on the concept NAME SET, so adding an arg re-does the write while a
    mere description edit does not."""
    base = _payload()
    same = _payload()
    same[0]["description"] = "a totally different description"
    assert V.payload_key(same) == V.payload_key(base), "a description edit changed the key"
    assert V.payload_key(base + [_obs("thing__arg__c")]) != V.payload_key(base), \
        "a new arg did not change the key"


def test_soma_unreachable_writes_NOTHING_and_never_raises():
    reset_flags()

    def boom(source, observations, domain="default"):
        raise OSError("connection refused")

    writes = []
    out = V.add_vault_payload(_payload(), soma_fn=boom,
                              write_fn=lambda concept_name, **kw: writes.append(concept_name))
    assert writes == [], "the record was written while SOMA was unreachable"
    assert "SOMA_UNREACHABLE" in out, out


def test_empty_payload_is_a_noop():
    assert "nothing to write" in V.add_vault_payload([])


def test_a_PRIMITIVE_target_becomes_a_PROPERTY_never_a_node():
    """The CartON daemon MERGEs a :Wiki node for every relationship target regardless of its
    declared type, so routing a string_value through the relationship channel MINTS A NODE
    NAMED AFTER THE VALUE. Concept refs stay edges; primitives ride the property channel."""
    rels, typed, props = V._to_carton_relationships(_payload()[1])
    assert rels == [{"relationship": "is_a", "related": ["code_arg"]}], str(rels)
    assert props == {"has_arg_property": "has_a"}, str(props)
    assert ("code_arg", "concept_ref") in typed, str(typed)
    assert not any(v == "has_a" for v, _ in typed), "a primitive leaked into the edge channel"


def test_a_DCHAIN_goal_string_never_becomes_a_node():
    """⭐ THE POLLUTION THIS PREVENTS, and it really happened. Wiring add_dchain through this
    lane with the old converter sent has_deduction_premise / has_deduction_conclusion — whose
    values are PROLOG GOAL STRINGS — as relationship targets, and the daemon minted 44 nodes
    named things like `Checking(C),_Triple(C,_Has_Personal_Domain,__)` in the real graph."""
    dchain = {"source": "dchain_registration", "name": "dchain_probe", "description": "d",
              "relationships": [
                  {"relationship": "is_a", "related": [{"value": "deduction_chain", "type": "concept_ref"}]},
                  {"relationship": "has_type_target", "related": [{"value": "skill", "type": "concept_ref"}]},
                  {"relationship": "has_deduction_premise",
                   "related": [{"value": "checking(C), triple(C, has_domain, _)", "type": "string_value"}]},
                  {"relationship": "has_deduction_conclusion",
                   "related": [{"value": "assertz(unmet_requirement(dchain_probe))", "type": "string_value"}]}]}
    rels, typed, props = V._to_carton_relationships(dchain)
    edge_targets = [t for r in rels for t in r["related"]]
    assert edge_targets == ["deduction_chain", "skill"], str(edge_targets)
    assert "checking(C), triple(C, has_domain, _)" in props.values(), str(props)
    assert "assertz(unmet_requirement(dchain_probe))" in props.values(), str(props)
    for goal in props.values():
        assert goal not in edge_targets, f"a goal string reached the edge channel: {goal}"


def test_the_properties_reach_the_write_call():
    reset_flags()
    s = Spy()
    s.run()
    by_name = {n: kw for n, kw in s.writes}
    assert by_name["thing__arg__a"].get("properties") == {"has_arg_property": "has_a"}, \
        str(by_name["thing__arg__a"].get("properties"))


def test_the_flag_store_is_a_file_shared_by_every_process():
    reset_flags()
    Spy().run()
    assert os.path.exists(V.flag_path()), V.flag_path()
    with open(V.flag_path()) as fh:
        assert isinstance(json.load(fh), dict)


def test_a_corrupt_flag_store_means_UNFLAGGED_rather_than_a_crash():
    with open(V.flag_path(), "w") as fh:
        fh.write("{not json at all")
    assert V._load_flags() == {}, "a corrupt flag store did not fail toward doing the work"
    s = Spy()
    s.run()
    assert len(s.writes) == 3, "a corrupt flag store blocked the write"


def test_a_RETURNED_REFUSAL_is_not_counted_as_a_write():
    """⭐ THE DEFECT THE FIRST REAL E2E RUN FOUND. `add_concept_tool_func` does NOT raise
    when the graph is unreachable — the circuit breaker RETURNS its stop-message actuator
    instead, by design. Counting the absence of a raise as a write flagged a payload that
    produced ZERO queue entries, which would have skipped it on every future boot and left
    the record permanently without the type."""
    reset_flags()
    payload = _payload()
    breaker_msg = ("CartON is unreachable: ServiceUnavailable.\n"
                   "This concept was NOT written (nothing was queued).\n"
                   "STOP calling carton tools now — do not retry in a loop.")

    calls = []

    def refusing_write(concept_name, **kw):
        calls.append(concept_name)
        return breaker_msg

    out = V.add_vault_payload(payload, soma_fn=Spy().soma, write_fn=refusing_write)
    assert len(calls) == 3, "the writes were not even attempted"
    assert "FAILED" in out, out
    assert V.payload_key(payload) not in V._load_flags(), \
        "a refused write was flagged as done — the next boot would skip it forever"


def test_the_refusal_detector_knows_a_real_success_from_a_refusal():
    assert V._is_refusal("This concept was NOT written (nothing was queued).")
    assert V._is_refusal("QuotaExceeded: node limit reached")
    assert V._is_refusal("❌ REJECTED: contradiction")
    assert not V._is_refusal("queued")
    assert not V._is_refusal("Concept 'Thing' queued for creation (soup)")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed.append(fn.__name__)
            print(f"  FAIL  {fn.__name__}  <- {e}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        print("FAILED:", ", ".join(failed))
        raise SystemExit(1)
