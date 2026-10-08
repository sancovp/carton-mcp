"""Pins the TYPE-SHATTERING bug class (found + fixed 2026-08-22).

PURE STATIC TEST — scans package source text. No neo4j, no daemon, never production.
Run as a SCRIPT from the repo root (the repo root IS the carton_mcp package, matching
test_carton_vault_payload.py and test_log_system_event_no_duplicate_types.py).

THE DEFECT, proven on a throwaway neo4j 5 by controlled pair:

    MERGE (es:Wiki {n: $step_id}) MERGE (es)-[:IS_A]->(:Wiki {n: 'Traversal_Step'})
                                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                                       ANONYMOUS + UNBOUND

    The second MERGE matches the WHOLE PATH. For a NEW `es` that path has never
    existed, so Cypher creates the entire pattern -- INCLUDING A BRAND NEW TYPE NODE.
    One private type node per instance, forever.

    Measured on the throwaway with 5 distinct instances:
        buggy shape  -> 5 type nodes (each with exactly 1 incoming IS_A)
        fixed shape  -> 1 type node
    That reproduces the production signature EXACTLY: 397 Traversal_Step copies each
    carrying exactly one HAS_PART and one INSTANTIATED_BY.

    Live damage this produced, all five names matching the five sm_gate constants with
    no misses and no extras: Traversal_Step 397, State_Machine 291, Sm_Chain 153,
    Execution_State 149, Agent_Identity 20 -- plus Skillgraph_Entry 550 from the same
    shape in carton_utils.

THE FIX is always the same one-line transformation: bind the type node by name FIRST,
then point the edge at the bound variable.

    MERGE (t:Wiki {n: 'Traversal_Step'})
    MERGE (es:Wiki {n: $step_id}) MERGE (es)-[:IS_A]->(t)

WHY A GREP-SHAPED TEST RATHER THAN A BEHAVIOURAL ONE: the defect is invisible at every
level above the query text. It needs a real graph AND several distinct instances to show
up at all, it produces no error, and the duplicate type node is byte-identical to the
real one -- so a functional test passes cleanly while the graph shatters. The query text
IS the observable. A prior monorepo sweep searched for this shape spelled with CREATE and
correctly reported clean; the shape is spelled with MERGE, which is why it survived.
"""

import ast
import io
import re
import traceback
from pathlib import Path

# An inline brace-literal :Wiki node sitting as the TARGET of a relationship MERGE.
# Tolerates the f-string doubled braces sm_gate uses ({{n: ...}}).
BAD = re.compile(r"MERGE\s*\([A-Za-z_]\w*\)\s*-\s*\[[^\]]*\]\s*->\s*\(\s*:Wiki\s*\{")

# `tests` IS SCANNED, and the reason it is scanned is the whole point of this line.
#
# It used to be skipped, on the stated grounds that "tests/ holds fixtures that deliberately build
# graphs by hand; they are not the writers." That was FALSE, and the exclusion is what hid it: five
# E2E fixtures carried this exact shape at 12 sites, and each one DEFAULTS ITS CONNECTION TO
# `bolt://host.docker.internal:7687` — the identical default the live daemon uses
# (observation_worker_daemon.py:1302). Run bare, they write to the PRODUCTION graph, so they are
# writers in the only sense that matters. Worse, the leak was invisible to their own teardown: every
# `_cleanup` deletes by a `Zztest_*` prefix, and a minted type node carries no prefix, so the copies
# survived every run. Fixed 2026-08-22; scanning tests/ is what keeps them fixed.
#
# `build` and `__pycache__` are copies of source scanned elsewhere; `.git` is not source.
SKIP_DIRS = {"build", "__pycache__", ".git"}


def _sources():
    root = Path(__file__).resolve().parent
    for p in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if p.name == Path(__file__).name:
            continue          # this file quotes the bad shape in its own docstring
        yield p


