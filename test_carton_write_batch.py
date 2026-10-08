"""test_carton_write_batch — the unit gate for the multi-statement transactional write (issue 485).

Run as a SCRIPT from the repo root (`python3 test_carton_write_batch.py`) — the repo root IS the
`carton_mcp` package, this repo's own convention (test_carton_quota.py, test_carton_breaker.py,
test_carton_pathguard.py, test_carton_disclose.py all do it, and their rules say why).

Every case runs on SYNTHETIC FAKES. Nothing here opens a socket or touches a graph, which is the
point: the first caller of this module is the doc-mirror task board, so a test that needed a live
store could not be run by the thing it gates.

THE TWO CASES THAT MATTER MOST, because they are the ones a careless conversion silently loses:
a failing batch must ROLL BACK (M7), and an unreachable store must RAISE rather than return an
empty result (M8). docmirror_kanban's callers depend on both.
"""
import sys

import carton_write_batch as wb

FAILURES = []


def check(marker, condition, detail=""):
    if condition:
        print(f"  ✅ {marker}")
    else:
        print(f"  ❌ {marker} — {detail}")
        FAILURES.append(marker)


# --------------------------------------------------------------------------- fakes


class FakeTx:
    def __init__(self, rows_by_call=None, fail_on=None, raise_exc=None):
        self.ran = []
        self.committed = False
        self.rolled_back = False
        self._rows = rows_by_call or {}
        self._fail_on = fail_on
        self._raise = raise_exc or RuntimeError("boom")

    def run(self, query, **params):
        self.ran.append((query, params))
        if self._fail_on is not None and len(self.ran) - 1 == self._fail_on:
            raise self._raise
        return self._rows.get(len(self.ran) - 1, [])

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class FakeSession:
    def __init__(self, tx):
        self._tx = tx
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True
        return False

    def begin_transaction(self):
        return self._tx


class FakeDriver:
    def __init__(self, tx):
        self._tx = tx
        self.sessions = 0

    def session(self):
        self.sessions += 1
        return FakeSession(self._tx)


class FakeConn:
    """A connection WITH a driver — the neo4j-backed shape, so the batch is atomic."""

    def __init__(self, tx):
        self.driver = FakeDriver(tx)
        self.ensured = 0

    def _ensure_connection(self):
        self.ensured += 1


class FakeDriverlessConn:
    """A connection with NO driver — the kuzu-backed shape, so the batch is sequential."""

    def __init__(self, rows_by_call=None, fail_on=None, raise_exc=None):
        self.driver = None
        self.ran = []
        self.ensured = 0
        self._rows = rows_by_call or {}
        self._fail_on = fail_on
        self._raise = raise_exc or RuntimeError("boom")

    def _ensure_connection(self):
        self.ensured += 1

    def execute_query(self, query, params=None):
        self.ran.append((query, params))
        if self._fail_on is not None and len(self.ran) - 1 == self._fail_on:
            raise self._raise
        return self._rows.get(len(self.ran) - 1, [])


class FakeUnreachable(Exception):
    """Stands in for neo4j.exceptions.ServiceUnavailable without importing the driver."""


# --------------------------------------------------------------------------- markers


def m1_validate_normalizes_a_good_batch():
    out = wb.validate_statements([("MATCH (n) RETURN n", {"a": 1}), ("CREATE (m)", None)])
    check("M1 returns (str, dict) pairs", out == [("MATCH (n) RETURN n", {"a": 1}), ("CREATE (m)", {})],
          f"got {out!r}")
    check("M1 a None params becomes an empty dict", out[1][1] == {})
    tup = wb.validate_statements((("CREATE (x)", {}),))
    check("M1 a tuple of tuples is accepted", tup == [("CREATE (x)", {})], f"got {tup!r}")


def m2_validate_is_loud_on_garbage():
    """A malformed batch must fail BEFORE the store is touched — never half-way through it."""
    bad = [
        "MATCH (n) RETURN n",                       # a bare string, not a sequence of pairs
        [("only-one-element",)],                    # a 1-tuple
        [("q", {}, "extra")],                       # a 3-tuple
        [(None, {})],                               # a non-str query
        [("   ", {})],                              # an empty query
        [("q", ["not", "a", "dict"])],              # non-dict params
        [("q", 7)],
    ]
    for item in bad:
        try:
            wb.validate_statements(item)
            check(f"M2 refuses {str(item)[:28]!r}", False, "it returned instead of raising")
        except wb.WriteStatementsInvalid:
            check(f"M2 refuses {str(item)[:28]!r}", True)
        except Exception as exc:
            check(f"M2 raises WriteStatementsInvalid for {str(item)[:28]!r}", False,
                  f"raised {type(exc).__name__}")


