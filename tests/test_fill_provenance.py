"""P1 — the FILL-PROVENANCE SUBSTRATE (Isaac 2026-06-28: "provenance substrate first").

record_fill_provenance stamps a persisted (Concept)-[:FILLED_FROM {prop, source_type, ts}]->(Source)
edge recording WHERE a slot value came from. Source is a NODE (step-5 joins it to role/org) and
prop/source_type are queryable props (step-4 accumulates them). DI-proven offline (recording fake
execute — NEVER live neo4j):
  (STAMP)   a fill records the FILLED_FROM edge with the right params + a constant rel type.
  (COMPOSED) realize_composed_triples now ALSO stamps provenance (source 'soma'/system_deduction)
             for every SOMA-deduced compose.
  (GUARD)   empty concept/source/prop -> None, no execute.
"""
import sys
from carton_mcp.soma_fillers import record_fill_provenance, realize_composed_triples

ident = lambda x: x.title() if isinstance(x, str) else x
ok = {}

# (STAMP) a single fill provenance
calls = []
r = record_fill_provenance("widget_a", "has_gadget", "alice", "agent_review",
                           lambda q, p: calls.append((q, p)), normalize=ident)
q, params = calls[0]
ok["stamp_returns_tuple"] = (r == ("Widget_A", "has_gadget", "Alice", "agent_review"))
ok["stamp_uses_FILLED_FROM_const"] = ("[fp:FILLED_FROM {prop: $p}]" in q and ":FILLED_FROM" in q)
ok["stamp_params_correct"] = (params == {"c": "Widget_A", "s": "Alice", "p": "has_gadget", "st": "agent_review"})
ok["stamp_no_rel_interpolation"] = ("$p" in q and "$st" in q and "$c" in q and "$s" in q)  # everything parameterized

# (COMPOSED) realize now also stamps provenance source='soma'
ccalls = []
realize_composed_triples(
    [{"composed_triples": [{"concept": "form_a", "prop": "has_bridge", "value": "bridge_one"}]}],
    lambda q, p: ccalls.append((q, p)), normalize=ident)
joined = " || ".join(q for q, _ in ccalls)
prov = [(q, p) for q, p in ccalls if "FILLED_FROM" in q]
ok["composed_writes_edge"] = any("MERGE (s)-[rel:HAS_BRIDGE]->(t)" in q for q, _ in ccalls)
ok["composed_also_stamps_provenance"] = (len(prov) == 1)
ok["composed_provenance_is_soma"] = (prov and prov[0][1] == {"c": "Form_A", "s": "Soma", "p": "HAS_BRIDGE", "st": "system_deduction"})

# (GUARD) missing pieces -> None, no execute
gcalls = []
ok["guard_empty_concept"] = (record_fill_provenance("", "p", "s", "t", lambda q, x: gcalls.append(1), normalize=ident) is None)
ok["guard_empty_source"] = (record_fill_provenance("c", "p", "", "t", lambda q, x: gcalls.append(1), normalize=ident) is None)
ok["guard_no_execute"] = (len(gcalls) == 0)

print("CHECKS:")
for k, v in ok.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}={v}")
n = sum(1 for v in ok.values() if v)
print(f"\nVERDICT: {n}/{len(ok)} " + ("P1 FILL-PROVENANCE SUBSTRATE PROVEN (FILLED_FROM stamp with "
      "node Source + prop/source_type props; composed fills auto-stamp source='soma'; injection-safe "
      "constant rel type; guards)" if all(ok.values()) else "GAP"))
sys.exit(0 if all(ok.values()) else 1)
