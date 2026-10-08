#!/usr/bin/env python3
"""Probe what is ACTUALLY running and write the measured result onto Gnosys_System.

WHY THIS EXISTS (measured 2026-08-25). Runtime status used to live as frozen prose in CLAUDE.md,
which is loaded verbatim every session and cannot update itself -- so it went stale silently and was
then quoted back as current. That was fixed by moving status to PROPERTIES on the `Gnosys_System`
concept, where `set_properties` can change it. But nothing MEASURED those properties: they were a
snapshot someone typed, carrying a `status_measured_at` stamp that made them LOOK measured.

The failure that proves it: on 2026-08-25 the lane read `chroma_semantic_search: down` while the
chroma daemon answered HTTP 200. Two days wrong, and the next agent to "read the authority" would
have repeated it. That is the same disease the property lane was created to cure, one layer down --
an editable claim is still a claim.

So this probe HITS EACH SUBSYSTEM and writes back what it found. After it runs, "is everything on"
is answered by RUNNING something, not by trusting a stamp.

THE DESIGN RULE THAT MATTERS: a check this cannot genuinely perform reports `unprobed` WITH A REASON.
It never guesses, and it never carries a previous value forward as if it were fresh. A probe that
fabricates is strictly worse than the stale snapshot it replaces, because it launders a guess through
a mechanism that looks like measurement. Anything marked `unprobed` is an honest gap and a TODO for
whoever can build that check -- see UNPROBED at the bottom.

USAGE
    python3 gnosys_status_probe.py            # probe and PRINT; touches nothing
    python3 gnosys_status_probe.py --write    # probe, print, and write onto Gnosys_System

The write lane is deliberate: properties are the SCRATCH lane (the-property-layer-doctrine), which is
a synchronous direct write, not the async observation queue -- so writing them straight to neo4j is
the sanctioned mechanism, not a bypass.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

CONCEPT = "Gnosys_System"
HEAVEN = os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")

# SOMA answers an empty /event by running the whole Prolog pipeline, which is SECONDS, not
# milliseconds -- 24.97s measured 2026-09-04 against a 227k-triple store. This is the liveness
# budget for that one route; every other check keeps _http's fast 4s default, because every other
# check really is a health endpoint. Env-overridable so a slower box can raise it without an edit.
SOMA_EVENT_TIMEOUT_S = int(os.environ.get("GNOSYS_PROBE_SOMA_TIMEOUT_S", "60"))


def _http(url, method="GET", body=None, timeout=4):
    """Return (status_code, reason). code is None when nothing answered.

    The exception is CAUGHT ON PURPOSE -- an unreachable service is a STATUS, not a crash; this tool
    exists to turn that into a reported value. But the reason is KEPT rather than discarded, because
    "down" without a why is barely more useful than the stale snapshot this replaces: connection
    refused, timed out, and DNS failure are three different problems with three different fixes.
    """
    try:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, "ok"
    except urllib.error.HTTPError as e:
        return e.code, "answered"   # a 4xx/5xx still means the service is UP
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _port_open(host, port, timeout=3):
    """Return (open, reason) -- same discipline as _http: keep the why."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _pgrep(pattern):
    """True if a process matches. Bracket-trick so the pgrep never matches itself."""
    br = f"[{pattern[0]}]{pattern[1:]}"
    try:
        out = subprocess.run(["pgrep", "-af", br], capture_output=True, text=True, timeout=5)
        return bool(out.stdout.strip())
    except Exception:
        return False


# ── the checks. each returns (value, detail) ────────────────────────────────────────────────────

def check_soma():
    """Port first, then the real ingest route -- the SAME three-outcome discipline check_neo4j
    already uses, and for the same reason: a validator that is UP but SLOW is not a validator that
    is DOWN.

    MEASURED 2026-09-04: SOMA answered an empty /event POST in 24.97s while holding 227k triples,
    so the 4s _http default read a perfectly healthy validator as "down". The frozen HUD then said
    live-while-dead for chroma and the fresh one said dead-while-live for SOMA, and the false
    "down" nearly triggered a relaunch of a running daemon -- which soma_daemon_dead_policy
    explicitly reserves for a validator that is actually dead. A timeout is not a diagnosis.
    """
    ok, why = _port_open("localhost", 8091)
    if not ok:
        return "down", f"nothing listening on :8091 ({why})"
    code, why = _http("http://localhost:8091/event", "POST",
                      {"source": "status_probe", "observations": []}, timeout=SOMA_EVENT_TIMEOUT_S)
    if code is None:
        return "degraded", (f"listening on :8091 but /event did not answer in "
                            f"{SOMA_EVENT_TIMEOUT_S}s ({why}) -- UP but not serving, NOT dead")
    return "live", f"POST /event -> HTTP {code}"


def check_chroma():
    code, why = _http("http://localhost:8190/health")
    if code is None:
        return "down", f"nothing answered on :8190 ({why})"
    return "live", f"GET /health -> HTTP {code}"


