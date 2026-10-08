Isaac verbatim: *"The circuit breaker just has to be on add_concept it has to like actually tell them
when it errors to stop calling and report this to the user. then heaven agents will use block reports."*

One capability, one module: the breaker lives in `carton_breaker.py`, and `add_concept_tool.py` carries
ONE guarded call at the top of `add_concept_tool_func` — after the empty-relationships check, BEFORE the
quota gate and the queue write. It does NOT touch the guarded optional-fields capability.

## States

| component | status | note |
|---|---|---|
| `carton_breaker.py` | **BUILT + 12/12 tests + wiring-proven** | file-backed shared state (`$HEAVEN_DATA_DIR/carton_breaker_state.json`, override `CARTON_BREAKER_STATE_PATH`); pure `evaluate`/`effective_cooldown_s`/`stop_message` cores with injectable probe_fn/env/now_fn; atomic state writes; corrupt state file = fresh CLOSED (logged, never a crash) |
| `add_concept_tool.py` wiring | EDITED (one call, after the empty-relationships check, BEFORE `check_quota`) | does NOT touch the guarded optional-fields capability |
| wiring proof (isolated subprocess, REAL dead DB `bolt://127.0.0.1:1`, tmp queue dir) | **VERIFIED 2026-07-19** | call 1 returns the STOP-AND-REPORT actuator + "NOT written"; call 3 logs `CLOSED -> OPEN`; call 4 fails fast with zero DB contact; **zero** queue files written during the outage (the issue-61 dead-letter feeder, closed at the front door) |
| live surface (real `mcp__carton__add_concept` after `reconnect_mcp carton`) | **VERIFIED 2026-07-19** | healthy path queues normally; state file shows `failures: 0, last_success` set; e2e harness `night_missing_days` 1/1 PASS after install |
| heaven-agent pickup | no restart required | CAVE agents construct a fresh BaseHeavenAgent per fire; their MCP subprocesses import the INSTALLED package → the next fire serves the breaker |

THE ACTUATOR IS THE RETURN VALUE. On any probe failure `add_concept` RETURNS the stop message; it never
raises and never leaks the raw `("Failed to connect to Neo4j…", None)` tuple. The message carries the
error, "This concept was NOT written", "STOP calling carton tools", "REPORT THIS TO THE USER", and
"heaven agents: write a BLOCK REPORT". Queue NOTHING while the database is down — a silent queue write
dead-letters.

THRESHOLD → OPEN → FAIL FAST. `CARTON_BREAKER_THRESHOLD` (3) consecutive failures open the breaker, and
open calls return the message with ZERO database contact.

EXPONENTIAL COOLDOWN. `CARTON_BREAKER_COOLDOWN_S` (120s) doubles per re-open, capped at
`CARTON_BREAKER_MAX_COOLDOWN_S` (1800s); half-open probes exactly once.

SHARED STATE IS A FILE — `$HEAVEN_DATA_DIR/carton_breaker_state.json`, override
`CARTON_BREAKER_STATE_PATH`. Every process calling `add_concept_tool_func` (the MCP server, per-agent
stdio MCP subprocesses, daemons) shares the OPEN state instead of independently hammering a dead
database. Writes are atomic, and a corrupt state file means a fresh CLOSED — logged, never a crash.

KEEP THE HEALTHY PATH CHEAP. One `RETURN 1` probe per `CARTON_BREAKER_PROBE_TTL_S` (15s) window,
TTL-cached on success; an outage beginning inside the window is caught by the first probe after it.

ONE LOG LINE PER STATE CHANGE — `CLOSED -> OPEN` at WARNING, `OPEN -> CLOSED` at INFO; sub-threshold
failures at DEBUG. Be loud on garbage config: a broken threshold must never silently disable the breaker.

Dev-flow, and NEVER edit one place only. Touching `check_breaker` / `evaluate` / `stop_message` / `_probe`
/ the state-file shape, or the one call site in `add_concept_tool_func` → edit `carton_breaker.py` and the
call site coherently, then the gate: `python3 test_carton_breaker.py` all 12 green — run it as a SCRIPT,
because the repo root IS the `carton_mcp` package and pytest-from-the-dir breaks on package inference —
AND the wiring proof (dead-port subprocess: stop message, zero queue files, OPEN at threshold) AND
`py_compile` on both files.

If your change goes anywhere NEAR the optional-fields params or `merge_optional_domain_fields`, STOP:
that is the `edit-add-concept-optional-fields` dev-flow. If it goes near `check_quota`, mind the
`carton-quota` dev-flow.

Installed-package law: a source edit without `pip install --no-deps` changes nothing running; your
session's carton MCP needs `reconnect_mcp carton`; heaven agents pick it up on their next construction,
with no restart required, because CAVE agents construct a fresh BaseHeavenAgent per fire and their MCP
subprocesses import the INSTALLED package.

Known bounds, named and accepted: the breaker guards `add_concept` ONLY. Read tools (`query_wiki_graph`,
`get_concept`, …) still surface their own `{"success": False, "error": ...}` on outage. Daemon tick loops
have their own retry lane — a separate capability, not this module.
