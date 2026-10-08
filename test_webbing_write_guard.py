"""Card 703 and issue 1009: the webbing agent never writes onto or declares a system type and never names a merged label.

Run as a script from this directory, one MARKER line per test. The front-door cases drive
add_concept_tool_func with SOMA, the breaker, the graph and the queue faked, so nothing reaches
CartON or SOMA.
"""

import os
import tempfile

import add_concept_tool as act
import carton_mcp.carton_breaker as breaker
import carton_mcp.carton_utils as cu
from carton_mcp.webbing_write_guard import CARTON_UNREADABLE, declares_system_type, webbing_write_refusal

DECLARED = "Zz_Declared_St_703"
RELS = [{"relationship": "is_a", "related": ["Validator"]}, {"relationship": "part_of", "related": ["Probe"]}]
DECLARING = [{"relationship": "is_a", "related": ["Validator", "System_Type"]},
             {"relationship": "part_of", "related": ["Probe"]}]


class _Graph:
    def __init__(self, *a, **k):
        pass

    def query_wiki_graph(self, query, params=None, *a, **k):
        if "'System_Type'" in query:
            return {"success": True, "data": [{"declared": DECLARED in (params or {}).get("names", [])}]}
        if "merged_from" in query:
            return {"success": True, "data": [{"left": "Task", "right": "Giint_Task"}]}
        return {"success": True, "data": []}


def _run(name, rels, source):
    queued, posted = [], []
    act._soma_up = lambda: True
    act.soma_validate = lambda **k: posted.append(k) or {"result": f"event=e1\nstatus={name.lower()}:code"}
    act.submit_queue_entry = lambda entry, suffix="": queued.append(entry) or "q.json"
    act.CARTON_CB_STORE = False
    breaker.check_breaker = lambda **k: None
    cu.CartOnUtils = _Graph
    os.environ["HEAVEN_DATA_DIR"] = tempfile.mkdtemp()
    out = act.add_concept_tool_func(name, "", rels, source=source)
    return out, queued, posted


def t_pure_refuses_only_the_webber():
    assert webbing_write_refusal("agent", DECLARED, DECLARING, True) == ""
    assert webbing_write_refusal("webbing_agent", "Zz_New_Child", RELS, False) == ""
    assert "declared system type" in webbing_write_refusal("webbing_agent", DECLARED, RELS, True)
    assert "may not declare" in webbing_write_refusal("webbing_agent", "Zz_New_Child", DECLARING, False)
    print("  MARKER: PURE_REFUSES_ONLY_THE_WEBBER_OK")


def t_pure_reads_every_spelling_of_system_type():
    for spelling in ("System_Type", "system_type", "SystemType", {"value": "system_type", "type": "concept_ref"}):
        assert declares_system_type([{"relationship": "is_a", "related": [spelling]}]), spelling
    assert not declares_system_type([{"relationship": "part_of", "related": ["System_Type"]}])
    assert not declares_system_type([{"relationship": "is_a", "related": ["System_Type_Validator"]}])
    print("  MARKER: PURE_READS_EVERY_SPELLING_OK")


def t_webber_write_onto_a_declared_system_type_is_refused_and_nothing_is_written():
    out, queued, posted = _run(DECLARED, RELS, "webbing_agent")
    assert out.startswith("❌ REFUSED") and DECLARED in out, out
    assert queued == [] and posted == [], (queued, posted)
    print("  MARKER: WEBBER_ONTO_DECLARED_REFUSED_OK")


def t_webber_write_onto_a_case_variant_of_a_declared_system_type_is_refused():
    out, queued, posted = _run(DECLARED.upper(), RELS, "webbing_agent")
    assert out.startswith("❌ REFUSED"), out
    assert queued == [] and posted == [], (queued, posted)
    print("  MARKER: WEBBER_ONTO_CASE_VARIANT_REFUSED_OK")


def t_webber_declaring_a_system_type_is_refused_and_nothing_is_written():
    out, queued, posted = _run("Zz_New_Child_703", DECLARING, "webbing_agent")
    assert out.startswith("❌ REFUSED") and "may not declare" in out, out
    assert queued == [] and posted == [], (queued, posted)
    print("  MARKER: WEBBER_DECLARING_REFUSED_OK")


def t_webber_ordinary_write_and_every_other_source_still_land():
    out, queued, _ = _run("Zz_New_Child_703", RELS, "webbing_agent")
    assert out.startswith("✅") and len(queued) == 1, out
    out, queued, _ = _run(DECLARED, DECLARING, "agent")
    assert out.startswith("✅") and len(queued) == 1, out
    print("  MARKER: ORDINARY_WRITES_STILL_LAND_OK")


def t_pure_refuses_a_merged_label_as_the_name_or_a_type_target():
    merged = {"task": "Giint_Task"}
    for name, rels in (("Task", RELS), ("Zz_Child", [{"relationship": "is_a", "related": ["Task"]}]),
                       ("Zz_Child", [{"relationship": "instantiates", "related": [{"value": "Task"}]}])):
        out = webbing_write_refusal("webbing_agent", name, rels, False, merged)
        assert "merged into Giint_Task" in out, out
    assert webbing_write_refusal("webbing_agent", "Zz_Child", [{"relationship": "part_of", "related": ["Task"]}],
                                 False, merged) == ""
    assert "could not be read" in webbing_write_refusal("webbing_agent", "Zz_Child", RELS, False, CARTON_UNREADABLE)
    assert webbing_write_refusal("agent", "Task", RELS, False, merged) == ""
    print("  MARKER: PURE_REFUSES_MERGED_LABEL_OK")


def t_webber_write_naming_a_merged_label_is_refused_and_nothing_is_written():
    out, queued, posted = _run("Zz_New_Child_1009", [{"relationship": "is_a", "related": ["Task"]},
                                                     {"relationship": "part_of", "related": ["Probe"]}], "webbing_agent")
    assert out.startswith("❌ REFUSED") and "Giint_Task" in out, out
    assert queued == [] and posted == [], (queued, posted)
    out, queued, _ = _run("Zz_New_Child_1009", [{"relationship": "is_a", "related": ["Task"]},
                                                {"relationship": "part_of", "related": ["Probe"]}], "agent")
    assert out.startswith("✅") and len(queued) == 1, out
    print("  MARKER: WEBBER_MERGED_LABEL_REFUSED_OK")


if __name__ == "__main__":
    tests = [t_pure_refuses_only_the_webber, t_pure_reads_every_spelling_of_system_type,
             t_webber_write_onto_a_declared_system_type_is_refused_and_nothing_is_written,
             t_webber_write_onto_a_case_variant_of_a_declared_system_type_is_refused,
             t_webber_declaring_a_system_type_is_refused_and_nothing_is_written,
             t_webber_ordinary_write_and_every_other_source_still_land,
             t_pure_refuses_a_merged_label_as_the_name_or_a_type_target,
             t_webber_write_naming_a_merged_label_is_refused_and_nothing_is_written]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {str(e)[:300]}")
    print(f"{'ALL' if not failed else len(tests) - failed} {len(tests)} PASS" if not failed
          else f"{len(tests) - failed}/{len(tests)} PASS")
    raise SystemExit(1 if failed else 0)
