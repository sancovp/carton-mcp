The canonical-path guard is one self-contained pure module, `carton_pathguard.py`, plus ONE guarded call
at each of three file-write chokepoints. `CartonPathRefused(ValueError)` names the path, the rule and the
sanctioned roots in every refusal. `sanctioned_roots` is `$HEAVEN_DATA_DIR` plus the `$CARTON_DOC_ROOTS`
entries. `detect_path_artifacts` names `double_slash`, `titlecased_self_segment` and `repeated_root`.
`check_write(path, mode)` takes a mode in `{create, append, wiki}`, and an unknown mode raises
RuntimeError.

## States

| component | status | note |
|---|---|---|
| `carton_pathguard.py` | **BUILT + 5/5 markers 2026-08-29** (a318160b3) | pure logic, injectable env; `CartonPathRefused(ValueError)` names path + rule + roots in every refusal; `sanctioned_roots` = $HEAVEN_DATA_DIR + $CARTON_DOC_ROOTS entries; `detect_path_artifacts` names double_slash / titlecased_self_segment / repeated_root; `check_write(path, mode∈{create,append,wiki})`; unknown mode raises RuntimeError (loud-on-garbage) |
| `substrate_projector.project_to_file` wiring | EDITED (b7b5bf158) | one call at the top, mode by EXISTENCE ('create' new / 'append' any rewrite incl. inject_at_line/inject_at_marker); refusal propagates as the existing ValueError contract |
| `server_fastmcp.add_document_concept` wiring | EDITED (05fb64e0d) | first act inside the try; `❌ REFUSED (not queued)` returned SYNCHRONOUSLY — the queue lane is fire-and-forget with silent async failures, so the front door is where the caller sees it |
| `observation_worker_daemon.create_wiki_files_for_concepts` wiring | EDITED (3be5e6e32) | `check_write(itself_file, 'wiki')` per concept BEFORE the mkdir; refusal → `errors` + stderr + continue (the drain never crashes; a garbage name mints nothing) |
| live daemon | RESTARTED 2026-08-29 12:25 (watchdog respawn from site-packages post-install; new module verified present via inspect) | the manual relaunch lost the PID-lock race to the watchdog — the documented shape; the survivor carries the new code |
| MCP front door env | `CARTON_DOC_ROOTS=/home/GOD/gnosys-plugin-v2` set in `.claude.json` `mcpServers.carton.env` | monorepo document indexing stays legal (CREATE-only); a long-running MCP server serves OLD code until reconnected |

APPEND IS WIKI-ONLY. Rewriting an existing file is allowed only under `$HEAVEN_DATA_DIR/wiki`. Registered
doc roots are CREATE-only: projection may mint a new file there, never rewrite a tracked one. Rewriting
tracked source IS the corruption this guard exists to stop.

ARTIFACTS REFUSE OUTRIGHT, NAMED — `double_slash` / `titlecased_self_segment` / `repeated_root`, the
recursive-normalizer garbage signature, refused before any root check.

THE FRONT DOOR REFUSES SYNCHRONOUSLY. Nothing is queued on refusal and the caller sees `❌ REFUSED (not
queued)`. NEVER move this check into the daemon — its failures are silent.

THE DRAIN NEVER CRASHES. The daemon's wiki-lane refusal is per-concept: recorded in the batch's errors,
printed, and the loop continues.

BE LOUD ON GARBAGE CONFIG AND CALLS. An unknown mode raises RuntimeError, and a refusal message always
carries the path, the rule and the sanctioned root set.

The three call sites: `substrate_projector.project_to_file` calls it at the top, with the mode chosen by
EXISTENCE — `create` for a new file, `append` for any rewrite including `inject_at_line` and
`inject_at_marker` — and the refusal propagates as the existing ValueError contract.
`server_fastmcp.add_document_concept` calls it as the first act inside the try.
`observation_worker_daemon.create_wiki_files_for_concepts` calls `check_write(itself_file, 'wiki')` per
concept BEFORE the mkdir, and a refusal goes to `errors` plus stderr and continues.

`CARTON_DOC_ROOTS=/home/GOD/gnosys-plugin-v2` is set in `.claude.json` `mcpServers.carton.env`, which
keeps monorepo document indexing legal as CREATE-only. A long-running MCP server serves OLD code until
reconnected.

Dev-flow, and NEVER edit one place only. Touching `check_write` / `sanctioned_roots` / `wiki_root` /
`detect_path_artifacts`, or any of the three call sites → edit `carton_pathguard.py` and the call sites
coherently, then the gate: `python3 test_carton_pathguard.py` all 5 markers — run as a SCRIPT from the
repo root, because the repo root IS the `carton_mcp` package, and integration cases resolve the INSTALLED
module, so `pip install --no-deps .` FIRST — AND `python3 test_carton_breaker.py` 12/12 as the regression
floor AND `py_compile` on every touched file.

Then the installed-package law: restart the daemon per `daemon-needs-env-vars`, expect the watchdog
respawn to win the relaunch race, and verify the SURVIVOR's start time and that its module carries the
new code. The MCP server picks the change up on reconnect.

If your change tightens what the daemon's wiki lane accepts, remember `$CARTON_DOC_ROOTS` reaches the
FRONT DOOR through `.claude.json` `mcpServers.carton.env`: env in one lane is not env in the other.

Known bounds, named and accepted: the guard covers those THREE chokepoints. The other projection handlers
— `project_skill`, `project_rule`, `project_state_machine`, `flush_starlog_diary` and the rest — write
their own paths and are NOT yet guarded; each is its own lane and its own dev-flow decision when its
layer arrives. The release-effect dispatcher's importlib-execution of graph-named handlers is the SAME
defect class with an arbitrary-CODE payload. A concept literally named `Wiki` / `Tmp` / `Concepts`
case-collides with a path segment and trips `titlecased_self_segment` — rare, loud, and accepted.
