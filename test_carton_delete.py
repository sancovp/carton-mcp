"""test_carton_delete — the gate for carton's concept delete (card 816, issue 1301).

Run as a SCRIPT from the repo root (`python3 test_carton_delete.py`); the repo root IS the `carton_mcp`
package. Every case runs on synthetic records and a fake statement runner: nothing opens a socket.
"""
import json
import sys
import tempfile
import traceback
from pathlib import Path

import carton_delete as cd

FAILURES = []


def check(marker, fn):
    try:
        fn()
        print(f"  ✅ {marker}")
    except Exception as exc:
        print(f"  ❌ {marker} — {type(exc).__name__}: {exc}")
        print("     " + traceback.format_exc().strip().splitlines()[-2].strip())
        FAILURES.append(marker)


def rec(name, outbound=(), inbound=()):
    return {"name": name, "exists": True, "props": {"n": name, "d": f"{name} text"},
            "outbound": [{"rel": r, "target": t} for r, t in outbound],
            "inbound": [{"rel": r, "source": s} for r, s in inbound]}


def m1_missing_name_is_refused():
    plan = cd.plan_deletion(["Ghost"], {"Ghost": {"name": "Ghost", "exists": False}})
    assert plan["delete"] == [], (
        "INVARIANT: a name no node holds is never planned for deletion. FIX: plan_deletion refuses a record "
        f"whose exists is false; got delete={plan['delete']}")
    assert "Ghost" in plan["refused"] and "no node" in plan["refused"]["Ghost"], (
        "INVARIANT: the refusal names why. FIX: refused[name] says no node is named that; "
        f"got {plan['refused']}")


def m2_cited_from_outside_is_refused():
    records = {"Probe": rec("Probe", outbound=[("IS_A", "Momentum")],
                            inbound=[("HAS_INSTANCES", "Momentum"), ("SYNTHESIZES", "Day_Synthesis")])}
    plan = cd.plan_deletion(["Probe"], records)
    assert plan["delete"] == [], (
        "INVARIANT: a node another node outside the batch cites is kept, so deleting junk never cuts a "
        f"record that points at it. FIX: refuse on any inbound edge from outside; got delete={plan['delete']}")
    reason = plan["refused"].get("Probe", "")
    assert "Day_Synthesis" in reason and "SYNTHESIZES" in reason, (
        "INVARIANT: the refusal names the citing node and its edge, so the keeper is visible. FIX: "
        f"refused[name] carries source and rel; got {reason!r}")


def m3_reciprocal_and_batch_edges_do_not_cite():
    records = {
        "Probe_A": rec("Probe_A", outbound=[("IS_A", "Momentum"), ("PART_OF", "Momentum_Domain")],
                       inbound=[("HAS_INSTANCES", "Momentum"), ("HAS_PART", "Momentum_Domain"),
                                ("ANNOTATES", "Probe_B")]),
        "Probe_B": rec("Probe_B", outbound=[("IS_A", "Momentum"), ("ANNOTATES", "Probe_A")],
                       inbound=[("HAS_INSTANCES", "Momentum")]),
    }
    plan = cd.plan_deletion(["Probe_A", "Probe_B"], records)
    assert plan["delete"] == ["Probe_A", "Probe_B"] and plan["refused"] == {}, (
        "INVARIANT: an inbound edge from a node this node points back at (IS_A beside HAS_INSTANCES, PART_OF "
        "beside HAS_PART) or from another batch member is not a citation. FIX: skip inbound sources in the "
        f"batch or among the node's own outbound targets; got {plan}")


def m4_cited_by_a_refused_member_is_refused():
    records = {
        "Kept": rec("Kept", outbound=[("ANNOTATES", "Leaf")], inbound=[("SYNTHESIZES", "Day_Synthesis")]),
        "Leaf": rec("Leaf", inbound=[("ANNOTATES", "Kept")]),
    }
    plan = cd.plan_deletion(["Kept", "Leaf"], records)
    assert plan["delete"] == [], (
        "INVARIANT: a member that a REFUSED member cites is cited by a node that stays, so it stays too. "
        f"FIX: recompute the batch until no refusal changes it; got delete={plan['delete']}")
    assert set(plan["refused"]) == {"Kept", "Leaf"}, f"both refused, got {plan['refused']}"


