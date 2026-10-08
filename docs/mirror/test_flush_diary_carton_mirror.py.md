# doc(m): test_flush_diary_carton_mirror.py

- **Canonical path:** /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_flush_diary_carton_mirror.py
- **Line count:** 178 (measured, wc -l)
- **Last derived:** 2026-08-28 — NET-NEW test, doc(m) derived as part of the build (issue #118 leg 2).
- **Module role:** the unit surface for `substrate_projector.flush_starlog_diary`'s carton mirror —
  proves the dragonbones diary lane now reaches BOTH the registry and the graph, with the agent
  lane's pass-1 mirror shape, in full isolation (no neo4j, no daemon, no :8091).

## What this test IS (from the code)

Script mode at the repo root (the repo root IS the carton_mcp package; the
test_sync_task_kanban_card.py convention). Isolation:
- `FakeGraph` rides as `shared_connection` — `CartOnUtils(shared_connection=...)` routes the read
  query to `execute_query`, answering the handler's "RETURN c.d AS descr" query with one row.
- `starlog_mcp.starlog.add_concept_tool_func` is replaced with a recorder (the
  test_diary_type_join.py capture shape) — zero graph writes; the captured kwargs ARE the mirror
  artifacts asserted on.
- `starlog_mcp.starlog_sessions.detect_starsystems_for_entry` is patched to a fixed
  {project: path} routing (the handler imports it inside the function, after the patch).
- Registry rows land under a per-run unique project name (heaven's RegistryService caches its data
  dir at import — the join test's measured caveat).

Checks (14): T1 handler return names the mirror node; T1b the registry row exists with
entry_type=bug / source=dragonbones / concept_ref (the registry lane untouched); T2/T2a-c the diary
node carries entry_type/source as properties, is_a Debug_Diary_Entry, related_to the source concept,
part_of Starlog_Project_; T3/T3a-c the content node is_a Desc_Content + part_of the diary node with
the prose in its DESCRIPTION, and no relationship target anywhere is prose-length (>120 chars);
T4 no-starsystem-context → skip with zero mirror writes; T5 starlog unimportable
(sys.modules[...]=None) → graceful "starlog unavailable" skip with zero writes; T6a a graph
explosion is absorbed INSIDE query_wiki_graph (success=False reads as the "not found" skip — the
measured behavior, not the handler's except branch); T6b a raising registry save
(`_save_debug_diary_entry` re-raises) → "starlog-diary error" string, never an exception.

## Status markers

- IS: ALL_PASS 14/14 on 2026-08-28.
- IS: run alongside starlog-mcp's tests/test_diary_type_join.py (ALL_PASS same day) — the two
  suites pin the agent lane and the dragonbones lane to the SAME mirror shape.
