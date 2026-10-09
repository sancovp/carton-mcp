The node-quota gate is one self-contained module, `carton_quota.py`, plus ONE guarded call at the top of
`add_concept_tool_func` — after the empty-relationships check, BEFORE the optional-fields merge and the
queue write. It does NOT touch the guarded optional-fields capability; domain, subdomain, personal_domain
and produces stay untouched.

## States

| component | status | note |
|---|---|---|
| `carton_quota.py` | **BUILT + 8/8 tests + LIVE-VERIFIED 2026-07-10** | pure logic, injectable count/exists fns; TTL-cached count (default 60s, `CARTON_QUOTA_TTL_S`). **The envelope law (the box smoke's catch):** `query_wiki_graph` returns `{'success':…,'data':[rows]}` — `_rows()` unwraps and **fails LOUD on a failed query** (a meter that can't count must never fail-open into 'unlimited'). Live 6/6: refused-at-quota with the exact message through the real MCP surface · refinement passed · freed+TTL-refresh passed (`application/carton-saas/box/smoke/`) |
| `add_concept_tool.py` wiring | EDITED (one call, after the empty-relationships check, BEFORE the optional-fields merge and the queue write) | does NOT touch the guarded optional-fields capability (domain/subdomain/personal_domain/produces untouched) |
| live E2E (real server, real neo4j, real MCP surface) | **VERIFIED 2026-07-10 (6/6)** | `application/carton-saas/box/smoke/` — against a throwaway Community neo4j on 7688. The standing warning holds forever: NEVER set `CARTON_MAX_NODES` on Isaac's live carton (his graph exceeds any test limit; it would start rejecting real writes) |
| daemon-side stub drift | NAMED, accepted | auto-created relationship-target stubs bypass the chokepoint; front door blocks all deliberate growth; the BLACKBOX nightly gauge shows true counts. Daemon-side enforcement = a separate capability with its own dev-flow if ever needed |

NO-OP UNLESS `CARTON_MAX_NODES` IS SET. Unset means byte-identical behaviour and zero queries. A quota
never appears uninvited.

REFUSE GROWTH, NOT REFINEMENT. At or over quota, EXISTING concepts still edit — `add_concept` is also the
update path — and only NEW nodes raise `QuotaExceeded`, with an actionable message naming the limit, the
count and the upgrade path. The existence query runs only on the rare over-quota branch.

THE LIVE PATH IS THE ENFORCED PATH. Rejection fires before the queue write, so it provably never reaches
the graph. Never enforce on a derived view.

ENFORCEMENT READS THE LIVE COUNT; BLACKBOX ONLY OBSERVES. Never conflate the two lanes.

BE LOUD ON GARBAGE. A non-integer or negative `CARTON_MAX_NODES` raises; a broken limit must never
silently mean unlimited.

THE ENVELOPE LAW: `query_wiki_graph` returns `{'success':…,'data':[rows]}`, so `_rows()` unwraps it and
FAILS LOUD on a failed query. A meter that cannot count must never fail-open into "unlimited".

⚠ NEVER set `CARTON_MAX_NODES` on Isaac's live carton. His graph exceeds any test limit and it would
start rejecting real writes.

Dev-flow, and NEVER edit one place only. Touching `check_quota` / `quota_limit` / the TTL cache (default
60s, `CARTON_QUOTA_TTL_S`), or the one call site in `add_concept_tool_func` → edit `carton_quota.py` and
the call site coherently, then the gate: `python3 test_carton_quota.py` all green AND `python3
test_network_gateway.py` still green AND `py_compile` on both edited files.

If your change goes anywhere NEAR the optional-fields params or `merge_optional_domain_fields`, STOP:
that is the `edit-add-concept-optional-fields` dev-flow, non-negotiable.

Installed-package law: source edits change nothing running without `pip install --no-deps` and a restart.

Known bound, named and accepted: daemon-side auto-created relationship-target stubs bypass the
chokepoint. The front door blocks all deliberate growth, and the BLACKBOX nightly gauge shows true
counts. Daemon-side enforcement is a separate capability with its own dev-flow if ever needed.

Read the `understand-carton-mcp-rules` skill for the history behind this rule.
