# Editing The Webbing Agent Uses The `edit-the-webbing-agent` Dev-Flow FIRST — repo-scoped

When you are about to edit `webbing_agent.py`, `webbing_agent_worker.py`, the eligibility predicate
(`_is_underdeveloped`), the batch-goal builder (`_build_batch_goal`), `WEBBER_SYSTEM_PROMPT`, the
`webbed`/`source` recursion-guard, or `CHAT_SOURCES`/`SYSTEM_SOURCES` in
`observation_worker_daemon.py` — you MUST FIRST use the `edit-the-webbing-agent` skill and do its
COMPLETE Part-2 coherence edit-set, then its Part-3 E2E gate. NEVER edit one place only.

→ Why it clones Sophia / the recursion guard / the PATH NOTE / the only-valid-test: read the `understand-carton-mcp-rules` skill.