class FakeRunner:
    def __init__(self, rows, wiki_dir, events):
        self.rows, self.wiki_dir, self.events, self.statements = rows, wiki_dir, events, []

    def __call__(self, statements):
        self.statements.extend(statements)
        query = statements[0][0]
        if "DETACH DELETE" in query:
            self.events.append(("delete", list(statements[0][1]["names"]),
                                (self.wiki_dir / "Probe").exists()))
            return [[]]
        return [self.rows]


def _world(tmp):
    """A wiki dir holding Probe's page, the records a store would answer, and a runner logging into events."""
    wiki = Path(tmp) / "wiki" / "concepts"
    (wiki / "Probe").mkdir(parents=True)
    (wiki / "Probe" / "Probe_itself.md").write_text("probe wiki text")
    rows = [rec("Probe", outbound=[("IS_A", "Momentum")], inbound=[("HAS_INSTANCES", "Momentum")]),
            rec("Cited", inbound=[("SYNTHESIZES", "Day_Synthesis")])]
    events = []
    return wiki, events, FakeRunner(rows, wiki, events)


def m5_executor_backs_up_then_deletes():
    with tempfile.TemporaryDirectory() as tmp:
        wiki, events, run = _world(tmp)
        report = cd.delete_concepts(["Probe", "Cited"], Path(tmp) / "backup", run=run, wiki_dir=wiki)
        assert events and events[0][1] == ["Probe"], (
            "INVARIANT: the delete statement names exactly the planned names and never a refused one. "
            f"FIX: run DELETE_NODES with plan['delete']; got {events}")
        backup = Path(report["backup"])
        saved = json.loads((backup / "records.json").read_text())
        assert set(saved) == {"Probe"} and saved["Probe"]["props"]["d"] == "Probe text", (
            "INVARIANT: every deleted node is backed up whole before the delete. FIX: write records.json with "
            f"each planned record; got {saved}")
        assert (backup / "wiki" / "Probe" / "Probe_itself.md").read_text() == "probe wiki text", (
            "INVARIANT: the wiki directory is copied into the backup. FIX: copytree each planned wiki dir")
        assert events[0][2] is True and not (wiki / "Probe").exists(), (
            "INVARIANT: the wiki directory is removed only after the node delete ran. FIX: rmtree after "
            f"the DETACH DELETE; wiki present at delete time={events[0][2]}")
        assert report["refused"].keys() == {"Cited"} and "SOMA" in report["not_touched"], (
            f"INVARIANT: the report names what was refused and what was not touched; got {report}")


def m6_dry_run_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        wiki, events, run = _world(tmp)
        report = cd.delete_concepts(["Probe"], Path(tmp) / "backup", run=run, wiki_dir=wiki, dry_run=True)
        assert events == [] and not (Path(tmp) / "backup").exists() and (wiki / "Probe").exists(), (
            "INVARIANT: a dry run reads and plans, and writes nothing. FIX: return the plan before any "
            f"backup or delete when dry_run; events={events}")
        assert report["delete"] == ["Probe"] and report["dry_run"] is True, f"got {report}"


if __name__ == "__main__":
    print("test_carton_delete")
    for marker, fn in [
        ("M1 a missing name is refused, naming why", m1_missing_name_is_refused),
        ("M2 a node cited from outside the batch is refused, naming the citing edge", m2_cited_from_outside_is_refused),
        ("M3 reciprocal and batch edges do not cite", m3_reciprocal_and_batch_edges_do_not_cite),
        ("M4 a member cited by a refused member is refused", m4_cited_by_a_refused_member_is_refused),
        ("M5 the executor backs up whole, deletes the plan, then removes the wiki dir", m5_executor_backs_up_then_deletes),
        ("M6 a dry run writes nothing", m6_dry_run_writes_nothing),
    ]:
        check(marker, fn)
    print(f"{6 - len(FAILURES)} of 6 passed")
    sys.exit(1 if FAILURES else 0)
