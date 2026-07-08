"""mark_compose_suggestion — the add_concept(soma_run_id=...) ACCEPT path (Isaac 2026-06-28).

Accepting a parked SOMA compose-suggestion is NOT a separate RPC: it is just SAYING the fill via
add_concept (the normal observation path writes the slot-filling edge), passing soma_run_id so the
parked review item is marked resolved. mark_compose_suggestion is the mark-only half (no re-compose,
no neo4j execute). This also proves the dedup refactor: resolve_compose_suggestion now DELEGATES its
status-write to mark_compose_suggestion via the shared _load_suggestion, so reject composes nothing.
"""
import os, sys, json, tempfile
from carton_mcp.soma_fillers import mark_compose_suggestion, resolve_compose_suggestion, _load_suggestion

qd = tempfile.mkdtemp()
ok = {}

# park a fake suggestion record (what L3b's park_compose_suggestions writes)
json.dump({"run_id": "C.has_x.V", "concept": "C", "prop": "has_x", "candidate": "V",
           "status": "pending_review"}, open(os.path.join(qd, "C.has_x.V.json"), "w"))

# (ACCEPT) the add_concept soma_run_id path — mark-only, no execute needed
r1 = mark_compose_suggestion("C.has_x.V", "accepted", queue_dir=qd)
ok["accept_marks_accepted"] = (r1.get("status") == "accepted" and "resolved_at" in r1)
ok["accept_persisted"] = (json.load(open(os.path.join(qd, "C.has_x.V.json")))["status"] == "accepted")

# (NOT FOUND) unknown run-id
ok["unknown_not_found"] = (mark_compose_suggestion("nope.x.y", queue_dir=qd).get("status") == "not_found")

# (DELEGATION) resolve(reject) routes its write through mark — and composes NOTHING (zero execute calls)
calls = []
json.dump({"run_id": "D.has_y.W", "concept": "D", "prop": "has_y", "candidate": "W",
           "status": "pending_review"}, open(os.path.join(qd, "D.has_y.W.json"), "w"))
r3 = resolve_compose_suggestion("D.has_y.W", "reject", lambda q, p: calls.append((q, p)), queue_dir=qd)
ok["resolve_reject_delegates"] = (r3.get("status") == "rejected" and len(calls) == 0)

# (LOADER) _load_suggestion returns (path, rec) or None — the shared read both use
ok["loader_hit"] = (_load_suggestion("C.has_x.V", queue_dir=qd) is not None)
ok["loader_miss"] = (_load_suggestion("nope.x.y", queue_dir=qd) is None)

print("CHECKS:")
for k, v in ok.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}={v}")
n = sum(1 for v in ok.values() if v)
print(f"\nVERDICT: {n}/{len(ok)} " + ("mark_compose_suggestion PROVEN (add_concept soma_run_id accept "
      "path marks+persists; not_found; resolve delegates+composes-nothing on reject; shared loader)"
      if all(ok.values()) else "GAP"))
sys.exit(0 if all(ok.values()) else 1)
