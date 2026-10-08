"""Card 726 condition 6: a domain or subdomain a write names that is not yet a domain node is written first from the
params the writer supplies, and nothing is refused.

Run as a script from this directory, one MARKER line per test, after pip install --no-deps of this package. The
front-door cases drive add_concept_tool_func with SOMA, the breaker, the graph and the queue faked, so nothing reaches
CartON or SOMA.
"""
import os
import tempfile

import add_concept_tool as act
import carton_mcp.carton_breaker as breaker
import carton_mcp.carton_domain_axis as cda
import carton_mcp.carton_merged_labels as cml
import carton_mcp.carton_utils as cu

KNOWN = {"Wealth", "Soma", "Soma_Type_Structure", "Domain_System_Type"}


def known(name):
    return name in KNOWN


def t_axis_targets_reads_both_axes_in_order():
    rels = [{"relationship": "is_a", "related": ["X"]},
            {"relationship": "has_domain", "related": ["Soma", {"value": "Soma", "type": "concept_ref"}]},
            {"relationship": "HAS_SUBDOMAIN", "related": "Domain_System_Type"}]
    assert cda.axis_targets(rels) == (["Soma"], ["Domain_System_Type"]), cda.axis_targets(rels)
    assert cda.axis_targets([]) == ([], [])
    print("  MARKER: AXIS_TARGETS_OK")


def t_no_param_plans_nothing_and_refuses_nothing():
    assert cda.plan_domain_axis(["New_Dom"], ["New_Sub"], known) == ([], [])
    print("  MARKER: NO_PARAM_PLANS_NOTHING_OK")


def t_new_subdomain_with_about_is_written_under_the_write_domains():
    writes, notes = cda.plan_domain_axis(["Soma"], ["Brand_New_Sub"], known, subdomain_about=" what it is about ")
    assert writes == [("Brand_New_Sub", "what it is about", ["Soma"])] and notes == [], (writes, notes)
    print("  MARKER: NEW_SUBDOMAIN_WRITTEN_OK")


def t_new_domain_then_its_new_subdomain_in_order():
    writes, notes = cda.plan_domain_axis(["New_Dom"], ["New_Sub"], known, domain_about="dom about",
                                         domain_part_of="Wealth", subdomain_about="sub about")
    assert writes == [("New_Dom", "dom about", ["Wealth"]), ("New_Sub", "sub about", ["New_Dom"])], writes
    writes, _ = cda.plan_domain_axis(["New_Dom"], [], known, domain_about="dom about")
    assert writes == [("New_Dom", "dom about", [])], "a new domain with no parent supplied lands with none"
    print("  MARKER: NEW_DOMAIN_AND_SUBDOMAIN_OK")


def t_unused_params_are_noted_never_refused():
    writes, notes = cda.plan_domain_axis(["Soma"], ["S1", "S2"], known, subdomain_about="x")
    assert writes == [] and "S1, S2" in notes[0] and "none was written" in notes[0], notes
    writes, notes = cda.plan_domain_axis(["Soma"], ["Domain_System_Type"], known, subdomain_about="x")
    assert writes == [] and "already a domain node" in notes[0], notes
    writes, notes = cda.plan_domain_axis(["New_Dom"], [], known, domain_part_of="Wealth")
    assert writes == [] and notes[0].startswith("domain_part_of unused"), notes
    print("  MARKER: UNUSED_PARAMS_NOTED_OK")


def t_land_writes_each_planned_node_and_reads_once():
    reads, written = [], []
    rels = [{"relationship": "has_domain", "related": ["Soma"]},
            {"relationship": "has_subdomain", "related": ["Brand_New_Sub"]}]
    lines = cda.land_domain_axis(
        rels, lambda n, a, r: written.append((n, a, r)) or f"✅ {n}: CartON Files queued\nx\nSOMA: SYSTEM_TYPE",
        lambda names: reads.append(set(names)) or {"Soma"}, subdomain_about="sub about")
    assert written == [("Brand_New_Sub", "sub about", [{"relationship": "is_a", "related": ["Domain"]},
                                                        {"relationship": "part_of", "related": ["Soma"]}])], written
    assert reads == [{"Soma", "Brand_New_Sub"}], reads
    assert lines == ["DOMAIN AXIS: Brand_New_Sub written first as is_a Domain part_of Soma with has_about: "
                     "✅ Brand_New_Sub: CartON Files queued SOMA: SYSTEM_TYPE"], lines
    assert cda.land_domain_axis(rels, None, None) == [], "no param supplied: no read and no write"
    def dead(names):
        raise RuntimeError("down")
    assert "read failed (down)" in cda.land_domain_axis(rels, None, dead, subdomain_about="x")[0]
    print("  MARKER: LAND_WRITES_AND_READS_ONCE_OK")


