# doc(m): carton_render.py

**Module:** `carton-mcp/carton_render.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Carton_Read_Facade — feature boundary of `Giint_Feature_Carton_Mcp_Carton_Read_Facade`

- **user action:** an agent or a doc-mirror CLI reads the graph through carton: the query_wiki_graph MCP tool, or CartOnUtils.query_wiki_graph from python, and must receive the words, never the auto-linker wiki markup stored in n.d
- **doc(v):** `knowledge/carton-mcp/docs/vision/server_fastmcp.py.md`
- **outputs to:** `tool_dispatch_loop`
- **sealed:** v16, key `304491fe0fbc2848`, commit `c5a453be4`, valid from 2026-10-08T04:41:37
- **ranges in this module** (layer order):
  - `L0 tool` · `carton_render.py:1-68` — carton_render, pure, cards 766 and 770: render_answer lays a tool result out the way seem and the gnosys router answer: scalars lead, every collection follows under key (count) with one record per block led by a dash, a list as rows (count) and an empty one as (none), a multi-line string indented under its key, and the whole answer passes through answer_refs.encode_refs so each repeated sequence, a path or an identifier, is said once as an @N ref in a leading refs legend. Its helpers: _present drops None and empty lists and dicts; _lines renders one value at an indent, a mapping as its present fields scalars first, a list as rows, a string through clean; _members renders each item of a list as its own block led by a dash
- **also passes through:** `server_fastmcp.py`, `base/answer-refs/answer_refs/__init__.py`, `carton_utils.py`, `test_carton_read_facade.py`, `base/answer-refs/tests/test_answer_refs.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
