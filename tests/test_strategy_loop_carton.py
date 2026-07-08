"""Step 3 proof (FULL LOOP) — the braid between step 2 (carton brain) and step 3 (SOMA strategy
deduction) closes through the live engine:

  SOMA strategy_deduction emits an llm_expert request for a universal (abstract) slot
    -> the carton llm-expert filler (soma_fillers.default_fillers(llm_call=...)) manufactures a fresh
       expert and returns its answer as the fill
    -> soma_sdk.resolve() merges the fill into the full observation set and re-derives
    -> the parked chain advances (soup -> code). Re-derivation IS the resume.

Concretely: an `observation_chain` instance is missing required has_chain_goal / has_plan_source
(string_value -> abstract; NOT in authorized_source -> deduced as llm_expert). A STUB llm_call (offline,
deterministic) fills them; resolve() advances the concept off soup with the llm-expert fills recorded.

This is the whole filling-strategies engine in miniature: dolce_category(built) -> strategy choice
(step 3) -> strategy-typed request -> carton brain acts (step 2) -> fill -> re-derive (resume).

Isolated daemon :8100, NEVER :8091. Requires the soma-prolog build WITH check_convention(strategy_deduction).
"""
import os
import sys
import json
import time
import signal
import shutil
import subprocess
import tempfile

from soma_sdk import resolve
from carton_mcp import soma_fillers

PORT = 8100
SOMA_URL = f"http://localhost:{PORT}/event"
STORE = "/tmp/test_strategy_loop_carton"
SOMA_OWL_SRC = "/home/GOD/gnosys-plugin-v2/base/soma-prolog/soma_prolog/soma.owl"

ok = {}


def node(name, rels):
    return {"name": name, "description": name,
            "relationships": [{"relationship": k, "related": [{"value": v, "type": t}]}
                              for k, v, t in rels]}


def start_daemon():
    shutil.rmtree(STORE, ignore_errors=True)
    os.makedirs(STORE, exist_ok=True)
    shutil.copy(SOMA_OWL_SRC, f"{STORE}/soma.owl")
    env = dict(os.environ,
               SOMA_QUADSTORE_PATH=f"{STORE}/store.sqlite3",
               SOMA_OWL_PATH=f"{STORE}/soma.owl",
               NEO4J_URI=os.environ.get("NEO4J_URI", "bolt://host.docker.internal:7687"))
    log = open(f"{STORE}/d.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "soma_prolog.api", "--port", str(PORT)],
                            env=env, stdout=log, stderr=subprocess.STDOUT)
    import urllib.request
    for _ in range(90):
        try:
            body = json.dumps({"source": "t", "observations": [node("ping", [("is_a", "string_value", "concept_ref")])], "domain": "default"}).encode()
            req = urllib.request.Request(SOMA_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=30).read()
            return proc, log
        except Exception:
            time.sleep(1)
    return proc, log


def main():
    proc, log = start_daemon()
    qd = tempfile.mkdtemp(prefix="strategy_loop_q_")
    calls = []

    def stub_llm(prompt):
        # A fresh LLM expert "generating" the universal — deterministic offline.
        calls.append(prompt)
        return "derived_universal_value"

    try:
        observations = [node("mychain", [("is_a", "observation_chain", "concept_ref")])]
        fillers = soma_fillers.default_fillers(llm_call=stub_llm, queue_dir=qd)

        result = resolve(observations, fillers, soma_url=SOMA_URL,
                         source="test_strategy_loop", domain="default")

        resolved_llm = {(r["gap"]) for r in result.resolved if r["authorization"] == "llm_expert"}
        ok["LOOP_llm_filled_chain_goal"] = "has_chain_goal" in resolved_llm
        ok["LOOP_llm_filled_plan_source"] = "has_plan_source" in resolved_llm
        ok["LOOP_llm_expert_was_invoked"] = len(calls) >= 1
        ok["LOOP_advanced_off_soup"] = result.final.statuses.get("mychain") not in ("soup", None)
        ok["LOOP_no_llm_expert_pending"] = all(r.authorization != "llm_expert" for r in result.pending)
        ok["LOOP_rounds_ran"] = result.rounds >= 1

        print("=== FULL LOOP: observation_chain — strategy_deduction(llm_expert) -> carton fills -> advance ===")
        print("  final status:", result.final.statuses.get("mychain"))
        print("  rounds:", result.rounds, "| llm_expert invocations:", len(calls))
        print("  resolved:", [(r["gap"], r["authorization"]) for r in result.resolved])
        print("  pending:", [(r.gap, r.authorization) for r in result.pending])
    finally:
        try:
            proc.send_signal(signal.SIGTERM); proc.wait(timeout=10)
        except Exception:
            try: proc.kill()
            except Exception: pass
        log.close()

    print("\nCHECKS:")
    for k, v in ok.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}={v}")
    n = sum(1 for v in ok.values() if v)
    print(f"\nVERDICT: {n}/{len(ok)} "
          + ("FILLING-STRATEGIES LOOP CLOSED (SOMA emits llm_expert -> carton fills -> re-derive advances)"
             if (ok and all(ok.values())) else "GAP FOUND — inspect above"))
    sys.exit(0 if (ok and all(ok.values())) else 1)


if __name__ == "__main__":
    main()
