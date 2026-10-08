"""Unit tests for normalize_concept_name's #200 sanitization (pure function — no neo4j).

Issue #200: normalize_concept_name normalized case/spacing and nothing else, so names
carrying slashes, quotes, brackets, newlines, or transcript-blob length landed as graph
nodes and failed one-time at projection. RULING (2026-08-28): SANITIZE, do not reject —
strip/replace the metachars, cap length at 200, and logger.warning every sanitization
with before/after so nothing is silent.

Test shape (per the issue's COLD-TEST ruling #4): a CONTROLLED PAIR per metachar class —
the dirty input is sanitized AND warned about; the clean twin is byte-identical to the
pre-#200 behavior and produces NO warning.

The auto-stub side door (observation_worker_daemon.py — the relationship-target MERGE
that births stub nodes) is covered by the SAME chokepoint: the daemon normalizes every
concept name and every relationship target through this exact function, which is why the
fix lives inside it. test_daemon_stub_door_routes_through_this_chokepoint pins that at
the source level (static read — no live daemon, no neo4j).

RUN:  python3 tests/test_normalize_concept_name.py
(direct execution — the repo's sanctioned test pattern, like test_network_gateway.py /
test_carton_quota.py. pytest collection is broken for this package in this env: the
carton-mcp dir carries a top-level __init__.py inside a hyphenated dir name, so pytest's
Package collector imports '__init__' with no parent package and EVERY test file under
this repo errors at setup — pre-existing, test_manifold.py fails identically.)
"""
import importlib.util
import logging
import os
import re
import sys
import traceback

# Load the module directly from THIS worktree's source file (not the installed
# site-packages copy) — the manifold-test pattern. Module top-level does a 2s-max
# SOMA availability probe and imports carton_mcp.concept_config; no DB connection.
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "add_concept_tool.py")
_spec = importlib.util.spec_from_file_location("act_under_test", _PATH)
act = importlib.util.module_from_spec(_spec)
sys.modules["act_under_test"] = act
_spec.loader.exec_module(act)

normalize_concept_name = act.normalize_concept_name
MAX_CONCEPT_NAME_LENGTH = act.MAX_CONCEPT_NAME_LENGTH


