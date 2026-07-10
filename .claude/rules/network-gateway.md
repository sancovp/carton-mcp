# The Network Gateway (opt-in streamable-HTTP + API key) — dev-flow + states

**BUILT 2026-07-09 (v0.1.81).** The carton-saas box's "one new code surface"
(monorepo `designs/carton-saas-DESIGN.md` §2), useful standalone: remote
agents reaching carton over the network, authenticated.

## States

| component | status | note |
|---|---|---|
| `network_gateway.py` | BUILT + 9/9 tests | stdlib-at-import; fastmcp lazy (network path only, needs fastmcp>=2.11 for `StaticTokenVerifier`; pinned 2.9 still runs stdio untouched) |
| `server_fastmcp.py` touchpoints | EDITED | `mcp = FastMCP("carton", auth=_gw_build_auth_verifier())` (auth=None on stdio — byte-identical locally) + `main()` dispatch (`resolve_transport()` + host/port kwargs) |
| `test_network_gateway.py` | 9/9 green (plain-python runner — the house idiom; pytest chokes on the repo-root `__init__.py` outside the container) | incl. a LIVE ASGI check: 401 without bearer, 200 with, on a real `FastMCP(...).http_app()` |
| live network smoke (real port, real Client) | PENDING | run in the box image / container: `CARTON_TRANSPORT=http CARTON_API_KEY=k carton-mcp` then a fastmcp Client with the token |

## The laws (now CODE, not prose)

1. **SSE is FORBIDDEN** — `resolve_transport` REFUSES `'sse'` citing
   `carton-mcp-transport.md` (Mar 13 2026: long sessions → Errno-32 broken
   pipes). Before this module, `main()` passed `CARTON_TRANSPORT=sse` straight
   through unauthenticated; the rule is now enforced at the only entrypoint.
2. **Fail closed** — a network transport without `CARTON_API_KEY` refuses to
   start. No unauthenticated network carton, ever.
3. **stdio is the default and the ONLY local transport** — `.claude.json`
   untouched, no start_sancrev.sh launcher, zero change to local behavior.
4. **Nothing blocking at import** — env reads only (the transport rule's
   30s-startup-timeout lesson).
5. **Binds 127.0.0.1 by default** — `CARTON_HOST=0.0.0.0` is an explicit act.

## Dev-flow (the edit-set — NEVER edit one place only)

Touching `resolve_transport` / `build_auth_verifier` / `network_run_kwargs`,
the `FastMCP("carton", auth=...)` construction, or `main()`'s dispatch →
edit `network_gateway.py` + the two `server_fastmcp.py` touchpoints
coherently, then the gate: `python3 test_network_gateway.py` all green
(the live-ASGI test IS the gate — "it imported" is not), then
`python3 -m py_compile server_fastmcp.py`. Env surface: `CARTON_TRANSPORT` ·
`CARTON_API_KEY` · `CARTON_HOST` · `CARTON_PORT` · `CARTON_CLIENT_ID`.
Remember the installed-package law: a source edit without
`pip install --no-deps` + restart changes nothing running.
