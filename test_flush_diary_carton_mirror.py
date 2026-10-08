"""Unit test for substrate_projector.flush_starlog_diary's carton mirror (issue #118 leg 2).

Script mode (the repo convention — the repo root IS the carton_mcp package):

    python3 test_flush_diary_carton_mirror.py

The dragonbones lane's typed diary rows reached ONLY the registry
(sl._save_debug_diary_entry); this proves the handler now ALSO mirrors to carton with
the agent lane's exact pass-1 mechanism (update_debug_diary, starlog_mcp.py): content
node first (is_a Desc_Content, prose in the DESCRIPTION), diary node second (is_a
Debug_Diary_Entry + has_content -> the content node + related_to -> the source
concept), entry_type/source as scratch-lane PROPERTIES, part_of the starlog project.

ISOLATION (the test_sync_task_kanban_card FakeGraph shape + the test_diary_type_join
capture shape): a FakeGraph rides as shared_connection (no neo4j read); the carton
writer starlog_mcp.starlog.add_concept_tool_func is REPLACED with a recorder (zero
graph writes); detect_starsystems_for_entry is patched to a fixed routing (no
filesystem walk); registry rows land under a per-run unique project name (heaven's
RegistryService caches its data dir at import — the join test's measured caveat).
"""

import json
import sys
import uuid

from substrate_projector import flush_starlog_diary


class FakeGraph:
    """Minimal stand-in for the shared connection: one concept row for the read query."""

    def __init__(self, row, explode=False):
        self.row = row
        self.explode = explode
        self.queries = []

    def execute_query(self, query, params=None):
        if self.explode:
            raise RuntimeError("boom")
        self.queries.append((query, params))
        if "RETURN c.d AS descr" in query:
            return [self.row] if self.row is not None else []
        return []


RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail else ""))


PROJ = f"flush_mirror_test_{uuid.uuid4().hex[:8]}"
ROW = {"descr": "Bug found in /home/GOD/somewhere/thing.py while tracing", "isa": ["Bug", "Concept"]}

import starlog_mcp.starlog as starlog_module
import starlog_mcp.starlog_sessions as sessions_module

captured = []
real_writer = starlog_module.add_concept_tool_func
real_detect = sessions_module.detect_starsystems_for_entry


def _capture_writer(**kwargs):
    captured.append(kwargs)
    return "captured (test stub — not written)"


starlog_module.add_concept_tool_func = _capture_writer
sessions_module.detect_starsystems_for_entry = lambda content, in_file: {PROJ: f"/tmp/{PROJ}"}

