Isaac verbatim: **"the saas is hit *FROM* an MCP. it CANNOT HAVE MCPS. THERE IS NO AGENT TO USE THEM."**
and **"MCPS ARE RUN BY USERS LOCALLY, ON THEIR LAPTOPS AND DESKTOPS, NOT WHERE THE SAAS SERVICE THEY HIT
IS."**

A tenant puts their user and key in their MCP SETTINGS. Their MCP runs on their own machine, reads
`CARTON_USER` and `CARTON_KEY` from env, and calls IN to their box. The box checks the key and returns
ROWS. Nothing is negotiated, minted or stored — that is the entire protocol.

```
tenant's laptop                                  their carton box
  MCP (stdio) → KuzuHttpStore ── Bearer key ──→ kuzu_query_endpoint (:8192)
                                                   /query /set_properties
                                                   /remove_properties
                                                   /find_by_properties /health
```

| component | status | note |
|---|---|---|
| `kuzu_query_endpoint.py` | **THE SERVICE SURFACE** | real routes, real rows. `required_key()` demands `CARTON_KEY` when set and checks it **before the body is read**; unset = the old private in-box wire, byte-identical. `serve_in_thread` **REFUSES TO START** on a non-local bind with no key |
| `KuzuHttpStore` (heaven-framework `graph_store.py`) | **THE CLIENT** | sends `Authorization: Bearer` + `X-Carton-User` from env, headers attached only when configured. Constructed with NO ARGUMENTS is the real path — that is how MCP settings deliver credentials |
| the worker (`observation_worker_daemon`) | **SERVES IT, ON EVERY BACKEND** | it owns the graph. The start used to be gated on `GRAPH_BACKEND=kuzu`; that gate is GONE, because with the MCP removed a neo4j box would come up healthy and answer nothing. The endpoint is store-agnostic by construction — it exposes exactly the four `GraphStore` methods, and both stores implement them |
| `carton_transport.py` | the transport law, all that outlived the gateway | stdio only; `sse` refused (Mar 13 2026 broken pipes); `http`/`streamable-http` refused **by name as REMOVED**, never downgraded. 14/14 |
| `network_gateway.py` | **DELETED** | it made carton's MCP server LISTEN so something could dial in. Nothing could: a box has no agent |
| `[program:carton-mcp]` in the box | **DELETED** | see `application/carton-saas/box/supervisord.conf`, which carries the reasoning where an operator will meet it |

`kuzu_query_endpoint.py` IS the service surface. `required_key()` demands `CARTON_KEY` when set and
checks it BEFORE the body is read; unset means the old private in-box wire, byte-identical.
`serve_in_thread` REFUSES TO START on a non-local bind with no key.

`KuzuHttpStore` (heaven-framework `graph_store.py`) IS the client. It sends `Authorization: Bearer` plus
`X-Carton-User` from env, attaching the headers only when configured. Construct it with NO ARGUMENTS —
that is the real path, and it is how MCP settings deliver credentials.

The worker (`observation_worker_daemon`) serves the endpoint ON EVERY BACKEND, because it owns the graph.
Do not gate that start on `GRAPH_BACKEND=kuzu`: with the MCP removed, a neo4j box would come up healthy
and answer nothing. The endpoint is store-agnostic by construction — it exposes exactly the four
`GraphStore` methods, and both stores implement them.

`carton_transport.py` carries the transport law: stdio only. `sse` is refused. `http` and
`streamable-http` are refused BY NAME AS REMOVED, never downgraded.

Never restore `network_gateway.py` or `[program:carton-mcp]` in the box. The gateway made carton's MCP
server LISTEN so something could dial in, and nothing could: a box has no agent.

Never use the MCP surface as a data plane. Every tool return goes through `server_fastmcp._fmt`, which
TRUNCATES at 10,000 chars into a file INSIDE the container that the caller cannot open, DROPS null
columns (`_present` in `carton_render.py`), and lays the rows out as prose for an agent — one record per
block, every repeated sequence rewritten as an `@N` ref (`carton_render.render_answer` through
`answer_refs.encode_refs`). That is
correct for an agent reading prose and silently wrong for anything reading rows: a board served through
it is partial and says nothing.

Dev-flow, and NEVER edit one place only. Touching `kuzu_query_endpoint` (`handle` / `required_key` /
`_authorized` / `serve_in_thread`), the `KuzuHttpStore` credential half, or the worker's endpoint start →
edit them coherently, then the gate: `python3 test_query_endpoint_auth.py` (7/7 — client against server
over a REAL socket, never two mocks agreeing) AND `python3 test_kuzu_query_endpoint.py` (6/6) AND `python3
test_carton_transport.py` (14/14). "It imported" is not the gate.

Changing the transport laws → `carton_transport.py` plus the one call in `server_fastmcp.main()`.

Installed-package law: a source edit reaches nothing running without `pip install --no-deps` (carton-mcp
AND heaven-framework), and the box needs its image REBUILT with `box/build-carton-box.sh`, which stages a
small tree rather than streaming the whole monorepo root.

Prove it end to end with a BOX, never a loopback: bring one up as its OWN compose project (`docker
compose -p <name>`, the provisioner pattern — never disturb a running `box-*`) with
`CARTON_QUERY_HOST=0.0.0.0`, a `CARTON_KEY` and a published query port, then drive it from outside with
`KuzuHttpStore()` and no arguments. Assert a NULL COLUMN SURVIVES — the thing the MCP surface would have
dropped, which is the whole reason this surface exists rather than that one.
