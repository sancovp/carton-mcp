"""Neo4j circuit breaker for add_concept — sancrev issue 62.

Isaac's ruling (2026-07-18, verbatim): "The circuit breaker just has to be on
add_concept it has to like actually tell them when it errors to stop calling and
report this to the user. then heaven agents will use block reports."

One capability, one module (this repo's convention — the carton_kv /
carton_kv / split_content precedent): the breaker logic lives here;
`add_concept_tool.py` gains ONE guarded call at the top of the
`add_concept_tool_func` chokepoint (the audited single path every
concept-creation caller passes through), BEFORE the quota gate and the queue
write.

WHY THIS EXISTS (the 2026-07-18 outage chain, issues 60/61/62): when neo4j went
down, add_concept kept SUCCEEDING silently (its write is a queue FILE) while the
daemon dead-lettered the queued writes, and every neo4j-touching tool leaked the
raw "Failed to connect to Neo4j: ..." error into agent surfaces — and the agents
kept firing turns against the dead store. The breaker converts that into:

  1. PROBE — a cheap `RETURN 1` against the same connection add_concept uses,
     TTL-cached on success so the healthy path pays ~one probe per
     CARTON_BREAKER_PROBE_TTL_S window, not per call.
  2. TELL — on ANY probe failure the call returns the STOP-AND-REPORT message
     (the actuator) instead of silently queueing a write that would dead-letter.
     The concept is NOT queued.
  3. OPEN — after CARTON_BREAKER_THRESHOLD consecutive failures the breaker
     OPENs: calls fail fast WITHOUT contacting the database for a cooldown that
     grows exponentially on each re-open (CARTON_BREAKER_COOLDOWN_S base,
     doubling per re-open, capped at CARTON_BREAKER_MAX_COOLDOWN_S).
  4. HALF-OPEN — after the cooldown elapses, the next call probes once:
     success closes the breaker (state reset), failure re-opens it with a
     doubled cooldown.

State is a FILE (`$HEAVEN_DATA_DIR/carton_breaker_state.json`, override
CARTON_BREAKER_STATE_PATH) per state-must-be-files: many processes call
add_concept_tool_func (the carton MCP server, per-agent stdio MCP subprocesses,
daemons, direct importers) and they must share the OPEN state instead of each
independently hammering a dead database. Writes are atomic (tmp + os.replace).
A missing/corrupt state file is treated as a fresh CLOSED state (logged loudly,
never a crash — the breaker must not be able to take down the write path).

Exactly ONE log line per breaker STATE CHANGE (CLOSED->OPEN at WARNING,
OPEN->CLOSED at INFO), per the ruled design; individual sub-threshold failures
log at DEBUG only.
"""

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 3          # consecutive failures before OPEN
DEFAULT_COOLDOWN_S = 120.0     # base fail-fast window once OPEN
DEFAULT_MAX_COOLDOWN_S = 1800.0  # cap for the exponential re-open growth
DEFAULT_PROBE_TTL_S = 15.0     # healthy-path probe cache window

_FRESH_STATE = {
    "failures": 0,       # consecutive probe failures
    "opened_at": None,   # epoch seconds when the breaker OPENed (None = not open)
    "reopens": 0,        # times the breaker re-opened from half-open (drives backoff)
    "last_error": None,  # text of the most recent probe failure
    "last_success": None,  # epoch seconds of the most recent successful probe
}


