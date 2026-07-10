"""CartON network gateway — opt-in streamable-HTTP transport + static API key.

One capability, one module (the carton_kv / split_content precedent). stdio
stays the DEFAULT and the ONLY local transport (.claude.json untouched;
local behavior byte-identical — the server object itself is NOT modified by
this module in stdio mode). Network mode exists for the hosted carton box
(monorepo `designs/carton-saas-DESIGN.md` — the box's "one new code
surface") and for any operator who wants remote agents reaching their own
carton.

MECHANISM (v2 — the box smoke corrected v1): carton's server is the SDK's
`mcp.server.fastmcp.FastMCP` (server_fastmcp.py:17), NOT the fastmcp-2.x
library class, so auth cannot ride a constructor param. Instead, network
mode wraps the SDK's own `streamable_http_app()` in a PURE-ASGI bearer
middleware — zero extra dependencies, works at every pinned fastmcp/mcp
version, and the stdio path never sees any of it.

LAWS (held in code, not prose):
1. **SSE is FORBIDDEN for carton** (`.claude/rules/carton-mcp-transport.md`,
   Mar 13 2026: SSE degraded over long sessions into Errno-32 broken pipes).
   `resolve_transport` REFUSES 'sse'. Network mode = streamable HTTP only.
2. **Fail closed**: a network transport without CARTON_API_KEY refuses to
   start. There is no unauthenticated network carton, ever.
3. **Nothing blocking at import** (the same rule's startup-timeout lesson):
   env reads only; the ASGI wrap happens inside main()'s network branch.
4. **Bind local by default**: host defaults to 127.0.0.1; exposing on
   0.0.0.0 is an explicit CARTON_HOST choice.

Env surface (all optional; unset == today's behavior exactly):
  CARTON_TRANSPORT   'stdio' (default) | 'http' ('streamable-http' alias;
                     'sse' refused)
  CARTON_API_KEY     required iff transport is network — the ONE static
                     bearer token remote clients present
  CARTON_HOST        default 127.0.0.1
  CARTON_PORT        default 8200
"""

import json
import os

STDIO = "stdio"
HTTP = "http"
_ALIASES = {"streamable-http": HTTP}
_FORBIDDEN = ("sse",)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8200


def resolve_transport(env=None) -> str:
    """The one transport decision. Refuses 'sse' (law 1); unknown values
    error loudly rather than falling through."""
    env = os.environ if env is None else env
    raw = env.get("CARTON_TRANSPORT", STDIO).strip().lower()
    transport = _ALIASES.get(raw, raw)
    if transport in _FORBIDDEN:
        raise RuntimeError(
            "CARTON_TRANSPORT='sse' is FORBIDDEN "
            "(.claude/rules/carton-mcp-transport.md, Mar 13 2026: SSE "
            "degraded over long sessions -> Errno 32 broken pipes; fully "
            "reversed). Use CARTON_TRANSPORT=http (streamable HTTP)."
        )
    if transport not in (STDIO, HTTP):
        raise RuntimeError(
            f"unknown CARTON_TRANSPORT {raw!r} — use 'stdio' (default) "
            "or 'http'"
        )
    return transport


def require_api_key(env=None) -> str:
    """The fail-closed key law (law 2). Network callers only."""
    env = os.environ if env is None else env
    key = (env.get("CARTON_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "network transport requires CARTON_API_KEY (fail-closed law: "
            "no unauthenticated network carton, ever)"
        )
    return key


def network_run_kwargs(env=None) -> dict:
    """host/port for uvicorn on the network path (law 4 defaults)."""
    env = os.environ if env is None else env
    return {
        "host": env.get("CARTON_HOST", DEFAULT_HOST),
        "port": int(env.get("CARTON_PORT", str(DEFAULT_PORT))),
    }


class BearerGateMiddleware:
    """Pure-ASGI static-bearer gate: every http request must present
    `Authorization: Bearer <key>` or gets 401. No deps, no sessions, no
    perception — a lock on the one door."""

    def __init__(self, app, key: str):
        self.app = app
        self.key = key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        auth = ""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth = value.decode("latin-1")
                break
        if auth != f"Bearer {self.key}":
            body = json.dumps({"error": "unauthorized"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def build_network_app(mcp_server, env=None):
    """Wrap the SDK FastMCP's streamable-http app in the bearer gate.
    Called ONLY on the network path (law 3 — nothing at import)."""
    key = require_api_key(env)
    return BearerGateMiddleware(mcp_server.streamable_http_app(), key)


def run_network(mcp_server, env=None) -> None:
    """The network entrypoint main() dispatches to: gated app under uvicorn."""
    import uvicorn  # brought by the mcp/fastmcp stack; network path only

    uvicorn.run(build_network_app(mcp_server, env), **network_run_kwargs(env))
