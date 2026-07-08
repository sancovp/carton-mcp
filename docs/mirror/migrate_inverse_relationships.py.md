# doc(m): migrate_inverse_relationships.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/migrate_inverse_relationships.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

A ONE-SHOT MIGRATION SCRIPT (run manually: `python3 migrate_inverse_relationships.py`) that backfills the FILESYSTEM wiki with inverse-relationship markdown files derived from what is already in Neo4j. It reads every `IS_A`/`PART_OF`/`DEPENDS_ON`/`INSTANTIATES`/`RELATES_TO` edge between `:Wiki` nodes, maps each to its inverse name (`has_instances`/`has_parts`/`supports`/`has_instances`/`relates_to`), and for each TARGET concept creates/appends `concepts/<Target>/components/<inverse_rel>/<Target>_<inverse_rel>.md` listing the sources. It only touches the markdown wiki tree under `ConceptConfig.base_path` — it writes nothing back to Neo4j.

---

## Surface (1:1 — every public thing, in file order)

- `normalize_concept_name(name) -> str` — `migrate_inverse_relationships.py:21` — `replace(' ', '_').title()`. NOTE: a duplicate of the same idea elsewhere in the package, and `.title()` lowercases interior capitals (e.g. `MCP` → `Mcp`).
- `migrate_inverse_relationships()` — `migrate_inverse_relationships.py:26` — the whole program:
  1. Requires env `GITHUB_PAT` + `REPO_URL` (exits 1 if missing — `:32-38`); optional `BRANCH` (default `main`), `BASE_PATH`, plus the `NEO4J_*` trio with the usual defaults; builds a `ConceptConfig` (`:42-50`). NOTE it imports `from concept_config import ConceptConfig` (`:30`) — a FLAT import, so it must be run from the repo dir, not as `carton_mcp.migrate_inverse_relationships`.
  2. `relationship_inverses` map — `:56-62` — `IS_A→has_instances`, `PART_OF→has_parts`, `DEPENDS_ON→supports`, `INSTANTIATES→has_instances` (collides with IS_A's inverse), `RELATES_TO→relates_to` (self-inverse).
  3. Queries Neo4j via `heaven_base.tool_utils.neo4j_utils.KnowledgeGraphBuilder` (`:67-84`) for all such edges; closes the connection.
  4. Groups into `{target: {inverse_rel: [sources]}}` (`:90-99`).
  5. For each target: mkdirs `concepts/<Target>/components/<inverse_rel>/`, creates the inverse file with an H1 if absent, appends one `- <Target> <inverse_rel> [<source>](../<Source>/<Source>_itself.md)` line per source not already present verbatim (`:112-155`).
  6. Prints stats: concepts_processed / files_created / entries_added / entries_skipped (`:157-165`).
- `__main__` guard — `migrate_inverse_relationships.py:168-175` — runs the migration, printing traceback and exiting 1 on any exception.

## Data contracts

- Env: `GITHUB_PAT`, `REPO_URL` (REQUIRED — note: NOT `CARTON_REPO_URL` as `ConceptConfig` itself reads), `BRANCH`, `BASE_PATH`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`.
- Filesystem layout written: `<base_path>/concepts/<Normalized_Target>/components/<inverse_rel>/<Normalized_Target>_<inverse_rel>.md`.
- Idempotent at the ENTRY level: an entry already present verbatim is skipped; re-running adds nothing.

## Deps

- `concept_config.ConceptConfig` (flat import, `:30`); `heaven_base.tool_utils.neo4j_utils.KnowledgeGraphBuilder` (`:67`); stdlib `os/sys/pathlib/typing/collections`.

## Defects / dead code

- The required `GITHUB_PAT`/`REPO_URL` are never actually USED for any git operation — the script neither clones nor pushes; the requirement is vestigial gating (`:32-38`).
- `IS_A` and `INSTANTIATES` both invert to `has_instances`, so the inverse file conflates subclassing with instantiation.
- `normalize_concept_name`'s `.title()` mangles acronyms and digits-with-underscores; link targets `<Source>_itself.md` assume a file convention this script never verifies.
- One-shot tool; nothing in the package imports it (grep-verified). Keep classified as a maintenance script, not part of the serving path.