def _env_float(env, key, default):
    raw = (env.get(key) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(
            f"{key} must be a number, got {raw!r} — refusing to guess "
            "(a broken breaker config must not silently disable the breaker)"
        )


def state_path(env=None) -> Path:
    env = os.environ if env is None else env
    override = (env.get("CARTON_BREAKER_STATE_PATH") or "").strip()
    if override:
        return Path(override)
    return Path(env.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "carton_breaker_state.json"


def _load_state(path: Path) -> dict:
    """Read the shared state file; a missing or corrupt file is a fresh CLOSED
    state (logged — never a crash: the breaker must never kill the write path)."""
    try:
        with open(path) as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError(f"state is {type(raw).__name__}, expected object")
        state = dict(_FRESH_STATE)
        state.update({k: raw.get(k, v) for k, v in _FRESH_STATE.items()})
        return state
    except FileNotFoundError:
        return dict(_FRESH_STATE)
    except Exception as e:
        logger.warning(
            f"carton breaker: unreadable state file {path} ({e}) — treating as CLOSED",
            exc_info=True,
        )
        return dict(_FRESH_STATE)


def _save_state(path: Path, state: dict) -> None:
    """Atomic write (tmp + os.replace) so concurrent readers never see torn JSON.
    Failure to persist is logged loudly but never raises — same never-kill-the-
    write-path discipline as _load_state."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning(
            f"carton breaker: could not persist state to {path}: {e}", exc_info=True)


def effective_cooldown_s(state: dict, base_s: float, max_s: float) -> float:
    """PURE. The OPEN fail-fast window: base doubled per re-open, capped.
    reopens=0 -> base; 1 -> 2x; 2 -> 4x; ... never above max_s."""
    return min(base_s * (2 ** int(state.get("reopens") or 0)), max_s)


def evaluate(state: dict, now_s: float, base_cooldown_s: float, max_cooldown_s: float) -> tuple:
    """PURE. Classify the breaker phase from state + clock.

    Returns (phase, remaining_s):
      ("closed", 0.0)      — not open; calls probe normally.
      ("open", remaining)  — open and inside the cooldown; fail fast, NO probe.
      ("half_open", 0.0)   — open but the cooldown elapsed; probe once.
    """
    opened_at = state.get("opened_at")
    if opened_at is None:
        return "closed", 0.0
    cooldown = effective_cooldown_s(state, base_cooldown_s, max_cooldown_s)
    elapsed = now_s - float(opened_at)
    if elapsed < cooldown:
        return "open", cooldown - elapsed
    return "half_open", 0.0


def stop_message(state: dict, phase: str, retry_in_s: float) -> str:
    """PURE. The actuator — the message add_concept returns INSTEAD of writing.
    Built from Isaac's ruling: tell the agent the error happened, to STOP
    calling, and to REPORT to the user; heaven agents use block reports."""
    err = state.get("last_error") or "connection failed"
    n = int(state.get("failures") or 0)
    lines = [
        f"🔌 CARTON CIRCUIT BREAKER — neo4j is UNREACHABLE ({err}).",
        "This concept was NOT written (nothing was queued).",
        "STOP calling carton tools now — do not retry in a loop.",
        "REPORT THIS TO THE USER in your next reply: the CartON knowledge-graph "
        "database is unreachable, so graph reads and writes are blocked.",
        "If you are a heaven agent, write a BLOCK REPORT (WriteBlockReportTool) "
        "and end your turn instead of continuing.",
    ]
    if phase == "open":
        lines.append(
            f"(breaker OPEN after {n} consecutive connection failures — failing fast "
            f"without contacting the database; automatic retry in ~{int(retry_in_s)}s.)"
        )
    else:
        lines.append(f"({n} consecutive connection failure(s) recorded.)")
    return "\n".join(lines)


def _probe(shared_connection=None) -> tuple:
    """Attempt one cheap `RETURN 1` against the SAME connection add_concept
    uses: the caller's shared_connection when given (the MCP passes its
    _neo4j_conn), else the add_concept module connection (which returns None
    when connection creation itself fails). Returns (ok, error_text_or_None)."""
    try:
        graph = shared_connection
        if graph is None:
            from carton_mcp.add_concept_tool import _get_module_connection
            graph = _get_module_connection()
        if graph is None:
            return False, "no neo4j connection available (connection creation failed)"
        graph.execute_query("RETURN 1 AS ok", {})
        return True, None
    except Exception as e:
        # The failure detail is DATA here (it rides into state.last_error and the
        # actuator message); the full traceback still goes to the log for forensics.
        logger.debug(f"carton breaker: probe raised: {e}", exc_info=True)
        return False, f"{type(e).__name__}: {e}"


def check_breaker(shared_connection=None, env=None, probe_fn=None, now_fn=None) -> "str | None":
    """The gate. Returns None when the database is reachable (add_concept
    proceeds), or the STOP-AND-REPORT actuator message when it is not.

    Phases (state shared via the state FILE across all calling processes):
      CLOSED    — probe (TTL-cached on success). ok -> None; fail -> record the
                  failure (threshold crossing OPENs the breaker, one WARNING log
                  line) and return the actuator message.
      OPEN      — inside the cooldown: return the actuator message immediately,
                  ZERO database contact.
      HALF-OPEN — cooldown elapsed: probe once. ok -> CLOSED (state reset, one
                  INFO log line) and None; fail -> re-OPEN with doubled cooldown
                  (one WARNING log line) and the actuator message.

    probe_fn/env/now_fn are injectable for tests; production uses the live
    probe, os.environ, and time.time.
    """
    env = os.environ if env is None else env
    now_fn = time.time if now_fn is None else now_fn
    probe_fn = _probe if probe_fn is None else probe_fn

    threshold = int(_env_float(env, "CARTON_BREAKER_THRESHOLD", DEFAULT_THRESHOLD))
    base_cooldown = _env_float(env, "CARTON_BREAKER_COOLDOWN_S", DEFAULT_COOLDOWN_S)
    max_cooldown = _env_float(env, "CARTON_BREAKER_MAX_COOLDOWN_S", DEFAULT_MAX_COOLDOWN_S)
    probe_ttl = _env_float(env, "CARTON_BREAKER_PROBE_TTL_S", DEFAULT_PROBE_TTL_S)

    path = state_path(env)
    state = _load_state(path)
    now_s = float(now_fn())

    phase, remaining = evaluate(state, now_s, base_cooldown, max_cooldown)

    if phase == "open":
        return stop_message(state, "open", remaining)

    # CLOSED healthy-path TTL: a recent successful probe stands in for a new one,
    # so bursts of add_concept calls pay ~one probe per TTL window. (An outage that
    # begins inside the window is caught by the first probe after it — bounded
    # staleness, matching the quota gate's TTL-count discipline.)
    if phase == "closed" and probe_ttl > 0:
        last_ok = state.get("last_success")
        if last_ok is not None and (now_s - float(last_ok)) < probe_ttl and not state.get("failures"):
            return None

    ok, err = probe_fn(shared_connection)

    if ok:
        was_open = state.get("opened_at") is not None
        had_failures = bool(state.get("failures"))
        state.update(dict(_FRESH_STATE))
        state["last_success"] = now_s
        _save_state(path, state)
        if was_open:
            logger.info("carton breaker: OPEN -> CLOSED (neo4j reachable again)")
        elif had_failures:
            logger.info("carton breaker: failure streak reset (neo4j reachable)")
        return None

    # Probe failed.
    state["failures"] = int(state.get("failures") or 0) + 1
    state["last_error"] = err
    if phase == "half_open":
        state["opened_at"] = now_s
        state["reopens"] = int(state.get("reopens") or 0) + 1
        _save_state(path, state)
        logger.warning(
            f"carton breaker: HALF-OPEN -> OPEN (re-open #{state['reopens']}, "
            f"cooldown {effective_cooldown_s(state, base_cooldown, max_cooldown):.0f}s): {err}"
        )
        return stop_message(state, "open",
                            effective_cooldown_s(state, base_cooldown, max_cooldown))
    if state["failures"] >= threshold and state.get("opened_at") is None:
        state["opened_at"] = now_s
        _save_state(path, state)
        logger.warning(
            f"carton breaker: CLOSED -> OPEN ({state['failures']} consecutive "
            f"connection failures, cooldown "
            f"{effective_cooldown_s(state, base_cooldown, max_cooldown):.0f}s): {err}"
        )
        return stop_message(state, "open",
                            effective_cooldown_s(state, base_cooldown, max_cooldown))
    _save_state(path, state)
    logger.debug(f"carton breaker: probe failure {state['failures']}/{threshold}: {err}")
    return stop_message(state, "closed", 0.0)
