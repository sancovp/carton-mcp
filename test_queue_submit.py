"""test_queue_submit — a queue write lands on the machine whose worker drains it, and nowhere else.

Run: python3 test_queue_submit.py     (exit 0 = pass)

The defect this pins: add_concept once wrote its queue file to $HEAVEN_DATA_DIR/carton_queue on
whatever machine ran it. The worker that drains that queue is in the box, so a tenant's MCP produced
a file nobody would ever read — and returned success. Today a caller off the box never writes a
queue entry at all: it calls `add_concept` on CartON's server (`carton_api.call_carton`), and the
server's own `add_concept` writes into the box's queue through `submit_queue_entry`. So this
function is LOCAL ONLY, whatever the environment says — the two-machine split is proven over a real
socket in `test_carton_api.py` (t_g, t_i).
"""

import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "base", "heaven-framework"))
# The package under test is THIS directory, never an installed copy.
_spec = importlib.util.spec_from_file_location("carton_mcp", os.path.join(HERE, "__init__.py"),
                                               submodule_search_locations=[HERE])
_pkg = importlib.util.module_from_spec(_spec)
sys.modules["carton_mcp"] = _pkg
_spec.loader.exec_module(_pkg)

from carton_mcp.add_concept_tool import submit_queue_entry, write_queue_entry  # noqa: E402

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


def main():
    home = tempfile.mkdtemp(prefix="box_")
    prev = {k: os.environ.get(k) for k in ("HEAVEN_DATA_DIR", "CARTON_URL")}
    try:
        print("== the entry is written into THIS machine's queue, named a concept entry ==")
        os.environ["HEAVEN_DATA_DIR"] = home
        os.environ.pop("CARTON_URL", None)
        name = submit_queue_entry(ENTRY, "_concept")
        check("written locally", name in queue_files(home), str(queue_files(home)))
        check("and it is named a concept entry", name.endswith("_concept.json"), name)

        print("== CARTON_URL changes nothing here: the function is the box's own write path ==")
        os.environ["CARTON_URL"] = "http://127.0.0.1:9"   # nothing listens; a remote attempt would fail
        name2 = submit_queue_entry(ENTRY, "_concept")
        check("still written locally, no network", name2 in queue_files(home), str(queue_files(home)))
        check("the two sort in write order", sorted([name, name2]) == [name, name2], f"{name} {name2}")
        check("submit and write are the same path", write_queue_entry.__module__ == submit_queue_entry.__module__)
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(home, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
