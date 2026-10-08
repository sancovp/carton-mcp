"""Tests for carton_breaker.py — the add_concept neo4j circuit breaker (issue 62).

Standalone gate (test-before-wiring), in this repo's own test convention
(the test_carton_kv.py precedent): flat import of the sibling module, a
self-running script (`python3 test_carton_breaker.py`), one PASS line per test.

Everything runs with injectable probe_fn/env/now_fn against a tmp state file —
NO live neo4j, NO live carton. The one real-connection case points a
KnowledgeGraphBuilder at a dead local port (a REAL connection failure, no live
services touched).
"""

import json
import tempfile
from pathlib import Path

import carton_breaker as cb


def _env(tmp_path, **over):
    e = {
        "CARTON_BREAKER_STATE_PATH": str(Path(tmp_path) / "breaker_state.json"),
        "CARTON_BREAKER_THRESHOLD": "3",
        "CARTON_BREAKER_COOLDOWN_S": "120",
        "CARTON_BREAKER_MAX_COOLDOWN_S": "1800",
        "CARTON_BREAKER_PROBE_TTL_S": "15",
    }
    e.update({k: str(v) for k, v in over.items()})
    return e


def _read_state(tmp_path):
    with open(Path(tmp_path) / "breaker_state.json") as f:
        return json.load(f)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class Probe:
    """Injectable probe with a call counter and a settable outcome."""

    def __init__(self, ok=True, err="ConnectionError: Failed to connect to Neo4j: down"):
        self.ok = ok
        self.err = err
        self.calls = 0

    def __call__(self, shared_connection=None):
        self.calls += 1
        return (True, None) if self.ok else (False, self.err)


def _trip_open(tmp_path):
    """Drive a fresh breaker to OPEN with 3 failing probes; return (env, clock, probe)."""
    env, clock, probe = _env(tmp_path), Clock(), Probe(ok=False)
    for _ in range(3):
        cb.check_breaker(env=env, probe_fn=probe, now_fn=clock)
    return env, clock, probe


# ---------------------------------------------------------------- pure helpers

def t_state_path_override_and_default():
    assert str(cb.state_path({"CARTON_BREAKER_STATE_PATH": "/x/y.json"})) == "/x/y.json"
    p = cb.state_path({"HEAVEN_DATA_DIR": "/tmp/hd"})
    assert str(p) == "/tmp/hd/carton_breaker_state.json"


def t_effective_cooldown_doubles_and_caps():
    base, cap = 120.0, 1800.0
    assert cb.effective_cooldown_s({"reopens": 0}, base, cap) == 120.0
    assert cb.effective_cooldown_s({"reopens": 1}, base, cap) == 240.0
    assert cb.effective_cooldown_s({"reopens": 2}, base, cap) == 480.0
    assert cb.effective_cooldown_s({"reopens": 10}, base, cap) == 1800.0  # capped


def t_evaluate_phases():
    assert cb.evaluate({"opened_at": None}, 1000.0, 120.0, 1800.0) == ("closed", 0.0)
    phase, remaining = cb.evaluate({"opened_at": 1000.0, "reopens": 0}, 1060.0, 120.0, 1800.0)
    assert phase == "open" and abs(remaining - 60.0) < 1e-9
    assert cb.evaluate({"opened_at": 1000.0, "reopens": 0}, 1121.0, 120.0, 1800.0) == ("half_open", 0.0)


def t_stop_message_carries_the_ruling():
    # The actuator must carry Isaac's ruled content: the error, STOP calling,
    # REPORT to the user, heaven agents use block reports, and not-written.
    state = {"failures": 3, "last_error": "ConnectionError: Failed to connect to Neo4j: down"}
    msg = cb.stop_message(state, "open", 120.0)
    assert "STOP calling carton tools" in msg
    assert "REPORT THIS TO THE USER" in msg
    assert "BLOCK REPORT" in msg
    assert "NOT written" in msg
    assert "Failed to connect to Neo4j" in msg
    assert "OPEN" in msg and "120s" in msg
    closed_msg = cb.stop_message(state, "closed", 0.0)
    assert "STOP calling carton tools" in closed_msg
    assert "OPEN after" not in closed_msg


# ---------------------------------------------------------------- check_breaker

def t_healthy_probe_passes_and_ttl_caches():
    with tempfile.TemporaryDirectory() as tmp:
        env, clock, probe = _env(tmp), Clock(), Probe(ok=True)
        assert cb.check_breaker(env=env, probe_fn=probe, now_fn=clock) is None
        assert probe.calls == 1
        clock.t += 5   # within the TTL window: no second probe
        assert cb.check_breaker(env=env, probe_fn=probe, now_fn=clock) is None
        assert probe.calls == 1
        clock.t += 20  # past the TTL: probes again
        assert cb.check_breaker(env=env, probe_fn=probe, now_fn=clock) is None
        assert probe.calls == 2
        assert _read_state(tmp)["failures"] == 0


