The precompact hook queues `timeline_merge` files — `{timeline_merge, unnamed_concept, real_concept}`,
merging an `Unnamed_Conversation_At_*` node into the real conversation node — and they are processed on
the LIVE worker path by `_process_timeline_merge(data, graph)` in `observation_worker_daemon.py`, never
inside the dead `process_queue_file`.

## States

| component | status | note |
|---|---|---|
| `_process_timeline_merge(data, graph)` in `observation_worker_daemon.py` | **BUILT + 4/4 tests + LIVE-VERIFIED 2026-07-19** | the proven merge logic (transfer CREATED_DURING, delete the Unnamed) extracted to a live helper; query semantics deliberately identical to the dead path |
| worker-loop routing | EDITED (the empty-parse branch ONLY — zero overhead on the normal path) | a file whose parse returns `[]` is peeked; `timeline_merge` → the live handler (success = consumed, failure = dead-letter); anything else dead-letters as before |
| live E2E | **VERIFIED 2026-07-19** | 172 backlogged merges re-queued via `carton_management(retry_failed_observations=True)` → ALL 172 processed (`Timeline merge:` log lines, hundreds of relationships transferred each), queue drained, zero re-dead-letters |

SUCCESS CONSUMES, FAILURE DEAD-LETTERS. The handler returns a bool; the loop unlinks on True and moves
the file to `failed/` on False. It never raises into the loop.

MOOT MERGES SELF-CLEAR. An already-merged or missing `unnamed` transfers 0 and still succeeds, so stale
backlog files drain instead of bouncing forever.

THE DEAD `process_queue_file` COPY STAYS UNTOUCHED. Do NOT maintain it in lockstep; the live helper IS
the implementation of record.

The worker-loop routing touches the empty-parse branch ONLY, so there is zero overhead on the normal
path: a file whose parse returns `[]` is peeked, and `timeline_merge` goes to the live handler while
anything else dead-letters as before.

Known bound, named and accepted: if `real_concept` does not exist, the transfer matches nothing but the
Unnamed is still deleted — the dead path's own semantics, kept unchanged. Redesigning merge semantics is
a separate capability decision.

Dev-flow. Touching `_process_timeline_merge` or the empty-parse routing → edit both coherently, then the
gate: `python3 test_timeline_merge_live_path.py` all 4 green, run as a SCRIPT because the repo root IS
the `carton_mcp` package, plus `py_compile`, plus `pip install --no-deps`, plus a DAEMON RESTART — the
long-running daemon holds the old module; use the env-carrying restart command in `daemon-needs-env-vars`
and verify the PID changed AND that `Timeline merge:` lines appear on a real merge file.

If your change goes near `parse_queue_file_to_concepts` or `batch_create_concepts_neo4j`, STOP: that is
the `edit-carton-kv` dev-flow.
