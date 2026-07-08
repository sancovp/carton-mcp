#!/usr/bin/env python3
"""
webbing_agent_worker — the WEBBING AGENT'S thin stream driver (the "cron in a file").

CLONED FROM `sophia_worker.py` (near-verbatim structure), retargeted to `webbing_agent.py` instead of
`docmirror-cohere`. Same lifecycle shape: a PID-locked daemon loop that ticks `webbing_agent.py --loop`
on an interval, gated DRY-by-default via a `live.flag` file (or `WEBBING_AGENT_LIVE=1`) exactly like
Sophia's `_live()` gate — Isaac decides when to flip it live, never the build.

`webbing_agent.py` OWNS the eligibility query + the SDNAC primitive; this worker is a THIN driver that
asks it (`--once --dry-run`) how many concepts are pending, then (if `_live()`) runs it
(`--loop --limit <cap>`) to process up to `cap` BATCHES in one invocation. `caught_up` = no eligible
concepts remain. `webbing_agent.py` is invoked as a MODULE (`python3 -m carton_mcp.webbing_agent`) —
NOT a bare console-script name — because it lives inside the `carton_mcp` package, not a `plugin/bin/`
CLI (unlike `docmirror-cohere`, which IS an installed bin script Sophia's worker calls by bare name).

STATE (so a health-check can poll): $HEAVEN_DATA_DIR/webbing_agent/state.json
  {caught_up, pending, processed_total, last_webbed, heartbeat, last_catch_up, mode}

NON-DESTRUCTIVE end-to-end: it only invokes `webbing_agent.py`, which only ADDS relationships/child
concepts and sets its own `webbed` scratch-lane property — it never rewrites an existing description,
never deletes. Bounded + fail-open: a slow/missing worker never hard-blocks anything that depends on it.
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

HD = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"))
DIR = HD / "webbing_agent"
STATE = DIR / "state.json"
PIDFILE = DIR / "worker.pid"
LOG = DIR / "worker.log"
DEFAULT_CAP = 1                    # ONE catch-up loop-invocation per tick (mirrors Sophia's cap=1)
DEFAULT_INTERVAL = 60
WEBBING_AGENT_MODULE = "carton_mcp.webbing_agent"   # invoked via `python3 -m`, not a bare bin name


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _log(msg):
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(f"{_now()}  {msg}\n")
    except Exception:
        pass


def _read_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def _write_state(**kw):
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        st = _read_state()
        st.update(kw)
        st["heartbeat"] = _now()
        STATE.write_text(json.dumps(st, indent=2))
    except Exception:
        pass


def _pending_concepts(model="MiniMax-M2.7-highspeed") -> tuple:
    """SINGLE SOURCE OF TRUTH for 'what is left' = webbing_agent's own `--once --dry-run`.
    webbing_agent.py OWNS the eligibility query; the worker does NOT duplicate it (DRY). Returns
    (count, []) — count<0 signals a query failure. FAIL LOUD, never silent (mirrors sophia_worker's
    fix for the fd-1 stdout leak: empty/unparseable stdout is a FAILURE, never silently '0 pending')."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", WEBBING_AGENT_MODULE, "--once", "--dry-run", "--model", model],
            capture_output=True, text=True, timeout=120)
        raw = (proc.stdout or "").strip()
        if not raw:
            _log(f"pending dry-run EMPTY stdout (rc={proc.returncode}); stderr head: {(proc.stderr or '')[:300]}")
            return -1, []
        try:
            data = json.loads(raw)
        except Exception as je:
            _log(f"pending dry-run UNPARSEABLE stdout ({je}); head: {raw[:300]}")
            return -1, []
        count = data.get("pending", -1)
        return count, []
    except Exception as e:
        import traceback
        _log(f"pending dry-run failed ({e})\n{traceback.format_exc()}")
        return -1, []


def _live() -> bool:
    if (DIR / "live.flag").exists():
        return True
    return os.environ.get("WEBBING_AGENT_LIVE", "").strip().lower() in ("1", "true", "on", "yes")


