Observation validation is LIVE as a loud dead-letter: a validation failure on the live UNWIND lane sends
the failing observation file to `/tmp/heaven_data/carton_queue/failed/` with the reason NAMED in its
`error_message` key, the drain never crashes, and recovery is
`carton_management(check_failed_observations=True)` plus `retry_failed_observations` — fix the file, set
`"fixed": true`, retry.

## States

| component | status | note |
|---|---|---|
| `add_concept_tool.observation_validation_errors` | **BUILT (a42c45d2b) + 6/6** | PURE, faithful port of the dead raise: observation shapes only; empty relationships skip; four required rels (is_a, part_of, has_personal_domain, has_actual_domain); has_personal_domain ∈ PERSONAL_DOMAINS. Errors name concept + tag + gap |
| `OBSERVATION_NON_TAG_KEYS` | ONE HOME in add_concept_tool | consumed by the validator AND by `parse_queue_file_to_concepts` (whose local copy was replaced with the import — a second copy would drift the two consumers apart) |
| daemon worker-loop branch | **BUILT (28c44bf82) + LIVE-PROVEN 2026-08-29** | per queue file, BEFORE parse: non-empty errors → `[Worker] VALIDATION dead-letter` line + `error_message` written into the file + `failed_files` (the existing mover) + continue. Live proof: an invalid observation through the real drain landed in failed/ naming `part_of, has_actual_domain` |
| `observe_from_identity_pov` both-edges (#198) | **BUILT (28040766a)** | has_actual_domain PRESERVED + targets mirrored onto has_domain, MERGED into any existing has_domain dict. Without this, every identity-POV write would dead-letter (its old transform rewrote has_actual_domain AWAY) |
| `observe_from_identity_pov` part_of merge (#204) | **BUILT (1767d65f5) + regression-pinned (7cb14d187)** | the identity collection merges into the concept's own part_of dict — one dict, both targets; the appended-second-dict shape silently dropped the user's part_of at the observation parse |

FAILURE IS LOUD AND RECOVERABLE, NEVER SILENT AND NEVER FATAL. A failing file is annotated with
`error_message` — the key the check and retry verbs already read — and moved to `failed/`; the drain
continues. Never a raise into the loop, never a silent skip, never a warn-and-write.

THE RULE IS THE DEAD VALIDATOR'S RULE, VERBATIM SCOPE: four required relationships on observation parts
with non-empty relationships (`is_a`, `part_of`, `has_personal_domain`, `has_actual_domain`), the
`PERSONAL_DOMAINS` enum on `has_personal_domain`, empty relationships skip, and non-observation shapes go
untouched. Errors name the concept, the tag and the gap. Tightening or loosening the rule is a design
change, not a refactor.

WRITERS THAT TRANSFORM RELATIONSHIPS MUST NEVER EMIT TWO DICTS OF ONE REL-NAME. The observation parse
assigns `rels_dict[rel_type] = related`, so the LAST dict WINS. Merge into the existing dict.

`has_actual_domain` IS CARRIED, NEVER REWRITTEN AWAY. Both `add_observation_batch`
(`_normalize_observation_domain_edges`) and `observe_from_identity_pov` carry both axes:
`has_actual_domain` is preserved and its targets are mirrored onto `has_domain`, MERGED into any existing
`has_domain` dict. The identity collection likewise merges into the concept's own `part_of` dict — one
dict, both targets.

`OBSERVATION_NON_TAG_KEYS` has ONE HOME in `add_concept_tool`, consumed by the validator AND by
`parse_queue_file_to_concepts`. A second copy drifts the two consumers apart.

The daemon's worker-loop branch runs per queue file, BEFORE parse: non-empty errors produce a `[Worker]
VALIDATION dead-letter` line, write `error_message` into the file, hand it to the existing mover, and
continue.

Dev-flow, and NEVER edit one place only. Touching `observation_validation_errors` /
`OBSERVATION_NON_TAG_KEYS`, the daemon's validation branch, or `observe_from_identity_pov`'s transform
loop → edit them coherently, then the gate: `python3 test_observation_validation_deadletter.py` all 6
markers AND `python3 test_observation_domain_normalization.py` 6/6 AND `py_compile` on touched files.
Then `pip install --no-deps .` plus a daemon restart per `daemon-needs-env-vars` — expect the watchdog
respawn to win the relaunch race — plus a LIVE wiring re-proof: an invalid observation file through the
real drain lands in `failed/` with the named reason. The MCP server serves old `observe_from_identity_pov`
code until reconnected.

Known bounds, named and accepted: the observation parse branch's last-wins assignment remains a latent
hazard for OTHER writers emitting duplicate rel-name dicts — the concepts-list branch already merges via
setdefault and extend. Fixing the parse to merge is a separate lane decision. The raw_concept lane and
the concepts-list lane carry NO required-rels validation; the resurrected rule covers observation shapes
exactly as the dead validator did, and widening it is a design fork.
