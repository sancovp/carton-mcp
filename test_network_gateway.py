#!/usr/bin/env python3
"""Network gateway v2 laws: stdio default · sse refused · fail-closed key ·
the pure-ASGI bearer gate (401 without/wrong, pass-through with).

Plain-python runner (the house idiom): `python3 test_network_gateway.py`.
The module is stdlib-at-import; the ASGI gate is tested directly (no server
needed) — the live end-to-end runs in the box smoke
(application/carton-saas/box/).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import network_gateway as ng

FAILURES = []


def check(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
    except Exception as e:  # noqa: BLE001
        FAILURES.append((name, e))
        print(f"  FAIL  {name}: {e}")


def expect_raises(fn, *substrings):
    try:
        fn()
    except RuntimeError as e:
        msg = str(e)
        for s in substrings:
            assert s in msg, f"error missing {s!r}: {msg}"
        return
    raise AssertionError("expected RuntimeError, none raised")


# -- transport law -----------------------------------------------------------

def t_default_is_stdio():
    assert ng.resolve_transport({}) == "stdio"


def t_sse_refused_citing_the_rule():
    expect_raises(
        lambda: ng.resolve_transport({"CARTON_TRANSPORT": "sse"}),
        "FORBIDDEN",
        "carton-mcp-transport",
    )
    expect_raises(
        lambda: ng.resolve_transport({"CARTON_TRANSPORT": "SSE"}), "FORBIDDEN"
    )


def t_http_and_alias():
    assert ng.resolve_transport({"CARTON_TRANSPORT": "http"}) == "http"
    assert ng.resolve_transport({"CARTON_TRANSPORT": "streamable-http"}) == "http"


def t_unknown_transport_errors_loudly():
    expect_raises(
        lambda: ng.resolve_transport({"CARTON_TRANSPORT": "websocket"}),
        "unknown CARTON_TRANSPORT",
    )


# -- fail-closed key ---------------------------------------------------------

def t_missing_key_fails_closed():
    expect_raises(lambda: ng.require_api_key({}), "CARTON_API_KEY")
    expect_raises(
        lambda: ng.require_api_key({"CARTON_API_KEY": "  "}), "fail-closed"
    )
    assert ng.require_api_key({"CARTON_API_KEY": "k1"}) == "k1"


# -- run kwargs (bind-local default) ----------------------------------------

def t_run_kwargs_defaults_and_overrides():
    assert ng.network_run_kwargs({}) == {"host": "127.0.0.1", "port": 8200}
    assert ng.network_run_kwargs(
        {"CARTON_HOST": "0.0.0.0", "CARTON_PORT": "9300"}
    ) == {"host": "0.0.0.0", "port": 9300}


# -- the ASGI bearer gate ----------------------------------------------------

def _drive(app, headers):
    """Minimal ASGI driver: returns (status|None, reached_inner)."""
    sent = []
    reached = {"inner": False}

    async def inner(scope, receive, send):
        reached["inner"] = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    gate = ng.BearerGateMiddleware(inner, "sekrit-key")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}
    asyncio.run(gate(scope, receive, send))
    status = next(
        (m["status"] for m in sent if m["type"] == "http.response.start"), None
    )
    return status, reached["inner"]


def t_gate_401_without_bearer():
    status, reached = _drive(None, [])
    assert status == 401 and not reached


def t_gate_401_wrong_bearer():
    status, reached = _drive(None, [(b"authorization", b"Bearer wrong")])
    assert status == 401 and not reached


def t_gate_passes_right_bearer():
    status, reached = _drive(None, [(b"authorization", b"Bearer sekrit-key")])
    assert status == 200 and reached


def t_gate_ignores_non_http_scopes():
    async def inner(scope, receive, send):
        inner.called = True

    inner.called = False
    gate = ng.BearerGateMiddleware(inner, "k")
    asyncio.run(gate({"type": "lifespan"}, None, None))
    assert inner.called  # lifespan passes through untouched


if __name__ == "__main__":
    tests = [
        t_default_is_stdio,
        t_sse_refused_citing_the_rule,
        t_http_and_alias,
        t_unknown_transport_errors_loudly,
        t_missing_key_fails_closed,
        t_run_kwargs_defaults_and_overrides,
        t_gate_401_without_bearer,
        t_gate_401_wrong_bearer,
        t_gate_passes_right_bearer,
        t_gate_ignores_non_http_scopes,
    ]
    print(f"network_gateway tests ({len(tests)}):")
    for t in tests:
        check(t.__name__, t)
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED")
        sys.exit(1)
    print(f"\nall {len(tests)} passed")
