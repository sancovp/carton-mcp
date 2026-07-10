# doc(m): concept_config.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/concept_config.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

The env-var-backed configuration object for the whole CartON MCP — a single plain class, `ConceptConfig`, that resolves GitHub (PAT/repo/branch), Neo4j (URI/user/password/database), and the local wiki base path from constructor args with environment-variable fallbacks. Its header comment states the design: "Simplified config for MCP - no JSON file dependencies" — i.e. it is the replacement for the legacy `wiki_config.py` (which reads a JSON file from the legacy `/home/GOD/core` tree). Every Neo4j-touching path in the package (`server_fastmcp`, `add_concept_tool`, `carton_utils`, `migrate_inverse_relationships`) constructs one of these.

---

## Surface (1:1 — every public thing, in file order)

- `class ConceptConfig` — `concept_config.py:8`
  - `__init__(github_pat=None, repo_url=None, neo4j_url=None, neo4j_username=None, neo4j_password=None, branch="main", base_path=None, neo4j_database="neo4j")` — `concept_config.py:11`
    - Each `None` arg falls back to an env var (`concept_config.py:21-25`): `GITHUB_PAT` (default `""`), `CARTON_REPO_URL` (default `""`), `NEO4J_URI` (default `bolt://host.docker.internal:7687`), `NEO4J_USER` (default `neo4j`), `NEO4J_PASSWORD` (default `password`).
    - Sets attributes: `github_pat`, `repo_url`, `branch`, `base_path` (via `_get_base_path`), `neo4j_url`, `neo4j_username`, `neo4j_password`, `neo4j_database`.
  - `_get_base_path(base_path=None) -> str` — `concept_config.py:38`
    - If `base_path` is provided, returns it as-is. Otherwise reads `HEAVEN_DATA_DIR` env (default `/tmp/heaven_data`), mkdirs it if missing (`concept_config.py:48-50`), and returns `<HEAVEN_DATA_DIR>/wiki` — the wiki ROOT, not the `concepts/` subdir (the comment at `concept_config.py:52-53` says `add_concept_tool` clones the repo here and works with `concepts/` inside it).
  - `private_wiki_url` (property) — `concept_config.py:59` — alias for `self.repo_url`.
  - `private_wiki_branch` (property) — `concept_config.py:63` — alias for `self.branch`.

## Data contracts

- Env vars consumed: `GITHUB_PAT`, `CARTON_REPO_URL`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `HEAVEN_DATA_DIR`.
- `base_path` contract: the WIKI ROOT directory (`<HEAVEN_DATA_DIR>/wiki`); consumers append `concepts/` themselves.
- The two properties replicate the subset of the legacy `WikiConfig` interface that callers still use (`private_wiki_url`, `private_wiki_branch`), making `ConceptConfig` a drop-in for it.

## Deps

- Stdlib only: `os`, `logging`, `pathlib.Path`.
- Consumers (grep-verified): `server_fastmcp.py:23,119`; `add_concept_tool.py:82,94,1420,2676` plus ~15 functions typed against it; `carton_utils.py:1041-1043` (lazy import inside a method); `migrate_inverse_relationships.py:30,42`.

## Defects / dead code

- The `NEO4J_PASSWORD` fallback is the literal `"password"` — correct only because the dev container's Neo4j uses it; on any other deployment a missing env var silently yields wrong credentials instead of an error.
- `logger.info` in `_get_base_path` fires on every construction; some call paths construct a fresh `ConceptConfig` per tool call, producing repeated log chatter. Cosmetic.
