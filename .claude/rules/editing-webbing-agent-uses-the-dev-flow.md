# Editing The Webbing Agent Uses The `edit-the-webbing-agent` Dev-Flow FIRST — repo-scoped, NON-NEGOTIABLE

When you are about to edit `webbing_agent.py`, `webbing_agent_worker.py`, the eligibility predicate
(`_is_underdeveloped`), the batch-goal builder (`_build_batch_goal`), `WEBBER_SYSTEM_PROMPT`, the
`webbed`/`source` recursion-guard, or `CHAT_SOURCES`/`SYSTEM_SOURCES` in
`observation_worker_daemon.py` — you MUST FIRST use the `edit-the-webbing-agent` skill and do its
COMPLETE Part-2 coherence edit-set, then its Part-3 E2E gate. NEVER edit one place only.

The webbing agent is a DIRECT CLONE of Sophia's proven architecture (`doc-mirror-system/sophia/
docmirror-cohere` + `sophia_worker.py`), retargeted to a different unit (any carton concept, "already
atomized" = the `webbed=true` scratch-lane property on the SAME node, not a sibling observation node
the way Sophia's momentum node is). Its two files couple TIGHTLY to the exact same recursion-guard +
never-touch-description mechanisms `dev-flow-split-content` already documents for this repo: `_next_batch`
queries ONLY `c.source IN CHAT_SOURCES` (imported from `observation_worker_daemon.py`, NEVER redefined
locally — a second copy will drift), `'webbing_agent'` lives in `SYSTEM_SOURCES` and NEVER in
`CHAT_SOURCES`, and every `add_concept` call the SDNAC agent makes carries `source='webbing_agent'` — this
is the WHOLE recursion guard, and it breaks silently (the agent starts re-processing its own output) if
`'webbing_agent'` ever ends up in `CHAT_SOURCES` by accident (e.g. a future merge of the two sets).
Amending an EXISTING served concept relies on the SAME empty-description-leaves-`n.d`-unchanged mechanism
`dev-flow-split-content` documents (an omitted `concept` description argument normalizes to `""`, and
`observation_worker_daemon.batch_create_concepts_neo4j`'s UNWIND CASE branch `n.d CONTAINS c.description`
leaves an existing non-empty `n.d` untouched) — if that CASE's branch order is ever refactored, this
capability's core guarantee silently breaks too.

> ⚠️ **PATH NOTE (2026-07-04):** the real source files are `knowledge/carton-mcp/webbing_agent.py` and
> `knowledge/carton-mcp/webbing_agent_worker.py` — REPO-ROOT siblings of `observation_worker_daemon.py`/
> `carton_utils.py` (this repo's `pyproject.toml` maps the `carton_mcp` package to the repo root itself,
> `package-dir = {"carton_mcp" = "."}`). A stray `carton_mcp/` subdirectory exists in this repo but holds
> no real source for this capability — do not be misled by it.

**Why:** this is the project-scoped enforcement required by the global law
`every-build-ends-in-a-development-flow-skill`. See `edit-the-webbing-agent` for the full edit-set and the
only valid test — the unit gate (`test_webbing_agent.py` green, 10 pure assertions on the eligibility
predicate and the goal builder) PLUS the E2E gate through the real live surface: `add_concept` a real
test concept → wait for the autolinker → atomize it via the `--concept NAME` direct-invocation escape
hatch (NOT `--loop`/`--once` against the real backlog, which is FIFO oldest-first and tens of thousands
deep) → `query_wiki_graph` byte-for-byte confirms real `instantiates`/`produces`/`has_part` structure
landed, `webbed=true` is set, the served concept's `n.d` sha256-matches its pre-run snapshot exactly, any
new child concept carries `source='webbing_agent'`, and a fresh `_next_batch()` call no longer surfaces
the now-webbed concept. "The unit tests passed" / "it imported" is NOT the gate — this exact E2E run was
performed live 2026-07-04 and is the standard every future change must re-clear.