def _docstring_nodes(tree):
    """ids of the Constant nodes that are DOCSTRINGS, so prose is not read as code.

    This scoping is what makes the pin USABLE rather than a weakening of it. The bad
    shape legitimately appears in prose that DESCRIBES it -- retype_buckets.py:33
    documents the transformation in its module docstring while its executable code at
    :164-178 does the correct bound form. A line-based scan cannot tell those apart and
    reports the correct file as the bug. Note the pattern must still be found inside
    STRING LITERALS, because every real query in this package is a triple-quoted
    f-string -- so "skip strings" would disable the test entirely. Docstring-vs-query
    is the exact seam, and ast is the only thing that knows it.
    """
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.add(id(body[0].value))
    return out


def scan():
    """Return (hits, unscannable) — the bad shapes found, and the files that could not be read.

    UNSCANNABLE IS RETURNED, NEVER SWALLOWED. This used to be a bare `except ...: continue`, which
    makes "I could not parse this file" look exactly like "this file is clean" — a detector that
    silently skips its input reports GREEN over the very thing it was built to catch. That is the
    same silent-blindness as the `tests` exclusion above, one layer down, so it gets the same
    treatment: the caller asserts the list is empty and sees the reason if it is not.
    """
    hits, unscannable = [], []
    for p in _sources():
        try:
            text = io.open(p, encoding="utf-8").read()
            tree = ast.parse(text)
        except (OSError, UnicodeDecodeError, SyntaxError):
            unscannable.append((str(p), traceback.format_exc().strip().splitlines()[-1]))
            continue
        docs = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in docs:
                continue
            for line in node.value.splitlines():
                m = BAD.search(line)
                if m:
                    hits.append((str(p), getattr(node, "lineno", 0), line.strip()))
    return hits, unscannable


def test_every_source_file_was_actually_scanned():
    """THE COVERAGE GATE: a file the detector could not read must FAIL, never pass quietly.

    Without this, a syntax error or an unreadable file downgrades the pin to "clean" for that file
    and nothing says so — the detector's own version of the blindness it exists to catch.
    """
    _, unscannable = scan()
    assert not unscannable, (
        "the detector COULD NOT SCAN these files, so its GREEN says nothing about them:\n  "
        + "\n  ".join(f"{p}: {why}" for p, why in unscannable))


def test_no_writer_creates_an_anonymous_inline_type_node():
    """THE DEFECT PIN: a relationship MERGE must never inline its :Wiki target."""
    hits, _ = scan()
    assert not hits, (
        "TYPE-SHATTERING SHAPE IS BACK -- a relationship MERGE inlines an anonymous "
        ":Wiki target, which mints a NEW type node for every distinct source:\n  "
        + "\n  ".join(f"{p}:{n}: {l}" for p, n, l in hits)
        + "\nFIX: MERGE the type node by name first, then point the edge at that variable."
    )


def test_the_detector_actually_matches_the_known_bad_shape():
    """THE CONTROL: a detector that cannot fire proves nothing.

    Without this, deleting the regex body would make the suite pass forever.
    """
    assert BAD.search("MERGE (es)-[:IS_A]->(:Wiki {n: 'Traversal_Step'})")
    assert BAD.search("        MERGE (sm)-[:IS_A]->(:Wiki {{n: '{T_STATE_MACHINE}'}})")


def test_the_detector_does_not_flag_the_correct_bound_form():
    """THE SECOND CONTROL: the fix must not itself be reported as the bug.

    Guards against an over-broad regex that would make the pin unusable by flagging
    every correct write.
    """
    assert not BAD.search("MERGE (es)-[:IS_A]->(t_step)")
    assert not BAD.search("MERGE (t_step:Wiki {n: 'Traversal_Step'})")
    assert not BAD.search("MERGE (source)-[rel:IS_A]->(target)")


def test_a_docstring_describing_the_shape_is_not_reported_as_a_writer():
    """THE THIRD CONTROL: prose ABOUT the bug is not the bug.

    retype_buckets.py documents this exact transformation in its module docstring while
    its executable code uses the correct bound form. If scan() ever reports it, the
    ast docstring-scoping has regressed and the pin has become unusable.
    """
    offenders = {p for p, _, _ in scan()[0]}
    assert not any(p.endswith("retype_buckets.py") for p in offenders), (
        "scan() reported retype_buckets.py, whose only occurrence is module-docstring "
        "prose -- the ast docstring-scoping in _docstring_nodes has regressed."
    )


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
