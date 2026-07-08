"""Step 2 proof — the CARTON BRAIN: real fillers for SOMA's authorization-typed requests.

Proves carton_mcp.soma_fillers end-to-end:
  UNIT (no daemon): the filler table + the durable human-queue park + the llm-expert manufacture
    (with a deterministic stub) + park_fillable_requests (the daemon's passive-leg library fn).
  E2E (isolated SOMA daemon, NEVER :8091): soma_sdk.resolve() over a REAL SOMA verdict —
    invoice_processing is_a process surfaces human_domain_expert requests; the human filler durably
    PARKS each (a file lands in the queue) and returns None, so resolve() settles with those requests
    PENDING, resolved=[], and the concept still soup. That is filling-strategy 2 (ask-human) working
    against the live engine: re-derivation is the resume; a human answers later as a new event.

NOTE on filling-strategy 3 (llm_expert): SOMA's FIXED authorized_source/3 emits only human_* and
system_deduction today — it does NOT emit llm_expert (that emission is build-order step 3, the
dolce-driven strategy choice universal->llm). So the llm_expert filler is proven here at the UNIT level
(a synthetic LlmFillableRequest + a stub llm_call -> the fill); the full resolve() loop emitting +
filling an llm_expert request waits for step 3.
"""
import os
import sys
import json
import time
import signal
import shutil
import subprocess
import tempfile

# soma_sdk is installed in this env (carton add_concept_tool imports it).
from soma_sdk import (
    FillableRequest, LlmFillableRequest, build_fillable_request, resolve,
)

# The module under test is carton_mcp.soma_fillers (package-dir maps carton_mcp -> the repo root).
# Run after `pip install --no-deps knowledge/carton-mcp` so this is the real installed surface.
from carton_mcp import soma_fillers

PORT = 8097
SOMA_URL = f"http://localhost:{PORT}/event"
STORE = "/tmp/test_soma_fillers_store"
SOMA_OWL_SRC = "/home/GOD/gnosys-plugin-v2/base/soma-prolog/soma_prolog/soma.owl"

ok = {}


# ---------------------------------------------------------------------------
# UNIT — no daemon
# ---------------------------------------------------------------------------

def unit_tests():
    qd = tempfile.mkdtemp(prefix="soma_fillers_q_")

    # default_fillers — the table keyed by authorization, observing_agent ABSENT.
    fillers = soma_fillers.default_fillers(queue_dir=qd)
    ok["UNIT_table_has_human_authorities"] = all(
        a in fillers for a in ("human_domain_expert", "human_architect", "human_end_user")
    )
    ok["UNIT_table_has_system_deduction"] = "system_deduction" in fillers
    ok["UNIT_table_has_llm_expert"] = "llm_expert" in fillers
    ok["UNIT_observing_agent_absent"] = "observing_agent" not in fillers

    # human filler — parks (a file lands) and returns None.
    hreq = build_fillable_request("human_domain_expert", "invoice_processing", "has_steps",
                                  "template_sequence", "the steps are reality")
    before = set(os.listdir(qd))
    hres = fillers["human_domain_expert"](hreq)
    after = set(os.listdir(qd))
    ok["UNIT_human_returns_none"] = hres is None
    ok["UNIT_human_parked_a_file"] = len(after - before) == 1
    # the parked file is a faithful, durable record
    parked_path = os.path.join(qd, (after - before).pop())
    rec = json.load(open(parked_path))
    ok["UNIT_park_record_faithful"] = (
        rec["authorization"] == "human_domain_expert" and rec["concept"] == "invoice_processing"
        and rec["gap"] == "has_steps" and rec["status"] == "pending"
    )

    # system_deduction filler — returns None (SOMA deduces on re-derive).
    sreq = build_fillable_request("system_deduction", "invoice_processing", "dolce_category")
    ok["UNIT_system_deduction_none"] = fillers["system_deduction"](sreq) is None

    # llm_expert filler — a stub LLM that returns a value -> a fill triple.
    captured = {}

    def stub_llm(prompt):
        captured["prompt"] = prompt
        return "perdurant"

    llm_fillers = soma_fillers.default_fillers(llm_call=stub_llm, queue_dir=qd)
    lreq = LlmFillableRequest(concept="some_universal", gap="dolce_category",
                              expected_type="concept_ref", reason="abstract is LLM-fillable")
    lres = llm_fillers["llm_expert"](lreq)
    ok["UNIT_llm_expert_fills"] = (
        isinstance(lres, tuple) and lres[0] == "dolce_category" and lres[1] == "perdurant"
        and lres[2] == "concept_ref"
    )
    ok["UNIT_llm_prompt_has_gap"] = "dolce_category" in captured.get("prompt", "")

    # llm_expert escalates to human when the expert says NEEDS_HUMAN -> None (no fill).
    def stub_llm_escalate(prompt):
        return soma_fillers.NEEDS_HUMAN

    esc_fillers = soma_fillers.default_fillers(llm_call=stub_llm_escalate, queue_dir=qd)
    ok["UNIT_llm_expert_escalates_none"] = esc_fillers["llm_expert"](lreq) is None

    # llm_expert with NO llm_call wired -> the human (park) fallback (nothing dropped).
    nofill = soma_fillers.default_fillers(queue_dir=qd)
    ok["UNIT_llm_expert_no_llm_parks"] = nofill["llm_expert"](lreq) is None

    # park_fillable_requests — the daemon's passive leg. observing_agent dict is SKIPPED.
    qd2 = tempfile.mkdtemp(prefix="soma_fillers_q2_")
    concepts = [{
        "name": "invoice_processing",
        "fillable_requests": [
            {"authorization": "human_domain_expert", "concept": "invoice_processing",
             "gap": "has_steps", "expected_type": "template_sequence", "reason": "reality"},
            {"authorization": "system_deduction", "concept": "invoice_processing",
             "gap": "dolce_category", "expected_type": "", "reason": "deduced"},
            {"authorization": "observing_agent", "concept": "invoice_processing",
             "gap": "part_of", "expected_type": "", "reason": "caller states it"},
        ],
    }]
    parked_ids = soma_fillers.park_fillable_requests(concepts, queue_dir=qd2)
    # 2 parked (human + system_deduction map to subclasses); observing_agent -> None -> skipped.
    ok["UNIT_park_skips_observing_agent"] = len(parked_ids) == 2
    ok["UNIT_park_wrote_files"] = len(os.listdir(qd2)) == 2