def t_failures_return_message_and_threshold_opens():
    with tempfile.TemporaryDirectory() as tmp:
        env, clock, probe = _env(tmp), Clock(), Probe(ok=False)
        m1 = cb.check_breaker(env=env, probe_fn=probe, now_fn=clock)
        m2 = cb.check_breaker(env=env, probe_fn=probe, now_fn=clock)
        assert "STOP calling carton tools" in m1 and "OPEN after" not in m1
        assert m2 and _read_state(tmp)["failures"] == 2
        assert _read_state(tmp)["opened_at"] is None
        m3 = cb.check_breaker(env=env, probe_fn=probe, now_fn=clock)  # threshold -> OPEN
        assert "OPEN after 3 consecutive" in m3
        assert _read_state(tmp)["opened_at"] == clock.t
        assert probe.calls == 3
        clock.t += 30  # OPEN inside cooldown: fail fast, ZERO probe calls
        m4 = cb.check_breaker(env=env, probe_fn=probe, now_fn=clock)
        assert "failing fast" in m4 and probe.calls == 3


def t_half_open_failure_reopens_with_backoff():
    with tempfile.TemporaryDirectory() as tmp:
        env, clock, probe = _trip_open(tmp)
        clock.t += 121  # cooldown (120s) elapsed -> half-open
        msg = cb.check_breaker(env=env, probe_fn=probe, now_fn=clock)
        assert probe.calls == 4  # exactly one half-open probe
        state = _read_state(tmp)
        assert state["reopens"] == 1 and state["opened_at"] == clock.t
        assert "OPEN" in msg
        clock.t += 121  # doubled cooldown (240s): still open, no probe
        cb.check_breaker(env=env, probe_fn=probe, now_fn=clock)
        assert probe.calls == 4


def t_half_open_success_closes_and_resets():
    with tempfile.TemporaryDirectory() as tmp:
        env, clock, probe = _trip_open(tmp)
        clock.t += 121
        probe.ok = True  # neo4j back
        assert cb.check_breaker(env=env, probe_fn=probe, now_fn=clock) is None
        state = _read_state(tmp)
        assert state["failures"] == 0 and state["opened_at"] is None
        assert state["reopens"] == 0 and state["last_success"] == clock.t


def t_corrupt_state_file_is_fresh_closed():
    with tempfile.TemporaryDirectory() as tmp:
        env, clock, probe = _env(tmp), Clock(), Probe(ok=True)
        (Path(tmp) / "breaker_state.json").write_text("{not json!!")
        assert cb.check_breaker(env=env, probe_fn=probe, now_fn=clock) is None
        assert _read_state(tmp)["failures"] == 0  # rewritten clean


def t_state_shared_across_processes_via_file():
    # A second 'process' (fresh call, same file) sees OPEN without probing.
    with tempfile.TemporaryDirectory() as tmp:
        env, clock, _failing = _trip_open(tmp)
        other_probe = Probe(ok=True)  # would succeed — but must not be consulted
        msg = cb.check_breaker(env=env, probe_fn=other_probe, now_fn=clock)
        assert "failing fast" in msg and other_probe.calls == 0


def t_real_connection_failure_dead_port():
    # REAL probe against a dead local port — genuine connection failure text,
    # no live services involved.
    from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
    dead = KnowledgeGraphBuilder(uri="bolt://127.0.0.1:1", user="x", password="y")
    with tempfile.TemporaryDirectory() as tmp:
        env, clock = _env(tmp, CARTON_BREAKER_PROBE_TTL_S="0"), Clock()
        msg = cb.check_breaker(shared_connection=dead, env=env, now_fn=clock)
        assert msg is not None and "STOP calling carton tools" in msg
        assert _read_state(tmp)["failures"] == 1
        assert _read_state(tmp)["last_error"]


def t_garbage_config_fails_loud():
    with tempfile.TemporaryDirectory() as tmp:
        env = _env(tmp, CARTON_BREAKER_THRESHOLD="lots")
        try:
            cb.check_breaker(env=env, probe_fn=Probe(ok=True), now_fn=Clock())
            raise AssertionError("expected RuntimeError on garbage threshold")
        except RuntimeError as e:
            assert "CARTON_BREAKER_THRESHOLD" in str(e)


TESTS = [
    t_state_path_override_and_default,
    t_effective_cooldown_doubles_and_caps,
    t_evaluate_phases,
    t_stop_message_carries_the_ruling,
    t_healthy_probe_passes_and_ttl_caches,
    t_failures_return_message_and_threshold_opens,
    t_half_open_failure_reopens_with_backoff,
    t_half_open_success_closes_and_resets,
    t_corrupt_state_file_is_fresh_closed,
    t_state_shared_across_processes_via_file,
    t_real_connection_failure_dead_port,
    t_garbage_config_fails_loud,
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
