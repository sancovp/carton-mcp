"""PROVE CartON REJECTS a Type-2 geometric contradiction (Isaac 2026-06-22): the real
add_concept_tool_func, given a concept SOMA grades `contradiction`, returns ❌ REJECTED and
writes NOTHING to the queue (so the daemon never persists it to neo4j).

Safe: SOMA points at an ISOLATED daemon (prod :8091 runs old code w/o the contradiction status);
HEAVEN_DATA_DIR is a throwaway temp dir so the queue is isolated; the reject returns BEFORE the
queue write (the only write add_concept_tool_func does — the daemon does all neo4j/file writes from
the queue), so a reject pollutes nothing. NEVER :8091.
"""
import os, sys, json, time, signal, subprocess, shutil, urllib.request

PORT = 8113
SOMA_STORE = "/tmp/test_carton_contra_soma"
HEAVEN = "/tmp/test_carton_contra_heaven"
os.environ["HEAVEN_DATA_DIR"] = HEAVEN              # isolate the carton queue
os.environ.setdefault("NEO4J_URI", "bolt://host.docker.internal:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "password")
for d in (SOMA_STORE, HEAVEN):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
shutil.copy("/home/GOD/gnosys-plugin-v2/base/soma-prolog/soma_prolog/soma.owl", f"{SOMA_STORE}/soma.owl")
soma_env = dict(os.environ, SOMA_QUADSTORE_PATH=f"{SOMA_STORE}/store.sqlite3",
                SOMA_OWL_PATH=f"{SOMA_STORE}/soma.owl")
log = open(f"{SOMA_STORE}/d.log", "w")
daemon = subprocess.Popen([sys.executable, "-m", "soma_prolog.api", "--port", str(PORT)],
                          env=soma_env, stdout=log, stderr=subprocess.STDOUT)


def _ping():
    body = json.dumps({"source": "t", "observations": [
        {"source": "t", "name": "ping", "description": "p",
         "relationships": [{"relationship": "is_a", "related": [{"value": "string_value", "type": "concept_ref"}]}]}
    ], "domain": "default"}).encode()
    req = urllib.request.Request(f"http://localhost:{PORT}/event", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def wait_up():
    for _ in range(90):
        try:
            _ping(); return True
        except Exception:
            time.sleep(1)
    return False


ok = {}
try:
    assert wait_up(), "isolated SOMA daemon down"
    import carton_mcp.add_concept_tool as ACT
    ACT.SOMA_URL = f"http://localhost:{PORT}/event"   # point carton at the ISOLATED daemon
    ACT.SOMA_AVAILABLE = True   # SOMA_AVAILABLE is computed at import vs hardcoded :8091; force it
                                # so the soma_validate call runs against our patched isolated URL

    queue_dir = ACT.get_observation_queue_dir()
    before = set(os.listdir(queue_dir))

    # A Type-2 contradiction: is_a process (perdurant) AND physical_object (endurant).
    res = ACT.add_concept_tool_func(
        concept_name="Contra_Probe_Type2",
        description="a probe that claims two disjoint DOLCE branches",
        relationships=[{"relationship": "is_a", "related": ["process", "physical_object"]}],
        source="t",
    )
    print("=== add_concept_tool_func returned ===")
    print("   ", repr(res)[:200])

    after = set(os.listdir(queue_dir))
    new_queue_files = after - before
    # the REJECTED concept must NOT be queued (carton may write unrelated bootstrap concepts
    # like `Skill` — those are not our concept; the contract is Contra_Probe_Type2 is not saved).
    queued_names = []
    for f in new_queue_files:
        try:
            queued_names.append(json.load(open(os.path.join(queue_dir, f))).get("concept_name"))
        except Exception:
            pass

    ok["REJECT_returned"] = res.startswith("❌") and "REJECTED" in res
    ok["REJECT_mentions_contradiction"] = "contradiction" in res.lower()
    ok["REJECT_concept_not_queued"] = ("Contra_Probe_Type2" not in queued_names)
    print("   queued concept names:", queued_names, "(must NOT contain Contra_Probe_Type2)")

finally:
    try:
        daemon.send_signal(signal.SIGTERM)
        daemon.wait(timeout=10)
    except Exception:
        try:
            daemon.kill()
        except Exception:
            pass
    log.close()

print("\nCHECKS:")
for k, v in ok.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}={v}")
print("\nVERDICT:", "CARTON REJECTS TYPE-2 CONTRADICTION (no queue write)"
      if (ok and all(ok.values())) else "GAP — inspect the return + queue dir")
