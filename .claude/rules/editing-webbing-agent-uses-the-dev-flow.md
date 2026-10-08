When you are about to edit `webbing_agent.py`, `webbing_agent_worker.py`, the eligibility predicate
(`_is_underdeveloped`), the batch-goal builder (`_build_batch_goal`), `WEBBER_SYSTEM_PROMPT`, `SOMA_RESULT_ACTIONS` (what the agent does with each SOMA
verdict its writes return), the
`webbed`/`source` recursion-guard, the write guard (`webbing_write_guard.py` and its one call in
`add_concept_tool_func`), or `CHAT_SOURCES`/`SYSTEM_SOURCES` in
`observation_worker_daemon.py` — you MUST FIRST use the `edit-the-webbing-agent` skill and do its
COMPLETE Part-2 coherence edit-set, then its Part-3 E2E gate. NEVER edit one place only.

Read the `understand-carton-mcp-rules` skill for why it clones Sophia, the recursion guard, the PATH
note, and the only valid test.
