# doc(m): wiki_config.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/wiki_config.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

LEGACY JSON-file-backed configuration loader, superseded by `concept_config.py` (whose header explicitly says "no JSON file dependencies"). `WikiConfig` loads a JSON config from a hardcoded path in the legacy `/home/GOD/core` tree and exposes the private-wiki repo URL/branch/PAT/base-path as properties; `get_wiki_config()` is a function-attribute singleton around it. Nothing in the current package imports it (grep-verified: zero importers among the repo's .py files) — it is dead code kept in the tree.

---

## Surface (1:1 — every public thing, in file order)

- `class WikiConfig` — `wiki_config.py:7`
  - `__init__(config_path="/home/GOD/core/computer_use_demo/tools/base/utils/zk_config.json")` — `wiki_config.py:10` — stores the path, initializes `self._config = {}`, immediately calls `load_config()` (so construction RAISES if the file is absent).
  - `load_config() -> None` — `wiki_config.py:15` — `json.load`s the file into `self._config`; wraps any failure in a re-raised generic `Exception` with the path in the message.
  - `private_wiki_url` (property) — `wiki_config.py:23` — returns `_config["wiki"]["private_repo"]["url"]`.
  - `private_wiki_branch` (property) — `wiki_config.py:28` — returns `_config["wiki"]["private_repo"]["branch"]`.
  - `github_pat` (property) — `wiki_config.py:33` — returns `_config["wiki"]["private_repo"]["pat"]`.
  - `base_path` (property) — `wiki_config.py:38` — returns `_config["wiki"]["base_path"]`.
- `get_wiki_config() -> WikiConfig` — `wiki_config.py:43` — singleton via `hasattr(get_wiki_config, '_instance')`; constructs `WikiConfig()` with the default (legacy) path on first call.

## Data contracts

- Expected JSON shape: `{"wiki": {"private_repo": {"url", "branch", "pat"}, "base_path"}}`.
- The default `config_path` points into `/home/GOD/core/...` — the legacy off-limits tree; on a machine without that file every `WikiConfig()`/`get_wiki_config()` call raises.

## Deps

- Stdlib only: `json`, `pathlib.Path`, `typing`.
- Importers: NONE in this repo (grep over `*.py` excluding build/egg-info/pycache finds only the module itself). `ConceptConfig` replicates the `private_wiki_url`/`private_wiki_branch` interface it provided.

## Defects / dead code

- ENTIRE MODULE IS DEAD CODE: zero importers; superseded by `concept_config.py`. Candidate for removal (a vision-level decision, not done here).
- Hardcoded absolute legacy path as the default `config_path` (`wiki_config.py:10`).
- `load_config` catches all exceptions and re-raises as bare `Exception`, losing the original type/traceback chain.
