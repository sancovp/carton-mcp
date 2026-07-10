#!/usr/bin/env python3
"""Quota laws: no-op unset · loud on garbage · under passes · growth refused
at limit · refinement passes at limit · TTL cache bounds the count queries.

Plain-python runner (the house idiom): `python3 test_carton_quota.py`.
count_fn/exists_fn are injected — pure tests, no neo4j needed; the live
wiring is one guarded call in add_concept_tool_func (E2E in the box image).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carton_quota as q

FAILURES = []


def check(name, fn):
    q.invalidate_cache()
    try:
        fn()
        print(f"  PASS  {name}")
    except Exception as e:  # noqa: BLE001
        FAILURES.append((name, e))
        print(f"  FAIL  {name}: {e}")


class CountSpy:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self, shared_connection=None):
        self.calls += 1
        return self.value


def boom(*a, **k):
    raise AssertionError("must not be called")


# -- law 1: unset means untouched -------------------------------------------

def t_noop_when_unset():
    q.check_quota("X", env={}, count_fn=boom, exists_fn=boom)
    q.check_quota("X", env={"CARTON_MAX_NODES": ""}, count_fn=boom, exists_fn=boom)
    q.check_quota("X", env={"CARTON_MAX_NODES": "  "}, count_fn=boom, exists_fn=boom)


def t_garbage_limit_is_loud():
    for bad in ("fifty", "50k"):
        try:
            q.check_quota("X", env={"CARTON_MAX_NODES": bad}, count_fn=boom)
        except RuntimeError as e:
            assert "must be an integer" in str(e)
        else:
            raise AssertionError(f"{bad!r} did not raise")
    try:
        q.check_quota("X", env={"CARTON_MAX_NODES": "-1"}, count_fn=boom)
    except RuntimeError as e:
        assert ">= 0" in str(e)
    else:
        raise AssertionError("-1 did not raise")


# -- laws 2/3: under passes · growth refused · refinement passes -------------

def t_under_limit_passes():
    q.check_quota(
        "X", env={"CARTON_MAX_NODES": "50000"},
        count_fn=CountSpy(49999), exists_fn=boom,
    )


def t_new_concept_refused_at_limit():
    try:
        q.check_quota(
            "Brand_New", env={"CARTON_MAX_NODES": "50000"},
            count_fn=CountSpy(50000), exists_fn=lambda name, sc=None: False,
        )
    except q.QuotaExceeded as e:
        msg = str(e)
        assert "50000" in msg and "CARTON_MAX_NODES" in msg
        assert "EXISTING concepts still works" in msg  # the actionable half
    else:
        raise AssertionError("expected QuotaExceeded")


def t_existing_concept_passes_at_limit():
    q.check_quota(
        "Already_There", env={"CARTON_MAX_NODES": "50000"},
        count_fn=CountSpy(50001), exists_fn=lambda name, sc=None: True,
    )


# -- law 5: the TTL cache bounds count queries -------------------------------

def t_ttl_cache_bounds_queries():
    spy = CountSpy(10)
    env = {"CARTON_MAX_NODES": "50"}
    q.check_quota("A", env=env, count_fn=spy, ttl_s=3600)
    q.check_quota("B", env=env, count_fn=spy, ttl_s=3600)
    q.check_quota("C", env=env, count_fn=spy, ttl_s=3600)
    assert spy.calls == 1, f"expected 1 count query in-window, got {spy.calls}"
    q.invalidate_cache()
    q.check_quota("D", env=env, count_fn=spy, ttl_s=3600)
    assert spy.calls == 2, "invalidate must force a recount"


def t_ttl_zero_always_recounts():
    spy = CountSpy(10)
    env = {"CARTON_MAX_NODES": "50"}
    q.check_quota("A", env=env, count_fn=spy, ttl_s=0)
    q.check_quota("B", env=env, count_fn=spy, ttl_s=0)
    assert spy.calls == 2


if __name__ == "__main__":
    tests = [
        t_noop_when_unset,
        t_garbage_limit_is_loud,
        t_under_limit_passes,
        t_new_concept_refused_at_limit,
        t_existing_concept_passes_at_limit,
        t_ttl_cache_bounds_queries,
        t_ttl_zero_always_recounts,
    ]
    print(f"carton_quota tests ({len(tests)}):")
    for t in tests:
        check(t.__name__, t)
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED")
        sys.exit(1)
    print(f"\nall {len(tests)} passed")
