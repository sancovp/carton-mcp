# THE BOX SERVICE SURFACE — CartON's SDK on one door, the MCP a client of it

<docsys kind="dev-flow" role="instance"/>

TRIGGER:[editing `carton_api.py` (`call_carton` · `execute` · `serve_in_thread` · `load_gate` · `CartonOperation`) · any
`@mcp.tool()` or `@_carton_api.operation(...)` in `server_fastmcp.py` · the worker's server start · `graph_store.py`'s
`KuzuStore`/`embedded_store`/`make_store` · `add_concept_tool.submit_queue_entry` · any program that writes CartON from
off the box (SOMA's vault mirror, Ribcage, a hook) · the box's env (`supervisord.conf` · `Dockerfile` · `fly.toml` ·
`docker-compose.yml` · `provision.py` · `fly.ts`) · the metering gate]

The hosted CartON is hit FROM an MCP; it serves no MCP. The MCP runs on the tenant's machine and every tool is
`call_carton(<tool>, <its arguments>)` plus a render. The box's worker — the one process that owns the graph file and
drains the queue — serves CARTON'S SDK, the MCP's tool list by name, on ONE door:

```
caller's machine                                    the box (the worker: owns the graph file, drains the queue)
  MCP tool ── call_carton(op, params) ──►  POST /call {"operation","params"} → {"ok","result"}   carton_api.py
  Ribcage · SOMA · any program ─────────►  GET  /health
                       Bearer CARTON_KEY, X-Carton-User
no CARTON_URL ⇒ call_carton = execute() in this process (self-hosted, the MCP beside its own worker)
```

## RETRIEVE — read whole, in this order, before any edit

| file | lines | what it answers |
|---|---|---|
| `knowledge/carton-mcp/carton_api.py` | 1–400 | the enum · the registry · `execute` (params validated by the OPERATION's own arg model, top-level `None` dropped) · `call_carton` · `remote()` · the server (key before body · 400 by name · 402 gate · `SERVING` · `WRITE_OVERFLOW_FILES=False` in the serving process) |
| `knowledge/carton-mcp/server_fastmcp.py` | 85–125 · 176–297 · 467–513 · 545–4117 · 4120–4151 | overflow rule · import-time `_neo4j_conn`/`utils`/`_concept_stash` · `_graph_conn` · the SM gate's actor · the name gate · every op/tool pair (grep `_carton_api.operation`) · `main()` |
| `knowledge/carton-mcp/observation_worker_daemon.py` | 1418–1453 · 1915–1975 · 2645–2694 | the worker's own builder and its reconnect · the drain · the server start (fail-open) |
| `knowledge/carton-mcp/add_concept_tool.py` | 593–616 · 681–700 · 842–925 · 1512–1700 · 2045–2200 · 2751–2820 · 3867–4100 | `/proc` guard · the module connection · the queue (local only) · the helpers that BUILD AND CLOSE their own `KnowledgeGraphBuilder` (harmless: a holder's close is a no-op on the shared store) · `add_concept_tool_func` — THE SDK'S WRITE FRONT DOOR: with `CARTON_URL` set and not `SERVING` it is `call_carton("add_concept", …)` · `rename_concept_func` |
| `base/heaven-framework/heaven_base/tool_utils/graph_store.py` | 229–620 · 640–690 | `KuzuStore` · `close()` (a NO-OP on the process's shared store; `_really_close` only through `shutdown_embedded()`) · `embedded_store` (one store per path per process) · `make_store` (kuzu needs `KUZU_DB_PATH`; no remote store exists) |
| `base/heaven-framework/heaven_base/tool_utils/neo4j_utils.py` | 54–112 | a builder caches its store; `close()` closes the store it holds |
| `knowledge/carton-mcp/substrate_projector.py` · `carton_pathguard.py` | 52–56 · 319–332 · 2999–3045 · 68–80 · 121–155 | what an op does to the SERVER's process and disk (the env projector REFUSES when `carton_api.SERVING`; file projectors; the doc-root gate) |
| `application/carton-saas/metering/call_gate.py` · `carton_quota.py` | 18–40 · 48–65 · 119–160 | the gate; the limit and the env it counts with are SNAPSHOTTED at the gate's load (the box's start environment) — a write into the live process env lifts nothing |
| `base/soma-prolog/soma_prolog/vault.py` | 371–417 | SOMA's carton mirror imports `add_concept_tool_func` directly — an off-box writer, carried to the box by that function's own remote lane |
| `knowledge/carton-mcp/carton_utils.py` | 1628–1660 | `CartOnUtils.query_wiki_graph` — THE SDK'S READ FRONT DOOR: with `CARTON_URL` set and not `SERVING` it is `call_carton("query_wiki_graph", …)` |
| `not-unified/business-runtime/ribcage/ribcage/carton_store.py` | 61–100 | a program's `add_concept`/`query_wiki_graph` over the door — the concept, its relationships, its properties, the mode; no domain the store did not give it |
| `application/carton-saas/box/{supervisord.conf,Dockerfile,fly.toml,docker-compose.yml,provision.py}` · `control-plane/lib/provisioner/fly.ts` | whole | who sets `CARTON_HOST`/`CARTON_PORT`/`CARTON_KEY`/`CARTON_CALL_GATE`/`CARTON_URL` |
| tests: `test_carton_api.py` · `test_carton_transport.py` · `test_queue_submit.py` · `test_universal_write.py` · `base/heaven-framework/tests/test_graph_store.py` · `metering/test_call_gate.py` · ribcage `tests/test_carton_store.py` | whole | the gates below |

## COHERENCE SET — what moves when this moves

- an operation runs in the BOX's process: anything it reads from env, disk or process state is the box's. DO:[resolve
  every caller-side input in the TOOL and send it as a PARAM — `add_concept` reads a `desc_update_mode="path"` file
  and runs `_check_name_expectations` on the agent's machine; `observe_from_identity_pov` resolves `AGENT_IDENTITY`
  there and the op takes the param first; `query_cb_math` runs its passthrough in the TOOL — the CB shell and its key
  are the agent's machine's, the op touches no graph] NOT:[read `os.environ`/a caller path/a caller flag file inside an op — the
  SM-gate actor file, the frames file, the CB key file, `SOMA_OWL_DIR`, the GPS flag are still read box-side and owed
  the same move; the op REFUSES a `path` mode when `SERVING`]
- an operation mutates the BOX's process: `substrate_projector` type `env` refuses when `carton_api.SERVING`; the gate
  snapshots its limit and env at load, so the quota cannot be lifted from the wire. NOT:[a new op that writes
  `os.environ` · an op that writes server files a caller then expects on its own disk]
- one embedded store per path per process: a holder's `close()` is a NO-OP on the shared store (every
  `KnowledgeGraphBuilder` in the worker — the drain, `server_fastmcp._neo4j_conn`, `utils`, `get_shared_graph`,
  `rename_concept_func`'s own — resolves to it); only `shutdown_embedded()` closes it, at process exit.
  DO:[take `shared_connection` / `_graph_conn()`; a build-and-close helper is harmless but still redundant]
- ONE overflow per answer, the tool's: `_fmt` renders only; the tool wraps its result in `overflow_to_file` once; the
  file name carries microseconds and the pid. NOT:[an `overflow_to_file` inside an op or a render]
- an off-box writer has NO local lane on kuzu: `make_store` opens only an embedded file, `submit_queue_entry` writes
  only the local queue. The SDK's two front doors route THEMSELVES: `add_concept_tool_func` and
  `CartOnUtils.query_wiki_graph` are `call_carton(...)` when `CARTON_URL` is set and the process is not `SERVING`, so
  SOMA's vault mirror, the summarizers, dragonbones and Ribcage reach the box without knowing. NOT:[a program-side
  duplicate of that routing · a direct `submit_queue_entry` off the box]
- the enum = the registry = the tool list (`operations()`); a tool and its op share parameter NAMES; the op is the
  SDK's contract for a PROGRAM, so it may take as optional what the tool requires of an AGENT (`add_concept`'s four
  core relations and three domains: None = not given, no relationship built); `execute` validates against the OP
- env names, writer ↔ reader: `CARTON_HOST`/`CARTON_PORT`/`CARTON_KEY`/`CARTON_CALL_GATE` (server) ·
  `CARTON_URL`/`CARTON_KEY`/`CARTON_USER`/`CARTON_TIMEOUT_S` (client) · `CARTON_QUERY_BIND`/`CARTON_HOST_PORT` are
  compose-side port mapping only; a compose box binds `127.0.0.1` inside the container unless `CARTON_HOST=0.0.0.0`
- the docs that state this surface: this rule · `DESIGN.md` · `deployment/DESIGN.md` + its `22-seq-deploy-a-box.md` ·
  ribcage `DESIGN.md` · `carton-quota.md` · `carton-write-execution-boundary.md` · `knowledge/carton-mcp/docs/` mirrors
  — rewritten in the same commit

## THE CHANGE — what this feature is

- `carton_api.CartonOperation` names the 31 operations; `server_fastmcp.py` registers each beside its tool with
  `@_carton_api.operation(name)` — same signature, no rendering; a read answers data (`query_wiki_graph`: the facade's
  envelope, null columns kept), a write answers the SDK's text; the tool renders on the caller's side
- `execute(op, params)`: unknown name → 400 by name; params dropped of top-level `None`, validated by the operation's
  own arg model (`func_metadata` on the op); coroutine results run; `TextContent` → its text
- `call_carton`: no `CARTON_URL` → `execute` here; with one → `POST {url}/call`, `Bearer CARTON_KEY`,
  `X-Carton-User CARTON_USER`; refusal → `CartonError(status, message)`
- `serve_in_thread`: non-`127.0.0.1` bind with no key REFUSES TO START; key checked before the body (401); `/health`
  behind the key; gate `CARTON_CALL_GATE=module:function` → 402; an op's exception → 400 with its message; the real
  dispatcher sets `SERVING` (so `carton_management(restart_bg_server)` refuses in the worker) and
  `WRITE_OVERFLOW_FILES=False`
- the worker starts it on every backend (`CARTON_PORT`, default 8192); a failed bind leaves the drain running
- `server_fastmcp`: `CARTON_URL` set ⇒ no graph connection, no worker spawned
- NOT:[a second route beside `/call` and `/health` · a Cypher write pipe · an operation that is not a tool · logic in a
  tool body · an MCP server, a network MCP transport or a graph socket in the box]

## THE PROOF — per store, before and after

| store | measure | pass |
|---|---|---|
| the queue `$HEAVEN_DATA_DIR/carton_queue` | `add_concept` over the wire; list the server's and the client's dirs | exactly one new `.json` in the SERVER's dir; the client's dir empty (`test_carton_api.py` t_i) · an off-box `add_concept_tool_func` with `CARTON_URL` set lands nowhere — prove the off-box writer goes through `call_carton` instead |
| the embedded graph | two builders in one process: `b1._store is b2._store`; then `b2.close()` and `b1.execute_query("RETURN 1")`; then `shutdown_embedded()` | the same store; the other holder still reads after the close; closed only by the shutdown (`test_graph_store.py` ONE_PROCESS_HOLDS_ONE_EMBEDDED_STORE_PER_PATH) · served `rename_concept` (any outcome) followed by `query_wiki_graph` still answers rows |
| the socket :8192 | `test_carton_api.py` 9/9 | 401 no key / wrong key (before the body) · 400 unknown op by name · 400 an op's own message · 402 the gate · a non-local keyless bind refuses |
| the process env | `substrate_projector` `{"type":"env","var_name":"CARTON_MAX_NODES"}` over the wire (refused), then `CARTON_MAX_NODES` written in the serving process after the gate loaded, then a NEW `add_concept` at the limit | the projection refused; still 402 (`test_call_gate.py` writes 1000000 into the env after load and gets 402) |
| env names | `git grep` each name in the writer list and the reader list (excluding `CHANGELOG.md`, `docs/`, `context/journal/`, `system/rules/`) | every reader's name has a writer and the reverse; zero hits for a removed name in code or config |
| the registry | `operations()` (t_a) and per-op signature: parameter names equal to the tool's (t_h) | 31 = 31 = 31; no mismatch |
| the overflow file | a tool answer over 10k chars | ONE overflow file holding the WHOLE text, its pointer in the answer; two answers in one second never share a name |

Gates, run bare, read the counts: `test_carton_api.py` (9/9) · `test_carton_transport.py` (14/14) ·
`test_queue_submit.py` (5/5) · `test_universal_write.py` (6/6) · `base/heaven-framework/tests/test_graph_store.py`
(42/42) · `application/carton-saas/metering/test_call_gate.py` (9/9) · ribcage `tests.test_carton_store` (7/7).
`test_carton_api.py` needs `base/answer-refs` and `base/soma-sdk` on `PYTHONPATH`, or t_h/t_i fail at import.
"It imported" is not the gate. A source edit reaches nothing running without `pip install --no-deps` (carton-mcp AND
heaven-framework); the box needs its image rebuilt with `box/build-carton-box.sh`. End to end is a BOX, never a
loopback: its own compose project (`docker compose -p <name>`), `CARTON_HOST=0.0.0.0`, a `CARTON_KEY`, a published
port, driven from outside by `box/smoke/box_smoke_client.py` with the credentials in the environment — assert a null
column survives in `query_wiki_graph`'s rows and that it refuses a write verb.