def m3_an_empty_batch_is_valid_and_writes_nothing():
    """Callers build statement lists conditionally, so an empty list is a real case, not garbage."""
    check("M3 validate accepts []", wb.validate_statements([]) == [])
    conn = FakeConn(FakeTx())
    check("M3 execute returns [] on an empty batch", wb.execute_write_statements([], conn) == [])
    check("M3 execute opened no session for an empty batch", conn.driver.sessions == 0)


def m4_atomicity_is_reported_not_assumed():
    check("M4 a driver-bearing connection is TRANSACTION",
          wb.atomicity_for(FakeConn(FakeTx())) == wb.TRANSACTION)
    check("M4 a driverless connection is SEQUENTIAL",
          wb.atomicity_for(FakeDriverlessConn()) == wb.SEQUENTIAL)
    check("M4 an object with no driver attribute at all is SEQUENTIAL",
          wb.atomicity_for(object()) == wb.SEQUENTIAL)


def m5_classify_error_separates_unreachable_from_everything_else():
    check("M5 an unreachable type classifies unreachable",
          wb.classify_error(FakeUnreachable("down"), (FakeUnreachable,)) == "unreachable")
    check("M5 any other error classifies other",
          wb.classify_error(ValueError("nope"), (FakeUnreachable,)) == "other")
    check("M5 with no known types nothing is unreachable",
          wb.classify_error(FakeUnreachable("down"), ()) == "other")


def m6_transaction_mode_runs_every_statement_in_one_transaction():
    tx = FakeTx(rows_by_call={0: [{"n": "a"}], 1: [{"n": "b"}, {"n": "c"}]})
    conn = FakeConn(tx)
    out = wb.execute_write_statements([("MERGE (a)", {"x": 1}), ("MERGE (b)", None)], conn)
    check("M6 one row-list per statement, in order",
          out == [[{"n": "a"}], [{"n": "b"}, {"n": "c"}]], f"got {out!r}")
    check("M6 both statements ran", len(tx.ran) == 2, f"ran {tx.ran!r}")
    check("M6 params are passed through", tx.ran[0][1] == {"x": 1})
    check("M6 a None params reaches the driver as no kwargs", tx.ran[1][1] == {})
    check("M6 exactly ONE session was opened", conn.driver.sessions == 1,
          f"opened {conn.driver.sessions}")
    check("M6 the transaction COMMITTED", tx.committed)
    check("M6 it did not roll back", not tx.rolled_back)
    check("M6 the connection was ensured first", conn.ensured == 1)


def m7_a_failing_batch_rolls_back_and_reraises():
    """THE GUARANTEE THE CONVERSION EXISTS TO PRESERVE. docmirror_kanban's update_card writes a
    lane change, its reason, its kind and the BLOCKED_BY replacement together, and its own comment
    says why: so a block never lands half-recorded."""
    tx = FakeTx(fail_on=1, raise_exc=ValueError("second statement is bad"))
    conn = FakeConn(tx)
    try:
        wb.execute_write_statements([("MERGE (a)", {}), ("BAD", {}), ("MERGE (c)", {})], conn)
        check("M7 a failing batch raises", False, "it returned instead of raising")
    except ValueError:
        check("M7 a failing batch raises the original error", True)
    except Exception as exc:
        check("M7 a failing batch raises the original error", False,
              f"raised {type(exc).__name__}")
    check("M7 the transaction ROLLED BACK", tx.rolled_back)
    check("M7 it did NOT commit", not tx.committed)
    check("M7 the third statement never ran", len(tx.ran) == 2, f"ran {len(tx.ran)}")


