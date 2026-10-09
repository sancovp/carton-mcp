The hosted CartON is hit FROM an MCP; it serves no MCP. An MCP server exists to be driven by an agent, and a box
has none: the MCP runs on the tenant's own machine, and every one of its tools is `call_carton(<tool>, <its
arguments>)` plus the rendering of the answer. What the box serves is CARTON'S SDK — the SDK's operations, which are
the MCP's tool list by name — on ONE door:

```
tenant's machine                                     their carton box (the worker, which owns the graph file)
  MCP tool  ── call_carton(op, params) ──►  POST /call {"operation", "params"}   → {"ok", "result"}
  Ribcage · SOMA · any program ──────────►  GET  /health
                        Bearer CARTON_KEY, X-Carton-User                          knowledge/carton-mcp/carton_api.py
```

`carton_api.CartonOperation` names the operations; `server_fastmcp.py` registers each beside its tool with
`@operation(name)` — the same signature, no rendering — and `carton_api.operations()` refuses to serve if the
enum, the registered operations and the tool list disagree. A read operation answers the SDK's data
(`query_wiki_graph` answers the facade's envelope: rows with their null columns); a write answers the SDK's text.
The rendering (`_fmt`, the overflow file, the reminders) is the tool's, on the caller's side.

| component | status | note |
|---|---|---|
| `carton_api.py` — `call_carton` · `execute` · `serve_in_thread` · `CartonOperation` | **THE DOOR AND THE CALL** | `call_carton` runs in-process with no `CARTON_URL` and POSTs `/call` with one; `execute` validates params exactly as the MCP validates a tool's arguments, then runs the operation; `serve_in_thread` REFUSES TO START on a non-local bind with no key, checks the key before reading the body, refuses an unknown operation by name (400), answers an operation's own failure as a 400 carrying its message, and refuses through the operator's gate with 402 |
| `server_fastmcp.py` | **THE OPERATIONS AND THE TOOLS** | every `@mcp.tool()` body is `call_carton` + a render; every `@_carton_api.operation(name)` is the function behind it. With `CARTON_URL` set the module opens no graph connection and starts no worker |
| the worker (`observation_worker_daemon`) | **SERVES IT, ON EVERY BACKEND** | it owns the graph file and drains the queue, so it is where every operation runs; it imports the operations into its own process, whose graph connection is the one embedded store per path (`graph_store.embedded_store`) |
| `graph_store.py` | the store, private to the worker's process | `KuzuStore` only; a second process never opens the file and never reaches it over the wire |
| `carton_transport.py` | the transport law | stdio only; `sse` refused; `http`/`streamable-http` refused by name as removed |
| the metering | the operator's, through `CARTON_CALL_GATE` | `application/carton-saas/metering/call_gate.py` — `gate(operation, params)`: `add_concept` of a NEW concept at the limit → 402; edits and every other operation pass. Never in the published package |

Env — the client: `CARTON_URL` · `CARTON_KEY` · `CARTON_USER` · `CARTON_TIMEOUT_S`. The server: `CARTON_HOST`
(127.0.0.1 unless the box is opened) · `CARTON_PORT` (8192) · `CARTON_KEY` · `CARTON_CALL_GATE`.

Never give the box a second door: no route beside `/call` and `/health`, no Cypher pipe, no operation that is not a
tool of the MCP. A product on top of CartON (a board, a card) is concepts and properties written through
`add_concept` and `set_properties`. Never restore an MCP server, a network MCP transport or a graph socket in the box.

Never put logic in a tool: a tool is `call_carton(<tool>, <args>)` and a render. A new capability is a new SDK
function, registered as an operation beside its tool, named in `CartonOperation`.

Dev-flow, and NEVER edit one place only. Touching `carton_api` (`execute` · `call_carton` · `serve_in_thread` ·
`load_gate` · `CartonOperation`), a tool or its operation in `server_fastmcp.py`, `add_concept_tool.submit_queue_entry`,
or the worker's server start → edit them coherently, then the gate: `python3 test_carton_api.py` (9/9 — client
against server over a REAL socket, never two mocks agreeing; the enum = the registry = the tools; a real
`add_concept` over the wire writes the SERVER's queue and `query_wiki_graph` answers rows) AND `python3
test_carton_transport.py` (14/14) AND, for the queue or the drain, `python3 test_queue_submit.py` (5/5) AND
`python3 test_universal_write.py` (6/6 — write → drain → graph on a real embedded graph) AND
`python3 application/carton-saas/metering/test_call_gate.py` (9/9). "It imported" is not the gate.

Installed-package law: a source edit reaches nothing running without `pip install --no-deps` (carton-mcp AND
heaven-framework), and the box needs its image REBUILT with `box/build-carton-box.sh`, which stages a small tree
rather than streaming the whole monorepo root.

Prove it end to end with a BOX, never a loopback: bring one up as its OWN compose project (`docker compose -p
<name>`, the provisioner pattern — never disturb a running `box-*`) with `CARTON_HOST=0.0.0.0`, a `CARTON_KEY` and a
published port, then drive it from outside with `call_carton` and the credentials in the environment
(`box/smoke/box_smoke_client.py`). Assert a NULL COLUMN SURVIVES in `query_wiki_graph`'s rows and that
`query_wiki_graph` refuses a write verb — the two facts that make this door the SDK and not a pipe.