def check_neo4j():
    host = os.environ.get("NEO4J_HOST", "host.docker.internal")
    ok, why = _port_open(host, 7687)
    if not ok:
        return "down", f"bolt {host}:7687 unreachable ({why})"
    try:
        from neo4j import GraphDatabase
        d = GraphDatabase.driver(f"bolt://{host}:7687",
                                 auth=(os.environ.get("NEO4J_USER", "neo4j"),
                                       os.environ.get("NEO4J_PASSWORD", "password")))
        with d.session() as s:
            n = s.run("MATCH (x:Wiki) RETURN count(x) AS c").single()["c"]
        d.close()
        return "live", f"bolt up, {n} :Wiki nodes"
    except Exception as e:
        return "degraded", f"port open but query failed: {type(e).__name__}"


def check_observation_daemon():
    return ("live", "process found") if _pgrep("observation_worker_daemon") \
        else ("down", "no observation_worker_daemon process")


def check_omnisanc():
    p = os.path.join(HEAVEN, ".omnisanc_disabled")
    if os.path.exists(p):
        return "disabled_in_this_container", f"kill-switch present at {p}"
    return "enabled_in_this_container", "no kill-switch file (PER-CONTAINER: says nothing about others)"


def check_uniqueness_constraint():
    """The 2026-08-25 shattering repair. If this is ever absent, universals can re-shatter."""
    host = os.environ.get("NEO4J_HOST", "host.docker.internal")
    try:
        from neo4j import GraphDatabase
        d = GraphDatabase.driver(f"bolt://{host}:7687",
                                 auth=(os.environ.get("NEO4J_USER", "neo4j"),
                                       os.environ.get("NEO4J_PASSWORD", "password")))
        with d.session() as s:
            names = [r.get("name") for r in s.run("SHOW CONSTRAINTS")
                     if "Wiki" in str(r.get("labelsOrTypes")) and r.get("type") == "UNIQUENESS"]
            dupes = s.run("MATCH (n:Wiki) WHERE n.n IS NOT NULL WITH n.n AS x, count(*) AS c "
                          "WHERE c > 1 RETURN count(x) AS d").single()["d"]
        d.close()
        if names and dupes == 0:
            return "enforced", f"{names[0]} present, 0 duplicated names"
        if names:
            return "degraded", f"constraint present but {dupes} duplicated names exist"
        return "absent", f"NO uniqueness constraint on :Wiki -- {dupes} duplicated names"
    except Exception as e:
        return "unprobed", f"could not reach the graph: {type(e).__name__}"


CHECKS = {
    "soma_validator":        check_soma,
    "chroma_semantic_search": check_chroma,
    "carton_store":          check_neo4j,
    "observation_daemon":    check_observation_daemon,
    "omnisanc":              check_omnisanc,
    "wiki_uniqueness":       check_uniqueness_constraint,
}

# HONEST GAPS. These are NOT probed, and they are listed rather than defaulted so that nobody reads
# a fabricated value as a measurement. Each needs a real signal before it can join CHECKS above.
#   dragonbones_ec_emission -- needs a way to ask whether the output-style injector is attached to
#       the running agent. There is no endpoint or file that answers this today.
#   persona_output_frame    -- same shape: a property of the agent's own prompt assembly.
#   context_alignment       -- CA shares this neo4j, so "is it up" is answered by carton_store; what
#       is NOT answerable here is whether a given container has it REGISTERED as an MCP, which is
#       per-container config, not a global fact.
UNPROBED = {
    "dragonbones_ec_emission": "no signal exists for whether the output-style injector is attached",
    "persona_output_frame":    "property of the agent's own prompt assembly; not externally visible",
    "context_alignment":       "liveness = carton_store; per-container MCP registration is not a global fact",
}


def probe():
    return {k: fn() for k, fn in CHECKS.items()}


def write_back(results, stamp):
    host = os.environ.get("NEO4J_HOST", "host.docker.internal")
    from neo4j import GraphDatabase
    d = GraphDatabase.driver(f"bolt://{host}:7687",
                             auth=(os.environ.get("NEO4J_USER", "neo4j"),
                                   os.environ.get("NEO4J_PASSWORD", "password")))
    props = {k: v for k, (v, _) in results.items()}
    props["status_measured_at"] = stamp
    props["status_measured_by"] = "gnosys_status_probe.py"
    props["status_unprobed"] = json.dumps(UNPROBED)
    with d.session() as s:
        # MERGE, not CREATE: the concept must already exist, and after the 2026-08-25 uniqueness
        # constraint a stray CREATE here would be refused anyway -- which is the constraint doing
        # exactly its job.
        s.run("MERGE (g:Wiki {n:$n}) SET g += $props", {"n": CONCEPT, "props": props})
    d.close()
    return props


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help=f"write the measured values onto {CONCEPT} (default: print only)")
    args = ap.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = probe()

    width = max(len(k) for k in list(CHECKS) + list(UNPROBED))
    print(f"GNOSYS STATUS — measured {stamp}\n")
    for k, (v, detail) in results.items():
        print(f"  {k:<{width}}  {v:<28} {detail}")
    print()
    for k, why in UNPROBED.items():
        print(f"  {k:<{width}}  {'UNPROBED':<28} {why}")

    if args.write:
        write_back(results, stamp)
        print(f"\nwritten onto {CONCEPT} (status_measured_at={stamp})")
    else:
        print(f"\n(print only — nothing written. Re-run with --write to update {CONCEPT}.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
