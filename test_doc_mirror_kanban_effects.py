"""Markers for the doc-mirror board's release-effect handlers.

Run as a script from the repo root: python3 test_doc_mirror_kanban_effects.py

The handler is dispatched by the observation worker inside its drain loop, so the property that
matters most is that it NEVER RAISES — a handler that throws would be swallowed by the daemon's
own guard and the failure would be invisible. Every case here drives the real functions; the graph
connection and the board library are the only things faked.
"""

import sys
import tempfile
from pathlib import Path

from carton_mcp.doc_mirror_kanban_effects import (
    board_of, kanban_lib, ratchet_on_build_freed)

FAILURES = []


def check(marker, condition, detail=""):
    """Record one marker.

    Args:
        marker: What is being asserted.
        condition: The result of asserting it.
        detail: What was seen instead, when the condition is false.
    """
    print(f"{'PASS' if condition else 'FAIL'}  {marker}" + (f"  -- {detail}" if not condition and detail else ""))
    if not condition:
        FAILURES.append(marker)


class FakeConnection:
    """A graph connection that returns rows it was handed."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute_query(self, query, params=None):
        self.queries.append((query, params))
        return self.rows


class RaisingConnection:
    """A graph connection whose every query fails."""

    def execute_query(self, query, params=None):
        raise RuntimeError("store is unreachable")


def t_board_of_returns_none_without_a_connection():
    check("board_of with no connection answers None, never a guess",
          board_of("Doc_Mirror_Lane_Transition_X", None) is None)


def t_board_of_reads_the_board_through_the_card():
    conn = FakeConnection([{"board": "f7d6e53e-b371"}])
    got = board_of("Doc_Mirror_Lane_Transition_X", conn)
    check("board_of returns the endeavor", got == "f7d6e53e-b371", got)
    check("board_of reads the transition's OWN board field first, because a relationship target "
          "is name-normalized on write and a hex endeavor id does not survive it (issue #723)",
          "t.board" in conn.queries[0][0], conn.queries[0][0])
    check("board_of still falls back to the HAS_CARD join when the field is absent",
          "HAS_CARD" in conn.queries[0][0], conn.queries[0][0])


def t_board_of_returns_none_when_no_row():
    check("board_of answers None when the transition names no card",
          board_of("Doc_Mirror_Lane_Transition_X", FakeConnection([])) is None)


def t_handler_reports_when_there_is_no_board():
    out = ratchet_on_build_freed("Doc_Mirror_Lane_Transition_X", FakeConnection([]))
    check("the handler says so when the transition names no card on a board",
          "no card on a board" in out, out)


def t_handler_never_raises_on_a_dead_store():
    out = ratchet_on_build_freed("Doc_Mirror_Lane_Transition_X", RaisingConnection())
    check("a dead store is RETURNED as a failure line, never raised",
          isinstance(out, str) and "ratchet failed" in out, out)


def t_handler_reports_a_pull(monkey):
    out = ratchet_on_build_freed("Doc_Mirror_Lane_Transition_X",
                                 FakeConnection([{"board": "board-1"}]))
    check("a pull is reported with its sprint and its counts",
          "sprint Doc_Mirror_Task_1 -> build" in out and "2 moved" in out and "1 skipped" in out,
          out)


def t_handler_reports_when_nothing_was_pulled(monkey):
    out = ratchet_on_build_freed("Doc_Mirror_Lane_Transition_X",
                                 FakeConnection([{"board": "board-1"}]))
    check("a ratchet that declines to pull is reported, not treated as a failure",
          "nothing pulled" in out, out)


def t_kanban_lib_raises_when_the_library_is_absent():
    import carton_mcp.doc_mirror_kanban_effects as mod
    saved_cache, saved_root = mod._kanban, mod.os.environ.get("DOCMIRROR_MONOREPO")
    mod._kanban = None
    with tempfile.TemporaryDirectory() as empty:
        mod.os.environ["DOCMIRROR_MONOREPO"] = empty
        try:
            kanban_lib()
            check("kanban_lib raises ImportError when the board library is not there", False,
                  "it returned instead of raising")
        except ImportError as e:
            check("kanban_lib raises ImportError naming the path it looked at",
                  "doc-mirror-system/plugin/lib" in str(e), str(e))
        except Exception as e:
            check("kanban_lib raises ImportError when the board library is not there", False,
                  f"{type(e).__name__}: {e}")
    mod._kanban = saved_cache
    if saved_root is None:
        mod.os.environ.pop("DOCMIRROR_MONOREPO", None)
    else:
        mod.os.environ["DOCMIRROR_MONOREPO"] = saved_root


class FakeKanban:
    """The board library, answering a fixed ratchet result."""

    def __init__(self, result):
        self.result = result
        self.boards = []

    def ratchet(self, board):
        self.boards.append(board)
        return self.result


def main():
    """Run every marker and exit non-zero on any failure."""
    import carton_mcp.doc_mirror_kanban_effects as mod

    t_board_of_returns_none_without_a_connection()
    t_board_of_reads_the_board_through_the_card()
    t_board_of_returns_none_when_no_row()
    t_handler_reports_when_there_is_no_board()
    t_handler_never_raises_on_a_dead_store()

    mod._kanban = FakeKanban({"sprint": "Doc_Mirror_Task_1",
                              "moved": ["Doc_Mirror_Task_1", "Doc_Mirror_Task_2"],
                              "skipped": [{"id": "Doc_Mirror_Task_3", "lane": "archived"}]})
    t_handler_reports_a_pull(mod)

    mod._kanban = FakeKanban(None)
    t_handler_reports_when_nothing_was_pulled(mod)

    mod._kanban = None
    t_kanban_lib_raises_when_the_library_is_absent()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        sys.exit(1)
    print("all markers passed")


if __name__ == "__main__":
    main()
