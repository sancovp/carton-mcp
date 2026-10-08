"""Issue 1009: add_concept writes the label a merged label was merged into, never the merged label.

Run as a script from this directory, one MARKER line per test. The front-door cases drive
add_concept_tool_func with SOMA, the breaker, the graph and the queue faked, so nothing reaches
CartON or SOMA.
"""

import os
import tempfile

import add_concept_tool as act
import carton_mcp.carton_breaker as breaker
import carton_mcp.carton_merged_labels as cml
import carton_mcp.carton_utils as cu

MERGED = {"task": "Giint_Task", "doc_mirror_domain": "Domain"}


class _Graph:
    reads = 0

    def __init__(self, *a, **k):
        pass

    def query_wiki_graph(self, query, params=None, *a, **k):
        if "merged_from" in query:
            _Graph.reads += 1
            return {"success": True, "data": [{"left": "Task", "right": "Giint_Task"},
                                              {"left": "Doc_Mirror_Domain", "right": "Domain"}]}
        return {"success": True, "data": []}


class _DeadGraph(_Graph):
    def query_wiki_graph(self, query, params=None, *a, **k):
        return {"success": False, "error": "connection refused"}


def _fresh_cache():
    cml._CACHE.update({"at": 0.0, "map": None})


def _run(name, rels, source="agent"):
    queued, posted = [], []
    act._soma_up = lambda: True
    act.soma_validate = lambda **k: posted.append(k) or {"result": f"event=e1\nstatus={name.lower()}:code"}
    act.submit_queue_entry = lambda entry, suffix="": queued.append(entry) or "q.json"
    act.CARTON_CB_STORE = False
    breaker.check_breaker = lambda **k: None
    cu.CartOnUtils = _Graph
    _fresh_cache()
    os.environ["HEAVEN_DATA_DIR"] = tempfile.mkdtemp()
    out = act.add_concept_tool_func(name, "", rels, source=source)
    return out, queued, posted


def t_pure_redirects_the_name_and_every_target_form():
    rels = [{"relationship": "is_a", "related": ["Task", "Other"]},
            {"relationship": "relates_to", "related": [{"value": "doc_mirror_domain", "type": "concept_ref"}]},
            {"relationship": "part_of", "related": "Task"}]
    name, out, redirects = cml.redirect_merged("Task", rels, MERGED)
    assert name == "Giint_Task", name
    assert out[0]["related"] == ["Giint_Task", "Other"], out
    assert out[1]["related"] == [{"value": "Domain", "type": "concept_ref"}], out
    assert out[2]["related"] == "Giint_Task", out
    assert ("Task", "Giint_Task") in redirects and ("doc_mirror_domain", "Domain") in redirects
    assert rels[0]["related"] == ["Task", "Other"], "the caller's list is not mutated"
    print("  MARKER: PURE_REDIRECTS_NAME_AND_TARGETS_OK")


def t_pure_leaves_unmerged_and_right_labels_alone():
    rels = [{"relationship": "is_a", "related": ["Giint_Task", "Agent_Identity"]}]
    name, out, redirects = cml.redirect_merged("Giint_Task", rels, {"agentidentity": "Agent_Identity"})
    assert (name, out, redirects) == ("Giint_Task", rels, []), (name, out, redirects)
    assert cml.redirect_merged("Task", rels, None) == ("Task", rels, [])
    assert cml.redirect_merged("doc mirror domain", [], MERGED,
                               normalize=lambda n: n.replace(" ", "_"))[0] == "Domain"
    print("  MARKER: PURE_LEAVES_OTHERS_ALONE_OK")


def t_map_is_cached_and_a_failed_read_keeps_the_last_map():
    cu.CartOnUtils = _Graph
    _fresh_cache()
    _Graph.reads = 0
    first = cml.merged_label_map(now=1000.0)
    again = cml.merged_label_map(now=1030.0)
    assert first == MERGED and again is first and _Graph.reads == 1, (first, _Graph.reads)
    cu.CartOnUtils = _DeadGraph
    assert cml.merged_label_map(now=2000.0) == MERGED, "a failed read answers the last map read"
    _fresh_cache()
    assert cml.merged_label_map(now=3000.0) is None, "no map read yet answers None"
    print("  MARKER: MAP_CACHED_AND_FAILED_READ_OK")


def t_front_door_queues_the_right_label_for_the_name_and_targets():
    out, queued, posted = _run("Task", [{"relationship": "is_a", "related": ["Task"]},
                                        {"relationship": "part_of", "related": ["Doc_Mirror_Domain"]}])
    assert out.startswith("✅") and len(queued) == 1, out
    entry = queued[0]
    text = repr(entry)
    assert "Giint_Task" in text and "'Domain'" in text, text[:600]
    assert "'Task'" not in text and "Doc_Mirror_Domain" not in text, text[:600]
    print("  MARKER: FRONT_DOOR_QUEUES_RIGHT_LABEL_OK")


def t_pure_confines_hwss_domain_to_the_four_roots():
    rels = [{"relationship": "is_a", "related": ["Hwss_Domain", "Domain"]},
            {"relationship": "part_of", "related": ["Hwss_Domain"]}]
    out, confined = cml.confine_hwss_domain("Skill_Development", rels)
    assert confined and out[0]["related"] == ["Domain"], out
    assert out[1]["related"] == ["Hwss_Domain"], "only is_a is confined, never another relationship"
    assert rels[0]["related"] == ["Hwss_Domain", "Domain"], "the caller's list is not mutated"
    out, confined = cml.confine_hwss_domain(
        "x", [{"relationship": "is_a", "related": [{"value": "hwss_domain", "type": "concept_ref"}]}])
    assert confined and out[0]["related"] == [{"value": "Domain", "type": "concept_ref"}], out
    for root in ("Health", "wealth", "Social", "Spiritual"):
        out, confined = cml.confine_hwss_domain(root, [{"relationship": "is_a", "related": ["Hwss_Domain"]}])
        assert not confined and out[0]["related"] == ["Hwss_Domain"], (root, out)
    print("  MARKER: PURE_CONFINES_HWSS_DOMAIN_OK")


def t_front_door_queues_domain_for_a_non_root_and_hwss_domain_for_a_root():
    out, queued, _ = _run("Skill_Development", [{"relationship": "is_a", "related": ["Hwss_Domain"]},
                                                {"relationship": "part_of", "related": ["Wealth"]}])
    assert out.startswith("✅") and len(queued) == 1, out
    text = repr(queued[0])
    assert "'Domain'" in text and "Hwss_Domain" not in text, text[:600]
    out, queued, _ = _run("Wealth", [{"relationship": "is_a", "related": ["Hwss_Domain"]},
                                     {"relationship": "part_of", "related": ["Hwss_Domain"]}])
    assert out.startswith("✅") and "Hwss_Domain" in repr(queued[0]), repr(queued)[:600]
    print("  MARKER: FRONT_DOOR_CONFINES_HWSS_DOMAIN_OK")


if __name__ == "__main__":
    tests = [t_pure_redirects_the_name_and_every_target_form, t_pure_leaves_unmerged_and_right_labels_alone,
             t_map_is_cached_and_a_failed_read_keeps_the_last_map,
             t_front_door_queues_the_right_label_for_the_name_and_targets,
             t_pure_confines_hwss_domain_to_the_four_roots,
             t_front_door_queues_domain_for_a_non_root_and_hwss_domain_for_a_root]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {str(e)[:300]}")
    print(f"ALL {len(tests)} PASS" if not failed else f"{len(tests) - failed}/{len(tests)} PASS")
    raise SystemExit(1 if failed else 0)
