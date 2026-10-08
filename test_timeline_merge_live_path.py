"""_process_timeline_merge — the LIVE-path timeline-merge handler (issue-61 follow-on,
2026-07-19). Run as a SCRIPT (repo root IS the carton_mcp package; the
test_carton_kv.py flat-import convention).

Pins: success path issues the transfer + delete queries and returns True; missing
fields / no graph / query explosion return False (caller dead-letters); the moot
case (unnamed already gone) still succeeds so stale merges self-clear.
"""
import observation_worker_daemon as owd


class StubGraph:
    def __init__(self, raise_on=None, transferred=3, real_exists=True):
        self.queries = []
        self.raise_on = raise_on
        self.transferred = transferred
        # models whether the real conversation node is actually in the graph -- the handler
        # refuses to DETACH DELETE the placeholder when it is not (see the absent-target test).
        self.real_exists = real_exists

    def execute_query(self, q, params=None):
        self.queries.append((q.strip().split("\n")[0], params))
        if self.raise_on and self.raise_on in q:
            raise RuntimeError("boom")
        if "transferred" in q:
            return [{"transferred": self.transferred}]
        if "count(r) AS n" in q:
            return [{"n": 1 if self.real_exists else 0}]
        return []


def test_success_transfers_and_deletes():
    g = StubGraph()
    ok = owd._process_timeline_merge(
        {"timeline_merge": True, "unnamed_concept": "Unnamed_X", "real_concept": "Conversation_Y"}, g)
    assert ok is True
    assert any("CREATED_DURING" in q for q, _ in g.queries)
    assert any("DETACH DELETE" in q for q, _ in g.queries)
    print("PASS success_transfers_and_deletes")


def test_moot_merge_still_succeeds():
    # unnamed already gone: transfer matches nothing (count 0), delete no-ops -> True
    g = StubGraph(transferred=0)
    ok = owd._process_timeline_merge(
        {"timeline_merge": True, "unnamed_concept": "Unnamed_Gone", "real_concept": "Conversation_Y"}, g)
    assert ok is True
    print("PASS moot_merge_still_succeeds")


def test_missing_fields_or_graph_fail():
    assert owd._process_timeline_merge({"timeline_merge": True, "real_concept": "C"}, StubGraph()) is False
    assert owd._process_timeline_merge({"timeline_merge": True, "unnamed_concept": "U"}, StubGraph()) is False
    assert owd._process_timeline_merge(
        {"timeline_merge": True, "unnamed_concept": "U", "real_concept": "C"}, None) is False
    print("PASS missing_fields_or_graph_fail")


def test_query_explosion_returns_false():
    g = StubGraph(raise_on="CREATED_DURING")
    ok = owd._process_timeline_merge(
        {"timeline_merge": True, "unnamed_concept": "U", "real_concept": "C"}, g)
    assert ok is False
    print("PASS query_explosion_returns_false")


class TypeAwareStubGraph(StubGraph):
    """Reports PART_OF alongside CREATED_DURING so the ALL-TYPES transfer can be pinned.

    The 2026-08-24 bug this pins: the handler moved ONLY CREATED_DURING and then ran DETACH DELETE,
    which destroys every other edge on the placeholder. Measured live at the time: 95 CREATED_DURING
    (moved) plus PART_OF / HAS_PART / HAS_INSTANCES (silently destroyed). That is real loss -- the
    doc-mirror journal positions its entries in the active conversation via part_of, and during the
    first window the active conversation IS the placeholder, so every entry written before a
    precompact assigned real_concept lost its position at the next compaction with nothing reporting
    it. There was no test on the non-CREATED_DURING path, which is why it survived.
    """

    def execute_query(self, q, params=None):
        self.queries.append((q.strip().split("\n")[0], params))
        if self.raise_on and self.raise_on in q:
            raise RuntimeError("boom")
        if "transferred" in q:
            return [{"transferred": self.transferred}]
        if "DISTINCT type(r)" in q:
            return [{"t": "CREATED_DURING"}, {"t": "PART_OF"}, {"t": "lower_case_bad"}]
        if "count(x) AS n" in q:
            return [{"n": 2}]
        if "count(r) AS n" in q:
            return [{"n": 1 if self.real_exists else 0}]
        return []


def test_non_created_during_edges_are_transferred_before_delete():
    g = TypeAwareStubGraph()
    ok = owd._process_timeline_merge(
        {"timeline_merge": True, "unnamed_concept": "Unnamed_X", "real_concept": "Conversation_Y"}, g)
    assert ok is True
    qs = [q for q, _ in g.queries]
    # PART_OF must be MOVED, not just deleted with the node
    assert any("PART_OF" in q and "MERGE" in q for q in qs), "PART_OF was never transferred"
    # and the move must happen BEFORE the node is detached
    move_at = min(i for i, q in enumerate(qs) if "PART_OF" in q and "MERGE" in q)
    del_at = min(i for i, q in enumerate(qs) if "DETACH DELETE" in q)
    assert move_at < del_at, "PART_OF moved AFTER the delete -- the edge is already gone"
    # a non-conforming type name must never be interpolated into Cypher
    assert not any("lower_case_bad" in q for q in qs), "unsanitised relationship type interpolated"
    print("PASS non_created_during_edges_are_transferred_before_delete")


def test_absent_real_target_refuses_to_delete():
    """The completion of the edge-loss fix: if the real conversation is not in the graph, every
    transfer above matched nothing (they all MATCH real), so deleting the placeholder would destroy
    its PART_OF edges with nowhere to have moved them. Must refuse and dead-letter instead."""
    g = TypeAwareStubGraph(real_exists=False)
    ok = owd._process_timeline_merge(
        {"timeline_merge": True, "unnamed_concept": "Unnamed_X", "real_concept": "Conversation_Gone"}, g)
    assert ok is False, "absent target must dead-letter, not succeed"
    assert not any("DETACH DELETE" in q for q, _ in g.queries), \
        "placeholder was DELETED even though the merge target does not exist -- edges lost"
    print("PASS absent_real_target_refuses_to_delete")


# The runner lives at the BOTTOM so a test appended to this file is reached by it.
# 2026-08-24: it used to sit above TypeAwareStubGraph, so the edge-loss test added that day
# -- the one pinning the DETACH DELETE data-loss fix -- was never called by the script run.
# The gate printed "ALL 4 PASS" and the fix sat unpinned. Add a test ABOVE this block, and
# add its call to the list.
if __name__ == "__main__":
    # log_system_event touches the graph; stub it out so tests stay pure
    owd.log_system_event = lambda *a, **k: None
    test_success_transfers_and_deletes()
    test_moot_merge_still_succeeds()
    test_missing_fields_or_graph_fail()
    test_query_explosion_returns_false()
    test_non_created_during_edges_are_transferred_before_delete()
    test_absent_real_target_refuses_to_delete()
    print("ALL 6 PASS")