# ---------------------------------------------------------------------------
# E2E — isolated SOMA daemon, resolve() over a real verdict (strat2)
# ---------------------------------------------------------------------------

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
    # wait for readiness via the SDK (an empty-ish ping that writes a soup probe, not persisted)
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


def e2e_test():
    proc, log = start_daemon()
    qd = tempfile.mkdtemp(prefix="soma_fillers_e2e_q_")
    try:
        # The original invoice intent: a process whose actual steps/roles/inputs/outputs are unknown.
        observations = [node("invoice_processing", [("is_a", "process", "concept_ref")])]
        fillers = soma_fillers.default_fillers(queue_dir=qd)   # no llm -> human authorities park

        result = resolve(observations, fillers, soma_url=SOMA_URL,
                         source="test_soma_fillers", domain="default")

        # The human-authorized gaps stayed PENDING (the human filler returned None each round).
        pend_auths = {r.authorization for r in result.pending}
        ok["E2E_human_requests_pending"] = "human_domain_expert" in pend_auths
        # has_steps/roles/inputs/outputs are all human_domain_expert -> all pending.
        pend_gaps = {r.gap for r in result.pending if r.authorization == "human_domain_expert"}
        ok["E2E_all_four_parts_pending"] = {"has_steps", "has_roles", "has_inputs", "has_outputs"} <= pend_gaps
        # NOTHING was auto-resolved (no llm wired; humans park) — the loop settled cleanly.
        ok["E2E_nothing_auto_resolved"] = result.resolved == []
        # The human requests were DURABLY PARKED — files landed in the queue.
        ok["E2E_human_requests_parked_to_disk"] = len(os.listdir(qd)) >= 4
        # The concept is still soup (a human must answer; re-derivation will resume when they do).
        ok["E2E_concept_still_soup"] = result.final.statuses.get("invoice_processing") == "soup"
        # observing_agent gaps (instantiates/part_of/produces) were NEVER raised as requests.
        ok["E2E_no_observing_agent_request"] = all(
            r.authorization != "observing_agent" for r in result.pending
        )

        print("=== E2E: resolve(invoice_processing is_a process) with carton human fillers ===")
        print("  final status:", result.final.statuses.get("invoice_processing"))
        print("  rounds:", result.rounds, "| resolved:", len(result.resolved), "| pending:", len(result.pending))
        for r in result.pending:
            print(f"    PENDING: {r.gap}  ->  {r.authorization}")
        print("  parked files:", sorted(os.listdir(qd)))
    finally:
        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        log.close()


if __name__ == "__main__":
    unit_tests()
    e2e_test()
    print("\nCHECKS:")
    for k, v in ok.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}={v}")
    n_pass = sum(1 for v in ok.values() if v)
    print(f"\nVERDICT: {n_pass}/{len(ok)} "
          + ("CARTON BRAIN STEP-2 FILLERS PROVEN (strat2 real + strat3 unit)"
             if (ok and all(ok.values())) else "GAP FOUND — inspect above"))
    sys.exit(0 if (ok and all(ok.values())) else 1)
