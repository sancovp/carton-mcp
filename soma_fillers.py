"""soma_fillers — carton's REAL fillers for SOMA's authorization-typed requests (the carton brain).

SOMA is the reasoner; it never DOES. When it reaches a gap it cannot fill from what it already
knows, it surfaces that gap TYPED BY WHO is authorized to fill it (the soma_sdk FillableRequest
hierarchy, derived from SOMA's authorized_source/3). This module is the carton-side OTHER half: the
REAL filler implementations the soma_sdk.resolve() dispatch loop routes each typed request to. It is
"the carton implementation of the SOMA SDK" — the brain that acts on SOMA's deductions.

The build order's step 2 — two real filling strategies:
  - HUMAN authorities (human_domain_expert / human_architect / human_end_user) -> filling-strategy 2
    (ask-human): durably PARK the request so a human can answer later, and return None (the gap stays
    pending this round). The human answering is a NEW SOMA event -> SOMA re-derives -> the parked
    chain advances. Re-derivation IS the resume; nothing here resumes a frozen Prolog stack.
  - llm_expert -> filling-strategy 3 (LLM dispatch of a universal): manufacture a FRESH LLM expert
    (NOT the calling LLM -- that is observing_agent, already handled by carton's caller-relay), give
    it the gap + context, and return its answer as the fill. (NOTE: SOMA's fixed authorized_source/3
    does not emit llm_expert today; that emission is build-order step 3 -- the dolce-driven strategy
    choice, universal->llm. This filler is the consumer it will dispatch to.)
  - system_deduction / authorized_agent -> return None (SOMA deduces it on the next re-derive / no
    auto-route exists yet).

DEPENDENCY INJECTION (so the loop is unit-testable offline AND the daemon can wire real behaviour):
`park` (how a human request is made durable) and `llm_call` (how an LLM expert is invoked) are
injectable. The default `park` writes a durable JSON record to a file queue under HEAVEN_DATA_DIR; a
later step swaps in a neo4j Soma_Request node (the cohered-note data model) without touching the loop.
With no `llm_call` wired, llm_expert ESCALATES to the human queue (the designed fallback, not silent —
it parks loudly), so nothing is ever dropped.

Returns a `default_fillers()` dict keyed by SOMA authorization for soma_sdk.resolve(). The already-
handled `observing_agent` has NO entry here -- the SDK never emits it (carton's caller-relay covers it).
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Callable, Dict, List, Optional

from soma_sdk import FillableRequest, build_fillable_request

logger = logging.getLogger(__name__)

# A filler matches soma_sdk's contract: callable(FillableRequest) -> (predicate, value[, type]) | None.
Filler = Callable[[FillableRequest], object]

# The SOMA authorizations that mean "a human must supply this" (filling-strategy 2 / ask-human).
HUMAN_AUTHORIZATIONS = ("human_domain_expert", "human_architect", "human_end_user")


# ---------------------------------------------------------------------------
# Filling-strategy 2 — the durable human-request queue (park, wait, re-derive)
# ---------------------------------------------------------------------------

def human_queue_dir() -> str:
    """The durable human-request queue directory (created if absent)."""
    base = os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")
    d = os.path.join(base, "soma_human_queue")
    os.makedirs(d, exist_ok=True)
    return d


def file_park(req: FillableRequest, *, queue_dir: Optional[str] = None) -> str:
    """Durably record a FillableRequest as a JSON file a human can answer later; return its request_id.

    The file IS the durable park: it survives restarts and waits (possibly hours) for a human. When the
    human answers -- a new add_concept supplying the gap -- SOMA re-derives over the now-bigger state and
    the parked chain advances. This file is the passive/pull side of the request/resume protocol.
    """
    qd = queue_dir or human_queue_dir()
    rid = req.request_id or f"{req.concept}.{req.gap}.{uuid.uuid4().hex[:8]}"
    record = {
        "request_id": rid,
        "authorization": req.authorization,
        "concept": req.concept,
        "gap": req.gap,
        "expected_type": req.expected_type,
        "reason": req.reason,
        "reply_contract": req.reply_contract,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    }
    with open(os.path.join(qd, f"{rid}.json"), "w") as f:
        json.dump(record, f, indent=2)
    logger.info("soma_fillers: parked %s request %s.%s -> %s",
                req.authorization, req.concept, req.gap, rid)
    return rid


def make_human_filler(park: Optional[Callable[[FillableRequest], object]] = None,
                      *, queue_dir: Optional[str] = None) -> Filler:
    """A filler for the HUMAN authorities: durably park the request, return None (stays pending).

    `park(req) -> request_id` makes the request durable (default = file_park). The filler ALWAYS returns
    None -- a human gap is never auto-filled in-loop; it parks and waits for the human's next event.
    """
    _park = park or (lambda r: file_park(r, queue_dir=queue_dir))

    def human_filler(req: FillableRequest):
        _park(req)
        return None   # pending — a human answers later as a new SOMA event (re-derivation is the resume)

    return human_filler


# ---------------------------------------------------------------------------
# Filling-strategy 3 — manufacture a fresh LLM expert for a universal slot
# ---------------------------------------------------------------------------

NEEDS_HUMAN = "NEEDS_HUMAN"   # the LLM expert's escape hatch -> escalate to the human queue


def make_llm_expert_filler(llm_call: Callable[[str], str]) -> Filler:
    """A filler for llm_expert: manufacture a fresh LLM expert, return its answer as the fill.

    `llm_call(prompt) -> answer_string` is the injected LLM invocation (a heaven agent in production; a
    deterministic stub offline). The expert is asked for the single value of the specific gap, given the
    concept + SOMA's reason + the expected fill shape. A blank answer or the literal NEEDS_HUMAN escalates
    (returns None -> the request stays pending for the human queue). Otherwise returns (gap, value, type)
    so resolve() merges triple(concept, gap, value) back into the full observation set and re-derives.
    """
    def llm_expert_filler(req: FillableRequest):
        prompt = (
            f"You are a fresh domain expert manufactured to fill ONE missing slot.\n"
            f"Concept: {req.concept}\n"
            f"Missing slot: {req.gap}\n"
            f"Why it is needed: {req.reason or '(none given)'}\n"
            f"Expected value type: {req.expected_type or 'a concept name'}\n\n"
            f"Reply with ONLY the value for '{req.gap}' (a single concept name / token), or the exact "
            f"word {NEEDS_HUMAN} if only a human (not an LLM) can supply it."
        )
        answer = (llm_call(prompt) or "").strip()
        if not answer or answer == NEEDS_HUMAN:
            return None   # escalate — stays pending for the human queue (designed fallback, loud)
        return (req.gap, answer, req.expected_type or "string_value")

    return llm_expert_filler


# ---------------------------------------------------------------------------
# The filler table + the daemon's durable-park library function
# ---------------------------------------------------------------------------

def default_fillers(*, llm_call: Optional[Callable[[str], str]] = None,
                    park: Optional[Callable[[FillableRequest], object]] = None,
                    queue_dir: Optional[str] = None) -> Dict[str, Filler]:
    """The carton brain's filler table keyed by SOMA authorization, for soma_sdk.resolve().

    HUMAN authorities -> park + pending (strat2). llm_expert -> manufacture an expert (strat3) when an
    `llm_call` is provided, else ESCALATE to the human queue (park). system_deduction -> pending (SOMA
    deduces on re-derive). authorized_agent -> park (no auto-route yet). observing_agent has NO entry --
    the SDK never emits it (carton's caller-relay already handles the calling LLM's own gaps).
    """
    human = make_human_filler(park, queue_dir=queue_dir)
    fillers: Dict[str, Filler] = {
        "human_domain_expert": human,
        "human_architect": human,
        "human_end_user": human,
        "system_deduction": lambda req: None,   # SOMA deduces it on the next re-derive
        "authorized_agent": human,              # no specific-agent route yet -> park for a human
    }
    fillers["llm_expert"] = make_llm_expert_filler(llm_call) if llm_call is not None else human
    return fillers


def park_fillable_requests(concepts: List[dict], *,
                           park: Optional[Callable[[FillableRequest], object]] = None,
                           queue_dir: Optional[str] = None) -> List[str]:
    """Durably park every authorization-typed fillable request carried on a list of concept dicts.

    This is the daemon's passive/pull leg (the durable suspension the request/resume protocol needs).
    Each concept dict (the daemon's all_concepts shape) may carry c["fillable_requests"] = the
    [{authorization, concept, gap, expected_type, reason, reply_contract, request_id}] dicts
    add_concept_tool parsed from SOMA's soma_requests= block. Each is rebuilt as its typed FillableRequest
    (build_fillable_request) and parked (default = file_park). An observing_agent / unknown authorization
    yields None from build_fillable_request and is skipped (already handled / nothing to park). Returns
    the list of parked request_ids. The ACTIVE llm-expert fill (manufacture + POST back + re-derive) runs
    via soma_sdk.resolve() when a reachable SOMA_URL + an llm_call are wired -- separate from this park.
    """
    _park = park or (lambda r: file_park(r, queue_dir=queue_dir))
    parked: List[str] = []
    for c in (concepts or []):
        for fr in (c.get("fillable_requests") or []):
            req = build_fillable_request(
                (fr.get("authorization") or "").strip(),
                fr.get("concept", ""),
                fr.get("gap", ""),
                fr.get("expected_type", ""),
                fr.get("reason", ""),
                fr.get("reply_contract", "awaiting"),
            )
            if req is None:
                continue   # observing_agent / unknown -> caller-relay handles it / nothing to park
            parked.append(_park(req))
    return parked


# ---------------------------------------------------------------------------
# CARTON-BUNDLE-BACK — realize SOMA's DEDUCED composed triples into the neo4j KG
# ---------------------------------------------------------------------------

def realize_composed_triples(concepts: List[dict], execute: Callable[[str, dict], object],
                             *, normalize: Optional[Callable[[str], str]] = None) -> List[tuple]:
    """Realize SOMA's DEDUCED composed triples into the neo4j KG (the daemon's bundle-back leg).

    SOMA's backward-chain compose (L3a) found matches in the STORE and surfaced
    composed_triple(concept, prop, value) for each -- graph additions SOMA DEDUCED that the user
    never stated (e.g. spaghetti has_cuisine italian, inferred from its ingredients). SOMA is the
    INNER reflection: it releases the deductions UP and never touches carton's KG. add_concept_tool
    parsed them into c["composed_triples"]; THIS is the realize leg the daemon dispatches: MERGE
    each as a directed :PROP edge so carton's KG learns what SOMA deduced -- without it carton stays
    dumb ("that's literally SOMA's job"). The MERGE mirrors batch_create_concepts_neo4j's rel_query:
    the source must already exist (SOMA only composes onto observed concepts); the target is MERGEd
    as an AUTO-CREATED stub if new. Idempotent (MERGE + de-dup).

    DEPENDENCY INJECTION (so it is unit-testable offline, like park_fillable_requests): `execute(
    query_str, params) -> any` is the neo4j execute_query callable (a recording fake in tests,
    shared_neo4j.execute_query live). `normalize` maps SOMA-normalized (lowercase_underscore) names
    to the Title_Case neo4j nodes (default = carton's normalize_concept_name, imported lazily so this
    module stays import-light). Returns the (src, rel, val) tuples actually realized.
    """
    if normalize is None:
        from carton_mcp.add_concept_tool import normalize_concept_name as normalize
    realized: List[tuple] = []
    seen = set()
    for c in (concepts or []):
        for tr in (c.get("composed_triples") or []):
            src = normalize(str(tr.get("concept", "")))
            val = normalize(str(tr.get("value", "")))
            rel = str(tr.get("prop", "")).strip().upper()
            if not src or not val or not rel:
                continue
            # rel must be a safe neo4j identifier (it is interpolated, not a parameter — Neo4j
            # cannot parameterize relationship types). Reject anything but alnum + underscore.
            if not rel.replace("_", "").isalnum():
                logger.warning("soma_fillers: skip composed triple with unsafe rel type %r", rel)
                continue
            key = (src, rel, val)
            if key in seen:
                continue
            seen.add(key)
            query = (
                "MATCH (s:Wiki {n: $src}) "
                "MERGE (t:Wiki {n: $val}) "
                f"ON CREATE SET t.d = 'AUTO CREATED: composed by SOMA as {rel} target of ' + $src + "
                "'. SOMA-deduced; not yet fully defined.', t.linked = false, t.t = datetime() "
                f"MERGE (s)-[rel:{rel}]->(t) "
                "SET rel.ts = datetime(), rel.soma_composed = true"
            )
            try:
                execute(query, {"src": src, "val": val})
                realized.append((src, rel, val))
                logger.info("soma_fillers: composed (SOMA-deduced) (%s)-[:%s]->(%s)", src, rel, val)
            except Exception as e:
                logger.warning("soma_fillers: composed realize failed (%s)-[:%s]->(%s): %s",
                               src, rel, val, e)
            else:
                # P1 provenance substrate: a SOMA-deduced compose is a fill from source 'soma'.
                record_fill_provenance(src, rel, "soma", "system_deduction", execute, normalize=normalize)
    return realized


# ---------------------------------------------------------------------------
# P1 — the FILL-PROVENANCE SUBSTRATE (Isaac 2026-06-28: "provenance substrate first")
# ---------------------------------------------------------------------------

def record_fill_provenance(concept: str, prop: str, source: str, source_type: str,
                           execute: Callable[[str, dict], object], *,
                           normalize: Optional[Callable[[str], str]] = None):
    """Stamp a persisted per-fill PROVENANCE: WHERE a concept's `prop` slot value came from.

    The SUBSTRATE (Isaac's ruling: build this FIRST) that BOTH gated items build on:
      - step-5 (authorization): Source is a NODE, so a graph can join Source-[:HAS_ROLE]->Role
        -[:AUTHORIZES]->prop to deduce who-may-fill (graph-wins, authorized_source/3 table fallback).
      - step-4 (strategy learning): prop + source_type are queryable edge props, so accumulation
        groups (prop, source_type) across events and, at a threshold, generalizes a filling_strategy/4.
    Persisted as (Concept)-[:FILLED_FROM {prop, source_type, ts}]->(Source). It survives the ephemeral
    tc_* problem (a persisted edge, not tc_*). FILLED_FROM is a CONSTANT rel type (never interpolated ->
    injection-safe; only `prop`/`source_type`/names cross as parameters). Idempotent: MERGE keyed on
    (concept, source, prop); SET refreshes source_type + ts. DI `execute(query, params)`; `normalize`
    maps SOMA names to the Title_Case nodes (default carton's normalize_concept_name).
    Returns (concept, prop, source, source_type) on success, else None.
    """
    if normalize is None:
        from carton_mcp.add_concept_tool import normalize_concept_name as normalize
    c = normalize(str(concept or ""))
    s = normalize(str(source or ""))
    p = str(prop or "").strip()
    st = str(source_type or "").strip()
    if not c or not s or not p:
        return None
    query = (
        "MATCH (concept:Wiki {n: $c}) "
        "MERGE (src:Wiki {n: $s}) "
        "ON CREATE SET src.d = 'AUTO CREATED: fill-provenance source', src.linked = false, src.t = datetime() "
        "MERGE (concept)-[fp:FILLED_FROM {prop: $p}]->(src) "
        "SET fp.source_type = $st, fp.ts = datetime()"
    )
    try:
        execute(query, {"c": c, "s": s, "p": p, "st": st})
        logger.info("soma_fillers: fill-provenance (%s)-[:FILLED_FROM {prop:%s, source_type:%s}]->(%s)", c, p, st, s)
        return (c, p, s, st)
    except Exception as e:
        logger.warning("soma_fillers: fill-provenance failed (%s).%s <- %s: %s", c, p, s, e)
        return None


# ---------------------------------------------------------------------------
# P3 — step-4 STRATEGY LEARNING: accumulate fill-provenance -> generalize a filling_strategy
# ---------------------------------------------------------------------------

# How a recorded fill SOURCE_TYPE (P1's FILLED_FROM.source_type) maps to a SOMA filling-strategy type
# (the strategy_role/2 domain in soma_partials.pl). The generalized strategy is what the NEXT instance
# of that (type, prop) auto-uses, so it should reflect HOW the slot actually got filled.
_SOURCE_TYPE_TO_STRATEGY = {
    "system_deduction": "partial_accumulation",  # SOMA composed it from accumulated partials
    "agent_review": "ask_human",                 # an agent reviewed/answered a suggestion
    "human": "reality_observation",
    "human_domain_expert": "reality_observation",
    "llm_expert": "llm_dispatch",
    "tool": "tool_call",
    "tool_call": "tool_call",
}


def generalize_filling_strategies(execute: Callable[[str, dict], object], *, threshold: int = 3):
    """step-4 LEARNING: accumulate the P1 FILLED_FROM provenance and GENERALIZE a filling_strategy when a
    (concept-type, prop, source_type) has been observed >= `threshold` times across distinct concepts.

    Returns the list of learned strategy SPECS {for_type, for_prop, strategy_type, source_type, count} —
    the caller posts each as a SOMA `filling_strategy_decl` event (has_for_type / has_for_prop /
    has_strategy_type), which P3a's convention asserts into filling_strategy/4. strategy_for/5 looks that
    up FIRST (the override), so the NEXT instance of that (type, prop) auto-knows how to fill the slot =
    "the how-to-fill knowledge grows in the graph by watching how slots actually got filled" (Isaac).

    DI `execute(query, params) -> rows` (recording fake in tests; live neo4j execute_query otherwise).
    `threshold` is the MARKED TUNABLE (default 3; Isaac's redundancy bar governs it — arbitrary/human
    fields generalize first). Read-only query (it EMITS nothing itself — the caller posts the decls).
    """
    query = (
        "MATCH (c:Wiki)-[fp:FILLED_FROM]->(:Wiki) "
        "MATCH (c)-[:IS_A]->(ty:Wiki) "
        "WITH ty.n AS for_type, fp.prop AS for_prop, fp.source_type AS source_type, count(DISTINCT c) AS n "
        "WHERE n >= $threshold AND for_type IS NOT NULL AND for_prop IS NOT NULL "
        "RETURN for_type, for_prop, source_type, n"
    )
    try:
        rows = execute(query, {"threshold": threshold}) or []
    except Exception as e:
        logger.warning("soma_fillers: generalize_filling_strategies query failed: %s", e)
        return []
    specs = []
    for r in rows:
        d = r if isinstance(r, dict) else dict(r)
        strat = _SOURCE_TYPE_TO_STRATEGY.get(d.get("source_type"))
        if not strat or not d.get("for_type") or not d.get("for_prop"):
            continue
        specs.append({"for_type": d.get("for_type"), "for_prop": d.get("for_prop"),
                      "strategy_type": strat, "source_type": d.get("source_type"), "count": d.get("n")})
    if specs:
        logger.info("soma_fillers: step-4 generalized %d filling strategies (threshold=%d)", len(specs), threshold)
    return specs


# ---------------------------------------------------------------------------
# L3b — the pure-mereo compose-suggestion REVIEW QUEUE (park, await a reviewer)
# ---------------------------------------------------------------------------

def compose_suggestion_queue_dir() -> str:
    """The durable compose-suggestion review-queue directory (created if absent)."""
    base = os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")
    d = os.path.join(base, "soma_compose_suggestions")
    os.makedirs(d, exist_ok=True)
    return d


def _suggestion_run_id(concept: str, prop: str, candidate: str) -> str:
    """STABLE run-id for a suggestion: concept.prop.candidate, filesystem-safe. Deterministic so
    re-derivations are idempotent (same file) and the L3c reviewer event keys its accept/reject to it."""
    raw = f"{concept}.{prop}.{candidate}"
    return "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in raw)


def park_compose_suggestions(concepts: List[dict], *,
                             park: Optional[Callable[[dict], object]] = None,
                             queue_dir: Optional[str] = None) -> List[str]:
    """Durably park every pure-mereo compose SUGGESTION for review (the L3b review queue, passive leg).

    L3b: SOMA found a UNIQUE ADMISSIBLE candidate for a still-empty required slot with NO authorizing
    d-chain, so it SUGGESTS the candidate (it did NOT auto-compose — that is L3a). add_concept_tool parsed
    SOMA's compose_suggestions= block into c["compose_suggestions"] = [{concept, prop, expected_type,
    candidate, reviewer_role}]. This records each as a JSON review item with a STABLE run-id
    (concept.prop.candidate) under HEAVEN_DATA_DIR/soma_compose_suggestions. INERT — parking only; the
    candidate is NEVER composed here. A reviewer (L3c) answers a keyed event → that composes (accept) or
    drops (reject) and re-derivation resumes. reviewer_role routes WHO may review (the authed role, or
    observing_agent = agent-reviewable). Mirrors park_fillable_requests. Returns the parked run-ids.
    DI: `park(record) -> run_id` is overridable so the loop is unit-testable offline.
    """
    qd = queue_dir or compose_suggestion_queue_dir()
    os.makedirs(qd, exist_ok=True)   # ensure the dir exists even when queue_dir is passed explicitly

    def _default_park(rec: dict) -> str:
        rid = rec["run_id"]
        with open(os.path.join(qd, f"{rid}.json"), "w") as f:
            json.dump(rec, f, indent=2)
        logger.info("soma_fillers: parked compose-suggestion %s (review by %s)",
                    rid, rec.get("reviewer_role"))
        return rid

    _park = park or _default_park
    parked: List[str] = []
    for c in (concepts or []):
        for sg in (c.get("compose_suggestions") or []):
            concept = str(sg.get("concept", "")).strip()
            prop = str(sg.get("prop", "")).strip()
            candidate = str(sg.get("candidate", "")).strip()
            if not concept or not prop or not candidate:
                continue
            rid = _suggestion_run_id(concept, prop, candidate)
            rec = {
                "run_id": rid,
                "concept": concept,
                "prop": prop,
                "expected_type": str(sg.get("expected_type", "")),
                "candidate": candidate,
                "reviewer_role": str(sg.get("reviewer_role", "observing_agent")),
                "status": "pending_review",
                "created_at": datetime.now().isoformat(),
            }
            parked.append(_park(rec))
    return parked


def _load_suggestion(run_id: str, queue_dir: Optional[str] = None):
    """Load a parked compose-suggestion record by run-id. Returns (path, rec) or None if absent.
    The shared read used by both resolve_compose_suggestion (compose+mark) and mark_compose_suggestion."""
    qd = queue_dir or compose_suggestion_queue_dir()
    path = os.path.join(qd, f"{run_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return path, json.load(f)


def resolve_compose_suggestion(run_id: str, decision: str, execute: Callable[[str, dict], object],
                               *, queue_dir: Optional[str] = None,
                               normalize: Optional[Callable[[str], str]] = None) -> dict:
    """L3c — the AUTHED REVIEW-RESUME: a reviewer answers a parked compose-suggestion BY ITS RUN-ID.

    L3b parked a pending review item (run_id = concept.prop.candidate). A reviewer (an agent with the
    item's reviewer_role) answers `accept` or `reject`, keyed to the run_id:
      - ACCEPT -> COMPOSE the edge (concept)-[:PROP]->(candidate) into the KG (reusing
        realize_composed_triples' MERGE), then mark the item accepted. Re-derivation IS the resume:
        the slot is now filled, so the next event mentioning the concept re-grades it past that gap
        (and, once a reachable SOMA is wired, the accept can be POSTed for an active re-derive).
      - REJECT -> mark the item rejected (the candidate was not the right fill). NOTE: SOMA will
        re-suggest the same unique candidate on the next re-derivation unless a rejection-exclusion is
        fed back to compute_compose_suggestions — that SOMA-side suppression is a tracked follow-on
        (the EWS-strata bound, L3b/E2, also scopes this away). For now the carton review record is the
        durable rejection.
    DI: `execute(query, params)` is the neo4j execute_query (a recording fake in tests); `normalize`
    defaults to carton's normalize_concept_name. Returns the updated review record (status set).
    """
    loaded = _load_suggestion(run_id, queue_dir)
    if loaded is None:
        return {"run_id": run_id, "status": "not_found"}
    _path, rec = loaded
    decision = (decision or "").strip().lower()
    if decision == "accept":
        realize_composed_triples(
            [{"composed_triples": [{"concept": rec["concept"], "prop": rec["prop"],
                                    "value": rec["candidate"]}]}],
            execute, normalize=normalize)
        status = "accepted"
    elif decision == "reject":
        status = "rejected"
    else:
        status = "invalid_decision"
    # delegate the status-write to mark_compose_suggestion (the shared file read/set/write),
    # so resolve (compose+mark) and the add_concept-driven mark-only path stay one implementation.
    return mark_compose_suggestion(run_id, status, queue_dir=queue_dir)


def mark_compose_suggestion(run_id: str, status: str = "accepted", *,
                            queue_dir: Optional[str] = None) -> dict:
    """Mark a parked compose-suggestion resolved BY ITS RUN-ID — the add_concept-driven accept path.

    Accepting a pure-mereo suggestion is NOT a special compose RPC: it is just SAYING the fill via
    `add_concept` (the normal observation path already writes the (concept)-[:PROP]->(candidate) edge —
    observation is the only operation). So `add_concept(..., soma_run_id=<run_id>)` calls THIS to mark
    the parked review item resolved — NO re-compose (the add already did it), NO neo4j execute needed.
    (`resolve_compose_suggestion` remains the programmatic compose+mark path; this is the mark-only one.)
    Returns the updated review record, or not_found if the run-id has no parked item.
    """
    loaded = _load_suggestion(run_id, queue_dir)
    if loaded is None:
        return {"run_id": run_id, "status": "not_found"}
    path, rec = loaded
    rec["status"] = status
    rec["resolved_at"] = datetime.now().isoformat()
    with open(path, "w") as f:
        json.dump(rec, f, indent=2)
    logger.info("soma_fillers: compose-suggestion %s marked %s (via add_concept soma_run_id)", run_id, status)
    return rec
