"""carton_mirror against a REAL neo4j — a throwaway one of your own, never neo4j_rag.

Run: CARTON_MIRROR_TEST_NEO4J=bolt://127.0.0.1:7690 CARTON_MIRROR_TEST_PASSWORD=<pw> python3 test_carton_mirror.py
Without CARTON_MIRROR_TEST_NEO4J every test is SKIPPED — a skipped run proves nothing about the graph.
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

URI = os.environ.get("CARTON_MIRROR_TEST_NEO4J", "")
spec = importlib.util.spec_from_file_location("carton_mirror", Path(__file__).with_name("carton_mirror.py"))
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)


class Conn:
    """what the server's shared connection offers carton_mirror: a driver and _ensure_connection"""
    def __init__(self):
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(URI, auth=("neo4j", os.environ.get("CARTON_MIRROR_TEST_PASSWORD", "")))

    def _ensure_connection(self):
        pass


@unittest.skipUnless(URI and "7687" not in URI, "CARTON_MIRROR_TEST_NEO4J is not set (or names 7687): the graph is NOT tested")
class TheMirrorOnTheGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = Conn()
        with cls.conn.driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")

    def call(self, function, records, gone=None, location="loc1", answer=None):
        return cm.write(self.conn, "record_call", {"function": function, "location": location, "args": {"x": 1},
                                                   "exchanges": [{"method": "GET", "url": "u", "status": 200}],
                                                   "status": 200, "ok": True, "error": None, "answer": answer or {},
                                                   "ms": 5, "records": records, "gone": gone})

    def test_a_record_is_a_concept_with_its_type_its_sub_account_and_a_version_only_when_it_changed(self):
        first = self.call("contacts.get_contact", [["contact", "AbC1", {"id": "AbC1", "firstName": "Ada"}]])
        self.call("contacts.get_contact", [["contact", "AbC1", {"id": "AbC1", "firstName": "Ada"}]])
        self.call("contacts.get_contact", [["contact", "AbC1", {"id": "AbC1", "firstName": "Grace"}]])
        self.call("contacts.search", [["contact", "AbC1", {"id": "AbC1", "firstName": "Grace", "x": 1}]])  # another shape
        self.call("contacts.search", [["contact", "AbC1", {"id": "AbC1", "firstName": "Grace", "x": 1}]])
        v = cm.read(self.conn, "versions", {"kind": "contact", "id": "AbC1"})
        self.assertEqual([x["data"]["firstName"] for x in v], ["Ada", "Grace", "Grace"])
        self.assertEqual(cm.read(self.conn, "current", {"kind": "contact"}), [{"id": "AbC1", "firstName": "Grace", "x": 1}])
        name = cm.record_name("contact", "AbC1")
        with self.conn.driver.session() as s:
            row = s.run("MATCH (c:Wiki {n: $n})-[:IS_A]->(t), (c)-[:PART_OF]->(sa) RETURN t.n AS t, sa.n AS sa, "
                        "c.linked AS l, c.ghl_id AS id", n=name).single()
        self.assertEqual((row["t"], row["sa"], row["l"], row["id"]), ("Ghl_Contact", "Ghl_Sub_Account_Loc1", True, "AbC1"))
        self.assertEqual(cm.read(self.conn, "calls", {"limit": 1})[0]["function"], "contacts.search")
        self.assertIn(["contact", "AbC1"], cm.read(self.conn, "changed_since", {"call": first["n"]}))

    def test_ids_differing_only_in_case_are_two_records(self):
        self.call("tags.list", [["tag", "aa", {"id": "aa"}], ["tag", "AA", {"id": "AA"}]])
        self.assertEqual(sorted(cm.read(self.conn, "current_ids", {"kind": "tag"})), ["AA", "aa"])

    def test_a_delete_a_deleted_flag_and_mark_deleted_each_leave_a_deleted_version(self):
        self.call("notes.get", [["note", "n1", {"id": "n1"}], ["note", "n2", {"id": "n2"}], ["note", "n3", {"id": "n3"}]])
        self.call("notes.delete_note", [], gone=["note", "n1"])
        self.call("notes.get", [["note", "n2", {"id": "n2", "deleted": True}]])
        self.assertTrue(cm.write(self.conn, "mark_deleted", {"kind": "note", "id": "n3"})["removed"])
        self.assertFalse(cm.write(self.conn, "mark_deleted", {"kind": "note", "id": "n3"})["removed"])
        self.assertEqual(cm.read(self.conn, "current", {"kind": "note"}), [])
        self.assertEqual([v["deleted"] for v in cm.read(self.conn, "versions", {"kind": "note", "id": "n1"})], [False, True])
        self.assertEqual(cm.read(self.conn, "kinds_of", {"id": "n2"}), [])

    def test_events_and_passes_are_kept_and_an_event_is_read_once(self):
        self.assertTrue(cm.write(self.conn, "record_event", {"n": 7, "event": {"type": "ContactCreate", "locationId": "loc1"}})["new"])
        self.assertTrue(cm.write(self.conn, "record_event", {"n": 7, "event": {}})["new"])      # not read yet: again
        cm.write(self.conn, "event_read", {"n": 7, "read": {"read": ["contacts.get_contact"]}})
        self.assertFalse(cm.write(self.conn, "record_event", {"n": 7, "event": {}})["new"])
        self.assertEqual(cm.read(self.conn, "events", {})[0]["read"], {"read": ["contacts.get_contact"]})
        n = cm.write(self.conn, "record_pass", {"report": {"children": "all", "started": 1.0, "calls": 3, "records": 2}})["n"]
        self.assertEqual(cm.read(self.conn, "passes", {"children": "all"})[0]["n"], n)
        self.assertEqual(cm.read(self.conn, "passes", {"children": "moved"}), [])

    def test_learned_from_and_kinds_from(self):
        self.call("calendars.get_appointment", [["event", "e1", {"id": "e1"}]])
        self.assertIn("event", cm.read(self.conn, "kinds_from", {"source": "calendars.get_appointment"}))
        self.assertEqual([r[:3] for r in cm.read(self.conn, "learned_from", {"sources": ["calendars.get_appointment"]})],
                         [["event", "e1", "calendars.get_appointment"]])


if __name__ == "__main__":
    unittest.main()