def catch_up_once(cap: int, model: str) -> dict:
    """Tick the atomization stream: process up to `cap` `--loop` invocations of `webbing_agent.py`
    (each invocation ratchets batch-by-batch until it either catches up or hits `cap`'s implicit limit
    of 1 loop-run per tick). DRY (process nothing) unless `_live()`."""
    n, _ = _pending_concepts(model)
    if n == 0:
        _write_state(caught_up=True, pending=0, last_catch_up=_now())
        return {"caught_up": True, "pending": 0, "processed": 0}
    if n < 0:
        _write_state(caught_up=False, error="pending dry-run failed", last_catch_up=_now())
        return {"error": "pending dry-run failed"}
    if not _live():
        _write_state(caught_up=True, mode="dry", pending_dry=n, last_catch_up=_now())
        _log(f"DRY: {n} concepts pending; would process up to {cap} loop-invocations")
        return {"dry": True, "pending": n}
    # LIVE: run the agent's own --loop (it ratchets batch-by-batch internally, with its own
    # no-progress guard); this tick just drives ONE such --loop call.
    _log(f"LIVE: processing up to {cap} loop-invocation(s) of {n} pending concepts")
    try:
        r = subprocess.run(
            [sys.executable, "-m", WEBBING_AGENT_MODULE, "--loop", "--limit", str(cap), "--model", model],
            capture_output=True, text=True, timeout=cap * 1200)
        res = json.loads(r.stdout or "{}")
        processed = res.get("webbed", 0)
        remaining = res.get("pending")
    except Exception as e:
        import traceback
        _log(f"loop tick failed ({e})\n{traceback.format_exc()}")
        _write_state(caught_up=False, error=str(e), last_catch_up=_now())
        return {"error": str(e)}
    if remaining is None:
        remaining, _ = _pending_concepts(model)
    st = _read_state()
    _write_state(caught_up=(remaining == 0), mode="live",
                 processed_total=st.get("processed_total", 0) + processed,
                 pending=remaining, last_catch_up=_now())
    return {"caught_up": remaining == 0, "processed": processed, "pending_after": remaining}


# ── daemon / lifecycle (identical shape to sophia_worker.py) ────────────────────────────────────────
def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0); return True
    except Exception:
        return False


def _running_pid():
    try:
        pid = int(PIDFILE.read_text().strip())
        return pid if _alive(pid) else None
    except Exception:
        return None


def daemon(interval, cap, model):
    if _running_pid():
        print("webbing_agent_worker: already running", file=sys.stderr); return 0
    DIR.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    _log(f"daemon start pid={os.getpid()} interval={interval} cap={cap}")
    try:
        while True:
            try:
                catch_up_once(cap, model)
            except Exception as e:
                _log(f"tick error ({e})")
            time.sleep(interval)
    finally:
        PIDFILE.unlink(missing_ok=True)
        _log("daemon exit")
    return 0


def ensure_running(cap, model, interval) -> int:
    if _running_pid():
        return _running_pid()
    DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, os.path.abspath(__file__), "--daemon",
           "--interval", str(interval), "--cap", str(cap), "--model", model]
    with open(LOG, "a") as lf:
        subprocess.Popen(cmd, stdout=lf, stderr=lf, start_new_session=True, stdin=subprocess.DEVNULL)
    _log("ensure: launched daemon")
    time.sleep(1)
    return _running_pid() or -1


def wait_caught_up(timeout: int) -> bool:
    deadline = time.time() + max(0, timeout)
    while time.time() < deadline:
        st = _read_state()
        if st.get("caught_up") is True and (st.get("pending") or 0) == 0:
            return True
        time.sleep(2)
    return False


def main(argv):
    p = argparse.ArgumentParser(prog="webbing_agent_worker")
    p.add_argument("--daemon", action="store_true")
    p.add_argument("--catch-up", action="store_true")
    p.add_argument("--ensure", action="store_true")
    p.add_argument("--ensure-and-wait", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    p.add_argument("--cap", type=int, default=DEFAULT_CAP)
    p.add_argument("--timeout", type=int, default=45)
    p.add_argument("--model", default="MiniMax-M2.7-highspeed")
    a = p.parse_args(argv[1:])

    if a.status:
        print(json.dumps(_read_state(), indent=2)); return 0
    if a.daemon:
        return daemon(a.interval, a.cap, a.model)
    if a.catch_up:
        print(json.dumps(catch_up_once(a.cap, a.model))); return 0
    if a.ensure:
        pid = ensure_running(a.cap, a.model, a.interval)
        print(f"webbing_agent_worker: running pid={pid}"); return 0
    if a.ensure_and_wait:
        ensure_running(a.cap, a.model, a.interval)
        ok = wait_caught_up(a.timeout)
        print(f"webbing_agent_worker: caught_up={ok} (timeout={a.timeout}s, fail-open)")
        return 0
    p.print_help(); return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
