#!/usr/bin/env python3
"""Network gateway laws: stdio default · sse refused · fail-closed key ·
token verification · live ASGI 401-without / pass-with bearer.

Plain-python runner (the test_relationship_constraints.py house idiom) —
runs standalone on host or container: `python3 test_network_gateway.py`.
The module is stdlib-at-import, imported via path shim (the repo root IS
the carton_mcp package, so bare-module import avoids the heavy __init__).
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
    except Exception as e:  # noqa: BLE001 — a test runner reports, never hides
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
    expect_raises(  # case-insensitive
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


# -- fail-closed auth --------------------------------------------------------

def t_stdio_gets_no_verifier():
    assert ng.build_auth_verifier({}) is None


def t_network_without_key_fails_closed():
    expect_raises(
        lambda: ng.build_auth_verifier({"CARTON_TRANSPORT": "http"}),
        "CARTON_API_KEY",
    )
    expect_raises(  # whitespace key is no key
        lambda: ng.build_auth_verifier(
            {"CARTON_TRANSPORT": "http", "CARTON_API_KEY": "  "}
        ),
        "fail-closed",
    )


def t_network_with_key_verifies_only_that_token():
    v = ng.build_auth_verifier(
        {"CARTON_TRANSPORT": "http", "CARTON_API_KEY": "sekrit-key"}
    )
    assert v is not None
    good = asyncio.run(v.verify_token("sekrit-key"))
    bad = asyncio.run(v.verify_token("wrong-key"))
    assert good is not None and good.client_id == "carton-box"
    assert bad is None


# -- run kwargs (bind-local default) ----------------------------------------

def t_run_kwargs_defaults_and_overrides():
    assert ng.network_run_kwargs({}) == {"host": "127.0.0.1", "port": 8200}
    assert ng.network_run_kwargs(
        {"CARTON_HOST": "0.0.0.0", "CARTON_PORT": "9300"}
    ) == {"host": "0.0.0.0", "port": 9300}


# -- live ASGI: the wire actually rejects/accepts ---------------------------

def t_http_app_rejects_without_bearer_and_passes_with():
    import httpx
    from fastmcp import FastMCP

    v = ng.build_auth_verifier(
        {"CARTON_TRANSPORT": "http", "CARTON_API_KEY": "sekrit-key"}
    )
    app = FastMCP("gw-test", auth=v).http_app()

    async def _roundtrip():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                body = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"},
                    },
                }
                headers = {
                    "content-type": "application/json",
                    "accept": "application/json, text/event-stream",
                }
                no_auth = await client.post("/mcp", json=body, headers=headers)
                with_auth = await client.post(
                    "/mcp",
                    json=body,
                    headers={**headers, "authorization": "Bearer sekrit-key"},
                )
                return no_auth.status_code, with_auth.status_code

    no_auth_status, with_auth_status = asyncio.run(_roundtrip())
    assert no_auth_status == 401, f"expected 401 without bearer, got {no_auth_status}"
    assert with_auth_status == 200, f"expected 200 with bearer, got {with_auth_status}"


if __name__ == "__main__":
    tests = [
        t_default_is_stdio,
        t_sse_refused_citing_the_rule,
        t_http_and_alias,
        t_unknown_transport_errors_loudly,
        t_stdio_gets_no_verifier,
        t_network_without_key_fails_closed,
        t_network_with_key_verifies_only_that_token,
        t_run_kwargs_defaults_and_overrides,
        t_http_app_rejects_without_bearer_and_passes_with,
    ]
    print(f"network_gateway tests ({len(tests)}):")
    for t in tests:
        check(t.__name__, t)
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED")
        sys.exit(1)
    print(f"\nall {len(tests)} passed")