class _Graph:
    reads = []

    def __init__(self, *a, **k):
        pass

    def query_wiki_graph(self, query, params=None, *a, **k):
        if "$types" in query:
            _Graph.reads.append(set((params or {}).get("names") or []))
            return {"success": True, "data": [{"n": n} for n in (params or {}).get("names") or [] if n in KNOWN]}
        return {"success": True, "data": []}


def _run(name, rels, **kw):
    queued = []
    act._soma_up = lambda: True
    act.soma_validate = lambda **k: {"result": f"event=e1\nstatus={k['observations'][0]['name'].lower()}:system_type"}
    act.submit_queue_entry = lambda entry, suffix="": queued.append(entry) or "q.json"
    act.CARTON_CB_STORE = False
    breaker.check_breaker = lambda **k: None
    cu.CartOnUtils = _Graph
    _Graph.reads = []
    cml._CACHE.update({"at": 0.0, "map": None})
    os.environ["HEAVEN_DATA_DIR"] = tempfile.mkdtemp()
    return act.add_concept_tool_func(name, "", rels, **kw), queued


def t_front_door_lands_the_new_subdomain_before_the_concept():
    rels = [{"relationship": "is_a", "related": ["Idea"]}, {"relationship": "has_domain", "related": ["Soma"]},
            {"relationship": "has_subdomain", "related": ["Brand_New_Sub"]}]
    out, queued = _run("Some_Entry", rels, subdomain_about="the brand new part of soma")
    names = [q.get("concept_name") for q in queued]
    assert names == ["Brand_New_Sub", "Some_Entry"], names
    sub = queued[0]
    assert sub["properties"].get("has_about") == "the brand new part of soma", sub["properties"]
    assert {"relationship": "is_a", "related": ["Domain"]} in sub["relationships"], sub["relationships"]
    assert {"relationship": "part_of", "related": ["Soma"]} in sub["relationships"], sub["relationships"]
    assert out.startswith("✅ Some_Entry") and "DOMAIN AXIS: Brand_New_Sub written first" in out, out
    print("  MARKER: FRONT_DOOR_LANDS_NEW_SUBDOMAIN_OK")


def t_front_door_without_params_writes_as_said_and_reads_nothing():
    rels = [{"relationship": "is_a", "related": ["Idea"]}, {"relationship": "has_subdomain", "related": ["Unseen"]}]
    out, queued = _run("Plain_Entry", rels)
    assert [q.get("concept_name") for q in queued] == ["Plain_Entry"] and _Graph.reads == [], (queued, _Graph.reads)
    assert out.startswith("✅ Plain_Entry") and "DOMAIN AXIS" not in out, out
    print("  MARKER: FRONT_DOOR_NO_PARAMS_UNCHANGED_OK")


if __name__ == "__main__":
    tests = [t_axis_targets_reads_both_axes_in_order, t_no_param_plans_nothing_and_refuses_nothing,
             t_new_subdomain_with_about_is_written_under_the_write_domains,
             t_new_domain_then_its_new_subdomain_in_order, t_unused_params_are_noted_never_refused,
             t_land_writes_each_planned_node_and_reads_once,
             t_front_door_lands_the_new_subdomain_before_the_concept,
             t_front_door_without_params_writes_as_said_and_reads_nothing]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {str(e)[:400]}")
    print(f"ALL {len(tests)} PASS" if not failed else f"{len(tests) - failed}/{len(tests)} PASS")
    raise SystemExit(1 if failed else 0)
