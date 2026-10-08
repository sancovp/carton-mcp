# doc(m): server_fastmcp.py

**Module:** `carton-mcp/server_fastmcp.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 6 sealed boundaries land here

## Features whose sealed boundary lands in this module

### Bounded_Collection_Walk — feature boundary of `Giint_Feature_Bounded_Collection_Walk`

- **user action:** the agent calls the carton activate_collection MCP tool on a collection and must receive its members without any hub member importing its whole subtree, every stop reported ahead of the members
- **doc(v):** `knowledge/carton-mcp/docs/vision_extracted/activate_collection.md`
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v2, key `256db61ccf68e43e`, commit `21bee0c41`, valid from 2026-09-29T21:18:29
- **ranges in this module** (layer order):
  - `L0 face` · `server_fastmcp.py:3585-3611` — THE FACE: the activate_collection MCP tool, its signature and the docstring the agent reads. depth, hub_cap and boundary_types pass straight through to the executor, so every knob of the walk is reachable from the tool call
  - `L0 face` · `server_fastmcp.py:3612-3624` — the tool body: one call to get_collection_concepts, the result rendered by _fmt on success, the error string on failure or exception
- **also passes through:** `carton_utils.py`, `carton_bounded_walk.py`, `test_carton_bounded_walk.py`

### Carton_Read_Facade — feature boundary of `Giint_Feature_Carton_Mcp_Carton_Read_Facade`

- **user action:** an agent or a doc-mirror CLI reads the graph through carton: the query_wiki_graph MCP tool, or CartOnUtils.query_wiki_graph from python, and must receive the words, never the auto-linker wiki markup stored in n.d
- **doc(v):** `knowledge/carton-mcp/docs/vision/server_fastmcp.py.md`
- **outputs to:** `tool_dispatch_loop`
- **sealed:** v15, key `482d03b2bf6c0bb3`, commit `5fecd2b7c`, valid from 2026-10-04T03:46:22
- **ranges in this module** (layer order):
  - `L0 tool` · `server_fastmcp.py:1723-1780` — the query_wiki_graph MCP tool: SM-gate check, the library facade call, _fmt on the data, the Title_Case reminder on an empty result, errors returned as text
  - `L0 tool` · `server_fastmcp.py:57-105` — _strip_md, _dedup_desc, _fmt and _fmt_inner: every tool result is laid out by carton_render.render_answer with each string through the canonical stripper and the paragraph dedup, then overflows to a file past 10000 chars
  - `L0 tool` · `server_fastmcp.py:107-115` — the FastMCP instance: the registration point every tool passes through, where a return-value chokepoint belongs
- **also passes through:** `carton_render.py`, `base/answer-refs/answer_refs/__init__.py`, `carton_utils.py`, `test_carton_read_facade.py`, `base/answer-refs/tests/test_answer_refs.py`

### Carton_Soma_Verdict_Relay — feature boundary of `Carton_Soma_Verdict_Relay`

- **user action:** the agent calls the carton add_concept or get_concept MCP tool and must read, in the result it gets back, what SOMA graded and, last, the exact fill or drop SOMA asks of it, plus one line pointing at the soma-help skill and every CRITICAL line of the verdict
- **doc(v):** `knowledge/carton-mcp/docs/vision/add_concept_tool.py.md`
- **outputs to:** `['tool_dispatch_loop']`
- **sealed:** v15, key `60e8dc465f987672`, commit `b80684b69`, valid from 2026-10-01T07:39:39
- **ranges in this module** (layer order):
  - `L0 entry` · `server_fastmcp.py:538-692` — the add_concept MCP tool: builds the relationships, calls add_concept_tool_func, resolves a soma_run_id accept into a note, and returns _format_concept_result of the result and that note
  - `L1 relay` · `server_fastmcp.py:428-446` — _format_concept_result: the result first line, then a note about the call itself (the soma_run_id accept), then SOMA DEATH block, then the rest, so the DO lines stay last
  - `L1 relay` · `server_fastmcp.py:1884-2087` — get_concept: Name (with the DO pointer when there are DO lines), Description with its coverage score, Props, Rels, then the live SOMA verdict for the concept relationships through soma_concept_status, soma_grade_flags, soma_grade_line and soma_result_lines: the SOMA line, the numbered lines, the raw verdict (event name, d-chains fired, every block) only with details=True, the SOMA help line and the DO lines last
- **also passes through:** `add_concept_tool.py`, `base/soma-prolog/soma_prolog/core.py`, `test_soma_critical_relay.py`, `test_cb_failure_note.py`, `.claude/skills/soma-help/SKILL.md`

### Domain_Axis_Front_Door — feature boundary of `Giint_Feature_Domain_Axis_Front_Door`

- **user action:** a writer calls add_concept naming a domain or subdomain that is not yet a domain node and supplies domain_about, domain_part_of or subdomain_about, and that node must be written first as is_a Domain with has_about and part_of its parent, while a write without them lands as said and SOMA grades the node against that same subject
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['carton_queue_ingest']`
- **sealed:** v2, key `5d3dfdafe92d8173`, commit `b80684b69`, valid from 2026-10-01T07:39:37
- **ranges in this module** (layer order):
  - `L0 entry` · `server_fastmcp.py:557-559` — the add_concept MCP tool three optional params domain_about, domain_part_of and subdomain_about
  - `L0 entry` · `server_fastmcp.py:576-582` — their docstring: a domain or subdomain not yet a domain node is written first, is_a Domain with has_about and part_of its parent, and without them it lands as said and SOMA grades it
  - `L0 entry` · `server_fastmcp.py:656-656` — the pass-through: the MCP tool hands the three params to add_concept_tool_func unchanged
