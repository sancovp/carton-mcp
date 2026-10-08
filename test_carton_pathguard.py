"""Tests for carton_pathguard.py — the #206 canonical-path guard.

Standalone gate in this repo's own test convention (the test_carton_breaker.py
precedent): flat import of the sibling module, a self-running script
(`python3 test_carton_pathguard.py`), one PASS line per test.

Everything runs with HEAVEN_DATA_DIR pointed at a temp dir — NEVER the
production /tmp/heaven_data, never the live graph. The pure functions need no
neo4j; the two integration cases (project_to_file, add_document_concept) call
the REAL functions, whose guarded call resolves the INSTALLED
carton_mcp.carton_pathguard — so run `pip install --no-deps .` before this
script (the installed-package law; the run order the dev-flow states).
"""

import hashlib
import os
import tempfile
from pathlib import Path

import carton_pathguard as pg

# The call sites raise the INSTALLED package's exception class, which is a
# DIFFERENT class object from the flat-imported source copy above (same code,
# two module instances). Integration cases must catch the installed one.
from carton_mcp.carton_pathguard import CartonPathRefused as InstalledRefused

REFUSED = (pg.CartonPathRefused, InstalledRefused)


def sha(p) -> str:
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()


class EnvSandbox:
    """Point HEAVEN_DATA_DIR (+ optionally CARTON_DOC_ROOTS) at temp dirs for
    the duration of one test, restoring os.environ afterwards. os.environ is
    mutated (not just an injected dict) because the integration surfaces
    (project_to_file, add_document_concept) read the process env."""

    KEYS = ("HEAVEN_DATA_DIR", "CARTON_DOC_ROOTS")

    def __init__(self, heaven_dir, doc_roots=None):
        self.heaven_dir = str(heaven_dir)
        self.doc_roots = doc_roots
        self._saved = {}

    def __enter__(self):
        for k in self.KEYS:
            self._saved[k] = os.environ.get(k)
        os.environ["HEAVEN_DATA_DIR"] = self.heaven_dir
        if self.doc_roots is None:
            os.environ.pop("CARTON_DOC_ROOTS", None)
        else:
            os.environ["CARTON_DOC_ROOTS"] = str(self.doc_roots)
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


# ---------------------------------------------------------------- pure logic

def t_artifacts_detected():
    arts = pg.detect_path_artifacts('/home/GOD//Home/God/Home/x/Server_Fastmcp.py')
    assert 'double_slash' in arts and 'titlecased_self_segment' in arts
    assert 'repeated_root' in arts  # /home/god recurs after the //
    assert pg.detect_path_artifacts('/tmp/heaven_data/wiki/concepts/X/X_itself.md') == []
    # loud-on-garbage: an unknown mode must never silently disable the guard
    try:
        pg.check_write('/tmp/heaven_data/x', 'overwrite')
        raise AssertionError("expected RuntimeError on unknown mode")
    except RuntimeError as e:
        assert 'unknown mode' in str(e)
    print("  MARKER: ARTIFACTS_DETECTED_OK")


# ------------------------------------------------------- project_to_file gate

def t_writer_refuses_outside_root():
    from substrate_projector import FileSubstrate, project_to_file
    with tempfile.TemporaryDirectory() as heaven, tempfile.TemporaryDirectory() as elsewhere:
        victim = Path(elsewhere) / "victim.py"
        victim.write_text("original = True\n")
        before = sha(victim)
        with EnvSandbox(heaven):
            try:
                project_to_file(FileSubstrate(path=str(victim)),
                                'File: garbage\n## Relationships')
                raise AssertionError("expected CartonPathRefused")
            except REFUSED as e:
                assert 'victim.py' in str(e) and 'sanctioned root' in str(e)
        assert sha(victim) == before  # byte-identical: nothing was written
    print("  MARKER: WRITER_REFUSES_OUTSIDE_ROOT_OK")


def t_append_wiki_only_doc_roots_create_only():
    from substrate_projector import FileSubstrate, project_to_file
    with tempfile.TemporaryDirectory() as heaven, tempfile.TemporaryDirectory() as docroot:
        tracked = Path(docroot) / "tracked.py"
        tracked.write_text("tracked = True\n")
        before = sha(tracked)
        with EnvSandbox(heaven, doc_roots=docroot):
            # rewriting an EXISTING file under a registered doc root -> refused
            try:
                project_to_file(FileSubstrate(path=str(tracked)), 'garbage')
                raise AssertionError("expected CartonPathRefused on append")
            except REFUSED as e:
                assert 'CREATE-only' in str(e)
            assert sha(tracked) == before
            # minting a NEW file under the same doc root -> allowed
            fresh = Path(docroot) / "rendered" / "new_doc.md"
            msg = project_to_file(FileSubstrate(path=str(fresh)), 'rendered content')
            assert fresh.read_text() == 'rendered content' and 'Created' in msg
    print("  MARKER: DOC_ROOT_CREATE_ONLY_OK")


def t_wiki_lane_intact():
    from substrate_projector import FileSubstrate, project_to_file
    with tempfile.TemporaryDirectory() as heaven:
        with EnvSandbox(heaven):
            itself = Path(heaven) / "wiki" / "concepts" / "X_Concept" / "X_Concept_itself.md"
            # the daemon's own lane check
            pg.check_write(str(itself), 'wiki')
            # create under the wiki root
            msg1 = project_to_file(FileSubstrate(path=str(itself)), '# X_Concept')
            assert itself.exists() and 'Created' in msg1
            # append (the wiki lane is the ONE place appends are allowed)
            msg2 = project_to_file(FileSubstrate(path=str(itself)), 'more')
            assert 'Appended' in msg2 and itself.read_text().endswith('more')
            # and a wiki-mode path OUTSIDE the wiki root refuses
            try:
                pg.check_write(str(Path(heaven) / 'skills' / 'x.md'), 'wiki')
                raise AssertionError("expected CartonPathRefused")
            except pg.CartonPathRefused:
                pass
    print("  MARKER: WIKI_LANE_INTACT_OK")


# ------------------------------------------------------- the front door (MCP)

def t_front_door_refuses_tracked_py():
    # The UNDECORATED callable: FastMCP's @mcp.tool() registers and returns the
    # original function, so the module attribute IS the honest surface.
    from carton_mcp.server_fastmcp import add_document_concept
    tracked = Path(__file__).resolve().parent / "carton_breaker.py"  # a REAL tracked .py
    assert tracked.exists()
    before = sha(tracked)
    with tempfile.TemporaryDirectory() as heaven:
        with EnvSandbox(heaven):  # queue dir isolated + empty; no doc roots
            result = add_document_concept(
                concept_name="Pathguard_Front_Door_Probe",
                description="probe: must be refused, never queued",
                canonical_path=str(tracked),
            )
            assert result.startswith("❌ REFUSED (not queued)"), result
            queue_dir = Path(heaven) / "carton_queue"
            queued = list(queue_dir.glob("*.json")) if queue_dir.exists() else []
            assert queued == [], f"refusal must queue NOTHING, found {queued}"
    assert sha(tracked) == before
    print("  MARKER: FRONT_DOOR_REFUSES_TRACKED_PY_OK")


TESTS = [
    t_artifacts_detected,
    t_writer_refuses_outside_root,
    t_append_wiki_only_doc_roots_create_only,
    t_wiki_lane_intact,
    t_front_door_refuses_tracked_py,
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
