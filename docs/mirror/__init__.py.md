# doc(m): __init__.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/__init__.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

The package root of `carton_mcp`. The repo directory itself IS the package: `pyproject.toml:31-33` maps `packages = ["carton_mcp"]` with `package-dir = {"carton_mcp" = "."}`, so this flat directory installs as the `carton_mcp` package and this file is `carton_mcp/__init__.py`. It exposes exactly one public symbol — `add_concept_tool_func` re-exported from `add_concept_tool` — plus the version string. The docstring still carries the project's original name ("Idea Concepts MCP - Zettelkasten-style concept management").

---

## Surface (1:1 — every public thing, in file order)

- Module docstring — `__init__.py:1-3` — "Idea Concepts MCP - Zettelkasten-style concept management".
- `from .add_concept_tool import add_concept_tool_func` — `__init__.py:5` — the single re-export; importing the package therefore eagerly imports the (large) `add_concept_tool` module.
- `__version__ = "0.1.67"` — `__init__.py:7`.
- `__all__ = ["add_concept_tool_func"]` — `__init__.py:8-10`.

## Data contracts

- Public package API contract: `carton_mcp.add_concept_tool_func` (the core concept-write entrypoint; see `docs/mirror/add_concept_tool.py.md`).
- Version is maintained HERE, by hand, separately from `pyproject.toml` — two version sources.

## Deps

- `.add_concept_tool` (intra-package). Nothing else.

## Defects / dead code

- Importing the bare package pulls in all of `add_concept_tool` (and its transitive neo4j/git machinery) even for consumers that only want the version — heavy import side-effect surface. UNVERIFIED whether any consumer is hurt by this in practice.
- `__version__` (0.1.67) is not synchronized with `pyproject.toml`'s version field by any mechanism; drift is possible.