try:
    # ── T1: the handler writes the registry row AND returns the mirror node name ──
    out = flush_starlog_diary("Bug_Probe_Concept_X", shared_connection=FakeGraph(ROW))
    check("T1 handler succeeds and names the carton mirror node",
          out.startswith("starlog-diary bug for Bug_Probe_Concept_X") and "carton mirror: Debug_Diary_" in out,
          out)

    rows = starlog_module.Starlog()._get_registry_data(PROJ, "debug_diary")
    reg = [r for r in rows.values() if "Bug_Probe_Concept_X" in r.get("content", "")]
    check("T1b registry row exists (the registry lane is untouched)",
          len(reg) == 1 and reg[0].get("entry_type") == "bug"
          and reg[0].get("source") == "dragonbones"
          and reg[0].get("concept_ref") == "Bug_Probe_Concept_X",
          f"rows={len(reg)}")

    # ── T2: the diary node mirrors with the pass-1 identity shape ───────────────
    diary_calls = [c for c in captured if str(c.get("concept_name", "")).startswith("Debug_Diary_")
                   and not str(c.get("concept_name", "")).endswith("_Content")]
    check("T2 diary node written", len(diary_calls) == 1, f"captured {len(captured)} writer calls")
    diary_name = None
    if diary_calls:
        p = diary_calls[0]
        diary_name = p.get("concept_name")
        props = p.get("properties") or {}
        rels = p.get("relationships") or []
        rel_names = [rd.get("relationship") for rd in rels]
        targets = [t for rd in rels for t in rd.get("related", [])]
        check("T2a properties entry_type=bug / source=dragonbones",
              props.get("entry_type") == "bug" and props.get("source") == "dragonbones",
              json.dumps(props))
        check("T2b is_a Debug_Diary_Entry + related_to the source concept",
              "Debug_Diary_Entry" in targets and "related_to" in rel_names
              and "Bug_Probe_Concept_X" in targets,
              json.dumps(rels)[:240])
        check("T2c part_of the starlog project (project_name routing)",
              any(f"Starlog_Project_" in t for t in targets), json.dumps(rels)[:240])

    # ── T3: the content node (prose in the DESCRIPTION, identifier as the target) ──
    if diary_name:
        content_calls = [c for c in captured if c.get("concept_name") == f"{diary_name}_Content"]
        check("T3 content node written", len(content_calls) == 1,
              f"found {len(content_calls)}")
        if content_calls:
            cc = content_calls[0]
            c_targets = [t for rd in (cc.get("relationships") or []) for t in rd.get("related", [])]
            check("T3a content node is_a Desc_Content + part_of the diary node",
                  "Desc_Content" in c_targets and diary_name in c_targets,
                  json.dumps(cc.get("relationships"))[:200])
            check("T3b prose rides in the DESCRIPTION and matches the diary node's",
                  cc.get("description") == diary_calls[0].get("description") and bool(cc.get("description")),
                  repr(cc.get("description"))[:120])
        overlong = [t for c in captured for rd in (c.get("relationships") or [])
                    for t in rd.get("related", []) if len(str(t)) > 120]
        check("T3c no relationship target is prose (none over 120 chars)", not overlong,
              f"offenders: {[str(t)[:60] for t in overlong]}")

    # ── T4: no starsystem context → skip, no mirror ────────────────────────────
    sessions_module.detect_starsystems_for_entry = lambda content, in_file: {}
    before = len(captured)
    out = flush_starlog_diary("Bug_Probe_Concept_X", shared_connection=FakeGraph(ROW))
    check("T4 no starsystem context -> skip, zero mirror writes",
          "no starsystem context" in out and len(captured) == before, out)
    sessions_module.detect_starsystems_for_entry = lambda content, in_file: {PROJ: f"/tmp/{PROJ}"}

    # ── T5: starlog unavailable → graceful no-op (the ImportError contract) ────
    saved_mod = sys.modules.pop("starlog_mcp.starlog")
    sys.modules["starlog_mcp.starlog"] = None  # forces ImportError on the from-import
    try:
        before = len(captured)
        out = flush_starlog_diary("Bug_Probe_Concept_X", shared_connection=FakeGraph(ROW))
        check("T5 starlog unavailable -> graceful skip string, zero writes",
              "starlog unavailable" in out and len(captured) == before, out)
    finally:
        sys.modules["starlog_mcp.starlog"] = saved_mod

    # ── T6: never raises — the handler's own except branch ─────────────────────
    # A graph explosion is absorbed INSIDE query_wiki_graph (it returns success=False,
    # measured on the first run of this test: the handler reads it as a graceful
    # "not found" skip). To exercise the handler's OWN try/except, make the registry
    # save raise — _save_debug_diary_entry re-raises (`raise e`), so this is a real
    # exception crossing the handler's body.
    out = flush_starlog_diary("Bug_Probe_Concept_X", shared_connection=FakeGraph(ROW, explode=True))
    check("T6a graph explosion is absorbed by query_wiki_graph -> graceful skip string",
          out.startswith("starlog-diary skipped"), out)

    real_save = starlog_module.Starlog._save_debug_diary_entry

    def _exploding_save(self, project_name, entry):
        raise RuntimeError("boom")

    starlog_module.Starlog._save_debug_diary_entry = _exploding_save
    try:
        out = flush_starlog_diary("Bug_Probe_Concept_X", shared_connection=FakeGraph(ROW))
        check("T6b registry-save explosion -> error string, not an exception",
              out.startswith("starlog-diary error") and "boom" in out, out)
    finally:
        starlog_module.Starlog._save_debug_diary_entry = real_save

finally:
    starlog_module.add_concept_tool_func = real_writer
    sessions_module.detect_starsystems_for_entry = real_detect

print()
passed = sum(1 for _, ok in RESULTS if ok)
print(f"{passed}/{len(RESULTS)} passed")
print("ALL_PASS" if passed == len(RESULTS) else "SOME_FAILED")
