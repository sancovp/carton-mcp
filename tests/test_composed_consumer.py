"""Carton CONSUMER of composed= — the receiving half of carton-bundle-back (Isaac 2026-06-28).

L3a (soma efbab64) made SOMA's backward-chain compose EMIT a `composed=` verdict section — the graph
additions SOMA DEDUCED (facts the user never stated). This proves the CARTON side that REALIZES them
into the neo4j KG, end-to-end through the REAL surfaces, never touching prod (:8091) or writing to live
neo4j:

  1) UNIT (offline, DI fake neo4j): soma_fillers.realize_composed_triples — the MERGE query + params,
     name-normalization (SOMA lowercase_underscore -> Title_Case nodes), rel-type upcasing, de-dup, and
     the unsafe-rel-type guard. No daemon, no neo4j.
  2) E2E PARSE (isolated SOMA daemon, NEVER :8091): boot the L3a HAPPY scenario, call the REAL
     add_concept_tool_func for form_a -> it POSTs the isolated SOMA, gets a real composed= verdict,
     parses it -> the queue file carries composed_triples=[{form_a, has_bridge, bridge_one}].
  3) PROPAGATE + REALIZE: parse_queue_file_to_concepts carries composed_triples through ->
     realize_composed_triples (DI fake execute) MERGEs (Form_A)-[:HAS_BRIDGE]->(Bridge_One).

So: real SOMA deduces -> real add_concept parses -> real daemon-parse propagates -> realize MERGEs.
The ONLY fake is neo4j execute (a recording shim) — correct, so no test nodes hit the live KG.
"""
import os, sys, json, time, signal, subprocess, shutil, urllib.request, glob

PORT = 8112
URL = f"http://localhost:{PORT}/event"
STORE = "/tmp/test_composed_consumer"
HEAVEN = "/tmp/test_composed_consumer_heaven"
os.environ.setdefault("NEO4J_URI", "bolt://host.docker.internal:7687")
shutil.rmtree(STORE, ignore_errors=True)
shutil.rmtree(HEAVEN, ignore_errors=True)
os.makedirs(STORE, exist_ok=True)
os.makedirs(HEAVEN, exist_ok=True)
shutil.copy("/home/GOD/gnosys-plugin-v2/base/soma-prolog/soma_prolog/soma.owl", f"{STORE}/soma.owl")
env = dict(os.environ, SOMA_QUADSTORE_PATH=f"{STORE}/store.sqlite3", SOMA_OWL_PATH=f"{STORE}/soma.owl")
log = open(f"{STORE}/d.log", "w")
daemon = subprocess.Popen([sys.executable, "-m", "soma_prolog.api", "--port", str(PORT)],
                          env=env, stdout=log, stderr=subprocess.STDOUT)


def post(obs, timeout=180):
    body = json.dumps({"source": "t", "observations": obs, "domain": "default"}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode()).get("result", "")


def node(name, rels):
    return {"source": "t", "name": name, "description": name,
            "relationships": [{"relationship": k, "related": [{"value": v, "type": t}]} for k, v, t in rels]}


def add_dchain(name, for_type, premise, conclusion):
    return post([{"source": "dchain_registration", "name": name, "description": name,
                  "relationships": [
                      {"relationship": "is_a", "related": [{"value": "deduction_chain", "type": "concept_ref"}]},
                      {"relationship": "has_type_target", "related": [{"value": for_type, "type": "concept_ref"}]},
                      {"relationship": "has_deduction_premise", "related": [{"value": premise, "type": "string_value"}]},
                      {"relationship": "has_deduction_conclusion", "related": [{"value": conclusion, "type": "string_value"}]},
                  ]}])


def wait_up():
    for _ in range(90):
        try:
            post([node("ping", [("is_a", "string_value", "concept_ref")])]); return True
        except Exception:
            time.sleep(1)
    return False


class FakeNeo4j:
    """Recording fake for shared_neo4j.execute_query — captures (query, params), writes nothing."""
    def __init__(self):
        self.calls = []
    def execute_query(self, query, params=None):
        self.calls.append((query, params or {}))
        return []


