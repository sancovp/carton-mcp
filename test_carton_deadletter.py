"""Tests for carton_deadletter — the dead-letter reason + retry-backoff module.

Standalone gate in this repo's script convention (the test_carton_breaker.py /
test_observation_validation_deadletter.py precedent): flat import of the sibling
module, `python3 test_carton_deadletter.py`, one PASS line per test.

Every function is pure except `dead_letter`, which is exercised against a real
temporary directory rather than a mock, because the one thing it must do is MOVE A
FILE and a mock cannot prove that happened.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import carton_deadletter as dl


def _fixed_now():
    return datetime(2026, 1, 2, 3, 4, 5)


def t_backoff_is_exponential_and_capped():
    assert dl.backoff_delays(1) == [], "a single attempt never waits"
    assert dl.backoff_delays(0) == []
    assert dl.backoff_delays(None) == []
    # 4 attempts -> 3 waits, doubling from the base
    assert dl.backoff_delays(4, base=2.0, cap=100.0) == [2.0, 4.0, 8.0]
    # the cap binds
    assert dl.backoff_delays(5, base=10.0, cap=25.0) == [10.0, 20.0, 25.0, 25.0]
    print("  MARKER: BACKOFF_EXPONENTIAL_AND_CAPPED_OK")


def t_knobs_fall_back_loudly_rather_than_disabling_the_retry():
    # A garbage knob must NEVER silently mean "do not retry" — that would reinstate
    # the exact defect this module exists to remove.
    assert dl.retry_attempts(env={}) == dl.DEFAULT_RETRY_ATTEMPTS
    assert dl.retry_attempts(env={"CARTON_BATCH_RETRY_ATTEMPTS": "banana"}) == dl.DEFAULT_RETRY_ATTEMPTS
    assert dl.retry_attempts(env={"CARTON_BATCH_RETRY_ATTEMPTS": "0"}) == dl.DEFAULT_RETRY_ATTEMPTS
    assert dl.retry_attempts(env={"CARTON_BATCH_RETRY_ATTEMPTS": "-3"}) == dl.DEFAULT_RETRY_ATTEMPTS
    # a good knob is honoured
    assert dl.retry_attempts(env={"CARTON_BATCH_RETRY_ATTEMPTS": "7"}) == 7
    # and a garbage backoff knob still yields a real, growing schedule
    delays = dl.backoff_delays(3, env={"CARTON_BATCH_RETRY_BASE_S": "not-a-number"})
    assert len(delays) == 2 and delays[0] > 0 and delays[1] > delays[0], delays
    print("  MARKER: KNOBS_FALL_BACK_LOUDLY_OK")


def t_a_failing_write_is_retried_and_lands():
    # THE CORE CLAIM OF THE RETRY HALF, proven deterministically rather than by staging
    # an outage against a live store: a write that fails twice and then succeeds must
    # come back as a SUCCESS, and nothing may be condemned along the way.
    calls = {"n": 0}
    slept = []
    reconnects = []

    def attempt():
        calls["n"] += 1
        # the real predicate the daemon uses: concepts_created > 0
        return {"concepts_created": 0 if calls["n"] < 3 else 5,
                "errors": ["ServiceUnavailable"] if calls["n"] < 3 else []}

    def before_retry(attempt_no, delay, result):
        reconnects.append(attempt_no)
        return True

    result, attempts = dl.run_with_retry(
        attempt, lambda r: r["concepts_created"] > 0,
        dl.backoff_delays(4, base=1.0, cap=10.0),
        sleep_fn=slept.append, before_retry=before_retry)

    assert result["concepts_created"] == 5, "the successful result is returned"
    assert attempts == 3, f"it landed on the third attempt, not {attempts}"
    assert calls["n"] == 3, "it stopped attempting once it succeeded"
    assert slept == [1.0, 2.0], "it waited between attempts, with backoff"
    assert reconnects == [1, 2], "it reconnected before each retry"
    print("  MARKER: FAILING_WRITE_RETRIED_AND_LANDS_OK")


def t_retry_gives_up_and_returns_the_failure_it_actually_got():
    calls = {"n": 0}

    def attempt():
        calls["n"] += 1
        return {"concepts_created": 0, "errors": [f"boom {calls['n']}"]}

    result, attempts = dl.run_with_retry(
        attempt, lambda r: r["concepts_created"] > 0,
        dl.backoff_delays(3, base=1.0, cap=10.0), sleep_fn=lambda _s: None)

    assert attempts == 3, attempts
    assert result["errors"] == ["boom 3"], "the LAST real failure is what gets reported"
    # and that failure is what the recorded reason is built from
    assert "boom 3" in dl.batch_failure_reason(result["errors"], attempts)
    print("  MARKER: RETRY_GIVES_UP_WITH_REAL_FAILURE_OK")


def t_retry_aborts_when_the_connection_cannot_be_re_established():
    # before_retry returning False (the daemon's "no connection could be rebuilt" case)
    # must stop immediately rather than burning the remaining attempts against nothing.
    calls = {"n": 0}

    def attempt():
        calls["n"] += 1
        return {"concepts_created": 0, "errors": ["down"]}

    result, attempts = dl.run_with_retry(
        attempt, lambda r: r["concepts_created"] > 0,
        dl.backoff_delays(5, base=1.0, cap=10.0),
        sleep_fn=lambda _s: None, before_retry=lambda *a: False)

    assert calls["n"] == 1, "it did not keep attempting after the abort"
    assert attempts == 1, attempts
    print("  MARKER: RETRY_ABORTS_ON_DEAD_CONNECTION_OK")


def t_a_single_attempt_still_runs_once():
    # backoff_delays([]) means no retries — the write must still happen exactly once.
    calls = {"n": 0}

    def attempt():
        calls["n"] += 1
        return {"concepts_created": 1, "errors": []}

    result, attempts = dl.run_with_retry(attempt, lambda r: True, [])
    assert calls["n"] == 1 and attempts == 1
    print("  MARKER: SINGLE_ATTEMPT_STILL_RUNS_OK")


def t_classify_names_connectivity_transient():
    assert dl.classify_failure(["Failed to connect to Neo4j: ServiceUnavailable"]) == "transient"
    assert dl.classify_failure(["connection closed with incomplete handshake"]) == "transient"
    assert dl.classify_failure(["Network is unreachable (IPv6)"]) == "transient"
    # a genuine payload defect is not dressed up as transient
    assert dl.classify_failure(["Concept creation failed: invalid property type"]) == "unknown"
    assert dl.classify_failure([]) == "unknown"
    assert dl.classify_failure(None) == "unknown"
    print("  MARKER: CLASSIFY_NAMES_CONNECTIVITY_OK")


def t_a_reason_is_never_empty_even_with_no_error_text():
    # THE REGRESSION PIN FOR THE ORIGINAL DEFECT. The bare rename it replaces recorded
    # NOTHING, so a dead letter was untriageable forever. There is no input for which
    # this module produces an empty reason — not even a failure that captured no text.
    for errors in ([], None, [""]):
        reason = dl.batch_failure_reason(errors, 3)
        assert reason.strip(), f"empty reason for {errors!r}"
        assert "3 attempt(s)" in reason, reason
        assert "batch" in reason.lower(), reason
    print("  MARKER: REASON_NEVER_EMPTY_OK")


def t_batch_reason_names_the_batch_the_attempts_and_the_store_error():
    reason = dl.batch_failure_reason(
        ["Concept creation failed: ServiceUnavailable: connection refused"], 3)
    assert "transient" in reason
    assert "3 attempt(s)" in reason
    assert "ServiceUnavailable" in reason, "the store's own text must survive verbatim"
    # It must say the payload was condemned WITH a batch, not that it is itself broken —
    # that distinction is the whole point of recording a reason.
    assert "same batch" in reason, reason
    print("  MARKER: BATCH_REASON_NAMES_EVERYTHING_OK")


def t_annotate_uses_the_key_the_recovery_verbs_read():
    out = dl.annotate_payload({"concept_name": "X"}, "because", "2026-01-02T03:04:05", 3)
    # error_message is load-bearing: check_failed_observations / retry_failed_observations
    # already read exactly this key, so an annotated dead letter is triageable today.
    assert out[dl.REASON_KEY] == "because"
    assert out["error_message"] == "because"
    assert out[dl.WHEN_KEY] == "2026-01-02T03:04:05"
    assert out[dl.ATTEMPTS_KEY] == 3
    assert out["fixed"] is False
    assert out["concept_name"] == "X", "the original payload must survive intact"
    # an operator's own "fixed": true is NEVER clobbered by a re-run
    kept = dl.annotate_payload({"fixed": True}, "r", "w")
    assert kept["fixed"] is True
    print("  MARKER: ANNOTATE_USES_RECOVERY_KEY_OK")


def t_dead_letter_records_the_reason_and_moves_the_file():
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp)
        failed = qdir / "failed"
        qf = qdir / "20260101_000000_abc.json"
        qf.write_text(json.dumps({"concept_name": "Probe", "relationships": []}))

        assert dl.dead_letter(qf, failed, "the store was unreachable", attempts=3,
                              now_fn=_fixed_now) is True
        assert not qf.exists(), "the file must leave the queue"
        moved = failed / qf.name
        assert moved.exists(), "the file must arrive in failed/"

        data = json.loads(moved.read_text())
        assert data["error_message"] == "the store was unreachable"
        assert data["dead_lettered_at"] == "2026-01-02T03:04:05"
        assert data["dead_letter_write_attempts"] == 3
        assert data["concept_name"] == "Probe", "the payload itself is preserved"
    print("  MARKER: DEAD_LETTER_RECORDS_AND_MOVES_OK")


def t_unannotatable_payload_is_moved_rather_than_lost():
    # Losing the file would be worse than losing the reason, so a payload whose JSON
    # cannot be parsed is STILL moved (and the annotation failure is logged, not
    # swallowed). The old bare rename had this property by accident; keep it on purpose.
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp)
        failed = qdir / "failed"
        qf = qdir / "20260101_000001_broken.json"
        qf.write_text("{ this is not json at all")

        assert dl.dead_letter(qf, failed, "unparseable payload", now_fn=_fixed_now) is True
        assert not qf.exists()
        moved = failed / qf.name
        assert moved.exists()
        assert moved.read_text() == "{ this is not json at all", "bytes preserved verbatim"
    print("  MARKER: UNANNOTATABLE_STILL_MOVED_OK")


def t_dead_letter_never_raises_on_a_missing_file():
    # It is called from inside a drain loop; it must never be the thing that kills one.
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp)
        assert dl.dead_letter(qdir / "does_not_exist.json", qdir / "failed",
                              "gone", now_fn=_fixed_now) is False
    print("  MARKER: DEAD_LETTER_NEVER_RAISES_OK")


def t_summary_separates_explained_from_unexplained():
    records = [
        ("a.json", {"error_message": "batch write to the graph failed (transient): boom",
                    "source": "precompact"}),
        ("b.json", {"error_message": "batch write to the graph failed (transient): boom",
                    "source": "precompact"}),
        ("c.json", {"error_message": "observation validation failed (issue #198): missing rels",
                    "source": "agent"}),
        ("d.json", {"source": "precompact"}),          # the historical shape: no reason
        ("e.json", None),                               # unparseable
    ]
    s = dl.summarize_dead_letters(records)
    assert s["total"] == 5
    assert s["with_reason"] == 3
    assert s["without_reason"] == 2, "an unparseable file is also unexplained"
    assert s["unreadable"] == 1
    # identically-worded reasons collapse to ONE line with a count, not two rows
    top = dict(s["by_reason"])
    assert top["batch write to the graph failed (transient)"] == 2, s["by_reason"]
    assert top["observation validation failed (issue #198)"] == 1
    print("  MARKER: SUMMARY_SEPARATES_EXPLAINED_OK")


def t_report_says_out_loud_how_many_cannot_be_explained():
    # The number that matters to a reader is the UNEXPLAINED one — that is the part
    # nothing can act on — so it must be in the headline, not inferable by subtraction.
    s = dl.summarize_dead_letters([("a.json", {"error_message": "x: y"}),
                                   ("b.json", {}), ("c.json", {})])
    text = dl.format_dead_letter_report(s)
    assert "3 payload(s)" in text, text
    assert "1 explained" in text and "2 with NO recorded reason" in text, text
    assert dl.format_dead_letter_report(dl.summarize_dead_letters([])) == "dead-letter queue: EMPTY"
    print("  MARKER: REPORT_NAMES_THE_UNEXPLAINED_OK")


def t_dead_letter_report_reads_a_real_directory():
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "1.json").write_text(json.dumps({"error_message": "parse failed: bad shape"}))
        (d / "2.json").write_text(json.dumps({"source": "precompact"}))
        (d / "3.json").write_text("{ broken")
        text = dl.dead_letter_report(d)
        assert "3 payload(s)" in text, text
        assert "1 explained" in text, text
        assert "parse failed" in text, text
        assert "could not be parsed at all" in text, text
    # a directory that does not exist is reported, never raised
    assert dl.dead_letter_report(Path(tempfile.gettempdir()) / "no_such_dl_dir_xyz") \
        == "dead-letter queue: EMPTY"
    print("  MARKER: REPORT_READS_REAL_DIRECTORY_OK")


def _assert_module_imports_what_it_calls(module, label):
    """The import-consistency rule, applied to ONE module that wires this one.

    REGRESSION PIN, and it is pinning a mistake that actually shipped: run_with_retry was
    added here and called from the daemon, but never added to the daemon's import list.
    py_compile cannot see a NameError and no suite exercises worker_daemon(), so both were
    green while the live daemon raised on every drain and the queue stopped moving. This
    closes that hole statically, for every symbol, forever.

    It is ONE helper rather than a copy per consumer on purpose: the rule is a single rule,
    and a second hand-written copy would be free to drift from the first — which is the same
    class of defect it exists to catch, one level up.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "carton_mcp.carton_deadletter":
            imported |= {a.name for a in node.names}
    assert imported, f"{label} imports nothing from carton_deadletter — wiring is gone"

    # every name it imports must actually exist here
    for name in sorted(imported):
        assert hasattr(dl, name), \
            f"{label} imports {name!r}, which carton_deadletter does not define"

    # ...and every function DEFINED here that it calls must be imported
    defined_here = {
        n for n in dir(dl)
        if not n.startswith("_")
        and callable(getattr(dl, n))
        and getattr(getattr(dl, n), "__module__", None) == dl.__name__
    }
    called = {
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    missing = (called & defined_here) - imported
    assert not missing, \
        f"{label} calls {sorted(missing)} from carton_deadletter without importing them"


def t_the_daemon_imports_every_symbol_it_calls_from_this_module():
    import carton_mcp.observation_worker_daemon as daemon
    _assert_module_imports_what_it_calls(daemon, "the daemon")
    print("  MARKER: DAEMON_IMPORTS_WHAT_IT_CALLS_OK")


def t_the_mcp_server_imports_every_symbol_it_calls_from_this_module():
    # THE SECOND CONSUMER (issue #275). check_failed_observations is now a thin wrapper over
    # dead_letter_report, so the verb an agent actually CALLS depends on this module exactly
    # the way the daemon does — and is exposed to exactly the same NameError. There it
    # crashlooped a drain; here it would surface as a management tool that raises, which is
    # no better for being quieter.
    import carton_mcp.server_fastmcp as server
    _assert_module_imports_what_it_calls(server, "the MCP server")
    print("  MARKER: MCP_SERVER_IMPORTS_WHAT_IT_CALLS_OK")


def t_check_failed_observations_returns_the_reasons_not_a_bare_count():
    # THE POINT OF ISSUE #275, asserted on the VERB rather than on the reader. The reader was
    # already correct and already tested while the verb still answered
    # `❌ N failed observations in: <dir>` — a count under which a transient rejection and a
    # permanently-broken payload are indistinguishable, which is how the pile reached 2000
    # with nobody able to name a single entry. Testing the library alone would have passed
    # throughout that entire period, so it proves nothing about the surface.
    import carton_mcp.server_fastmcp as server

    with tempfile.TemporaryDirectory() as tmp:
        failed = Path(tmp) / "carton_queue" / "failed"
        failed.mkdir(parents=True)
        (failed / "1.json").write_text(json.dumps(
            {"error_message": "batch write to the graph failed (transient): ServiceUnavailable"}))
        (failed / "2.json").write_text(json.dumps({"source": "precompact"}))

        previous = os.environ.get("HEAVEN_DATA_DIR")
        os.environ["HEAVEN_DATA_DIR"] = tmp
        try:
            out = server.carton_management(check_failed_observations=True)
        finally:
            if previous is None:
                os.environ.pop("HEAVEN_DATA_DIR", None)
            else:
                os.environ["HEAVEN_DATA_DIR"] = previous

        assert "2 payload(s)" in out, out
        assert "1 explained" in out and "1 with NO recorded reason" in out, out
        assert "batch write to the graph failed (transient)" in out, \
            f"the verb must carry the REASON, not merely a count: {out}"
        assert str(failed) in out, "it must still name the directory a reader has to go to"
    print("  MARKER: VERB_RETURNS_REASONS_OK")


def t_check_failed_observations_is_calm_when_there_is_nothing_to_report():
    # An empty (or absent) pile must not read as a failure. dead_letter_report answers EMPTY
    # for both, so the verb needs no exists() branch of its own — this pins that, because
    # re-adding one would be the natural "fix" for a report that looked bare.
    import carton_mcp.server_fastmcp as server

    with tempfile.TemporaryDirectory() as tmp:
        previous = os.environ.get("HEAVEN_DATA_DIR")
        os.environ["HEAVEN_DATA_DIR"] = tmp          # no carton_queue/failed under it at all
        try:
            out = server.carton_management(check_failed_observations=True)
        finally:
            if previous is None:
                os.environ.pop("HEAVEN_DATA_DIR", None)
            else:
                os.environ["HEAVEN_DATA_DIR"] = previous

    assert "EMPTY" in out, out
    assert "Error" not in out, f"a missing directory is not an error: {out}"
    print("  MARKER: VERB_CALM_WHEN_EMPTY_OK")


def _pre_fix_rule(succeeded, attempts):
    """The rule Phase 3 HAD before issue 280, reproduced as its two branches.

    The pre-fix block asked exactly one question and gave exactly two answers:

        if neo4j_succeeded:   -> move every parsed file to processed/
        else:                 -> if parsed_files: dead-letter every one of them

    The attempt count appears nowhere in it, which is the whole defect: a batch that was
    never attempted takes the identical `else` that a batch which failed takes. This
    helper exists so the pair below differs in exactly ONE variable — the rule — while
    the files, the directories and the mover are literally the same code.
    """
    return dl.PROCESSED if succeeded else dl.DEAD_LETTER


def t_batch_disposition_has_three_states_not_two():
    # Succeeded is PROCESSED whatever the attempt count says.
    assert dl.batch_disposition(True, 0) == dl.PROCESSED
    assert dl.batch_disposition(True, 3) == dl.PROCESSED
    # NOT succeeded with ZERO attempts is the never-attempted state — REQUEUE, not a
    # condemnation. This is the state the pre-fix rule did not have at all.
    assert dl.batch_disposition(False, 0) == dl.REQUEUE
    # NOT succeeded having actually tried is still a dead letter, unchanged.
    assert dl.batch_disposition(False, 1) == dl.DEAD_LETTER
    assert dl.batch_disposition(False, 3) == dl.DEAD_LETTER
    # The three are distinct values, so a caller cannot collapse two of them by accident.
    assert len({dl.PROCESSED, dl.REQUEUE, dl.DEAD_LETTER}) == 3
    print("  MARKER: DISPOSITION_HAS_THREE_STATES_OK")


def t_controlled_pair_no_connection_requeues_where_the_old_rule_condemned():
    """THE CONTROLLED PAIR for issue 280, on real files through the real mover.

    Both arms get the same batch state — the one the daemon is in when
    `_ensure_neo4j_alive` returned None: the write did not succeed, and NOTHING was
    attempted, so there are no errors and the attempt count is 0. Only the RULE differs.

    The assertion is about where the files physically END UP, because that is what the
    defect was about: a payload that was never attempted being filed as permanently
    failed, beside genuinely malformed ones.
    """
    succeeded, attempts, errors = False, 0, []

    # --- arm A: the PRE-FIX rule ---------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp)
        failed = qdir / "failed"
        files = []
        for i in range(3):
            f = qdir / f"2026091600000{i}_payload.json"
            f.write_text(json.dumps({"concept_name": f"Probe_{i}"}))
            files.append(f)

        assert _pre_fix_rule(succeeded, attempts) == dl.DEAD_LETTER
        reason = dl.batch_failure_reason(errors, attempts)
        for f in files:
            dl.dead_letter(f, failed, reason, attempts=attempts, now_fn=_fixed_now)

        assert not any(f.exists() for f in files), "pre-fix: the queue was emptied"
        assert len(list(failed.glob("*.json"))) == 3, "pre-fix: all three were condemned"
        # ...and condemned under the exact reason observed on the live pile.
        condemned = json.loads(next(failed.glob("*.json")).read_text())
        assert condemned["error_message"].startswith(
            "batch write to the graph failed (unknown) after 0 attempt(s)"), \
            condemned["error_message"]
        assert condemned["dead_letter_write_attempts"] == 0, \
            "0 attempts, recorded on a payload filed as permanently failed"

    # --- arm B: the FIXED rule -----------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp)
        failed = qdir / "failed"
        files = []
        for i in range(3):
            f = qdir / f"2026091600000{i}_payload.json"
            f.write_text(json.dumps({"concept_name": f"Probe_{i}"}))
            files.append(f)

        assert dl.batch_disposition(succeeded, attempts) == dl.REQUEUE
        # REQUEUE means the drain does nothing at all to these files.
        assert all(f.exists() for f in files), "fixed: every file STAYS IN THE QUEUE"
        assert not failed.exists(), \
            "fixed: nothing was condemned, so failed/ is never even created"
        # and each payload is byte-identical — not annotated, not marked failed
        for i, f in enumerate(files):
            assert json.loads(f.read_text()) == {"concept_name": f"Probe_{i}"}, \
                "fixed: an unattempted payload is left exactly as it was"

    print("  MARKER: CONTROLLED_PAIR_NO_CONNECTION_REQUEUES_OK")


def t_a_genuine_failure_after_retries_still_dead_letters():
    # The fix must not buy requeue-on-no-connection by weakening the real failure path.
    # A store that was REACHED and refused the write is still condemned, still carries
    # the store's own text, and is still distinguishable from the never-attempted case.
    assert dl.batch_disposition(False, 3) == dl.DEAD_LETTER
    reason = dl.batch_failure_reason(
        ["Concept creation failed: ServiceUnavailable: connection refused"], 3)
    assert "3 attempt(s)" in reason and "ServiceUnavailable" in reason, reason
    assert "transient" in reason
    with tempfile.TemporaryDirectory() as tmp:
        qdir = Path(tmp)
        failed = qdir / "failed"
        qf = qdir / "20260916_000009_real_failure.json"
        qf.write_text(json.dumps({"concept_name": "Probe"}))
        assert dl.dead_letter(qf, failed, reason, attempts=3, now_fn=_fixed_now) is True
        assert not qf.exists() and (failed / qf.name).exists()
        data = json.loads((failed / qf.name).read_text())
        assert data["dead_letter_write_attempts"] == 3
        assert "ServiceUnavailable" in data["error_message"]
    print("  MARKER: GENUINE_FAILURE_STILL_DEAD_LETTERS_OK")


def t_the_daemon_phase_three_actually_branches_on_the_disposition():
    """STRUCTURAL PIN: the daemon must USE the three-state rule, not merely import it.

    The import-consistency test above proves the symbol is imported. That is not enough
    here — a revert of Phase 3 to `if neo4j_succeeded: ... else: ...` would leave the
    import untouched, pass every other test in this file, and restore the exact defect.
    Nothing can execute worker_daemon() (it starts chroma servers and never returns),
    which is why the call is asserted statically instead of exercised.
    """
    import ast
    import inspect
    import carton_mcp.observation_worker_daemon as daemon

    tree = ast.parse(inspect.getsource(daemon))
    worker = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "worker_daemon"), None)
    assert worker is not None, "worker_daemon is gone — this pin needs rewriting, not deleting"

    calls = {n.func.id for n in ast.walk(worker)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "batch_disposition" in calls, \
        "worker_daemon no longer calls batch_disposition — Phase 3 is back to two states"

    names = {n.id for n in ast.walk(worker) if isinstance(n, ast.Name)}
    assert "REQUEUE" in names, \
        "worker_daemon no longer references REQUEUE — the never-attempted branch is gone"
    print("  MARKER: DAEMON_BRANCHES_ON_DISPOSITION_OK")


TESTS = [
    t_backoff_is_exponential_and_capped,
    t_knobs_fall_back_loudly_rather_than_disabling_the_retry,
    t_a_failing_write_is_retried_and_lands,
    t_retry_gives_up_and_returns_the_failure_it_actually_got,
    t_retry_aborts_when_the_connection_cannot_be_re_established,
    t_a_single_attempt_still_runs_once,
    t_classify_names_connectivity_transient,
    t_a_reason_is_never_empty_even_with_no_error_text,
    t_batch_reason_names_the_batch_the_attempts_and_the_store_error,
    t_annotate_uses_the_key_the_recovery_verbs_read,
    t_dead_letter_records_the_reason_and_moves_the_file,
    t_unannotatable_payload_is_moved_rather_than_lost,
    t_dead_letter_never_raises_on_a_missing_file,
    t_summary_separates_explained_from_unexplained,
    t_report_says_out_loud_how_many_cannot_be_explained,
    t_dead_letter_report_reads_a_real_directory,
    t_the_daemon_imports_every_symbol_it_calls_from_this_module,
    t_the_mcp_server_imports_every_symbol_it_calls_from_this_module,
    t_check_failed_observations_returns_the_reasons_not_a_bare_count,
    t_check_failed_observations_is_calm_when_there_is_nothing_to_report,
    # issue 280 — the never-attempted state
    t_batch_disposition_has_three_states_not_two,
    t_controlled_pair_no_connection_requeues_where_the_old_rule_condemned,
    t_a_genuine_failure_after_retries_still_dead_letters,
    t_the_daemon_phase_three_actually_branches_on_the_disposition,
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
