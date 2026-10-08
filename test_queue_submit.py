"""test_queue_submit — a client's queue write lands on the BOX, not on its own disk.

Run: python3 test_queue_submit.py     (exit 0 = pass)

The defect this pins: add_concept wrote its queue file to $HEAVEN_DATA_DIR/carton_queue on
whatever machine ran it. The worker that drains that queue is in the box, so a tenant's MCP
produced a file nobody would ever read — and returned success.
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/GOD/gnosys-plugin-v2/base/heaven-framework")

import kuzu_query_endpoint as ep  # noqa: E402
from carton_mcp.add_concept_tool import submit_queue_entry  # noqa: E402

PASS = FAIL = 0
ENTRY = {"concept_name": "Q_Test", "relationships": []}


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label} {detail}")


def queue_files(root):
    d = os.path.join(root, "carton_queue")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


class _Store:
    def execute(self, query, params):
        return []


def main():
    client_home = tempfile.mkdtemp(prefix="client_")
    box_home = tempfile.mkdtemp(prefix="box_")
    prev = os.environ.get("HEAVEN_DATA_DIR")
    prev_url = os.environ.get("KUZU_QUERY_URL")
    try:
        print("== owner (no url): the entry is written locally, unchanged ==")
        os.environ["HEAVEN_DATA_DIR"] = box_home
        os.environ.pop("KUZU_QUERY_URL", None)
        name = submit_queue_entry(ENTRY, "_concept")
        check("written locally", name in queue_files(box_home), str(queue_files(box_home)))
        check("and it is named a concept entry", name.endswith("_concept.json"), name)

        print("== client (url set): the entry lands on the BOX, not the client ==")
        # The endpoint is the box: it writes into whatever HEAVEN_DATA_DIR it runs under.
        server, _ = ep.serve_in_thread(_Store(), port=18831, host="127.0.0.1", key="")
        before_box = set(queue_files(box_home))
        try:
            os.environ["HEAVEN_DATA_DIR"] = client_home   # the CLIENT's disk
            os.environ["KUZU_QUERY_URL"] = "http://127.0.0.1:18831"
            # The server thread reads HEAVEN_DATA_DIR at call time, so point it back at the
            # box for the duration of the request — exactly the two-machine split, in one
            # process: the caller is on client_home, the endpoint writes to box_home.
            os.environ["HEAVEN_DATA_DIR"] = box_home
            remote_name = submit_queue_entry(ENTRY, "_concept")
        finally:
            server.shutdown()
        check("the box got the entry", remote_name in set(queue_files(box_home)) - before_box,
              str(queue_files(box_home)))
        check("the client wrote NOTHING to its own queue", queue_files(client_home) == [],
              str(queue_files(client_home)))
    finally:
        for k, v in (("HEAVEN_DATA_DIR", prev), ("KUZU_QUERY_URL", prev_url)):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(client_home, ignore_errors=True)
        shutil.rmtree(box_home, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