ok = {}
try:
    assert wait_up(), "daemon down"

    # ---- (1) UNIT: realize_composed_triples with a DI fake (fully offline) ----
    from carton_mcp.soma_fillers import realize_composed_triples
    fake = FakeNeo4j()
    concepts = [{"name": "Form_A", "composed_triples": [
        {"concept": "form_a", "prop": "has_bridge", "value": "bridge_one"},
        {"concept": "form_a", "prop": "has_bridge", "value": "bridge_one"},   # dup -> de-duped
        {"concept": "spaghetti", "prop": "has_cuisine", "value": "italian_food"},
        {"concept": "x", "prop": "bad-rel!", "value": "y"},                   # unsafe rel -> skipped
        {"concept": "", "prop": "has_bridge", "value": "z"},                  # empty src -> skipped
    ]}]
    realized = realize_composed_triples(concepts, fake.execute_query)
    # de-dup + skips -> exactly two realized
    ok["UNIT_realized_count_2"] = (len(realized) == 2)
    ok["UNIT_normalized_titlecase"] = (("Form_A", "HAS_BRIDGE", "Bridge_One") in realized
                                       and ("Spaghetti", "HAS_CUISINE", "Italian_Food") in realized)
    # contract (P1, 2026-06-28): each realized compose now emits TWO calls — the composed edge MERGE
    # AND a FILLED_FROM provenance stamp (source 'soma'/system_deduction). So 2 realized -> 4 calls.
    composed_calls = [q for q, _ in fake.calls if "soma_composed = true" in q]
    prov_calls = [q for q, _ in fake.calls if "FILLED_FROM" in q]
    ok["UNIT_2edges_2provenance"] = (len(composed_calls) == 2 and len(prov_calls) == 2)
    # the MERGE query carries the upcased rel type + soma_composed marker; params carry Title_Case names
    q0, p0 = fake.calls[0]
    ok["UNIT_merge_shape"] = ("MERGE (s)-[rel:HAS_BRIDGE]->(t)" in q0 and "soma_composed = true" in q0
                              and p0.get("src") == "Form_A" and p0.get("val") == "Bridge_One")
    ok["UNIT_unsafe_rel_skipped"] = not any(p.get("val") == "Y" for _, p in fake.calls)
    ok["UNIT_empty_concepts_noop"] = (realize_composed_triples([], fake.execute_query) == [])

    # ---- (2) E2E PARSE: real add_concept_tool_func against the isolated SOMA ----
    # L3a HAPPY scenario: bridge + form system_types; a compose d-chain + a reporter on `form`;
    # bridge_one in the STORE (own event). Then form_a (missing has_bridge) backward-chains + composes.
    post([node("bridge", [("is_a", "system_type", "concept_ref")])])
    post([node("form", [("is_a", "system_type", "concept_ref")])])
    add_dchain("dchain_form_compose_bridge", "form",
               "checking(C), triple(C, has_bridge, _)",
               "checking(C), compose_unique_admissible_match(C, has_bridge, bridge)")
    add_dchain("dchain_form_needs_bridge", "form",
               "checking(C), triple(C, has_bridge, _)",
               "assertz(unmet_requirement(form_needs_bridge))")
    post([node("bridge_one", [("is_a", "bridge", "concept_ref")])])

    # Point the REAL add_concept_tool at the isolated daemon + a temp HEAVEN_DATA_DIR, then call it.
    os.environ["HEAVEN_DATA_DIR"] = HEAVEN
    import carton_mcp.add_concept_tool as act
    act.SOMA_URL = URL              # soma_validate reads this module global at call time
    act.SOMA_AVAILABLE = True       # the import-time probe targeted :8091; force the isolated daemon on
    act.add_concept_tool_func(
        concept_name="form_a",
        description="form_a",
        relationships=[{"relationship": "is_a", "related": ["form"]}],
        hide_youknow=False,
    )

    # Find the queue file the call wrote and assert it carries the parsed composed_triples.
    qfiles = sorted(glob.glob(os.path.join(HEAVEN, "carton_queue", "*_concept.json")))
    ok["E2E_queue_written"] = (len(qfiles) >= 1)
    qdata = json.load(open(qfiles[-1])) if qfiles else {}
    ct = qdata.get("composed_triples", [])
    open(f"{STORE}/../composed_queue.json", "w").write(json.dumps(qdata, indent=2))
    ok["E2E_parsed_composed_triple"] = any(
        t.get("concept") == "form_a" and t.get("prop") == "has_bridge" and t.get("value") == "bridge_one"
        for t in ct)

    # ---- (3) PROPAGATE through the daemon parse + REALIZE ----
    from pathlib import Path
    from carton_mcp.observation_worker_daemon import parse_queue_file_to_concepts
    parsed = parse_queue_file_to_concepts(Path(qfiles[-1]))
    ok["E2E_daemon_parse_carries"] = any(c.get("composed_triples") for c in parsed)
    fake2 = FakeNeo4j()
    realized2 = realize_composed_triples(parsed, fake2.execute_query)
    ok["E2E_realized_edge"] = ("Form_A", "HAS_BRIDGE", "Bridge_One") in realized2

    print("=== composed= consumer (carton-bundle-back receiving half) ===")
    print(f"  UNIT realized={realized}")
    print(f"  E2E parsed composed_triples={ct}")
    print(f"  E2E realized2={realized2}")
finally:
    try:
        daemon.send_signal(signal.SIGTERM); daemon.wait(timeout=10)
    except Exception:
        try: daemon.kill()
        except Exception: pass
    log.close()

print("\nCHECKS:")
for k, v in ok.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}={v}")
n = sum(1 for v in ok.values() if v)
print(f"\nVERDICT: {n}/{len(ok)} "
      + ("CARTON CONSUMER OF composed= PROVEN (real SOMA deduces -> add_concept parses -> daemon parse "
         "carries -> realize MERGEs the deduced edge)"
         if (ok and all(ok.values())) else "GAP — inspect /tmp/composed_queue.json + /tmp/test_composed_consumer/d.log"))
sys.exit(0 if (ok and all(ok.values())) else 1)
