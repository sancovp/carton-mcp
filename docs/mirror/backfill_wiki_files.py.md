# doc(m): backfill_wiki_files.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/backfill_wiki_files.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-08-29 (201 lines, `wc -l`)

## Purpose (one paragraph)

A ONE-TIME MAINTENANCE SCRIPT (`python3 backfill_wiki_files.py [--dry-run]`) that closes the Neo4j→filesystem sync gap: for every `:Wiki` concept in Neo4j that has no `<Name>_itself.md` under `<HEAVEN_DATA_DIR>/wiki/concepts/`, it generates that markdown file from the node's `n`/`d` and its outgoing relationships. Neo4j is read-only here; the script only WRITES markdown. Unlike `migrate_inverse_relationships.py` it needs no git env vars. Since 2026-08-11 (42be5f90e) it normalizes names through THE canonical normalizer, imported — its own acronym-preserving variant is gone.

---

## Surface (1:1 — every public thing, in file order)

- `normalize_concept_name` — `backfill_wiki_files.py:30` — IMPORTED from `carton_mcp.add_concept_tool` and re-exported (`# noqa: F401`). The comment at `:24-29` records why: this file used to carry its OWN fifth variant (it preserved all-caps acronyms and never touched hyphens), so the same name normalized differently depending on which module touched it — and a name that normalizes two ways is TWO NODES.
- `get_all_concepts_from_neo4j() -> list[dict]` — `backfill_wiki_files.py:33-80`
  - Connects via `heaven_base.tool_utils.neo4j_utils.KnowledgeGraphBuilder` with the `NEO4J_*` env trio (defaults `bolt://host.docker.internal:7687` / `neo4j` / `password`, `:37-41`).
  - Query 1 (`:44-48`): all `(c:Wiki)` → `{name, description}`; empty description becomes `"No description for <name>"` (`:57`).
  - Query 2 (`:62-66`): ALL outgoing edges `(c:Wiki)-[r]->(t:Wiki)`; appended per source under the LOWERCASED relationship type (`:73-77`).
  - Returns `[{name, description, relationships: {rel_type_lower: [targets]}}]`; handles both dict-style and index-style records defensively (`:52-53`, `:69-71`).
- `create_wiki_file(concept, wiki_concepts_dir) -> (bool, str)` — `backfill_wiki_files.py:83-124`
  - Returns `(False, "empty name")` for a nameless concept (`:86-87`); skips (`False, "exists"`) if `<dir>/<Normalized>/<Normalized>_itself.md` already exists (`:97-98`); never overwrites.
  - Writes: H1 = normalized name; `## Overview` = description; `## Relationships` with one `### <Rel Type>` section per sorted rel type, each line `- <Name> <rel_type> [<target>](../<NormTarget>/<NormTarget>_itself.md)` (`:104-123`).
- `backfill_wiki_files(dry_run=False)` — `backfill_wiki_files.py:127-196`
  - Computes `wiki_concepts_dir = <HEAVEN_DATA_DIR (default /tmp/heaven_data)>/wiki/concepts` (`:129-130`).
  - Existing-file detection: scans dirs and checks `<dirname>/<dirname>_itself.md` (`:142-148`); missing = concepts whose NORMALIZED name is not in that set (`:154-158`).
  - Dry-run prints the first 10 missing and returns (`:167-173`). Real run creates files with per-100 progress lines and per-concept error catch (`:182-191`), then prints created/errors/already-existed totals (`:193-196`).
- `__main__` guard — `backfill_wiki_files.py:199-201` — `--dry-run` flag is the only CLI arg.

## Data contracts

- Env: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `HEAVEN_DATA_DIR` (default `/tmp/heaven_data`).
- Filesystem written: `<HEAVEN_DATA_DIR>/wiki/concepts/<Normalized>/<Normalized>_itself.md` — the same `_itself.md` convention `add_concept_tool` maintains, under the same normalization.
- Idempotent at FILE level: existing files are never touched (so stale files do not get refreshed descriptions — by design, this is a backfill not a sync).

## Deps

- `carton_mcp.add_concept_tool.normalize_concept_name` (package import, `:30`); `heaven_base.tool_utils.neo4j_utils.KnowledgeGraphBuilder` (lazy import inside `get_all_concepts_from_neo4j`, `:35`); stdlib `os/sys/pathlib`. Nothing in the package imports this script (grep-verified 2026-06-10; the 2026-08-11 change touched only the normalizer).

## Defects / dead code

- Loads the ENTIRE graph (all nodes + all edges) into memory in two unbounded queries — no pagination.
- The relationship dump includes EVERY edge type (not just the ontology core), so generated files mirror whatever edge noise exists in the graph.
- The final "Already existed" stat (`:196`) counts `create_wiki_file`'s `(False,"exists")` returns implicitly as `len(missing) - created - errors`; a concept skipped for "empty name" is also counted there — minor stat blur.
- This script's existence-detection keys on directory NAMES already on disk, while the daemon's wiki lane now refuses garbage paths through `carton_pathguard` (issue #206); this backfill does NOT call the guard, so a garbage name still in the graph would be written by it. Flagged, not fixed here.
