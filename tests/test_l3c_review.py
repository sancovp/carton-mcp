"""L3c — AUTHED REVIEW-RESUME by run-id (Isaac 2026-06-28). Offline, DI fake neo4j (NEVER live writes).

L3b parked a pending compose-suggestion review item keyed by a stable run-id (concept.prop.candidate).
L3c is the reviewer's answer keyed to that run-id:
  - ACCEPT -> COMPOSE the edge (concept)-[:PROP]->(candidate) into the KG (reuses realize_composed_triples'
    MERGE) + mark the item accepted (re-derivation resumes: the slot is now filled).
  - REJECT -> mark the item rejected; NO graph mutation.
  - unknown run-id -> not_found.
Proves the resume MECHANISM end-to-end with a recording fake for neo4j (no live writes).
"""
import os, sys, json, shutil
from carton_mcp.soma_fillers import park_compose_suggestions, resolve_compose_suggestion

QD = "/tmp/test_l3c_review_q"
shutil.rmtree(QD, ignore_errors=True)


class Fake:
    def __init__(self): self.calls = []
    def execute_query(self, q, p=None): self.calls.append((q, p or {})); return []


ok = {}

# Park two pending review items.
park_compose_suggestions([{"compose_suggestions": [
    {"concept": "widget_a", "prop": "has_gadget", "expected_type": "gadget",
     "candidate": "gadget_one", "reviewer_role": "observing_agent"},
    {"concept": "form_a", "prop": "has_bridge", "expected_type": "bridge",
     "candidate": "bridge_one", "reviewer_role": "human_domain_expert"},
]}], queue_dir=QD)
ok["parked_two"] = (len(os.listdir(QD)) == 2)

# ACCEPT -> composes the edge (DI fake records the MERGE) + status accepted, persisted.
f1 = Fake()
r1 = resolve_compose_suggestion("widget_a.has_gadget.gadget_one", "accept", f1.execute_query, queue_dir=QD)
ok["accept_status"] = (r1.get("status") == "accepted")
ok["accept_merged_edge"] = any(
    "MERGE (s)-[rel:HAS_GADGET]->(t)" in q and p.get("src") == "Widget_A" and p.get("val") == "Gadget_One"
    for q, p in f1.calls)
ok["accept_persisted"] = (json.load(open(os.path.join(QD, "widget_a.has_gadget.gadget_one.json")))["status"]
                          == "accepted")

# REJECT -> status rejected, NO graph mutation.
f2 = Fake()
r2 = resolve_compose_suggestion("form_a.has_bridge.bridge_one", "reject", f2.execute_query, queue_dir=QD)
ok["reject_status"] = (r2.get("status") == "rejected")
ok["reject_no_merge"] = (len(f2.calls) == 0)
ok["reject_persisted"] = (json.load(open(os.path.join(QD, "form_a.has_bridge.bridge_one.json")))["status"]
                          == "rejected")

# Unknown run-id -> not_found (no crash, no write).
f3 = Fake()
r3 = resolve_compose_suggestion("nope.x.y", "accept", f3.execute_query, queue_dir=QD)
ok["unknown_not_found"] = (r3.get("status") == "not_found" and len(f3.calls) == 0)

print("=== L3c: authed review-resume by run-id ===")
print(f"  accept -> {r1.get('status')} ; merge calls={f1.calls}")
print(f"  reject -> {r2.get('status')} ; merge calls={f2.calls}")
print(f"  unknown -> {r3.get('status')}")

print("\nCHECKS:")
for k, v in ok.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}={v}")
n = sum(1 for v in ok.values() if v)
print(f"\nVERDICT: {n}/{len(ok)} "
      + ("L3c REVIEW-RESUME PROVEN (accept composes the edge by run-id + marks accepted; reject marks "
         "rejected with no mutation; unknown -> not_found)"
         if (ok and all(ok.values())) else "GAP — inspect /tmp/test_l3c_review_q/"))
sys.exit(0 if (ok and all(ok.values())) else 1)
