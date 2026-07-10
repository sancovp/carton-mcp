"""CartON network gateway — opt-in streamable-HTTP transport + static API key.

One capability, one module (this repo's own convention — the carton_kv /
split_content precedent). stdio stays the DEFAULT and the ONLY local
transport (.claude.json untouched; local behavior byte-identical). Network
mode exists for the hosted carton box (monorepo
`designs/carton-saas-DESIGN.md` — the box's "one new code surface") and for
any operator who wants remote agents reaching their own carton.

LAWS (held in code, not prose):
1. **SSE is FORBIDDEN for carton** (`.claude/rules/carton-mcp-transport.md`,
   Mar 13 2026: SSE degraded over long sessions into Errno-32 broken pipes
   and the whole setup was reversed). `resolve_transport` REFUSES 'sse'.
   Network mode = streamable HTTP ("http") only — request-scoped, no
   long-lived event stream to degrade.
2. **Fail closed**: a network transport without CARTON_API_KEY refuses to
   start. There is no unauthenticated network carton, ever.
3. **Nothing blocking at import** (the same rule's startup-timeout lesson):
   this module reads env only; fastmcp's verifier is imported lazily and
   only on the network path.
4. **Bind local by default**: host defaults to 127.0.0.1; exposing on
   0.0.0.0 is an explicit CARTON_HOST choice.

Env surface (all optional; unset == today's behavior exactly):
  CARTON_TRANSPORT   'stdio' (default) | 'http' (network; 'streamable-http'
                     accepted as an alias; 'sse' refused)
  CARTON_API_KEY     required iff transport is network — the ONE static
                     bearer token remote clients present
  CARTON_HOST        default 127.0.0.1
  CARTON_PORT        default 8200
  CARTON_CLIENT_ID   claim label on the token (default 'carton-box')

Note: the lazy verifier import needs fastmcp>=2.11
(`StaticTokenVerifier`); the pinned fastmcp==2.9.0 still runs stdio mode
untouched — the box image pins its own newer fastmcp.
"""

import os

STDIO = "stdio"
HTTP = "http"
_ALIASES = {"streamable-http": HTTP}
_FORBIDDEN = ("sse",)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8200


def resolve_transport(env=None) -> str:
    """The one transport decision. Refuses 'sse' (law 1); unknown values
    error loudly rather than falling through to fastmcp."""
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


def build_auth_verifier(env=None):
    """None on stdio (local carton byte-identical); a StaticTokenVerifier on
    the network path; RuntimeError (fail closed, law 2) on a network
    transport without CARTON_API_KEY."""
    env = os.environ if env is None else env
    if resolve_transport(env) == STDIO:
        return None
    key = env.get("CARTON_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "network transport requires CARTON_API_KEY (fail-closed law: "
            "no unauthenticated network carton, ever)"
        )
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    return StaticTokenVerifier(
        tokens={key: {"client_id": env.get("CARTON_CLIENT_ID", "carton-box")}}
    )


def network_run_kwargs(env=None) -> dict:
    """host/port kwargs for mcp.run() on the network path (law 4 defaults)."""
    env = os.environ if env is None else env
    return {
        "host": env.get("CARTON_HOST", DEFAULT_HOST),
        "port": int(env.get("CARTON_PORT", str(DEFAULT_PORT))),
    }
