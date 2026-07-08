# doc(m): backfill_wiki_files.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/backfill_wiki_files.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

A ONE-TIME MAINTENANCE SCRIPT (`python3 backfill_wiki_files.py [--dry-run]`) that closes the Neo4j→filesystem sync gap: for every `:Wiki` concept in Neo4j that has no `<Name>_itself.md` under `<HEAVEN_DATA_DIR>/wiki/concepts/`, it generates that markdown file from the node's `n`/`d` and its outgoing relationships. Neo4j is read-only here; the script only WRITES markdown. Unlike `migrate_inverse_relationships.py` it needs no git env vars and uses an acronym-preserving name normalizer.

---

## Surface (1:1 — every public thing, in file order)

- `normalize_concept_name(name) -> str` — `backfill_wiki_files.py:24` — spaces→underscores, then per-`_`-part capitalization that PRESERVES all-caps acronyms (`part.isupper() and len(part)>1` kept as-is — `:34-35`); otherwise first-letter-upper with the rest untouched. A third, distinct normalizer in the package (cf. `migrate_inverse_relationships.py:21`'s `.title()` variant).
- `get_all_concepts_from_neo4j() -> list[dict]` — `backfill_wiki_files.py:41`
  - Connects via `heaven_base.tool_utils.neo4j_utils.KnowledgeGraphBuilder` with the `NEO4J_*` env trio (defaults `bolt://host.docker.internal:7687` / `neo4j` / `password`).
  - Query 1 (`:52-55`): all `(c:Wiki)` → `{name, description}`; empty description becomes `"No description for <name>"`.
  - Query 2 (`:70-73`): ALL outgoing edges `(c:Wiki)-[r]->(t:Wiki)`; appended per source under the LOWERCASED relationship type.
  - Returns `[{name, description, relationships: {rel_type_lower: [targets]}}]`; handles both dict-style and index-style records defensively (`:60-61, 77-79`).
- `create_wiki_file(concept, wiki_concepts_dir) -> (bool, str)` — `backfill_wiki_files.py:91`
  - Skips (`False, "exists"`) if `<dir>/<Normalized>/<Normalized>_itself.md` already exists; never overwrites.
  - Writes: H1 = normalized name; `## Overview` = description; `## Relationships` with one `### <Rel Type>` section per sorted rel type, each line `- <Name> <rel_type> [<target>](../<NormTarget>/<NormTarget>_itself.md)` (`:112-131`).
- `backfill_wiki_files(dry_run=False)` — `backfill_wiki_files.py:135`
  - Computes `wiki_concepts_dir = <HEAVEN_DATA_DIR (default /tmp/heaven_data)>/wiki/concepts`.
  - Existing-file detection: scans dirs and checks `<dirname>/<dirname>_itself.md` (`:150-156`); missing = concepts whose NORMALIZED name is not in that set.
  - Dry-run prints the first 10 missing and returns. Real run creates files with per-100 progress lines and per-concept error catch (`:190-199`), then prints created/errors/already-existed totals.
- `__main__` guard — `backfill_wiki_files.py:207-209` — `--dry-run` flag is the only CLI arg.

## Data contracts

- Env: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `HEAVEN_DATA_DIR` (default `/tmp/heaven_data`).
- Filesystem written: `<HEAVEN_DATA_DIR>/wiki/concepts/<Normalized>/<Normalized>_itself.md` — the same `_itself.md` convention `add_concept_tool` maintains.
- Idempotent at FILE level: existing files are never touched (so stale files do not get refreshed descriptions — by design, this is a backfill not a sync).

## Deps

- `heaven_base.tool_utils.neo4j_utils.KnowledgeGraphBuilder` (lazy import inside `get_all_concepts_from_neo4j`); stdlib `os/sys/pathlib`. No intra-package imports; nothing in the package imports this script (grep-verified).

## Defects / dead code

- Loads the ENTIRE graph (all nodes + all edges) into memory in two unbounded queries — fine for the current scale, no pagination.
- The relationship dump includes EVERY edge type (not just the ontology core), so generated files mirror whatever edge noise exists in the graph.
- The final "Already existed" stat (`:204`) counts `create_wiki_file`'s `(False,"exists")` returns implicitly as `len(missing) - created - errors`; a concept skipped for "empty name" is also counted there — minor stat blur.