- **also passes through:** `add_concept_tool.py`, `carton_domain_axis.py`, `base/soma-prolog/soma_prolog/util_deps/prolog_interop.py`, `test_carton_domain_axis.py`, `base/soma-prolog/tests/test_domain_slot_targets_are_domains.py`

### Progressive_Disclosure — feature boundary (no Giint_Feature node declared)

- **user action:** the agent asks carton what the LEVELS of the graph are, or names one level and asks for its members, instead of writing freehand Cypher to navigate
- **doc(v):** `knowledge/carton-mcp/docs/vision/_progressively_disclose.md`
- **outputs to:** `tool_dispatch_loop`
- **sealed:** v4, key `f6d1644592f54ba3`, commit `28670f88e`, valid from 2026-09-29T12:56:44
- **ranges in this module** (layer order):
  - `L5 face` · `server_fastmcp.py:3626-3675` — THE RELEASE IS DISABLED, DELIBERATELY, AND THIS RANGE IS THE COMMENTED-OUT TOOL PLUS THE INSTRUCTION THAT DISABLED IT. Line 3682 carries Isaac 2026-09-14 verbatim: DISABLED on Isaacs instruction, this tool is NOT REAL and should not exist yet, it was never actually made as a decided capability, and it was being offered to the agent as THE navigation surface of the graph, which is not a thing anyone agreed it is; commented out rather than deleted so the code is recoverable if it is ever genuinely designed; the pure half carton_disclose.py and its unit gate test_carton_disclose.py are left on disk untouched and are now unreferenced by the server. Lines 3683-3731 are that tool, every line prefixed with a hash including its decorator, so progressively_disclose is absent from the live MCP tool list -- confirmed from both sides, the source and the tool listing. WHAT THIS BOUNDARY THEREFORE IS: a traced capability with a LIVE PURE HALF and NO RELEASE. The hops below it are real, current code that runs when called; nothing calls them. The seal is honest about exactly that, which is why it is sealed rather than left invalid: an invalid boundary covers nothing, so the pure module would sit under no boundary at all and the next agent to open it would find neither the trace nor the ruling. Re-enabling is a DESIGN decision that is Isaacs, not a re-seal -- if it is ever taken, this hop becomes a live release again and the state line below must be rewritten with it  ⟵ RELEASE
- **also passes through:** `carton_disclose.py`, `test_carton_disclose.py`

### Worker_Restart — feature boundary of `Giint_Feature_Carton_Mcp_Worker_Restart`

- **user action:** the agent calls the carton carton_management MCP tool with restart_bg_server, because a pip install changes no running observation worker, and one call must end with a live worker running the installed code, or a named survivor, and say which
- **doc(v):** `docs/vision/_carton_worker_control.md`
- **outputs to:** `['dead_letter_lane_fires']`
- **sealed:** v3, key `e610c45b7e4265a1`, commit `65b574104`, valid from 2026-10-04T07:21:03
- **ranges in this module** (layer order):
  - `L0 entry` · `server_fastmcp.py:1318-1371` — carton_management, the carton MCP tool: its restart_bg_server branch is a thin wrapper that hands the installed daemon file to carton_worker_control.restart_worker
  - `L0 entry` · `server_fastmcp.py:1372-1377` — the verdict message is appended to the tool answer the agent reads; an exception is reported as a failed restart  ⟵ RELEASE
- **also passes through:** `carton_worker_control.py`, `observation_worker_daemon.py`, `test_carton_worker_control.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
