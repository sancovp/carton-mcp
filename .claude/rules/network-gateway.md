# The Network Gateway (opt-in streamable-HTTP + API key) — dev-flow + states

**BUILT 2026-07-09 (v0.1.81).** The carton-saas box's "one new code surface"
(monorepo `designs/carton-saas-DESIGN.md` §2), useful standalone: remote
agents reaching carton over the network, authenticated.

## States (v2 — the box smoke corrected v1, 2026-07-10)

| component | status | note |
|---|---|---|
| `network_gateway.py` | **v2 BUILT + LIVE-VERIFIED** | v1's `auth=StaticTokenVerifier` constructor param was WRONG-CLASS (carton uses the SDK's `mcp.server.fastmcp.FastMCP`, `server_fastmcp.py:17`, NOT the fastmcp-2.x lib — v1 died at real boot). v2 = pure-ASGI `BearerGateMiddleware` around `streamable_http_app()` under uvicorn — zero extra deps, every pinned version |
| `server_fastmcp.py` touchpoints | EDITED (v2) | constructor PRISTINE (`mcp = FastMCP("carton")` — stdio even more untouched than v1) + `main()` dispatch → `run_network(mcp)` |
| `test_network_gateway.py` | 10/10 green | transport laws + fail-closed key + the ASGI gate driven directly (401/401/200/lifespan-passthrough) |
| live network smoke (real port, real Client, real server) | **VERIFIED 2026-07-10, 6/6** | `application/carton-saas/box/smoke/` — no-token 401 · wrong-token 401 · token → 31 real tools · plus the quota lifecycle |

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
