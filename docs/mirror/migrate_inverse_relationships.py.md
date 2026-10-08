# doc(m): migrate_inverse_relationships.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/migrate_inverse_relationships.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-08-29 (176 lines, `wc -l`)

## Purpose (one paragraph)

A ONE-SHOT MIGRATION SCRIPT (run manually: `python3 migrate_inverse_relationships.py`) that backfills the FILESYSTEM wiki with inverse-relationship markdown files derived from what is already in Neo4j. It reads every `IS_A`/`PART_OF`/`DEPENDS_ON`/`INSTANTIATES`/`RELATES_TO` edge between `:Wiki` nodes, maps each to its inverse name (`has_instances`/`has_parts`/`supports`/`has_instances`/`relates_to`), and for each TARGET concept creates/appends `concepts/<Target>/components/<inverse_rel>/<Target>_<inverse_rel>.md` listing the sources. It only touches the markdown wiki tree under `ConceptConfig.base_path` — it writes nothing back to Neo4j. Since 2026-08-11 (42be5f90e) it normalizes names through THE canonical normalizer, imported — it no longer carries a normalizer of its own.

---

## Surface (1:1 — every public thing, in file order)

- `normalize_concept_name` — `migrate_inverse_relationships.py:24` — IMPORTED from `carton_mcp.add_concept_tool` and re-exported (`# noqa: F401`). The comment at `:21-23` records why the local copy was removed: it dropped the hyphen handling entirely, so a hyphenated name (UUIDs, session ids) normalized differently here than through `add_concept` — and a name that normalizes two ways is TWO NODES.
- `migrate_inverse_relationships()` — `migrate_inverse_relationships.py:27-166` — the whole program:
  1. Requires env `GITHUB_PAT` + `REPO_URL` (exits 1 if missing — `:33-39`); optional `BRANCH` (default `main`), `BASE_PATH`, plus the `NEO4J_*` trio with the usual defaults; builds a `ConceptConfig` (`:43-51`). NOTE it imports `from concept_config import ConceptConfig` (`:31`) — a FLAT import, so it must be run from the repo dir, not as `carton_mcp.migrate_inverse_relationships` (while the normalizer import at `:24` is the PACKAGE form — the two import styles coexist in one file).
  2. `relationship_inverses` map — `:57-63` — `IS_A→has_instances`, `PART_OF→has_parts`, `DEPENDS_ON→supports`, `INSTANTIATES→has_instances` (collides with IS_A's inverse), `RELATES_TO→relates_to` (self-inverse).
  3. Queries Neo4j via `heaven_base.tool_utils.neo4j_utils.KnowledgeGraphBuilder` (`:68-85`) for all such edges; closes the connection.
  4. Groups into `{target: {inverse_rel: [sources]}}` (`:91-100`).
  5. For each target: mkdirs `concepts/<Target>/components/<inverse_rel>/`, creates the inverse file with an H1 if absent, appends one `- <Target> <inverse_rel> [<source>](../<Source>/<Source>_itself.md)` line per source not already present verbatim (`:113-156`).
  6. Prints stats: concepts_processed / files_created / entries_added / entries_skipped (`:159-166`).
- `__main__` guard — `migrate_inverse_relationships.py:169-176` — runs the migration, printing traceback and exiting 1 on any exception.

## Data contracts

- Env: `GITHUB_PAT`, `REPO_URL` (REQUIRED — note: NOT `CARTON_REPO_URL` as `ConceptConfig` itself reads), `BRANCH`, `BASE_PATH`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`.
- Filesystem layout written: `<base_path>/concepts/<Normalized_Target>/components/<inverse_rel>/<Normalized_Target>_<inverse_rel>.md`, with names normalized exactly as `add_concept` normalizes them.
- Idempotent at the ENTRY level: an entry already present verbatim is skipped; re-running adds nothing.

## Deps

- `carton_mcp.add_concept_tool.normalize_concept_name` (package import, `:24`); `concept_config.ConceptConfig` (flat import, `:31`); `heaven_base.tool_utils.neo4j_utils.KnowledgeGraphBuilder` (`:68`); stdlib `os/sys/pathlib/typing/collections`.

## Defects / dead code

- The required `GITHUB_PAT`/`REPO_URL` are never actually USED for any git operation — the script neither clones nor pushes; the requirement is vestigial gating (`:33-39`).
- `IS_A` and `INSTANTIATES` both invert to `has_instances`, so the inverse file conflates subclassing with instantiation.
- Link targets `<Source>_itself.md` assume a file convention this script never verifies.
- `typing.Dict/List/Tuple` are imported (`:18`) and unused.
- One-shot tool; nothing in the package imports it (grep-verified 2026-06-10; the 2026-08-11 change touched only the normalizer). Keep classified as a maintenance script, not part of the serving path.
