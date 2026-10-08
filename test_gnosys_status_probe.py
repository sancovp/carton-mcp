#!/usr/bin/env python3
"""test_gnosys_status_probe — the probe is the mechanism by which a status claim becomes
trustworthy, and until 2026-09-04 nothing verified the mechanism. Both its doc(m) and its
vision(m) said so; the vision's closing line is "KNOWN GAP, stated: zero test coverage, and the
check functions have no injection point today, so testing them means adding one." This file
realizes that gap.

Run as a SCRIPT from knowledge/carton-mcp (the repo root IS the carton_mcp package), the same
convention as test_carton_quota.py / test_carton_breaker.py:

    python3 test_gnosys_status_probe.py

WHAT IS COVERED, and why these cases and not others. The checks take no injection point, so the
only seam is monkeypatching the module's transport helpers (_port_open / _http), exactly as the
doc(m) records. That is enough to pin the invariant that actually matters:

  A TIMEOUT IS NOT A DIAGNOSIS.

Measured 2026-09-04: SOMA answered an empty /event in 24.97s while the probe's _http default
timeout was 4s, so check_soma reported a perfectly healthy validator as "down". The frozen
property lane had already said chroma was live while it was dead — which is why meta-SOPHIA
failed 18 consecutive times — and the fresh probe then said SOMA was dead while it was live. The
false "down" nearly triggered a relaunch of a running daemon, which soma_daemon_dead_policy
reserves for a validator that is genuinely dead. Both directions of that error are one defect: a
status the system cannot distinguish from a measurement.
"""
import sys

import gnosys_status_probe as P

_fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


# ── check_soma: the three outcomes must be three, not two ───────────────────────────────────────

def t_soma_port_closed_is_down():
    P._port_open = lambda h, p, timeout=3: (False, "ConnectionRefusedError: refused")
    P._http = lambda *a, **k: (None, "should not be called")
    v, d = P.check_soma()
    check("port closed -> down", v == "down", f"got {v!r}")
    check("down names the port", ":8091" in d, d)


def t_soma_answering_is_live():
    P._port_open = lambda h, p, timeout=3: (True, "ok")
    P._http = lambda *a, **k: (200, "ok")
    v, d = P.check_soma()
    check("port open + answers -> live", v == "live", f"got {v!r}")


def t_soma_slow_is_degraded_not_down():
    """THE REGRESSION THIS FILE EXISTS FOR. A listening SOMA that does not answer inside the
    budget is UP-but-not-serving. Reporting it as down is what makes a healthy daemon look dead,
    and down is the value the dead-daemon policy actuates on."""
    P._port_open = lambda h, p, timeout=3: (True, "ok")
    P._http = lambda *a, **k: (None, "TimeoutError: timed out")
    v, d = P.check_soma()
    check("port open + no answer -> degraded, NOT down", v == "degraded", f"got {v!r}")
    check("degraded says UP but not serving", "NOT dead" in d, d)


def t_soma_uses_the_generous_timeout():
    """The whole bug was a 4s budget on a route that takes ~25s. Pin that check_soma passes its
    own constant rather than inheriting _http's fast default."""
    seen = {}
    P._port_open = lambda h, p, timeout=3: (True, "ok")

    def fake_http(url, method="GET", body=None, timeout=4):
        seen["timeout"] = timeout
        return 200, "ok"

    P._http = fake_http
    P.check_soma()
    check("check_soma passes SOMA_EVENT_TIMEOUT_S", seen.get("timeout") == P.SOMA_EVENT_TIMEOUT_S,
          f"passed {seen.get('timeout')!r}, constant is {P.SOMA_EVENT_TIMEOUT_S!r}")
    check("the budget is generous enough for a ~25s answer", P.SOMA_EVENT_TIMEOUT_S >= 30,
          f"{P.SOMA_EVENT_TIMEOUT_S}s")


# ── the refusal-to-guess invariant the vision names as the design decision that matters most ────

def t_unprobed_keys_never_become_measured_values():
    """The module's central design property: three checks it cannot genuinely perform live in
    UNPROBED as REASONS, not statuses, and probe() must never give them a value."""
    overlap = set(P.UNPROBED) & set(P.CHECKS)
    check("UNPROBED and CHECKS are disjoint", not overlap, f"overlap: {sorted(overlap)}")
    check("every UNPROBED value is a reason string, not a status",
          all(isinstance(v, str) and len(v) > 20 for v in P.UNPROBED.values()),
          repr(P.UNPROBED))


def main():
    orig = (P._port_open, P._http)
    try:
        for t in (t_soma_port_closed_is_down, t_soma_answering_is_live,
                  t_soma_slow_is_degraded_not_down, t_soma_uses_the_generous_timeout,
                  t_unprobed_keys_never_become_measured_values):
            print(f"MARKER: {t.__name__}")
            t()
    finally:
        P._port_open, P._http = orig
    print(f"\n{len(_fails)} FAILED" if _fails else "\nALL PASS")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