def m8_unreachable_raises_store_unavailable_never_an_empty_result():
    """An empty result on this surface reads as 'the store answered nothing'. A store that cannot
    be REACHED did not answer at all, and the two must never render the same."""
    real = wb._unreachable_types()
    if not real:
        check("M8 SKIPPED — the neo4j driver is not installed, so there are no types to raise",
              True)
        return
    unreachable = real[0]
    tx = FakeTx(fail_on=0, raise_exc=unreachable("connection refused"))
    conn = FakeConn(tx)
    try:
        wb.execute_write_statements([("MERGE (a)", {})], conn)
        check("M8 an unreachable store raises", False, "it returned instead of raising")
    except wb.WriteStoreUnavailable as exc:
        check("M8 raises WriteStoreUnavailable", True)
        check("M8 the refusal carries the driver's own error text",
              "connection refused" in str(exc), f"message was {exc}")
    except Exception as exc:
        check("M8 raises WriteStoreUnavailable", False, f"raised {type(exc).__name__}")
    check("M8 it rolled back on the way out", tx.rolled_back)

    # and on the ensure, before any statement runs
    class Dead(FakeConn):
        def _ensure_connection(self):
            raise unreachable("no route to host")

    try:
        wb.execute_write_statements([("MERGE (a)", {})], Dead(FakeTx()))
        check("M8 an unreachable ENSURE raises", False, "it returned instead of raising")
    except wb.WriteStoreUnavailable:
        check("M8 an unreachable ENSURE raises WriteStoreUnavailable", True)
    except Exception as exc:
        check("M8 an unreachable ENSURE raises WriteStoreUnavailable", False,
              f"raised {type(exc).__name__}")


def m9_sequential_mode_runs_in_order_through_execute_query():
    conn = FakeDriverlessConn(rows_by_call={0: [{"k": 1}], 1: []})
    out = wb.execute_write_statements([("MERGE (a)", {"p": 2}), ("MERGE (b)", None)], conn)
    check("M9 one row-list per statement", out == [[{"k": 1}], []], f"got {out!r}")
    check("M9 both statements ran in order",
          [q for q, _ in conn.ran] == ["MERGE (a)", "MERGE (b)"], f"ran {conn.ran!r}")
    check("M9 params pass through", conn.ran[0][1] == {"p": 2})
    check("M9 a None params became {}", conn.ran[1][1] == {})


def m10_no_connection_raises_rather_than_returning_empty():
    class NoDriverNoQuery:
        driver = None
    try:
        wb.execute_write_statements([("MERGE (a)", {})], NoDriverNoQuery())
        check("M10 a connection that cannot execute raises", False, "it returned")
    except wb.WriteStoreUnavailable:
        check("M10 a connection that cannot execute raises", True)
    except AttributeError:
        check("M10 a connection that cannot execute raises WriteStoreUnavailable, not AttributeError",
              False, "raised AttributeError")
    except Exception as exc:
        check("M10 a connection that cannot execute raises", False, f"raised {type(exc).__name__}")


def m11_the_pure_half_does_no_io_at_import():
    src = open(wb.__file__).read()
    head = src.split("def _unreachable_types")[0]
    for banned in ["import neo4j", "from neo4j", "GraphDatabase", "urllib", "requests",
                   "subprocess"]:
        check(f"M11 no {banned} above the lazy import", banned not in head,
              "the module must import cleanly on a backend with no driver installed")
    check("M11 the driver import is lazy and tolerant",
          "except ImportError" in src,
          "a driverless backend must not fail to import this module")


def main():
    for fn in [m1_validate_normalizes_a_good_batch,
               m2_validate_is_loud_on_garbage,
               m3_an_empty_batch_is_valid_and_writes_nothing,
               m4_atomicity_is_reported_not_assumed,
               m5_classify_error_separates_unreachable_from_everything_else,
               m6_transaction_mode_runs_every_statement_in_one_transaction,
               m7_a_failing_batch_rolls_back_and_reraises,
               m8_unreachable_raises_store_unavailable_never_an_empty_result,
               m9_sequential_mode_runs_in_order_through_execute_query,
               m10_no_connection_raises_rather_than_returning_empty,
               m11_the_pure_half_does_no_io_at_import]:
        print(f"\n{fn.__name__}")
        fn()
    print("\n" + ("=" * 60))
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} — {', '.join(FAILURES)}")
        return 1
    print("ALL MARKERS GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
