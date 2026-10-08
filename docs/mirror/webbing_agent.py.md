# doc(m): webbing_agent.py

**Module:** `carton-mcp/webbing_agent.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Webbing_Agent — feature boundary (no Giint_Feature node declared)

- **user action:** the sophia daemon ensures the webbing worker at start, or an operator ticks it, and concepts the main agent left as unstructured prose get real graph structure added instead of staying as auto stubs
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['meta_sophia_audit']`
- **sealed:** v23, key `8714a1ec836b8ea4`, commit `eabb1cd06`, valid from 2026-09-29T11:56:10
- **ranges in this module** (layer order):
  - `L2 batch_detection` · `webbing_agent.py:330-352` — _next_batch: the eligibility query, linked and chat-sourced and not yet webbed, oldest first over the WHOLE graph rather than a set served by sophia
  - `L2 batch_detection` · `webbing_agent.py:131-150` — _is_underdeveloped: the pure predicate, scoring the concept OWN description against the concept-name cache and counting its non-housekeeping edges; no function in webbing_agent.py calls it now, because _next_batch, _pending_count and _verify_and_mark_webbed ask the same predicate in Cypher on the stored score
  - `L2 batch_detection` · `webbing_agent.py:389-405` — _pending_count: the EXACT pending count, the same predicate _next_batch selects on asked as one Cypher count over the score D2 stores on each concept at write time, so the count and the selection cannot disagree; the dry run and the empty-batch return both report it
  - `L3 goal_service` · `webbing_agent.py:154-241` — _format_rels, SOMA_RESULT_ACTIONS and _build_batch_goal: the served list, each concept with its own description and current relationships, and the eight steps, the seventh the no-system-type law, the eighth SOMA_RESULT_ACTIONS, how to read an add_concept result: line 1 what was written, the middle information (DEATH, the SOMA line, numbered MEREO, FILL and SOUP lines, D2, CB, CRITICAL, the help line), a MEREO or SOUP grade meaning the concept is not validly the type it claims, its execution failed, and CartON keeps the write so it can be seen, the DO lines last naming their lines by token; every fill DO line opens this is important to fill next, but only if it is inside the meaning you meant, which for the webber is the served prose, never expanded past because SOMA names a part (Isaac 2026-09-29); DO MEREO define Y fills Y with its four lists when the prose means Y or drops the claim, one level, a REFUSED fill leaving Y; declare Y drops the claim; DO SOUP add_concept X with properties supplies each param from the prose or drops the claim; every other DO line is left; REFUSED or REJECTED leaves that concept; no DO line goes on
  - `L3 goal_service` · `webbing_agent.py:244-280` — WEBBER_SYSTEM_PROMPT: the identity, the FOUR hard laws (never touch a served description, never delete, always tag source webbing_agent, never write onto a declared system type nor put System_Type in an is_a list, the fourth enforced by webbing_write_guard) and then SOMA_RESULT_ACTIONS, the same constant the goal carries, so the prompt and the goal cannot drift
  - `L3 goal_service` · `webbing_agent.py:408-421` — _fetch_relationships: the served concepts current outgoing edges, so the agent is not guessing what is already there
  - `L3 goal_service` · `webbing_agent.py:283-286` — WEBBER_AGENT_PROMPT: the prompt the webbing agent is built with, WEBBER_SYSTEM_PROMPT behind the absolute persona line naming webbing_agent, so heaven renders only this prompt instead of the ambient devdir context and skills list (issue 688)
  - `L4 agent_run` · `webbing_agent.py:289-326` — _get_mcp, _webber_run_config and call_webber_with_this_prompt: ONE SDNAC run per batch built by the pure _webber_run_config: max_turns 3 heaven iterations of up to 200 tool calls each (Isaac 2026-09-28: 3 200 is probably fine thats probably a whole window), max_tool_calls riding HeavenAgentArgs to the agent constructor (extra_agent_kwargs drops it, leaving heaven default 10), compaction on, history_id None so nothing carries between runs; the prompt and goal ask for the fenced GOAL ACCOMPLISHED, the only text heaven ends agent mode on
  - `L5 verify_and_mark` · `webbing_agent.py:469-495` — call_webber: detect, serve, run, verify, write the state file
  - `L5 verify_and_mark` · `webbing_agent.py:498-529` — loop: ratchet batch by batch with the no-progress spin guard
  - `L5 verify_and_mark` · `webbing_agent.py:424-451` — _verify_and_mark_webbed: CODE re-checks which served concepts actually gained structure and sets webbed true on those only; this is where the effect leaves, and where ONE PASS ENDS with no loop back to closure  ⟵ RELEASE
- **also passes through:** `webbing_agent_worker.py`, `base/sdna/sdna/config.py`, `base/sdna/sdna/heaven_runner.py`, `add_concept_tool.py`, `webbing_write_guard.py`, `test_webbing_write_guard.py`, `test_webbing_agent.py`, `base/sdna/tests/test_heaven_runner_max_tool_calls.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