class LogCapture(logging.Handler):
    """Collects WARNING+ records from the module-under-test's logger."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def messages(self):
        return [r.getMessage() for r in self.records]

    def clear(self):
        self.records = []


_capture = LogCapture()
_logger = logging.getLogger("act_under_test")
_logger.addHandler(_capture)
_logger.setLevel(logging.WARNING)


def _warnings():
    return list(_capture.records)


# ── The clean baseline: pre-#200 behavior is byte-identical and silent ──────────

def test_clean_names_unchanged_and_silent():
    # The three docstring examples — the pre-#200 contract.
    assert normalize_concept_name("my cool concept") == "My_Cool_Concept"
    assert normalize_concept_name("NEURAL NETWORK") == "Neural_Network"
    assert normalize_concept_name("hello_world") == "Hello_World"
    # Hyphens still fold to underscores (UUIDs / session ids).
    assert normalize_concept_name("a-b-c") == "A_B_C"
    # An already-normalized name is a fixed point.
    assert normalize_concept_name("Already_Normal_Name") == "Already_Normal_Name"
    assert _warnings() == []


# ── Controlled pair per metachar class ──────────────────────────────────────────

def test_slashes_sanitized_and_warned():
    assert normalize_concept_name("path/to/thing") == "Path_To_Thing"
    assert len(_warnings()) == 1
    assert "SANITIZED" in _capture.messages()[0]
    _capture.clear()
    # Controlled clean twin: no metachars → no warning, same shape.
    assert normalize_concept_name("path_to_thing") == "Path_To_Thing"
    assert _warnings() == []


def test_backslashes_sanitized_and_warned():
    assert normalize_concept_name("dir\\file") == "Dir_File"
    assert len(_warnings()) == 1
    _capture.clear()
    assert normalize_concept_name("dir_file") == "Dir_File"
    assert _warnings() == []


def test_quotes_stripped_in_place_and_warned():
    # Quotes are intra-word punctuation: STRIPPED, not replaced with a separator.
    assert normalize_concept_name("Isaac's_Idea") == "Isaacs_Idea"
    assert normalize_concept_name('"Quoted"_Name') == "Quoted_Name"
    assert normalize_concept_name("`tick`") == "Tick"
    assert normalize_concept_name("‘smart’_“quotes”") == "Smart_Quotes"
    assert len(_warnings()) == 4
    _capture.clear()
    assert normalize_concept_name("Isaacs_Idea") == "Isaacs_Idea"
    assert _warnings() == []


def test_brackets_sanitized_and_warned():
    assert normalize_concept_name("Thing[1]") == "Thing_1"
    assert normalize_concept_name("fn(arg)") == "Fn_Arg"
    assert normalize_concept_name("{curly}") == "Curly"
    assert normalize_concept_name("<angle>") == "Angle"
    assert len(_warnings()) == 4
    _capture.clear()
    assert normalize_concept_name("Thing_1") == "Thing_1"
    assert _warnings() == []


def test_newlines_and_control_chars_sanitized_and_warned():
    assert normalize_concept_name("line1\nline2") == "Line1_Line2"
    assert normalize_concept_name("cr\rlf\ntab\tend") == "Cr_Lf_Tab_End"
    assert normalize_concept_name("nul\x00byte") == "Nul_Byte"
    assert len(_warnings()) == 3
    _capture.clear()
    assert normalize_concept_name("line1_line2") == "Line1_Line2"
    assert _warnings() == []


def test_metachar_runs_collapse_to_one_underscore():
    # A RUN of separators becomes ONE underscore — "a//b" is not "A__B".
    assert normalize_concept_name("a//b") == "A_B"
    assert normalize_concept_name("a/[\n]b") == "A_B"
    assert len(_warnings()) == 2


def test_leading_trailing_metachars_stripped():
    assert normalize_concept_name("/leading/slash") == "Leading_Slash"
    assert normalize_concept_name("trailing/") == "Trailing"
    assert len(_warnings()) == 2


# ── The length cap (transcript-blob names) ──────────────────────────────────────

def test_length_cap_truncates_and_warns():
    blob = "word_" * 100  # 500 chars raw
    result = normalize_concept_name(blob)
    assert len(result) <= MAX_CONCEPT_NAME_LENGTH
    assert result.startswith("Word_Word")
    assert not result.endswith("_")
    assert any("TRUNCATED" in m for m in _capture.messages())
    _capture.clear()
    # Controlled twin at exactly the cap: untouched, silent.
    exact = "A" * MAX_CONCEPT_NAME_LENGTH
    assert normalize_concept_name(exact) == exact.title()
    assert len(normalize_concept_name(exact)) == MAX_CONCEPT_NAME_LENGTH
    assert _warnings() == []


def test_cap_constant_is_200():
    # The ruling names 200 explicitly.
    assert MAX_CONCEPT_NAME_LENGTH == 200


# ── The measured defect shape: a transcript-blob with mixed metachars ───────────

def test_transcript_blob_name_lands_clean():
    blob = ('The user said: "let\'s fix the /path/to/file.py bug"\n'
            "and then [the agent] did (many things) " + "filler " * 60)
    result = normalize_concept_name(blob)
    assert len(result) <= MAX_CONCEPT_NAME_LENGTH
    # No metachar survives into the node name.
    assert not re.search(r"[/\\\[\]\(\)\{\}<>'\"`\n\r\t]", result)
    msgs = _capture.messages()
    assert any("SANITIZED" in m for m in msgs)
    assert any("TRUNCATED" in m for m in msgs)


def test_warning_carries_before_and_after():
    normalize_concept_name("bad/name")
    msg = _capture.messages()[0]
    assert "bad/name" in msg      # before
    assert "bad_name" in msg      # after (pre-title-case sanitized form)


# ── Totality / stability ────────────────────────────────────────────────────────

def test_all_metachars_sanitizes_to_empty_not_crash():
    # Sanitize-not-reject: a name that IS only metachars returns "" (callers
    # already skip empty names) rather than raising.
    assert normalize_concept_name("///") == ""
    assert normalize_concept_name('"\n"') == ""
    assert len(_warnings()) == 2


def test_idempotent_on_sanitized_output():
    for dirty in ["path/to/thing", "Isaac's_Idea", "line1\nline2",
                  "Thing[1]", "word_" * 100]:
        once = normalize_concept_name(dirty)
        _capture.clear()
        assert normalize_concept_name(once) == once
        # The second pass sees a clean name — silent.
        assert _warnings() == []


# ── The auto-stub side door is the same chokepoint (static source pin) ──────────

def test_daemon_stub_door_routes_through_this_chokepoint():
    """The observation_worker_daemon's auto-stub door (relationship-target MERGE)
    normalizes every target through normalize_concept_name imported from THIS module,
    so the sanitize above covers it with no daemon-side change. Pinned statically —
    no live daemon, no neo4j."""
    daemon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                               "observation_worker_daemon.py")
    src = open(daemon_path, encoding="utf-8").read()
    assert "from carton_mcp.add_concept_tool import" in src
    first_import_line = src.split("from carton_mcp.add_concept_tool import", 1)[1].split("\n", 1)[0]
    assert "normalize_concept_name" in first_import_line
    # The stub door: every relationship target is normalized before the MERGE.
    assert "target_normalized = normalize_concept_name(target)" in src
    # And the concept_name route through the same function.
    assert "normalize_concept_name(data.get('concept_name', ''))" in src


def _run_all():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed, failed = 0, 0
    for name, fn in tests:
        _capture.clear()
        try:
            fn()
            print(f"PASS  {name}")
            passed += 1
        except Exception:
            print(f"FAIL  {name}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
