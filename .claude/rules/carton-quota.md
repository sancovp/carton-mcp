# The Node-Quota Gate (carton_quota.py) — dev-flow + states

**BUILT 2026-07-09 (v0.1.82).** The carton-saas metering gate (monorepo
`designs/carton-saas-DESIGN.md` §4): one self-contained module + ONE guarded
call at the top of `add_concept_tool_func` (before the queue write).

## States

| component | status | note |
|---|---|---|
| `carton_quota.py` | **BUILT + 8/8 tests + LIVE-VERIFIED 2026-07-10** | pure logic, injectable count/exists fns; TTL-cached count (default 60s, `CARTON_QUOTA_TTL_S`). **The envelope law (the box smoke's catch):** `query_wiki_graph` returns `{'success':…,'data':[rows]}` — `_rows()` unwraps and **fails LOUD on a failed query** (a meter that can't count must never fail-open into 'unlimited'). Live 6/6: refused-at-quota with the exact message through the real MCP surface · refinement passed · freed+TTL-refresh passed (`application/carton-saas/box/smoke/`) |
| `add_concept_tool.py` wiring | EDITED (one call, after the empty-relationships check, BEFORE the optional-fields merge and the queue write) | does NOT touch the guarded optional-fields capability (domain/subdomain/personal_domain/produces untouched) |
| live E2E (real server, real neo4j, real MCP surface) | **VERIFIED 2026-07-10 (6/6)** | `application/carton-saas/box/smoke/` — against a throwaway Community neo4j on 7688. The standing warning holds forever: NEVER set `CARTON_MAX_NODES` on Isaac's live carton (his graph exceeds any test limit; it would start rejecting real writes) |
| daemon-side stub drift | NAMED, accepted | auto-created relationship-target stubs bypass the chokepoint; front door blocks all deliberate growth; the BLACKBOX nightly gauge shows true counts. Daemon-side enforcement = a separate capability with its own dev-flow if ever needed |

## The laws (in code)

1. **No-op unless `CARTON_MAX_NODES` is set** — unset = byte-identical, zero
   queries. A quota never appears uninvited.
2. **Refuse growth, not refinement** — at/over quota, EXISTING concepts still
   edit (add_concept is also the update path); only NEW nodes raise
   `QuotaExceeded` (actionable message: limit, count, the upgrade path). The
   existence query runs only on the rare over-quota branch.
3. **The LIVE path is the enforced path** — rejection fires before the queue
   write, so it provably never reaches the graph (the optional-fields build's
   burned lesson, designed-in: never enforce on a derived view).
4. **Enforcement reads the live count; BLACKBOX only observes** — separate
   lanes, never conflated.
5. **Loud on garbage** — a non-integer/negative `CARTON_MAX_NODES` raises; a
   broken limit must never silently mean unlimited.

## Dev-flow (the edit-set — NEVER edit one place only)

Touching `check_quota`/`quota_limit`/the cache, or the one call site in
`add_concept_tool_func` → edit `carton_quota.py` + the call site coherently,
then the gate: `python3 test_carton_quota.py` all green AND
`python3 test_network_gateway.py` still green AND `py_compile` on both edited
files. If your change goes anywhere NEAR the optional-fields params or
`merge_optional_domain_fields`, STOP — that is the
`edit-add-concept-optional-fields` dev-flow, non-negotiable. Installed-package
law applies: source edits change nothing running without
`pip install --no-deps` + restart.

→ Why / history / how-to behind this rule: read the `understand-carton-mcp-rules` skill.
