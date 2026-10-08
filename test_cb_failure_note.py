"""Card 767, issue 1114: a Crystal Ball outage is said ONCE per CLI answer, never once per carton write.

Measured 2026-10-01: with the CB service down, one journal call printed
"CB store failed (carton write unaffected): <urlopen error [Errno 111] Connection refused>" 8 to 11 times,
one per concept it wrote, burying the ack. Isaac 2026-10-01: "also fix the CB store failed being rendered
more than once per return".

Run as a SCRIPT from the repo root AFTER `pip install --no-deps .` (the tests resolve the INSTALLED
package): python3 test_cb_failure_note.py   (expect: 4 markers, all pass)
"""
import io
import logging
import os
import subprocess
import sys

REFUSED = "http://127.0.0.1:1/api/cb/store"


def _reset(act):
    os.environ.pop("CARTON_CB_SAID_AT", None)
    if hasattr(act, "_cb_state"):
        act._cb_state.update(last_said=None, unsaid=0)


def t_three_refused_writes_say_it_once():
    from carton_mcp import add_concept_tool as act
    _reset(act)
    act.CARTON_CB_STORE_URL = REFUSED
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    act.logger.addHandler(handler)
    try:
        for name in ("A", "B", "C"):
            assert act._cb_place(name, {"is_a": ["Thing"]}, "soup") == (None, None, "", None)
    finally:
        act.logger.removeHandler(handler)
    said = stream.getvalue()
    assert said.count("CB store failed") == 1, said
    print("  MARKER: THREE_REFUSED_WRITES_SAY_IT_ONCE_OK")


def t_the_note_is_pure_and_counts_what_it_did_not_say():
    from carton_mcp.add_concept_tool import cb_failure_note
    refused = ConnectionRefusedError(111, "Connection refused")
    line, last, unsaid = cb_failure_note(refused, "CB store", None, 0, now=100.0, quiet_s=600)
    assert line.startswith("CB store failed (carton write unaffected): ") and last == 100.0 and unsaid == 0
    assert cb_failure_note(refused, "CB store", 100.0, 0, now=200.0, quiet_s=600) == (None, 100.0, 1)
    line, last, unsaid = cb_failure_note(refused, "CB store", 100.0, 4, now=700.0, quiet_s=600)
    assert "4 more since" in line and last == 700.0 and unsaid == 0, line
    print("  MARKER: THE_NOTE_IS_PURE_AND_COUNTS_OK")


def t_an_unexpected_failure_is_always_said_with_its_trace():
    from carton_mcp.add_concept_tool import cb_failure_note
    try:
        raise ValueError("bad json")
    except ValueError as e:
        line, last, unsaid = cb_failure_note(e, "CB store", 100.0, 0, now=101.0, quiet_s=600)
    assert line is not None and "bad json" in line and "Traceback" in line, line
    assert (last, unsaid) == (100.0, 0)
    print("  MARKER: AN_UNEXPECTED_FAILURE_IS_ALWAYS_SAID_OK")


def t_a_child_process_of_the_same_answer_stays_quiet():
    from carton_mcp import add_concept_tool as act
    _reset(act)
    act.CARTON_CB_STORE_URL = REFUSED
    act._cb_place("Parent", {}, "soup")
    assert "CARTON_CB_SAID_AT" in os.environ, "the parent did not leave the said-at time for its children"
    child = ("import carton_mcp.add_concept_tool as a\n"
             f"a.CARTON_CB_STORE_URL = {REFUSED!r}\n"
             "a._cb_place('Child', {}, 'soup')\n")
    out = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, timeout=600)
    assert "CB store failed" not in out.stderr + out.stdout, out.stderr[-2000:]
    print("  MARKER: A_CHILD_PROCESS_STAYS_QUIET_OK")


TESTS = [
    t_three_refused_writes_say_it_once,
    t_the_note_is_pure_and_counts_what_it_did_not_say,
    t_an_unexpected_failure_is_always_said_with_its_trace,
    t_a_child_process_of_the_same_answer_stays_quiet,
]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\nall {len(TESTS)} passed" if not failed else f"\n{failed}/{len(TESTS)} FAILED")
    raise SystemExit(1 if failed else 0)
