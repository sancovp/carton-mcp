"""Unit test for substrate_projector.sync_task_kanban_card (issue #148 — the TK join half).

Script mode (the repo convention — the repo root IS the carton_mcp package):

    python3 test_sync_task_kanban_card.py

Covers the handler's whole decision tree with a FakeGraph (the test_edit_carton_obj
pattern) + a fake heaven_bml_sqlite client injected via sys.modules — no neo4j, no TK
HTTP API, no daemon. The env gate, the not-found gate, the client-availability gate,
create-when-absent, move-when-lane-differs, and unchanged-when-lane-matches.
"""

import os
import sys
import types

from substrate_projector import sync_task_kanban_card


class FakeGraph:
    """Minimal stand-in for KnowledgeGraphBuilder: one task row for the read query."""

    def __init__(self, row):
        self.row = row
        self.queries = []

    def execute_query(self, query, params=None):
        self.queries.append((query, params))
        if "RETURN t.d AS text" in query:
            return [self.row] if self.row is not None else []
        return []


class FakeTKClient:
    """Stand-in for HeavenBMLSQLiteClient recording calls."""

    cards = []
    calls = []

    def __init__(self, api_url=None):
        pass

    def get_all_cards(self, board):
        FakeTKClient.calls.append(("get_all_cards", board))
        return list(FakeTKClient.cards)

    def create_card(self, board, title="", description="", lane="backlog", tags=None):
        FakeTKClient.calls.append(("create_card", board, title, lane, tags))
        return {"id": 99, "status": lane}

    def _make_request(self, method, endpoint, data=None):
        FakeTKClient.calls.append(("request", method, endpoint, data))
        return {"ok": True}


def _install_fake_tk():
    pkg = types.ModuleType("heaven_bml_sqlite")
    mod = types.ModuleType("heaven_bml_sqlite.heaven_bml_sqlite_client")
    mod.HeavenBMLSQLiteClient = FakeTKClient
    pkg.heaven_bml_sqlite_client = mod
    sys.modules["heaven_bml_sqlite"] = pkg
    sys.modules["heaven_bml_sqlite.heaven_bml_sqlite_client"] = mod


RESULTS = []


def check(label, ok, detail=""):
    RESULTS.append((label, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail else ""))


ROW = {"text": "Probe task text", "status": "in_progress", "repo": "Doc_Mirror_System", "ord": 3}

# ── T1: env gate — no board set → graceful skip, zero graph reads ───────────
os.environ.pop("CARTON_TASK_TREEKANBAN_BOARD", None)
g = FakeGraph(ROW)
out = sync_task_kanban_card("Task_Probe_1", shared_connection=g)
check("T1 env gate: no board -> skip message, no graph query",
      "CARTON_TASK_TREEKANBAN_BOARD not set" in out and not g.queries, out)

# ── T2: node not found → skip ───────────────────────────────────────────────
os.environ["CARTON_TASK_TREEKANBAN_BOARD"] = "test_board"
_install_fake_tk()
out = sync_task_kanban_card("Task_Probe_Missing", shared_connection=FakeGraph(None))
check("T2 node not found -> skip", "not found" in out, out)

# ── T3: no existing card → create in lane == status ─────────────────────────
FakeTKClient.cards = []
FakeTKClient.calls = []
out = sync_task_kanban_card("Task_Probe_1", shared_connection=FakeGraph(ROW))
created = [c for c in FakeTKClient.calls if c[0] == "create_card"]
check("T3 absent card -> created in lane == status (in_progress)",
      "created card" in out and created and created[0][3] == "in_progress"
      and "Task_Probe_1" in (created[0][4] or []), out)

# ── T4: existing card, different lane → moved via PUT with status == lane ───
FakeTKClient.cards = [{"id": 7, "status": "open", "tags": ["Task_Probe_1", "carton_task"]}]
FakeTKClient.calls = []
out = sync_task_kanban_card("Task_Probe_1", shared_connection=FakeGraph(ROW))
puts = [c for c in FakeTKClient.calls if c[0] == "request"]
check("T4 lane differs -> PUT /api/sqlite/cards/7 status=in_progress",
      "moved card 7" in out and puts and puts[0][2] == "/api/sqlite/cards/7"
      and puts[0][3].get("status") == "in_progress", out)

# ── T5: existing card, same lane → unchanged, no PUT ────────────────────────
FakeTKClient.cards = [{"id": 7, "status": "in_progress", "tags": ["Task_Probe_1"]}]
FakeTKClient.calls = []
out = sync_task_kanban_card("Task_Probe_1", shared_connection=FakeGraph(ROW))
puts = [c for c in FakeTKClient.calls if c[0] == "request"]
check("T5 lane matches -> unchanged, zero PUTs", "unchanged" in out and not puts, out)

# ── T6: never raises — a client blowing up returns an error string ──────────
class ExplodingClient(FakeTKClient):
    def get_all_cards(self, board):
        raise RuntimeError("boom")

sys.modules["heaven_bml_sqlite.heaven_bml_sqlite_client"].HeavenBMLSQLiteClient = ExplodingClient
out = sync_task_kanban_card("Task_Probe_1", shared_connection=FakeGraph(ROW))
check("T6 client explosion -> error string, not an exception",
      out.startswith("task-kanban error") and "boom" in out, out)

os.environ.pop("CARTON_TASK_TREEKANBAN_BOARD", None)
print()
passed = sum(1 for _, ok in RESULTS if ok)
print(f"{passed}/{len(RESULTS)} passed")
print("ALL_PASS" if passed == len(RESULTS) else "SOME_FAILED")
