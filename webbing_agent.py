#!/usr/bin/env python3
"""
webbing_agent — carton's standing CONCEPT-ATOMIZATION daemon.

CLONED FROM THE ALREADY-PROVEN SOPHIA ARCHITECTURE (Isaac, verbatim, this session: "we just made the
sophia coherer agents that work just fine. why not use that pattern? doesnt that have a daemon?"). This
module is NOT a new design — it is Sophia's exact shape (CODE-detects-window / SDNAC-agent-does-the-
judgment-call / CODE-verifies) retargeted from Sophia's unit (a `Doc_Mirror_Journal_Entry`) to a
different unit (any concept the carton daemon just linked).

THE DESIGN THIS BUILDS (already decided, in CartON — read these yourself via get_concept before
changing this file's behavior; this docstring restates them, it is NOT the source of truth):
  - `Daemon_Webbing_Agent_Design` — a worker that atomizes a newly-queued concept into a proper
    multi-node graph (real is_a/part_of/instantiates/produces + child concepts) instead of leaving it
    as unstructured prose. `triggers_after Autolinker_Processing_Step`, `part_of
    Carton_Add_Concept_Pipeline`, `fixes Sophia`, `fixes D2_Description_Rollup_Gap`.
  - `Provenance_Tracking_Main_Vs_Daemon_Origin` — queue entries tagged Main_System_Originated vs
    Daemon_Self_Generated; only Main_System_Originated is eligible_for_atomization; a daemon-self-
    generated concept is terminal_unless Reentered_Through_Main_Agent_Context. Isaac verbatim:
    "concepts the daemon-agent creates while atomizing are NOT re-sent for atomization again unless
    they become involved in the main agent's context and re-enter through the queue."
  - `Carton_Schema_Always_List_Requirement` — every relationship is a list by default; recursion depth
    is NOT an engineering problem to solve with a stopping rule — it terminates the same way all
    bounded agent work terminates, on finite context/turns.

THE ONE REAL DESIGN TRANSLATION (Sophia's journal-annotation shape -> concept-atomization shape):
Sophia's unit = a `Doc_Mirror_Journal_Entry`; her "already annotated" check = a SIBLING node
(`{journal}_Momentum`) existing. This agent's unit = ANY concept the daemon just linked; its "already
atomized" check = a SCRATCH-LANE PROPERTY (`webbed=true`), NOT a sibling node — atomization ADDS
structure to the SAME concept (is_a/part_of/instantiates/produces children + relationships ON it), it
does not create a side-car observation the way Sophia's momentum node does.

THE RECURSION GUARD (the one safety property Isaac was explicit about): every add_concept call this
agent's SDNAC makes — for its OWN new concepts AND when amending a served concept — carries
`source='webbing_agent'`. `'webbing_agent'` lives in `SYSTEM_SOURCES` (observation_worker_daemon.py),
NEVER in `CHAT_SOURCES` — and `_next_batch` below only ever queries `c.source IN CHAT_SOURCES`. So a
webbing-agent-authored concept is STRUCTURALLY excluded from ever being re-served to this agent; no
extra bookkeeping is needed. If a real agent later works with that concept and it gets re-queued with
`source='agent'`, it becomes eligible again automatically — this falls out of the eligibility query
being source-based, per Isaac's design, with nothing extra built for the re-entry case.

THE THREE HARD LAWS this agent's SDNAC obeys (see `WEBBER_SYSTEM_PROMPT`): (1) NEVER touch a served
concept's existing `n.d` — verified mechanism: an add_concept call that OMITS the `concept` (description)
argument normalizes to an empty string (add_concept_tool_func), and the daemon's write-CASE
`n.d CONTAINS c.description` branch leaves an existing non-empty `n.d` COMPLETELY UNCHANGED when the
incoming description is empty (`n.d CONTAINS ''` is always true in Cypher) — see
`observation_worker_daemon.batch_create_concepts_neo4j`'s UNWIND CASE. (2) NEVER delete anything —
additive only. (3) ALWAYS pass `source='webbing_agent'` on every add_concept call this run.

THE TWO FUNCTIONS (mirrors Sophia's "call_sophia() and call_sophia_with_this_prompt() — that is it"):
  - call_webber_with_this_prompt(prompt, model) -> run ONE webbing-agent SDNAC on an arbitrary goal
    (the primitive).
  - call_webber(model, dry_run)                -> detect next batch, serve it, run the agent, verify.

STATUS (state-what-is-vs-vision discipline): the eligibility THRESHOLDS below
(`DEFAULT_SCORE_THRESHOLD`, `DEFAULT_MIN_REL_COUNT`) are JUDGMENT CALLS Isaac may want to tune — they
are NOT derived from any spec, they are this build's own choice, env-overridable. Flag them, do not
bury them.

Usage:
  webbing_agent.py --loop  [--limit N] [--model M] [--cap C]   ratchet batch-by-batch until caught up
       (or N batches). THE normal entry — mirrors docmirror-cohere's --loop.
  webbing_agent.py --once  [--model M] [--cap C]               process exactly ONE batch, then exit.
  webbing_agent.py --dry-run                                   report the next batch; run no agent.
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "MiniMax-M2.7-highspeed"   # per the minimax-model rule: ALL Heaven agents use this,
                                            # never M2.5, never claude-sonnet/opus.
BATCH_CAP = int(os.environ.get("WEBBING_AGENT_BATCH_CAP", "15"))
# How large a candidate pool to FETCH before Python-side filtering (the description-score signal below
# cannot be pushed into Cypher — it needs the full concept_cache — so we over-fetch, filter in Python,
# then truncate to BATCH_CAP). Bounded, not unlimited — per Carton_Schema_Always_List_Requirement,
# recursion/scan depth terminates on a finite bound, not an engineered "find exactly the right N" rule.
FETCH_MULTIPLIER = int(os.environ.get("WEBBING_AGENT_FETCH_MULTIPLIER", "6"))

# JUDGMENT CALLS (Isaac may want to tune these — flagged explicitly, not silently buried):
# a concept is "under-structured" (eligible for atomization) when EITHER of these signals fires.
DEFAULT_SCORE_THRESHOLD = int(os.environ.get("WEBBING_AGENT_SCORE_THRESHOLD", "50"))   # compute_description_score() < this
DEFAULT_MIN_REL_COUNT = int(os.environ.get("WEBBING_AGENT_MIN_REL_COUNT", "2"))          # other_rel_count < this

# Relationship types that do NOT count toward "real structure" for the min-rel-count signal — the
# housekeeping/administrative edges every concept gets regardless of how well-graphed its content is.
# NOTE: IS_A/PART_OF are excluded here (a concept needs MORE than just those to be well-structured);
# INSTANTIATES/PRODUCES and any custom relationship DO count (they are the real content structure).
BASE_RELS_EXCLUDED = frozenset({
    "IS_A", "PART_OF", "CREATED_DURING", "HAS_TAG", "TIMELINE_LINKED", "ODYSSEY_LINKED",
})

HD = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"))
WEBBING_DIR = HD / "webbing_agent"
WEBBING_STATE = WEBBING_DIR / "webbing_state.json"   # {last_batch_names, processed_in_batch, heartbeat}


def _carton():
    from carton_mcp.carton_utils import CartOnUtils
    return CartOnUtils()


def _q(carton, cypher, **params):
    res = carton.query_wiki_graph(cypher, params or None)
    return (res.get("data") or []) if isinstance(res, dict) and res.get("success") else []


def _write_wstate(**kw):
    try:
        WEBBING_DIR.mkdir(parents=True, exist_ok=True)
        st = {}
        try:
            st = json.loads(WEBBING_STATE.read_text())
        except Exception:
            pass
        st.update(kw)
        st["heartbeat"] = datetime.now().isoformat(timespec="seconds")
        WEBBING_STATE.write_text(json.dumps(st, indent=2))
    except Exception:
        pass


# ── PURE eligibility predicate (onion-arch inner layer — no I/O, unit-tested standalone) ───────────
def _is_underdeveloped(description: str, concept_cache: list, other_rel_count: int,
                       score_threshold: int = DEFAULT_SCORE_THRESHOLD,
                       min_rel_count: int = DEFAULT_MIN_REL_COUNT) -> bool:
    """Return True iff a concept genuinely looks under-structured (needs atomization).

    PURE — no neo4j, no MCP, no I/O. Fires when EITHER signal says the concept is under-structured:
      - `compute_description_score(description, concept_cache) < score_threshold` — the prose is not
        yet reflected as real graph structure (few of its meaningful words resolve to existing
        concepts), OR
      - `other_rel_count < min_rel_count` — fewer than `min_rel_count` outgoing relationships beyond
        the housekeeping set (`BASE_RELS_EXCLUDED`) — i.e. no real instantiates/produces/has_part/
        custom structure, just a placeholder is_a/part_of/created_during.

    `compute_description_score` is imported lazily (matches this codebase's established lazy-import
    convention — see observation_worker_daemon.py / soma_fillers.py) so this module stays import-light.
    """
    from carton_mcp.observation_worker_daemon import compute_description_score
    score = compute_description_score(description or "", concept_cache or [])
    return score < score_threshold or other_rel_count < min_rel_count


# ── PURE goal-text builder (onion-arch inner layer — no I/O, unit-tested standalone) ───────────────
def _format_rels(rels: dict) -> str:
    if not rels:
        return "(none besides housekeeping — is_a/part_of/created_during only, or empty)"
    return "; ".join(
        f"{rel_type}: [{', '.join(targets)}]" for rel_type, targets in sorted(rels.items())
    )


def _build_batch_goal(batch: list, rels_by_concept: dict) -> str:
    """SERVE the batch's concept LIST (names + current description + current relationships) in the
    goal, exactly like Sophia's `_build_convo_goal` serves a journal list — the agent does NOT hunt for
    what to atomize, the list is given complete (no separate query_wiki_graph re-fetch is needed for
    the base facts, though the agent may still look things up for context)."""
    listing = "\n\n".join(
        f"  {i + 1}. {r['n']}\n"
        f"     Current description: {r.get('d') or '(empty)'}\n"
        f"     Current relationships: {_format_rels(rels_by_concept.get(r['n'], {}))}"
        for i, r in enumerate(batch)
    )
    names = ", ".join(r["n"] for r in batch)
    return (
        f"ATOMIZE this batch of {len(batch)} under-structured concepts into a proper multi-node graph. "
        f"This run covers EXACTLY this list — do not hunt for other work, do not query for more concepts "
        f"to process:\n\n{listing}\n\n"
        f"For EACH concept above, IN ORDER:\n"
        f"  1. Read its current description + existing relationships (served above).\n"
        f"  2. Identify the real is_a / part_of / instantiates / produces structure the prose IMPLIES, "
        f"and any CHILD concepts the prose describes that do not yet exist as their own concepts.\n"
        f"  3. Call add_concept to ADD the missing structure. ALWAYS supply is_a/part_of/instantiates/"
        f"produces as LISTS (never a single bare value — every relationship is a list by default, per "
        f"Carton_Schema_Always_List_Requirement).\n"
        f"  4. NEVER touch the served concept's existing description: when amending one of the "
        f"{len(batch)} concepts above (it already exists and already has a description), OMIT the "
        f"`concept` (description) argument entirely — leave it unset. This is verified safe: an omitted "
        f"description normalizes to an empty string, and carton's write path leaves an existing "
        f"description COMPLETELY UNCHANGED whenever the incoming description is empty. Only supply a "
        f"real `concept` (description) argument when creating a genuinely NEW child concept that does "
        f"not exist yet.\n"
        f"  5. NEVER delete anything. Additive only.\n"
        f"  6. ALWAYS pass source='webbing_agent' on EVERY add_concept call you make this run (both "
        f"amending the served concepts above and creating new children). This is the recursion-guard: "
        f"it is a harmless no-op on an already-sourced existing concept (source is set once at creation "
        f"and never overwritten) and it is the load-bearing tag on any brand-new concept you create, so "
        f"it is never re-served to you or any future webbing-agent run.\n\n"
        f"Process ALL {len(batch)} concepts above ({names}). Say GOAL ACCOMPLISHED once every one has "
        f"been given real structure."
    )


# ── the webbing agent's identity + laws (the losslessness/recursion-guard rules live HERE) ─────────
WEBBER_SYSTEM_PROMPT = (
    "You are the WEBBING AGENT, carton's standing CONCEPT-ATOMIZATION daemon. Your WHOLE JOB: take a "
    "concept that a real conversation just wrote as unstructured prose (it already has a real is_a/"
    "part_of, but little else) and ADD the proper multi-node graph structure its prose implies — the "
    "graphification a human agent should have done when it first wrote the concept, per "
    "Daemon_Webbing_Agent_Design.\n\n"
    "YOU ARE GIVEN AN EXACT LIST of concepts to atomize this run (in your goal) — do NOT hunt for other "
    "work, do NOT query for more concepts to process. Process exactly the served list, in order.\n\n"
    "For each served concept: read its description + existing relationships (already given to you), "
    "identify the real is_a/part_of/instantiates/produces structure and any child concepts the prose "
    "implies, and call add_concept to ADD that structure. ALWAYS pass every relationship as a LIST "
    "(Carton_Schema_Always_List_Requirement — real entities generically have more than one part; never "
    "a bare single value).\n\n"
    "THE THREE HARD LAWS (never violate any of these):\n"
    "  1. NEVER touch a served concept's existing description (n.d). When calling add_concept on one of "
    "the concepts you were SERVED, OMIT the `concept` argument (description) entirely — leave it unset. "
    "This is verified safe: an omitted/absent description normalizes to an empty string, and carton's "
    "write path leaves an existing description completely untouched when the incoming description is "
    "empty. Only give a `concept` (description) argument when creating a genuinely NEW child concept "
    "that does not exist yet.\n"
    "  2. NEVER delete anything. You are purely ADDITIVE — you only ADD relationships and new concepts, "
    "never remove or rewrite.\n"
    "  3. ALWAYS pass source='webbing_agent' on every single add_concept call you make this run — both "
    "when amending a served concept and when creating a brand-new child concept. This is the "
    "recursion-guard that keeps your own output from being re-served back to you: any concept you "
    "create with this tag is excluded from a future webbing-agent run unless a real agent later "
    "re-engages it through the main queue.\n\n"
    "Recursion/depth is bounded naturally by your own finite turns this run — atomize what the served "
    "prose genuinely implies, do not chase structure indefinitely. Execute tool calls immediately; say "
    "GOAL ACCOMPLISHED once every served concept in your list has real structure."
)


def _get_mcp():
    """Same carton MCP server wiring Sophia uses (docmirror-cohere._get_mcp) — this agent needs the
    identical carton tool access (add_concept, query_wiki_graph) to do its job."""
    from sdna.defaults import _get_strata_carton_env
    env = _get_strata_carton_env()
    gv = lambda k, d="": env.get(k) or os.environ.get(k, d)
    return {"carton": {"command": "carton-mcp", "args": [], "env": {
        "GITHUB_PAT": gv("GITHUB_PAT"), "REPO_URL": gv("REPO_URL"),
        "HEAVEN_DATA_DIR": gv("HEAVEN_DATA_DIR", "/tmp/heaven_data"),
        "NEO4J_URI": gv("NEO4J_URI"), "NEO4J_USER": gv("NEO4J_USER"),
        "NEO4J_PASSWORD": gv("NEO4J_PASSWORD"), "OPENAI_API_KEY": gv("OPENAI_API_KEY"),
        "CHROMA_PERSIST_DIR": gv("CHROMA_PERSIST_DIR", "/tmp/carton_chroma_db"),
    }}}


# ── THE PRIMITIVE: run ONE webbing-agent SDNAC on an arbitrary goal ─────────────────────────────────
async def call_webber_with_this_prompt(prompt: str, model: str = DEFAULT_MODEL) -> dict:
    """Run ONE webbing-agent SDNAC to completion on `prompt` (the goal). Compaction ON, thousands of
    tool calls, history_id=None — unlike Sophia there is no cross-run momentum web to rehydrate from
    (each run is a fresh, self-contained, bounded batch), so a fresh history every run is correct, not
    a gap. Returns the flow result dict. Mirrors docmirror-cohere.call_sophia_with_this_prompt almost
    verbatim (same HeavenInputs shape, same MCP wiring, same model default)."""
    from sdna import sdna_flow, sdnac, ariadne
    from sdna.config import HermesConfig, HeavenInputs, HeavenAgentArgs, HeavenHermesArgs
    heaven_inputs = HeavenInputs(
        agent=HeavenAgentArgs(provider="ANTHROPIC", max_tokens=8000, enable_compaction=True,
                              extra_agent_kwargs={"max_tool_calls": 2000}),
        hermes=HeavenHermesArgs(history_id=None),
    )
    flow = sdna_flow('webbing_agent', sdnac('webbing_agent', ariadne('prep'),
        config=HermesConfig(
            name="webbing_agent", system_prompt=WEBBER_SYSTEM_PROMPT, goal=prompt,
            model=model, max_turns=200, permission_mode="bypassPermissions", backend="heaven",
            heaven_inputs=heaven_inputs, mcp_servers=_get_mcp())))
    result = await flow.execute()
    return {"status": str(getattr(result, "status", "?"))}


# ── CODE detection: the next batch of eligible concepts (NO LLM discovery) ─────────────────────────
def _next_batch(carton, cap: int = BATCH_CAP) -> list:
    """Pure-CODE eligibility query (mirrors Sophia's `_next_convo_window`): concepts where
    `linked=true` (autolinker has run) AND `source` is in the EXISTING `CHAT_SOURCES` set (imported,
    never redefined — see the module docstring's recursion-guard note) AND `webbed IS NULL` (not yet
    processed by this agent) AND the concept genuinely looks under-structured
    (`_is_underdeveloped`).

    The description-score signal cannot be pushed into Cypher (it needs the full concept_cache), so
    this over-fetches a candidate pool (`cap * FETCH_MULTIPLIER`, oldest-linked first), Python-filters
    via the pure predicate, then truncates to `cap`.
    """
    from carton_mcp.observation_worker_daemon import CHAT_SOURCES

    rows = _q(carton,
        "MATCH (c:Wiki) WHERE c.linked = true AND c.source IN $chat_sources AND c.webbed IS NULL "
        "WITH c, size([(c)-[r2]->() WHERE NOT type(r2) IN $base_rels | r2]) AS other_rel_count "
        "RETURN c.n AS n, c.d AS d, toString(c.t) AS t, other_rel_count "
        "ORDER BY c.t ASC LIMIT $fetch_cap",
        chat_sources=list(CHAT_SOURCES), base_rels=list(BASE_RELS_EXCLUDED),
        fetch_cap=cap * FETCH_MULTIPLIER)
    if not rows:
        return []

    concept_cache = carton.get_all_concept_names()
    eligible = [
        r for r in rows
        if _is_underdeveloped(r.get("d") or "", concept_cache, r.get("other_rel_count") or 0)
    ]
    selected = eligible[:cap]
    print(f"[WebbingAgent] _next_batch: {len(rows)} candidates fetched, "
          f"{len(eligible)} eligible, {len(selected)} selected (cap={cap})", file=sys.stderr)
    return selected


def _pending_count(carton) -> int:
    """Upper-bound pending count (dry-run/report only): concepts that PASS the coarse Cypher filter
    (linked/source/webbed). This does NOT apply the description-score signal (which needs the
    concept_cache computed in Python) — so it can over-report slightly versus what `_next_batch`
    actually selects. Honest bound, not a precise figure — state what this is, not more."""
    from carton_mcp.observation_worker_daemon import CHAT_SOURCES
    rows = _q(carton,
        "MATCH (c:Wiki) WHERE c.linked = true AND c.source IN $chat_sources AND c.webbed IS NULL "
        "RETURN count(c) AS c", chat_sources=list(CHAT_SOURCES))
    return rows[0]["c"] if rows else 0


def _fetch_relationships(carton, names: list) -> dict:
    """Fetch each served concept's CURRENT outgoing relationships (grouped by type), so the goal can
    serve them to the agent (item 2 of the design: "list the concept names + their current description
    + their current relationships so the agent isn't guessing what's already there")."""
    if not names:
        return {}
    rows = _q(carton,
        "MATCH (c:Wiki)-[r]->(t:Wiki) WHERE c.n IN $names "
        "RETURN c.n AS n, type(r) AS rel, collect(DISTINCT t.n) AS targets",
        names=names)
    out: dict = {}
    for r in rows:
        out.setdefault(r["n"], {})[r["rel"]] = r["targets"]
    return out


def _verify_and_mark_webbed(carton, batch: list) -> list:
    """CODE (not the agent) verifies which served concepts now have real structure — a plain Cypher
    re-check mirroring Sophia's call_sophia post-run verify block — and sets `webbed=true` via
    `set_concept_properties` on each ONE THAT IMPROVED. A concept the agent did not manage to improve
    stays un-webbed (eligible again on the next tick) — no silent partial credit, no false "done"."""
    from carton_mcp.carton_utils import set_concept_properties

    names = [r["n"] for r in batch]
    if not names:
        return []
    rows = _q(carton,
        "MATCH (c:Wiki) WHERE c.n IN $names "
        "WITH c, size([(c)-[r2]->() WHERE NOT type(r2) IN $base_rels | r2]) AS other_rel_count "
        "RETURN c.n AS n, c.d AS d, other_rel_count",
        names=names, base_rels=list(BASE_RELS_EXCLUDED))
    concept_cache = carton.get_all_concept_names()
    marked = []
    for r in rows:
        if _is_underdeveloped(r.get("d") or "", concept_cache, r.get("other_rel_count") or 0):
            continue  # still under-structured — leave un-webbed, eligible again next tick
        res = set_concept_properties(r["n"], {"webbed": True}, mode="merge")
        if res.get("success"):
            marked.append(r["n"])
    return marked


def _batch_for_names(carton, names: list) -> list:
    """Build an explicit batch from GIVEN concept names, bypassing `_next_batch`'s FIFO scan/
    eligibility filter entirely. TEST/DEBUG entrypoint ONLY (mirrors Sophia's `--prompt-file`/
    `--journal` direct-invocation escape hatches) — lets you atomize ONE specific concept without
    waiting for it to surface from a real, possibly enormous, oldest-first backlog. Never used by the
    normal `--loop`/`--once` production path."""
    if not names:
        return []
    rows = _q(carton,
        "MATCH (c:Wiki) WHERE c.n IN $names RETURN c.n AS n, c.d AS d, toString(c.t) AS t",
        names=names)
    return rows


# ── call_webber(): detect next batch, serve it, run the agent, verify ───────────────────────────────
def call_webber(model: str = DEFAULT_MODEL, dry_run: bool = False, cap: int = BATCH_CAP,
               concept_names: list = None) -> dict:
    carton = _carton()
    batch = _batch_for_names(carton, concept_names) if concept_names else _next_batch(carton, cap=cap)
    if not batch:
        return {"processed_batch": False, "pending": 0, "msg": "caught up"}
    if dry_run:
        return {"dry": True, "batch_size": len(batch), "names": [b["n"] for b in batch],
                "pending": _pending_count(carton)}
    rels_by_concept = _fetch_relationships(carton, [b["n"] for b in batch])
    goal = _build_batch_goal(batch, rels_by_concept)
    asyncio.run(call_webber_with_this_prompt(goal, model))
    webbed = _verify_and_mark_webbed(carton, batch)
    _write_wstate(last_batch_names=[b["n"] for b in batch], processed_in_batch=len(webbed))
    return {"processed_batch": True, "batch_size": len(batch), "webbed": len(webbed),
            "webbed_names": webbed, "pending": _pending_count(carton)}


def loop(model: str = DEFAULT_MODEL, limit: int = None, dry_run: bool = False,
        cap: int = BATCH_CAP) -> dict:
    """Ratchet batch-by-batch until caught up (or `limit` batches). After each batch, CODE runs the
    next-batch query and runs the agent again — exactly the summarizer/Sophia-worker drive loop,
    including the no-progress spin-guard (a real safety property, kept verbatim)."""
    carton = _carton()
    if dry_run:
        return call_webber(model, dry_run=True, cap=cap)
    batches = 0
    total_webbed = 0
    no_progress = 0
    while True:
        before = _pending_count(carton)
        if before == 0:
            break
        res = call_webber(model, cap=cap)
        if not res.get("processed_batch"):
            break
        batches += 1
        total_webbed += res.get("webbed", 0)
        after = res.get("pending", before)
        if after >= before:                      # this batch webbed nothing — guard against a spin
            no_progress += 1
            if no_progress >= 2:
                return {"batches": batches, "webbed": total_webbed, "pending": after,
                        "error": "two batches made no progress"}
        else:
            no_progress = 0
        if limit and batches >= limit:
            break
    return {"batches": batches, "webbed": total_webbed, "pending": _pending_count(carton),
            "msg": "caught up" if _pending_count(carton) == 0 else "stopped at limit"}


def main(argv):
    # ── stdout-contract guard (CRITICAL, copied verbatim from docmirror-cohere) ────────────────────
    # carton's query layer leaks an OS-level redirect of fd 1 (fd 1 -> stderr) after the first query.
    # Our caller (webbing_agent_worker.py) reads our STDOUT for the result JSON, so we SAVE the real
    # stdout fd BEFORE any carton work and emit the machine-readable result on THAT fd.
    _real_out = os.dup(1)

    def _emit(obj):
        os.write(_real_out, (json.dumps(obj, indent=2) + "\n").encode())

    p = argparse.ArgumentParser(prog="webbing_agent", description="carton concept-atomization daemon")
    p.add_argument("--loop", action="store_true", help="ratchet batch-by-batch until caught up")
    p.add_argument("--once", action="store_true", help="process exactly ONE batch")
    p.add_argument("--limit", type=int, help="max batches this --loop invocation")
    p.add_argument("--cap", type=int, default=BATCH_CAP, help="max concepts per batch")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--concept", action="append", metavar="NAME",
                    help="TEST/DEBUG ONLY: atomize this EXACT concept (repeatable), bypassing the "
                         "FIFO scan/eligibility filter entirely (mirrors Sophia's --prompt-file/"
                         "--journal direct-invocation escape hatch)")
    a = p.parse_args(argv[1:])

    if a.concept:
        _emit(call_webber(a.model, dry_run=a.dry_run, cap=a.cap, concept_names=a.concept)); return 0
    if a.once:
        _emit(call_webber(a.model, dry_run=a.dry_run, cap=a.cap)); return 0
    if a.loop:
        _emit(loop(a.model, a.limit, a.dry_run, cap=a.cap)); return 0
    p.print_help(); return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
