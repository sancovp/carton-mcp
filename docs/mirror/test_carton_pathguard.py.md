# doc(m): test_carton_pathguard.py

- **Canonical path:** /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_carton_pathguard.py
- **Line count:** 189 (measured, `wc -l`)
- **Module role:** The only valid gate for the #206 canonical-path guard: a self-running script
  (`python3 test_carton_pathguard.py` from the repo root, the test_carton_breaker.py convention)
  proving the guard's pure logic AND its two integration chokepoints, with five markers.

## What this module IS (from the code)

**Isolation law:** every case runs with `HEAVEN_DATA_DIR` (and optionally `CARTON_DOC_ROOTS`)
pointed at `tempfile.TemporaryDirectory()` dirs via the `EnvSandbox` context manager, which
mutates `os.environ` (the integration surfaces read the process env) and restores it afterwards.
The production `/tmp/heaven_data` and the live graph are never touched; the pure cases need no
neo4j.

**The dual-class subtlety this file documents in code:** the flat `import carton_pathguard as pg`
tests the SOURCE copy; the call sites raise the INSTALLED package's `CartonPathRefused`, a
DIFFERENT class object. `REFUSED = (pg.CartonPathRefused, InstalledRefused)` catches both — and
this is why `pip install --no-deps .` precedes the run (the installed-package law).

**The five cases, one MARKER each:**

1. `t_artifacts_detected` — ARTIFACTS_DETECTED_OK. `detect_path_artifacts` on the literal #206
   corruption path names double_slash + titlecased_self_segment + repeated_root; a clean wiki path
   yields `[]`; an unknown `check_write` mode raises RuntimeError (loud-on-garbage).
2. `t_writer_refuses_outside_root` — WRITER_REFUSES_OUTSIDE_ROOT_OK. A REAL file outside every
   sanctioned root: `project_to_file` raises, the message names the file + rule, and the victim's
   sha1 is byte-identical after (nothing was written).
3. `t_append_wiki_only_doc_roots_create_only` — DOC_ROOT_CREATE_ONLY_OK. Under a registered
   `CARTON_DOC_ROOTS` root: rewriting an EXISTING file refuses (message says CREATE-only, sha
   unchanged); minting a NEW file succeeds and carries the content.
4. `t_wiki_lane_intact` — WIKI_LANE_INTACT_OK. Under `$HEAVEN_DATA_DIR/wiki`: `check_write('wiki')`
   passes, create succeeds, append succeeds (the ONE place appends are allowed); a wiki-mode path
   outside the wiki root refuses.
5. `t_front_door_refuses_tracked_py` — FRONT_DOOR_REFUSES_TRACKED_PY_OK. Calls the REAL
   `add_document_concept` (FastMCP's `@mcp.tool()` returns the original function, so the module
   attribute is the honest surface) with `canonical_path` = this repo's own carton_breaker.py and
   an isolated queue dir: the return starts `❌ REFUSED (not queued)`, the queue dir holds ZERO
   files, the tracked .py sha is unchanged.

**Runner:** the `TESTS` list + `__main__` block prints one `PASS`/`FAIL` line per test (traceback
on failure) and exits nonzero on any failure — identical shape to test_carton_breaker.py.

## Boundary

Imports: stdlib (`hashlib`, `os`, `tempfile`, `pathlib`) + flat `carton_pathguard` + installed
`carton_mcp.carton_pathguard` / `carton_mcp.server_fastmcp` + flat `substrate_projector`
(function-local). Writes: only inside its own temp dirs. Exit: 0 all pass · 1 any failure.
