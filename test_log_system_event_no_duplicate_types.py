"""Pins the type-shattering defect in log_system_event (found + fixed 2026-08-21).

PURE UNIT TEST — a fake connection captures the query and params. No neo4j, no daemon,
never production. Run as a SCRIPT from the repo root (the repo root IS the carton_mcp
package, matching test_carton_vault_payload.py).

THE DEFECT, measured on the live graph before the fix:
    log_system_event's query ended with

        CREATE (e)-[:IS_A]->(:Wiki {n: "System_Event"})

    CREATE, not MERGE — so every single call minted a BRAND NEW System_Event node.
    Result: 41,721 byte-identical System_Event nodes (one distinct description, one
    canonical, all stamped 2026-02-26), each receiving exactly one IS_A edge from a
    correctly-named instance like System_Event_2026_07_04T05_17_47_linker_batch.

    The instances were innocent — properly timestamped instance names, correctly
    claiming is_a the universal. The UNIVERSAL was shattered into 41,721 private
    copies, so `is_a System_Event` converged on nothing.

    Isaac, verbatim: "there should be *ZERO DUPLICATES* because all these things *ARE
    THEMSELVES*... there are *zero instances* with universal names because instances
    have instance names and are typed being isa other things that progressively
    universalize". A universal IS ITSELF: exactly one node.

THE SECOND DEFECT in the same function: the instance name used SECOND resolution
    (%Y_%m_%dT%H_%M_%S), so two events in the same second got the SAME name and the
    CREATE made two nodes for them. Measured: System_Event_2026_07_19T04_59_59_
    timeline_merge existed 77 times. Fixed with microsecond resolution.

WHY THE INSTANCE IS STILL `CREATE`d AND THAT IS CORRECT: each event genuinely is a new
    thing. Merging instances on name would COLLAPSE distinct events and lose data. Only
    the TYPE is merged. Test 3 guards that distinction so a future "fix" doesn't
    over-merge in the name of deduplication.

NOT COVERED HERE: the ~43,683 duplicate nodes already in the graph. This stops the
    bleeding; the dedupe and the :Wiki uniqueness constraint are separate, authorized
    operations on live data.
"""

import re

from observation_worker_daemon import log_system_event


class FakeConn:
    """Captures execute_query calls instead of touching a database."""

    def __init__(self):
        self.calls = []

    def execute_query(self, query, params=None):
        self.calls.append((query, params or {}))
        return []


def _one_call():
    conn = FakeConn()
    log_system_event(conn, "linker_batch", "Auto-linked 3 descriptions", "linker")
    assert len(conn.calls) == 1, f"expected exactly one query, got {len(conn.calls)}"
    return conn.calls[0]


def test_the_type_node_is_merged_never_created():
    """THE DEFECT PIN: a CREATE of the System_Event type node must never come back."""
    query, _ = _one_call()

    bad = re.search(r'CREATE\s*\([^)]*\)\s*-\s*\[:IS_A\]\s*->\s*\(\s*:Wiki', query)
    assert bad is None, (
        "the type-shattering defect is BACK: the query CREATEs its IS_A target inline. "
        "That mints a fresh System_Event node on every call — it produced 41,721 "
        "identical copies before. MERGE the type node and point IS_A at it."
    )

    assert re.search(r'MERGE\s*\(\s*\w+\s*:Wiki\s*\{\s*n\s*:\s*"System_Event"\s*\}', query), (
        "the System_Event type node is not MERGEd by name — a universal must resolve "
        "to exactly one node."
    )


def test_the_instance_is_still_created_not_merged():
    """THE CONTROL: do not over-merge. Distinct events must stay distinct nodes.

    Without this, a future 'dedupe everything' change could MERGE instances on name and
    silently collapse separate events into one, losing every description but the first.
    """
    query, _ = _one_call()
    assert re.search(r'CREATE\s*\(\s*e\s*:Wiki\s*\{\s*n\s*:\s*\$name', query), (
        "the event INSTANCE is no longer CREATEd — if it is now MERGEd on name, "
        "genuinely distinct events will be collapsed into one node."
    )


def test_two_events_in_the_same_second_get_different_names():
    """THE SECOND DEFECT PIN: second-resolution names collided (77 dupes measured)."""
    _, p1 = _one_call()
    _, p2 = _one_call()
    assert p1["name"] != p2["name"], (
        f"two events produced the SAME instance name ({p1['name']!r}) — second-"
        "resolution timestamps are back and same-second events will duplicate."
    )


def test_instance_name_keeps_the_queryable_prefix():
    """Readers select these by prefix; microseconds must not break that."""
    _, params = _one_call()
    assert params["name"].startswith("System_Event_"), params["name"]
    assert params["name"].endswith("_linker_batch"), params["name"]


def test_a_failure_is_swallowed_and_never_kills_the_daemon():
    """log_system_event runs inside the daemon loop; a dead graph must not kill it.

    Asserts the OBSERVABLE consequences rather than merely 'it did not raise': the call
    is attempted against a live-looking connection, and a None connection short-circuits
    before any query is built.
    """
    class Exploding:
        def __init__(self):
            self.attempts = 0

        def execute_query(self, *a, **k):
            self.attempts += 1
            raise RuntimeError("neo4j down")

    boom = Exploding()
    try:
        log_system_event(boom, "linker_batch", "desc", "linker")
    except Exception as e:
        raise AssertionError(
            f"log_system_event let {type(e).__name__} escape into the daemon loop: {e}"
        )
    assert boom.attempts == 1, (
        f"expected exactly one attempted write before the failure, got {boom.attempts}"
    )

    # A missing connection must short-circuit — nothing built, nothing attempted.
    quiet = FakeConn()
    log_system_event(None, "linker_batch", "desc", "linker")
    assert quiet.calls == [], "a None connection must not produce any query"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = []
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed.append(fn.__name__)
            print(f"  FAIL  {fn.__name__}  <- {e}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    if failed:
        print("FAILED:", ", ".join(failed))
        raise SystemExit(1)
