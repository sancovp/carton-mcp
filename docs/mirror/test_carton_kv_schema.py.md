# doc(m): test_carton_kv_schema.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_carton_kv_schema.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

The GRAPH-BOUND lib gate for the CartonObj capability's STEP-4 logic — the `carton_utils` wrappers that need a graph connection, tested against a `FakeGraph` stub (no real neo4j) plus a real (temp-dir) observation queue. 13 tests prove: `check_kv_refs` fuzzy did-you-mean, `register_kv_schemas` auto-typing (`IS_A Carton_Kv_Schema` + `USES_KV_SCHEMA`), `validate_carton_obj` (schema bad-key + unresolved-ref reporting), the `edit_carton_obj` WRITE GUARD (refuse-on-unknown-ref, nothing written), the `remove_fence` op's queue payload, and the DAEMON-PATH REGRESSION that `parse_queue_file_to_concepts` forwards `removed_fences` (the canonical bug from the `edit-carton-kv` dev-flow). One of the four lib-gate files.

## How to run

- `python3 test_carton_kv_schema.py` (own runner `:245-259`, PASS/FAIL summary, exit 1 on failure) or via pytest.
- Self-isolating: sets `HEAVEN_DATA_DIR` to a fresh `tempfile.mkdtemp(prefix="kvschema_")` BEFORE importing `carton_mcp` (`:12`), so the queue writes land in a throwaway dir. NOTE: it imports the INSTALLED `carton_mcp` package, not the flat repo modules — the running-code-is-the-installed-package rule applies.

## Test infrastructure

- `_drain_queue()` — `:19` — reads + deletes all `*.json` in `get_observation_queue_dir()`; used to assert exactly what `edit_carton_obj` queued.
- `class FakeGraph` — `:28` — stub `KnowledgeGraphBuilder`: a `{name: description-or-None}` store; `execute_query` pattern-matches the FOUR query shapes the wrappers issue (existence check, `RETURN c.d` read via `$n` or `$name`, the `toLower(c.n) CONTAINS $tok` fuzzy candidate scan, and any `MERGE` which is recorded in `self.merges` and succeeds). This doubles as living documentation of the Cypher contract the wrappers depend on.
- `_SCHEMA_DESC` — `:56` — a concept description holding an `is_schema=true` fence whose body is a json-schema (`tier:integer` required, `repo:string`).
- `_store()` — `:65` — the base fake graph: `Reg_Schema`, `Cave_Repo`, `Free_Tier`, `A_Unit`, `B_Unit`.

## What the suite proves (invariants asserted)

### check_kv_refs (fuzzy did-you-mean) — `:80-98`
- All-resolving refs → `{ok: True, unresolved: {}}`.
- A typo (`Cave_Rep`) → `ok: False` with the REAL concept (`Cave_Repo`) in its did-you-mean suggestion list.
- A no-match ref → unresolved with an EMPTY suggestion list (no fabricated suggestions).

### register_kv_schemas (auto-typing) — `:104-124`
- A concept whose description holds an `is_schema=true` fence gets an `IS_A Carton_Kv_Schema` MERGE; returns `typed_schemas: ["reg_schema"]`.
- A fence with `schema=Reg_Schema` gets a `USES_KV_SCHEMA` MERGE; returns `uses_schemas: ["Reg_Schema"]`.
- No fences → exact no-op (`{typed_schemas: [], uses_schemas: []}`, zero MERGEs).

### validate_carton_obj — `:130-152`
- Good payload (schema-conformant, refs resolve) → `success`, `valid: True`, empty `errors`/`unresolved_refs`.
- Schema violation reports WHICH key (`errors[].path == "tier"`); unknown ref reported under `unresolved_refs` WITH its did-you-mean suggestion.

### edit_carton_obj WRITE GUARD — `:158-180`
- Setting a `$ref` to a nonexistent concept → `success: False`, `"unresolved"` in error, suggestion in `did_you_mean`, and `g.merges == []` — NOTHING written (no silent stub spawn).
- Known ref → write proceeds (queued). Literal (non-ref) value → no guard trip.

### remove_fence op (STEP 4B) — `:186-218`
- `remove_fence` queues exactly ONE entry with `desc_update_mode: "replace"`, `removed_fences: ["reg"]` (the daemon-guard signal), the target fence GONE from the queued description, the sibling fence preserved.
- `remove_fence` on a missing fence → `success: False` and NOTHING queued.
- A normal leaf edit queues `removed_fences: []`.

### Daemon-path regression — `:226-242`
- `observation_worker_daemon.parse_queue_file_to_concepts` MUST forward `removed_fences` (+ `desc_update_mode`) from a `raw_concept` queue file to the parsed concept dict — guarding the runtime bug where the MAIN worker loop's parse path dropped `removed_fences`, the fence-preservation guard saw `[]`, and carried a removed fence back.

## Deps

- `carton_mcp.carton_utils` (`check_kv_refs`, `register_kv_schemas`, `validate_carton_obj`, `edit_carton_obj`), `carton_mcp.add_concept_tool.get_observation_queue_dir`, `carton_mcp.observation_worker_daemon.parse_queue_file_to_concepts` (lazy, inside the regression test); stdlib `json/os/tempfile/pathlib`.

## Defects / dead code

- `FakeGraph` matches queries by collapsed-whitespace SUBSTRING — if the wrappers' Cypher text drifts, the stub silently returns `[]` instead of failing loudly; a passing suite therefore also certifies the query-shape coupling, and a Cypher rewrite must update the stub in lockstep.
- The `HEAVEN_DATA_DIR` mkdtemp is never cleaned up (one throwaway dir per run). Cosmetic.
