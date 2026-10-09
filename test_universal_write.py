#!/usr/bin/env python3
"""THE UNIVERSAL WRITE, END TO END ON A REAL EMBEDDED GRAPH — the gaps a program writing through it found.

    python3 knowledge/carton-mcp/test_universal_write.py            # every case
    python3 knowledge/carton-mcp/test_universal_write.py t_a t_b    # only the named cases

Run as a SCRIPT. The package under test is THIS directory, loaded as `carton_mcp` from the file system
(nothing installed is consulted), and the graph is ladybug (`ladybug==0.21.2`) in a temp dir, owned by
the worker's own connection class on GRAPH_BACKEND=kuzu. heaven-framework comes from the monorepo beside
this repo, or from PYTHONPATH.

    t_a_concepts_list_entry_lands_every_concept_with_its_properties
    t_b_fifty_entries_enqueued_in_one_second_drain_in_enqueue_order
    t_c_the_queue_name_never_goes_backwards_in_a_process
    t_d_queue_status_says_where_each_name_is
    t_e_none_unsets_a_property_and_a_dict_is_refused_with_how_to_store_it
    t_f_drain_once_is_the_whole_drain_and_a_test_can_call_it
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="universal_write_")
os.environ.update({
    "HEAVEN_DATA_DIR": TMP, "GRAPH_BACKEND": "kuzu", "KUZU_DB_PATH": os.path.join(TMP, "graph"),
    "HEAVEN_ALLOW_STDOUT": "1",
    "CHROMA_DAEMON_PORT": "9",  # the drain's RAG sync must reach nothing: discard port, nothing listens
})
for _k in ("CARTON_URL", "CARTON_KEY", "CARTON_CALL_GATE", "NEO4J_URI"):
    os.environ.pop(_k, None)
_HF = os.path.join(HERE, "..", "..", "base", "heaven-framework")
if os.path.isdir(_HF):
    sys.path.insert(0, _HF)

_spec = importlib.util.spec_from_file_location("carton_mcp", os.path.join(HERE, "__init__.py"),
                                               submodule_search_locations=[HERE])
_pkg = importlib.util.module_from_spec(_spec)
sys.modules["carton_mcp"] = _pkg
_spec.loader.exec_module(_pkg)

from carton_mcp import observation_worker_daemon as owd  # noqa: E402
from carton_mcp.add_concept_tool import queue_status, write_queue_entry  # noqa: E402
from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder  # noqa: E402

PASS, FAIL = [], []
GRAPH = None


def graph():
    global GRAPH
    if GRAPH is None:
        GRAPH = KnowledgeGraphBuilder()
        GRAPH._ensure_connection()
    return GRAPH


def queue_dir():
    return owd.get_observation_queue_dir()


def fresh():
    """An empty queue (and its two subdirs) and an empty graph."""
    q = queue_dir()
    for sub in ("", "processed", "failed"):
        d = q / sub if sub else q
        if d.is_dir():
            for f in d.glob("*.json"):
                f.unlink()
    graph().execute_query("MATCH (n:Wiki) DETACH DELETE n")


def land(files):
    """What the worker does with a batch, without drain_once: parse each file in order, write once."""
    concepts = [c for f in files for c in owd.parse_queue_file_to_concepts(f)]
    result = owd.batch_create_concepts_neo4j(concepts, graph())
    assert result["errors"] == [], result["errors"]
    return concepts


def props_of(name, keys):
    cols = ", ".join(f"c.`{k}` AS `{k}`" for k in keys)
    rows = graph().execute_query(f"MATCH (c:Wiki {{n: $n}}) RETURN {cols}", {"n": name})
    return rows[0] if rows else None


def t_a_concepts_list_entry_lands_every_concept_with_its_properties():
    fresh()
    entry = {"concepts": [
        {"name": "Uw_List_One", "description": "first of two",
         "relationships": [{"relationship": "is_a", "related": ["Uw_Thing"]}],
         "properties": {"uw_role": "one", "uw_rank": "1"}},
        {"name": "Uw_List_Two", "description": "second of two",
         "relationships": [{"relationship": "is_a", "related": ["Uw_Thing"]}],
         "properties": {"uw_role": "two", "uw_rank": "2"}, "desc_update_mode": "replace"},
    ], "source": "uw_test"}
    name = write_queue_entry(entry, "_list")
    rows = owd.parse_queue_file_to_concepts(queue_dir() / name)
    got = {r["name"]: r.get("properties") for r in rows}
    assert got == {"Uw_List_One": {"uw_role": "one", "uw_rank": "1"},
                   "Uw_List_Two": {"uw_role": "two", "uw_rank": "2"}}, f"the parse dropped properties: {got}"

    # A list entry's row carries every key a raw_concept file's row does.
    raw = queue_dir() / "uw_raw.json"
    raw.write_text(json.dumps({"raw_concept": True, "concept_name": "Uw_Raw", "description": "x",
                               "relationships": [], "properties": {"uw_role": "raw"}}))
    raw_keys = set(owd.parse_queue_file_to_concepts(raw)[0])
    raw.unlink()
    for r in rows:
        missing = raw_keys - set(r)
        assert not missing, f"{r['name']} lacks keys a raw_concept row carries: {sorted(missing)}"
    assert [r["source"] for r in rows] == ["uw_test", "uw_test"], rows
    assert rows[1]["desc_update_mode"] == "replace", rows[1]

    land([queue_dir() / name])
    for n, role, rank in (("Uw_List_One", "one", "1"), ("Uw_List_Two", "two", "2")):
        p = props_of(n, ["uw_role", "uw_rank"])
        assert p == {"uw_role": role, "uw_rank": rank}, f"{n} landed without its properties: {p}"


def t_b_fifty_entries_enqueued_in_one_second_drain_in_enqueue_order():
    fresh()
    time.sleep(1.02 - (time.time() % 1))  # start just after a second turns, so all fifty share it
    names = [write_queue_entry({"raw_concept": True, "concept_name": f"Uw_Seq_{i:02d}", "description": f"#{i}",
                         "relationships": [], "properties": {"uw_seq": f"{i:02d}"}}, "_seq")
             for i in range(50)]
    seconds = {n[:15] for n in names}
    assert len(seconds) == 1, f"the fifty did not fall in one second ({sorted(seconds)}); re-run"
    drained = sorted(queue_dir().glob("*.json"))  # exactly the worker's order
    order = [c["name"] for f in drained for c in owd.parse_queue_file_to_concepts(f)]
    want = [f"Uw_Seq_{i:02d}" for i in range(50)]
    assert order == want, f"drain order is not enqueue order: first mismatch at " \
                          f"{next(i for i, (a, b) in enumerate(zip(order, want)) if a != b)}: {order[:8]}..."
    land(drained)
    assert props_of("Uw_Seq_49", ["uw_seq"]) == {"uw_seq": "49"}


def t_c_the_queue_name_never_goes_backwards_in_a_process():
    from carton_mcp import add_concept_tool as act
    fresh()
    act._queue_name_last = 99991231235959999999  # a clock far ahead, as after a step backwards
    a = act.write_queue_entry({"raw_concept": True, "concept_name": "Uw_Late_A"}, "_late")
    b = act.write_queue_entry({"raw_concept": True, "concept_name": "Uw_Late_B"}, "_late")
    act._queue_name_last = 0
    assert sorted([b, a]) == [a, b], (a, b)
    assert a > "99991231_235959_999999", f"the name went back to the wall clock: {a}"
    leftovers = [p.name for p in queue_dir().iterdir() if p.name.endswith(".part")]
    assert leftovers == [], f"a half-written entry was left behind: {leftovers}"


def t_d_queue_status_says_where_each_name_is():
    """`queue_status` is the SDK's answer to "did my entry land": waiting = the top-level backlog, and
    per name queued · processed · failed · absent — read only, and only plain .json names inside the
    queue dir and its two subdirs. Reached in-process: the box's door is the SDK's operations."""
    fresh()
    a = write_queue_entry({"raw_concept": True, "concept_name": "Uw_Q_A"})
    b = write_queue_entry({"raw_concept": True, "concept_name": "Uw_Q_B"})
    c = write_queue_entry({"raw_concept": True, "concept_name": "Uw_Q_C"})
    for sub, name in (("processed", b), ("failed", c)):
        (queue_dir() / sub).mkdir(exist_ok=True)
        (queue_dir() / name).rename(queue_dir() / sub / name)
    ans = queue_status([a, b, c, "never_enqueued.json", "../graph.json", "processed"])
    assert ans["waiting"] == 1, ans
    assert ans["names"] == {a: "queued", b: "processed", c: "failed",
                            "never_enqueued.json": "absent", "../graph.json": "absent",
                            "processed": "absent"}, ans
    assert queue_status() == {"waiting": 1}, queue_status()


def t_e_none_unsets_a_property_and_a_dict_is_refused_with_how_to_store_it():
    from carton_mcp.carton_utils import set_concept_properties
    fresh()
    graph().execute_query("MERGE (c:Wiki {n: 'Uw_Props'}) ON CREATE SET c.d = 'p'")
    r = set_concept_properties("Uw_Props", {"uw_a": "1", "uw_b": "2"}, shared_connection=graph())
    assert r["success"] and sorted(r["updated_keys"]) == ["uw_a", "uw_b"], r
    r = set_concept_properties("Uw_Props", {"uw_a": None, "uw_c": "3"}, shared_connection=graph())
    assert r["success"], f"a None value refused the whole call: {r}"
    assert (r["updated_keys"], r["removed_keys"]) == (["uw_c"], ["uw_a"]), r
    assert props_of("Uw_Props", ["uw_a", "uw_b", "uw_c"]) == {"uw_a": None, "uw_b": "2", "uw_c": "3"}
    r = set_concept_properties("Uw_Props", {"uw_b": None}, shared_connection=graph())
    assert r["success"] and r["removed_keys"] == ["uw_b"] and r["error"] is None, r
    for bad in ({"uw_d": {"x": 1}}, {"uw_d": ["ok", {"x": 1}]}):
        r = set_concept_properties("Uw_Props", bad, shared_connection=graph())
        assert not r["success"] and "JSON-encode" in r["error"], r
    assert props_of("Uw_Props", ["uw_c"]) == {"uw_c": "3"}, "a refused call wrote something"


def t_f_drain_once_is_the_whole_drain_and_a_test_can_call_it():
    fresh()
    empty = owd.drain_once(queue_dir(), graph())
    assert (empty["files"], empty["processed"], empty["failed"]) == (0, 0, 0), empty
    a = write_queue_entry({"raw_concept": True, "concept_name": "Uw_Drain_One", "description": "one",
                    "relationships": [{"relationship": "is_a", "related": ["Uw_Thing"]}],
                    "properties": {"uw_k": "v1"}}, "_d")
    b = write_queue_entry({"concepts": [{"name": "Uw_Drain_Two", "description": "two",
                                  "relationships": [{"relationship": "is_a", "related": ["Uw_Thing"]}],
                                  "properties": {"uw_k": "v2"}}]}, "_d")
    bad = queue_dir() / (b[:-5] + "_zz.json")
    bad.write_text("{not json")
    res = owd.drain_once(queue_dir(), graph())
    assert res["connection"] is graph(), "a live connection was replaced"
    assert (res["files"], res["processed"], res["failed"]) == (3, 2, 1), res
    for n, v in (("Uw_Drain_One", "v1"), ("Uw_Drain_Two", "v2")):
        assert props_of(n, ["uw_k"]) == {"uw_k": v}, n
    status = queue_status([a, b, bad.name])
    assert status == {"waiting": 0, "names": {a: "processed", b: "processed", bad.name: "failed"}}, status
    assert owd.drain_once(queue_dir(), graph())["files"] == 0


if __name__ == "__main__":
    only = set(sys.argv[1:])
    print("the universal write, on ladybug\n")
    try:
        for name, fn in sorted((k, v) for k, v in list(globals().items()) if k.startswith("t_")):
            if only and not any(name.startswith(o) for o in only):
                continue
            try:
                fn()
                PASS.append(name)
                print(f"  PASS  {name}")
            except AssertionError as exc:
                FAIL.append(name)
                print(f"  FAIL  {name}\n        {exc}")
            except Exception:
                import traceback
                FAIL.append(name)
                print(f"  ERROR {name}\n{traceback.format_exc()}")
    finally:
        if GRAPH is not None:
            GRAPH.close()
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    raise SystemExit(1 if FAIL else 0)
