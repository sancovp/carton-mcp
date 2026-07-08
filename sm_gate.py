"""
sm_gate.py — the carton-native State-Machine GATE.

A SCIENTIFICALLY-EXACT port of CyberneticiRcus's gated state machine
(`cyberneticircus/lib/gates.py` + `lib/state_machines.py` + `neo4j_cypher_mcp/server.py`)
onto carton's own :Wiki graph. Isaac 2026-06-20: "IT IS A STATE MACHINE YOU CAN PROGRAM
IN CARTON THROUGH ADD CONCEPT AND SET PROPERTIES ... get_concept, EVERY SINGLE OTHER
APPLICABLE THING THAT CALLS CYPHER OR RETRIEVES ANY INFORMATION FROM ANYWHERE ARE GATED
BY THE STATE MACHINE AND ACTIVATE/CHECK IF THEY ARE LEGAL."

WHAT IT IS (the mechanic, ported exactly):
- The SM is GRAPH DATA, programmed through carton's own surface (add_concept + set_properties):
    State_Machine  -[:HAS_STEP]->     Traversal_Step
    Traversal_Step -[:NEXT_STEP{w}]-> Traversal_Step      (weighted transitions)
    Traversal_Step -[:CALLS_SM]->     State_Machine        (sub-SM calls)
  Each Traversal_Step carries  required_pattern  (a regex) + text (the instruction).
- A per-ACTOR cursor:  (actor)-[:HAS_LIFECYCLE]->(Execution_State{status})-[:CURRENT_STEP]->(Traversal_Step)
  The actor is whoever is acting (an agent/session name) — carton's analogue of CCC's Cybernet.
- THE GATE: while an actor is LOCKED at a step, every call (its canonical text) MUST match that
  step's required_pattern. A MATCH passes AND auto-advances the cursor to the highest-weight
  NEXT_STEP (or a CALLS_SM sub-machine, or — at a terminal step — UNLOCKS). A NON-MATCH is
  REFUSED with a PermissionError whose message carries the exact regex + instruction (the refusal
  IS the next-move instruction). UNLIKE CCC (reads ungated), carton gates BOTH reads and writes —
  every cypher/retrieval call is checked (Isaac's directive).
- ACTIVATION / TRIGGER: if a retrieval RESULT contains a node carrying a `trigger_traversal`
  property, the actor is LOCKED into that flow before continuing (CCC scan_and_trigger_traversal).

SAFETY (load-bearing — this gate wraps the live carton tools an agent uses on ITSELF):
- DEFAULT-UNGATED: `gate_call` returns ALLOW whenever the actor has no locked Execution_State.
  No SM is active until one is explicitly programmed + locked, so the gate is inert by default and
  cannot brick carton or the journal/doc-mirror tools.
- KILL SWITCH: if the file $CARTON_SM_GATE_DISABLED (default /tmp/heaven_data/carton_sm_gate_disabled)
  exists, the gate is globally OFF (returns ALLOW). The escape/abort hatch.
- Every gate path is wrapped so a gate fault FAILS OPEN (logs + ALLOW) — a buggy SM must never lock
  an agent out of carton. (The strictness is in the EXPLICIT refusal when a pattern genuinely fails.)

CARTON-NATIVE STORAGE: SM nodes are ordinary :Wiki concepts typed by an IS_A edge
(a Traversal_Step concept `IS_A Traversal_Step`), so they are journaled / RAG-able / property-
tracked like everything else. The cypher below matches on `(n:Wiki)-[:IS_A]->(:Wiki{n:'<Type>'})`
rather than a separate neo4j label — that is the only deviation from CCC, and it is required to
"marry into carton" (Isaac 2026-06-10).

This module is PURE w.r.t. the live MCP: it takes an injected `run` callable (query, params) -> rows
so it is unit-testable and never imports the server. Wiring it onto the live tool surface is a
separate, later step (so this increment cannot affect running carton).
"""
import json
import math
import os
import random
import re
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("carton_sm_gate")


# --- P0 EPISODE_LEDGER (Griess-Neural-Surrogate exhaust patch #2, 2026-07-06) --------------------
# CCC persisted every gate-traversal decision as `bandit_choices`; the carton port LOST that — every
# lock / branch-decision / advance / refusal / unlock existed only as a log line + return string and
# evaporated. This ledger is the trajectory exhaust the neural organs (Policy_Network_Sm_Selector /
# Chain_Prioritizer) train on: without it, every real traversal is dropped training data (the
# compounding-cost item). Append-only JSONL, one record per trajectory event, same park-file idiom
# as soma_fillers' human queue. BEST-EFFORT: a ledger fault is logged and swallowed — recording an
# episode must never affect the gate's behavior (the gate's own FAIL-OPEN discipline extends here).
def episode_ledger_path() -> str:
    """The SM-trajectory episode ledger file (dir created if absent)."""
    base = os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "sm_episodes.jsonl")


def _record_sm_episode(record: Dict[str, Any]) -> None:
    """Append one SM-trajectory event to the episode ledger. NEVER raises (best-effort exhaust
    capture — the ledger is a byproduct of normal operation, not a gate on it). Each record gets
    a real timestamp; the `event` key names the trajectory-event kind (lock / branch_chosen /
    advance_explicit / terminal_unlock / refusal_no_branch / refusal_pattern / lock_trigger)."""
    try:
        rec = {**record, "timestamp": datetime.now().isoformat()}
        with open(episode_ledger_path(), "a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception as e:
        logger.error(f"sm episode ledger append failed (non-fatal): {e}", exc_info=True)

# --- Type + edge vocabulary (the vaulted SM types; names are the scientifically-exact port) ---
T_STATE_MACHINE = "State_Machine"
T_TRAVERSAL_STEP = "Traversal_Step"
T_EXECUTION_STATE = "Execution_State"
R_HAS_STEP = "HAS_STEP"
R_NEXT_STEP = "NEXT_STEP"
R_CURRENT_STEP = "CURRENT_STEP"
R_CALLS_SM = "CALLS_SM"
R_HAS_LIFECYCLE = "HAS_LIFECYCLE"
P_TRIGGER = "trigger_traversal"
# Identity-as-actual-thing vocabulary (Isaac 2026-06-23): an identity is an Agent_Identity ENTITY
# (named '<TitleCase(handle)>_Identity') that HAS_COLLECTION its retrieval-map (the old Identity_Collection).
T_AGENT_IDENTITY = "Agent_Identity"
R_HAS_COLLECTION = "HAS_COLLECTION"
# The two-layer Agent_Identity shape (Isaac 2026-06-23, S2 — plain names, NO CCC labels):
#   persona-config (the "who"): HAS_FRAME (the persona system-prompt) + HAS_RULES (its rules)
#   substrate (the body it's reflected onto): HAS_SKILLSET (access) + HAS_COLLECTION (reflection store)
#     + the SM Execution_State (gate cursor, already wired via the lifecycle).
R_HAS_FRAME = "HAS_FRAME"
R_HAS_RULES = "HAS_RULES"
R_HAS_SKILLSET = "HAS_SKILLSET"

_DISABLE_FLAG = os.getenv("CARTON_SM_GATE_DISABLED",
                          "/tmp/heaven_data/carton_sm_gate_disabled")


def gate_disabled() -> bool:
    """Global kill switch (the abort/escape hatch). File present => gate OFF everywhere."""
    try:
        return os.path.exists(_DISABLE_FLAG)
    except Exception:
        return False


# --- The ACTIVE IDENTITY (the cross-process actor wire) -----------------------------------------
# equip_persona (skill-manager-mcp, a SEPARATE process) declares WHO is acting; _sm_actor (the carton
# server's process) must read it. Runtime os.environ does NOT cross processes, so — EXACTLY like the
# kill-switch + enable flag above — the active identity crosses the boundary via a FILE. Absent the
# file, callers fall back to env/default, so this is fully default-safe: carton behaviour is unchanged
# until a persona is equipped. The file holds ONE line = the acting identity name. (equip_persona wire,
# Isaac 2026-06-20, fork b: equipping a persona makes its carton_identity the gate's actor.)
_ACTIVE_IDENTITY_FILE = os.getenv("CARTON_SM_ACTIVE_IDENTITY",
                                  "/tmp/heaven_data/carton_sm_active_identity")


def get_active_identity() -> Optional[str]:
    """The acting identity declared by equip_persona (cross-process, via file), or None if none set.
    Read by _sm_actor so an equipped persona becomes the gate's actor across the process boundary."""
    try:
        if os.path.exists(_ACTIVE_IDENTITY_FILE):
            with open(_ACTIVE_IDENTITY_FILE) as f:
                name = f.read().strip()
            return name or None
    except Exception:
        pass
    return None


def set_active_identity(name: str) -> None:
    """Declare the acting identity (equip_persona calls this). Writes the cross-process file."""
    try:
        os.makedirs(os.path.dirname(_ACTIVE_IDENTITY_FILE), exist_ok=True)
        with open(_ACTIVE_IDENTITY_FILE, "w") as f:
            f.write((name or "").strip())
    except Exception as e:
        logger.error(f"set_active_identity failed (non-fatal): {e}", exc_info=True)


def clear_active_identity() -> None:
    """Clear the acting identity (deactivate_persona calls this). Removes the cross-process file."""
    try:
        if os.path.exists(_ACTIVE_IDENTITY_FILE):
            os.remove(_ACTIVE_IDENTITY_FILE)
    except Exception as e:
        logger.error(f"clear_active_identity failed (non-fatal): {e}", exc_info=True)


def _identity_node_name(handle: Optional[str]) -> str:
    """Canonical Agent_Identity ENTITY node name for a raw identity handle (the lowercase carton_identity
    equip_persona writes, e.g. 'gnosys'). Title_Cases each '_'-segment (the graph's name convention) and
    ensures the '_Identity' suffix: 'gnosys' -> 'Gnosys_Identity'; 'starship_pilot' ->
    'Starship_Pilot_Identity'; an already-'..._Identity' handle is returned Title_Cased unchanged; '' -> ''."""
    base = (handle or "").strip().replace(" ", "_")
    title = "_".join(seg.capitalize() for seg in base.split("_") if seg)
    if not title:
        return ""
    return title if title.endswith("_Identity") else f"{title}_Identity"


def resolve_identity_entity(handle: Optional[str],
                            run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]],
                            *,
                            frame: Optional[str] = None,
                            rules: Optional[str] = None,
                            skillset: Optional[str] = None) -> str:
    """Resolve a raw identity handle to its Agent_Identity ENTITY node (the 'identities are actual things'
    model, Isaac 2026-06-23), MERGE-ensuring the entity exists so the SM gate attaches its Execution_State
    /lifecycle (the per-identity gate state) to a REAL node. The prior bug: the gate locked the raw
    lowercase handle ('gnosys'), which matched NO node (graph names are Title_Cased), so
    `_lock_into_sm_chain`'s MATCH no-op'd and routing-persistence never engaged. The entity is
    `is_a Agent_Identity`; if its retrieval-map collection ('<X>_Collection', the old Identity_Collection)
    EXISTS it is linked `HAS_COLLECTION` (the entity is the thing; the collection is its knowledge map).

    S2 (the two-layer shape, 2026-06-23): when the caller HAS the persona-config/access (equip_persona, S3),
    it passes them and they are recorded as graph PARTS on the entity (MEANING → edges, per the property-
    layer doctrine), idempotently:
      - persona-config: HAS_FRAME -> '<Base>_Frame' (its .d = the system-prompt text) ; HAS_RULES ->
        '<Base>_Rules' (its .d = the rules text).
      - substrate access: HAS_SKILLSET -> the Title_Cased skillset node.
    All THREE are optional and default to None, so the GATE-RESOLVE path (_sm_actor, which has no persona-
    config at gate time) passes none and behaviour is UNCHANGED — default-safe. Projecting the frame as a
    running system prompt = host/`claude -p`, out of scope here; S2 only stores/reflects it onto the substrate.

    FAILS OPEN: returns the canonical name even if any MERGE errors, so identity resolution can never brick
    the gate. Returns the entity node name (the resolved actor), or the raw handle if uncanonicalizable."""
    entity = _identity_node_name(handle)
    if not entity:
        return (handle or "").strip()
    base = entity[: -len("_Identity")] if entity.endswith("_Identity") else entity
    try:
        coll = base + "_Collection"
        run(f"""
            MERGE (e:Wiki {{n: $entity}})
            MERGE (e)-[:IS_A]->(:Wiki {{n: '{T_AGENT_IDENTITY}'}})
            WITH e
            OPTIONAL MATCH (c:Wiki {{n: $coll}})
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
                MERGE (e)-[:{R_HAS_COLLECTION}]->(c))
        """, {"entity": entity, "coll": coll})
        if frame is not None:
            run(f"""MERGE (e:Wiki {{n: $entity}}) MERGE (f:Wiki {{n: $fn}})
                    MERGE (e)-[:{R_HAS_FRAME}]->(f) SET f.d = $frame""",
                {"entity": entity, "fn": base + "_Frame", "frame": frame})
        if rules is not None:
            run(f"""MERGE (e:Wiki {{n: $entity}}) MERGE (r:Wiki {{n: $rn}})
                    MERGE (e)-[:{R_HAS_RULES}]->(r) SET r.d = $rules""",
                {"entity": entity, "rn": base + "_Rules", "rules": rules})
        if skillset:
            sk = "_".join(s.capitalize() for s in str(skillset).replace(" ", "_").split("_") if s)
            if sk:
                run(f"""MERGE (e:Wiki {{n: $entity}}) MERGE (s:Wiki {{n: $sk}})
                        MERGE (e)-[:{R_HAS_SKILLSET}]->(s)""", {"entity": entity, "sk": sk})
    except Exception as e:
        logger.error(f"resolve_identity_entity MERGE failed (FAIL-OPEN, using canonical name): {e}",
                     exc_info=True)
    return entity


def _open_live_run():
    """Open a neo4j connection from env and return a `run(query, params)->rows` closure — the shared
    connection-open boilerplate for the self-contained *_live library entries (external callers pass only
    the spec, never a connection). Reads NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD (test defaults:
    bolt://host.docker.internal:7687 / neo4j / password)."""
    from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
    conn = KnowledgeGraphBuilder(
        uri=os.getenv("NEO4J_URI", "bolt://host.docker.internal:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )
    conn._ensure_connection()

    def run(query, params=None):
        rows = conn.execute_query(query, params or {})
        return [dict(r) if not isinstance(r, dict) else r for r in (rows or [])]

    return run


def resolve_identity_entity_live(handle: Optional[str], *,
                                 frame: Optional[str] = None,
                                 rules: Optional[str] = None,
                                 skillset: Optional[str] = None) -> str:
    """Self-contained resolve_identity_entity: opens its own neo4j connection from env, then delegates.

    The library-function entry external callers (equip_persona, S3 — running in the SEPARATE sancrev
    process) use: they pass only the handle + the persona-config parts, never a neo4j connection (same
    pattern as create_sm_chain_live). FAILS OPEN — if the connection itself can't be opened, returns the
    canonical entity name so equip can never be bricked by a carton-side failure."""
    try:
        run = _open_live_run()
        return resolve_identity_entity(handle, run, frame=frame, rules=rules, skillset=skillset)
    except Exception as e:
        logger.error(f"resolve_identity_entity_live failed (FAIL-OPEN, using canonical name): {e}",
                     exc_info=True)
        return _identity_node_name(handle) or (handle or "").strip()


# --- Reading the active cursor (port of get_active_traversal_step) ------------------------------

def get_active_step(actor: str, run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]
                    ) -> Optional[Dict[str, Any]]:
    """The locked Traversal_Step for `actor`, or None if the actor is not locked.

    Port of state_machines.get_active_traversal_step_cypher, carton-native (:Wiki + IS_A).
    """
    rows = run(f"""
        MATCH (a:Wiki {{n: $actor}})-[:{R_HAS_LIFECYCLE}]->(s:Wiki)-[:IS_A]->(:Wiki {{n: '{T_EXECUTION_STATE}'}})
        WHERE s.status = 'locked'
        MATCH (s)-[:{R_CURRENT_STEP}]->(curr:Wiki)-[:IS_A]->(:Wiki {{n: '{T_TRAVERSAL_STEP}'}})
        RETURN curr.n AS id, curr.text AS text, curr.required_pattern AS required_pattern,
               curr.pattern_description AS pattern_description, elementId(s) AS state_id
        LIMIT 1
    """, {"actor": actor})
    if not rows:
        return None
    r = dict(rows[0])
    r["transitions"] = run(f"""
        MATCH (curr:Wiki {{n: $curr_id}})-[t:{R_NEXT_STEP}]->(nxt:Wiki)-[:IS_A]->(:Wiki {{n: '{T_TRAVERSAL_STEP}'}})
        RETURN nxt.n AS id, coalesce(t.weight, 1.0) AS weight, t.required_pattern AS required_pattern
        ORDER BY weight DESC, id ASC
    """, {"curr_id": r["id"]})
    return r


# --- Advancing the cursor (port of auto_progress_step) ------------------------------------------

def auto_progress(active_step: Dict[str, Any],
                  run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]],
                  target_step_id: Optional[str] = None,
                  call_text: str = "",
                  reinforce_delta: float = 0.1,
                  actor: Optional[str] = None) -> str:
    """Advance this Execution_State to its next Traversal_Step, or to an explicit target; at a
    terminal step, UNLOCK. Port of gates.auto_progress_step (carton-native).

    BRANCHING (step 2 of the SM-branching build, 2026-07-04 — wires step 1's pure `select_branch`
    into the live traversal): when `target_step_id` is NOT given, the candidates are this step's
    outgoing `NEXT_STEP` branches (`active_step["transitions"]`, now carrying `required_pattern` per
    `get_active_step`'s query) and `select_branch(candidates, call_text)` DECIDES among them — it no
    longer always takes the single highest-weight edge unconditionally. Three outcomes:
      (a) ZERO outgoing transitions (the pre-existing terminal-step case) -> unchanged: UNLOCK.
      (b) `select_branch` returns a `next_id` (one eligible branch, or several resolved by softmax
          over weight) -> move CURRENT_STEP exactly as before, AND additionally
          `reinforce_transition(curr_id, next_id, reinforce_delta, run)` — the learning signal: the
          edge actually taken gets heavier, so branching decisions compound across traversals (ported
          math: `manifold.py`'s `SoftmaxBanditSelector`/`Traversal.fire`+`consolidate`).
          `reinforce_delta` defaults to 0.1, matching `Manifold.reinforce`'s own default increment
          (`manifold.py:107`, `def reinforce(self, edge, delta: float = 0.1)`) — not a magic inline
          number, this function's own explicit default parameter.
      (c) `select_branch` returns `None` — branches EXIST but NONE are eligible for this `call_text`.
          This is a NEW, INTENTIONAL refusal (branching working correctly, an agent's call matched no
          branch's `required_pattern`), NOT a fail-open case: raises `GateRefusal` directly (see the
          design note below), listing every branch's pattern + whether it matched, so the message
          tells the agent what WOULD have worked (the refusal-is-the-instruction principle this file
          already uses in `gate_call`'s own pattern-mismatch refusal).

    When `target_step_id` IS given, behavior is COMPLETELY UNCHANGED from before this build: the
    explicit override bypasses `select_branch` entirely and moves straight there — no candidate
    building, no reinforcement, no refusal path. (Preserved verbatim per the step-2 spec: an explicit
    override is a deliberate caller decision, not a decision this function should second-guess.)

    DESIGN NOTE — why this function RAISES `GateRefusal` directly (rather than returning a sentinel
    for `gate_call` to convert): `gate_call`'s existing pattern-mismatch refusal (~line 348) already
    raises `GateRefusal` directly from inside a similarly-nested code path, so raising here is the
    established idiom in this file, not a new one. It also PRESERVES this function's existing
    return-type contract exactly (a `str` event message on every successful path, never a dict/tuple
    sentinel that every caller would have to unpack) — the cleanest option per the step-2 brief. The
    cost of raising here is that `gate_call`'s two call sites (which wrap this call in a broad
    `except Exception` for fail-open) must catch `GateRefusal` FIRST and re-raise it so this
    INTENTIONAL refusal is never silently swallowed into a fail-open ALLOW — see the updated call
    sites in `gate_call` below, which do exactly that.
    """
    state_id, curr_id = active_step["state_id"], active_step["id"]
    next_id = target_step_id
    should_reinforce = False
    if not next_id:
        transitions = active_step.get("transitions") or []
        if transitions:
            candidates = [
                {"to": t.get("id"), "required_pattern": t.get("required_pattern"),
                 "weight": t.get("weight", 1.0)}
                for t in transitions
            ]
            next_id = select_branch(candidates, call_text)
            if next_id is None:
                # (c) branches exist but NONE eligible for this call_text -> refuse, not fail-open.
                lines = []
                for c in candidates:
                    pat = c.get("required_pattern")
                    if pat is None:
                        lines.append(f"  -> {c.get('to')}: unconditional (always eligible)")
                    else:
                        try:
                            matched = bool(re.search(pat, call_text))
                        except re.error:
                            matched = False
                        lines.append(
                            f"  -> {c.get('to')}: required_pattern: {pat}"
                            + ("  [would have matched]" if matched else "  [did not match]"))
                # P0 Episode_Ledger: a refusal is trajectory exhaust too (a hard negative for
                # the branch-selection organs) — record before raising.
                _record_sm_episode({"event": "refusal_no_branch", "actor": actor,
                                    "state_id": state_id, "curr_step": curr_id,
                                    "candidates": candidates, "call_text": call_text})
                raise GateRefusal(
                    f"GATE REFUSAL — no eligible branch from step '{curr_id}' for this call. "
                    f"Your call did not match any outgoing branch's required pattern.\n"
                    + "\n".join(lines)
                )
            should_reinforce = True  # (b) a branch was actually chosen -> learn from it
        # else: (a) zero outgoing transitions -> next_id stays None -> terminal, below.
    if not next_id:
        # Terminal step: unlock the Execution_State (it persists; only status clears).
        run(f"MATCH (s:Wiki) WHERE elementId(s) = $sid SET s.status = 'unlocked'", {"sid": state_id})
        msg = f"Traversal complete: final step '{curr_id}' passed. Execution_State UNLOCKED."
        _record_sm_episode({"event": "terminal_unlock", "actor": actor,
                            "state_id": state_id, "curr_step": curr_id, "call_text": call_text})
        logger.info(msg)
        return msg
    # Move CURRENT_STEP: delete the old edge, create the new one.
    run(f"""
        MATCH (s:Wiki)-[r:{R_CURRENT_STEP}]->(:Wiki) WHERE elementId(s) = $sid
        DELETE r
        WITH s
        MATCH (nxt:Wiki {{n: $next_id}}) CREATE (s)-[:{R_CURRENT_STEP}]->(nxt)
    """, {"sid": state_id, "next_id": next_id})
    # P0 Episode_Ledger: THE bandit_choices record (CCC's lost exhaust). `branch_chosen` carries
    # the full decision context (every candidate with its pattern+weight, the call text, the pick,
    # the reinforcement applied); `advance_explicit` = a caller-forced move (no decision was made).
    if should_reinforce:
        reinforce_transition(curr_id, next_id, reinforce_delta, run)
        _record_sm_episode({"event": "branch_chosen", "actor": actor, "state_id": state_id,
                            "curr_step": curr_id, "chosen": next_id,
                            "candidates": [
                                {"to": t.get("id"), "required_pattern": t.get("required_pattern"),
                                 "weight": t.get("weight", 1.0)}
                                for t in (active_step.get("transitions") or [])],
                            "call_text": call_text, "reinforce_delta": reinforce_delta})
    else:
        _record_sm_episode({"event": "advance_explicit", "actor": actor, "state_id": state_id,
                            "curr_step": curr_id, "chosen": next_id, "call_text": call_text})
    nrow = run("MATCH (n:Wiki {n:$id}) RETURN n.text AS text", {"id": next_id})
    text = (nrow[0]["text"] if nrow and nrow[0].get("text") else "(no instruction text)")
    msg = f"Auto-progressed: step '{curr_id}' passed. Next step '{next_id}': {text}"
    logger.info(msg)
    return msg


# --- THE GATE (port of the server.py /api/query gate) ------------------------------------------

class GateRefusal(PermissionError):
    """Raised when a call is illegal given the actor's locked step. Message = the instruction."""


def gate_call(actor: Optional[str], call_text: str,
              run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Check whether `call_text` (the canonical text of the carton tool call / cypher) is LEGAL for
    `actor` given its active Execution_State, and advance the cursor on a legal call.

    Returns {"allowed": True, "event": <progress msg or None>}. Raises GateRefusal on an illegal
    call (its message carries the required regex + step instruction). DEFAULT-UNGATED: returns
    allowed when the gate is disabled, no actor is given, or the actor is not locked. FAILS OPEN on
    any internal error (a buggy SM must never lock an agent out of carton).
    """
    if gate_disabled() or not actor:
        return {"allowed": True, "event": None}
    try:
        active = get_active_step(actor, run)
    except Exception as e:
        logger.error(f"gate fault reading active step (FAIL-OPEN, allowing): {e}")
        return {"allowed": True, "event": None}
    if not active:
        return {"allowed": True, "event": None}  # not locked => ungated
    pattern = active.get("required_pattern")
    if not pattern:
        # Locked at a step with no pattern => nothing constrains the move; allow + advance.
        try:
            return {"allowed": True,
                    "event": auto_progress(active, run, call_text=call_text, actor=actor)}
        except GateRefusal:
            # A NEW, INTENTIONAL refusal (auto_progress found branches but none eligible for this
            # call_text) — branching working correctly, NOT a fail-open case. Must propagate as a
            # real refusal, never be swallowed by the broad except below.
            raise
        except Exception as e:
            logger.error(f"gate fault progressing (FAIL-OPEN): {e}")
            return {"allowed": True, "event": None}
    try:
        legal = bool(re.search(pattern, call_text))
    except re.error as e:
        logger.error(f"bad required_pattern regex on step '{active['id']}' (FAIL-OPEN): {e}")
        return {"allowed": True, "event": None}
    if not legal:
        desc = active.get("pattern_description") or ""
        instruction = active.get("text") or ""
        # P0 Episode_Ledger: an illegal move is trajectory exhaust (a hard negative pairing
        # this step's required_pattern with a call that failed it) — record before raising.
        _record_sm_episode({"event": "refusal_pattern", "actor": actor,
                            "curr_step": active.get("id"), "required_pattern": pattern,
                            "call_text": call_text})
        raise GateRefusal(
            f"GATE REFUSAL — illegal move at step '{active['id']}'. Your call did not match the "
            f"required pattern. required_pattern: {pattern}"
            + (f"  ({desc})" if desc else "")
            + (f"\nStep instruction: {instruction}" if instruction else "")
        )
    try:
        return {"allowed": True,
                "event": auto_progress(active, run, call_text=call_text, actor=actor)}
    except GateRefusal:
        # Same as the no-pattern branch above: an intentional no-eligible-branch refusal must
        # propagate, never be converted into a fail-open ALLOW by the broad except below.
        raise
    except Exception as e:
        logger.error(f"gate fault progressing after legal call (FAIL-OPEN): {e}")
        return {"allowed": True, "event": None}


# --- Activation / trigger (port of scan_and_trigger_traversal) ---------------------------------

def _find_trigger(val: Any) -> Optional[str]:
    """Depth-first scan of a serialized result for a node carrying trigger_traversal (the step id)."""
    if isinstance(val, dict):
        if val.get(P_TRIGGER):
            return val[P_TRIGGER]
        props = val.get("properties")
        if isinstance(props, dict) and props.get(P_TRIGGER):
            return props[P_TRIGGER]
        for v in val.values():
            t = _find_trigger(v)
            if t:
                return t
    elif isinstance(val, (list, tuple)):
        for v in val:
            t = _find_trigger(v)
            if t:
                return t
    return None


def scan_and_trigger(results: Any, actor: Optional[str],
                     run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]) -> Optional[str]:
    """If `results` contains a node with a `trigger_traversal` property, LOCK `actor` into that flow
    (reuse the actor's existing Execution_State; never lock if already locked). Port of
    gates.scan_and_trigger_traversal. Returns the locked step id, or None. FAILS OPEN.
    """
    if gate_disabled() or not actor:
        return None
    step_id = _find_trigger(results)
    if not step_id:
        return None
    try:
        already = run(f"""
            MATCH (a:Wiki {{n: $actor}})-[:{R_HAS_LIFECYCLE}]->(s:Wiki)-[:IS_A]->(:Wiki {{n: '{T_EXECUTION_STATE}'}})
            WHERE s.status = 'locked' RETURN count(s) AS c
        """, {"actor": actor})
        if already and already[0].get("c"):
            return None  # don't interrupt a live flow
        run(f"""
            MATCH (step:Wiki {{n: $step_id}})-[:IS_A]->(:Wiki {{n: '{T_TRAVERSAL_STEP}'}})
            MATCH (a:Wiki {{n: $actor}})-[:{R_HAS_LIFECYCLE}]->(s:Wiki)-[:IS_A]->(:Wiki {{n: '{T_EXECUTION_STATE}'}})
            WHERE coalesce(s.status,'unlocked') <> 'locked'
            WITH s, step LIMIT 1
            OPTIONAL MATCH (s)-[r:{R_CURRENT_STEP}]->() DELETE r
            SET s.status = 'locked'
            CREATE (s)-[:{R_CURRENT_STEP}]->(step)
        """, {"step_id": step_id, "actor": actor})
        _record_sm_episode({"event": "lock_trigger", "actor": actor, "entry_step": step_id})
        logger.info(f"Trigger: actor '{actor}' locked into flow at step '{step_id}'.")
        return step_id
    except Exception as e:
        logger.error(f"scan_and_trigger fault (FAIL-OPEN, no lock): {e}")
        return None


# --- THE SM_CHAIN (CCC calls this the 'Core'): a per-concept STACK of SMs + the precondition-before-content visit gate -----------
# Isaac 2026-06-20: carton's SM system mirrors CCC's Core (cyberneticircus/lib/core.py). A Sm_Chain is an
# ORDERED STACK of State_Machines belonging to an identity. SCIENTIFICALLY-EXACT port of core.py,
# GENERALIZED from per-Cybernet to PER-CONCEPT (a persona is one kind of concept; ANY concept may carry
# a Sm_Chain that gates access to its content).
#   (concept:Wiki)-[:HAS_SM_CHAIN]->(Sm_Chain:Wiki IS_A Sm_Chain)-[:SM_CHAIN_RUNS {order}]->(SM:Wiki IS_A State_Machine)
# DEFAULT (no Sm_Chain): the concept just serves its content — "the SM is 1 step, show the thing, therefore
# off." A Sm_Chain does NOT withhold the visited concept's content (Isaac 2026-06-20: "a concept with a core
# does not WITHHOLD... it is supposed to REQUIRE NEXT"). PROGRAMMING a Sm_Chain step takes the REQUIRE-NEXT
# format "before seeing anything ELSE, you must traverse somewhere specific OR run this cypher: xyz": the
# concept IS served, but the visit LOCKS the actor so the actor's NEXT move is REQUIRED to match the
# step's required_pattern (a specific traversal/query). That next-move enforcement is exactly the
# existing gate_call (routing-persistence: while locked, the next call must match or it is refused).
# ACTIVATION (Isaac 2026-06-20 16:17, IMPLEMENTED in sm_chain_visit): a Sm_Chain is ON (gated) iff its
# stack holds >1 SM; a single SM (the show-SM) = OFF regardless of its entry's pattern. STILL DEFERRED:
# the multi-SM SM_CHAIN_RUNS ADVANCE across the stack (traversing order-0 -> order-1 as each SM terminates)
# -- v0 locks into the first gating SM and unlocks at its terminal. This layer is ADDITIVE (gate_call /
# auto_progress / scan_and_trigger are untouched), DEFAULT-OFF, FAILS OPEN (no require-next), and is NOT
# yet wired onto the live get_concept (that is the wiring increment, exactly as the gate was staged).
T_SM_CHAIN = "Sm_Chain"
R_HAS_SM_CHAIN = "HAS_SM_CHAIN"
R_SM_CHAIN_RUNS = "SM_CHAIN_RUNS"


def get_sm_chain(concept: str, run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]
             ) -> List[Dict[str, Any]]:
    """`concept`'s Sm_Chain stack as an ordered list of {sm_id, order}, or [] if it has no Sm_Chain (default
    OFF). Port of core.has_core_cypher, carton-native (:Wiki + IS_A), generalized to any concept."""
    return run(f"""
        MATCH (c:Wiki {{n: $concept}})-[:{R_HAS_SM_CHAIN}]->(core:Wiki)-[:IS_A]->(:Wiki {{n: '{T_SM_CHAIN}'}})
        MATCH (core)-[r:{R_SM_CHAIN_RUNS}]->(sm:Wiki)-[:IS_A]->(:Wiki {{n: '{T_STATE_MACHINE}'}})
        RETURN sm.n AS sm_id, coalesce(r.order, 0) AS order ORDER BY r.order ASC, sm_id ASC
    """, {"concept": concept})


def _entry_step(sm_id: str, run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]
                ) -> Optional[Dict[str, Any]]:
    """The entry Traversal_Step of an SM = a HAS_STEP step with no incoming NEXT_STEP edge."""
    rows = run(f"""
        MATCH (m:Wiki {{n: $sm}})-[:{R_HAS_STEP}]->(s:Wiki)-[:IS_A]->(:Wiki {{n: '{T_TRAVERSAL_STEP}'}})
        WHERE NOT ( (:Wiki)-[:{R_NEXT_STEP}]->(s) )
        RETURN s.n AS id, s.text AS text, s.required_pattern AS required_pattern,
               s.pattern_description AS pattern_description
        ORDER BY s.n ASC LIMIT 1
    """, {"sm": sm_id})
    return dict(rows[0]) if rows else None


def get_lifecycle(actor: str, run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]
                  ) -> Optional[Dict[str, Any]]:
    """The actor's Execution_State row (status + equipped_sm_id + sm_chain_index), locked OR unlocked.
    (get_active_step only returns while locked; this reads the cursor unconditionally.)"""
    rows = run(f"""
        MATCH (a:Wiki {{n: $actor}})-[:{R_HAS_LIFECYCLE}]->(s:Wiki)-[:IS_A]->(:Wiki {{n: '{T_EXECUTION_STATE}'}})
        RETURN elementId(s) AS state_id, coalesce(s.status, 'unlocked') AS status,
               s.equipped_sm_id AS equipped_sm_id, coalesce(s.sm_chain_index, 0) AS sm_chain_index
        LIMIT 1
    """, {"actor": actor})
    return dict(rows[0]) if rows else None


def _lock_into_sm_chain(actor: str, sm_id: str, entry_id: str,
                    run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]) -> None:
    """Lock `actor`'s Execution_State into a Sm_Chain SM at its entry step (port of the core equip /
    ADVANCE_CORE_CYPHER, degenerate order-0 case). The Execution_State is a deterministic per-actor
    node (n = '<actor>_Execution_State') so it is reused across visits."""
    run(f"""
        MATCH (a:Wiki {{n: $actor}})
        MERGE (s:Wiki {{n: $state_name}})
        MERGE (s)-[:IS_A]->(:Wiki {{n: '{T_EXECUTION_STATE}'}})
        MERGE (a)-[:{R_HAS_LIFECYCLE}]->(s)
        WITH s
        OPTIONAL MATCH (s)-[c:{R_CURRENT_STEP}]->() DELETE c
        SET s.status = 'locked', s.equipped_sm_id = $sm_id, s.sm_chain_index = 0
        WITH s MATCH (entry:Wiki {{n: $entry_id}}) CREATE (s)-[:{R_CURRENT_STEP}]->(entry)
    """, {"actor": actor, "state_name": f"{actor}_Execution_State",
          "sm_id": sm_id, "entry_id": entry_id})


def sm_chain_visit(actor: Optional[str], concept: str,
               run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]) -> Dict[str, Any]:
    """THE REQUIRE-NEXT GATE — deliberate-visit activation of a concept's Sm_Chain.

    Returns {"require_next": <the required next-move instruction or None>, "event": <msg|None>}.
    The concept's content is ALWAYS served — a Sm_Chain does NOT withhold it (Isaac 2026-06-20: "a concept
    with a core does not WITHHOLD... it is supposed to REQUIRE NEXT"). What a Sm_Chain does is REQUIRE that
    the actor's NEXT move is a specific traversal/cypher: a deliberate visit to a Sm_Chain-bearing concept
    LOCKS the actor into the Sm_Chain's order-0 SM entry step, so the actor's next call must match that
    step's required_pattern — enforced by the normal `gate_call` (routing-persistence: while locked, the
    next call must match or it is refused). require_next = the entry step's instruction (what the next
    move must be), to append to the served content. DEFAULT OFF: gate disabled / no actor / concept has
    NO Sm_Chain / an entry step with no required_pattern -> require_next=None (nothing required). Idempotent:
    if already locked mid-flow in THIS Sm_Chain, returns the current step's require-next WITHOUT re-locking.
    FAILS OPEN (require_next=None) on any fault — a Sm_Chain bug can only fail to ARM a requirement, never
    block carton or withhold content.
    """
    if gate_disabled() or not actor:
        return {"require_next": None, "event": None}
    try:
        core = get_sm_chain(concept, run)
        if not core:
            return {"require_next": None, "event": None}  # no Sm_Chain => nothing required
        # STACK-SIZE ACTIVATION (Isaac 2026-06-20 16:17): a Sm_Chain is ON (gated) iff its stack holds
        # MORE THAN 1 SM. A single SM (the show-SM — e.g. a skill->SM v0 concept) = OFF: serve the
        # concept, require nothing, never lock. Adding ANY further SM to the stack turns gating ON.
        if len(core) <= 1:
            return {"require_next": None, "event": None}  # single show-SM => OFF (the stack-size rule)
        # >1 SM => GATED. The order-0 SM is the show (serves content); lock into the FIRST SM (by order)
        # whose entry step imposes a requirement (the gating SM). (Multi-SM SM_CHAIN_RUNS advance ACROSS
        # the stack stays the deferred increment; this lands the on/off ACTIVATION criterion only.)
        sm_id, entry = None, None
        for sm in core:
            e = _entry_step(sm["sm_id"], run)
            if e and e.get("required_pattern"):
                sm_id, entry = sm["sm_id"], e
                break
        if not sm_id:
            return {"require_next": None, "event": None}  # >1 SM but none imposes a requirement => off
        life = get_lifecycle(actor, run)
        if life and life.get("equipped_sm_id") == sm_id and life.get("status") == "locked":
            # already mid-flow in this gating SM: the active step IS the current require-next (don't re-lock)
            active = get_active_step(actor, run)
            return {"require_next": ((active or {}).get("text")
                                     or (active or {}).get("required_pattern")), "event": None}
        _lock_into_sm_chain(actor, sm_id, entry["id"], run)
        _record_sm_episode({"event": "lock", "actor": actor, "concept": concept,
                            "sm_id": sm_id, "entry_step": entry["id"]})
        return {"require_next": (entry.get("text")
                                 or f"Your next move must match: {entry['required_pattern']}"),
                "event": f"Sm_Chain on '{concept}': content served; your NEXT move is now REQUIRED."}
    except Exception as e:
        logger.error(f"sm_chain_visit fault (FAIL-OPEN, no require-next): {e}", exc_info=True)
        return {"require_next": None, "event": None}


# --- The skill->SM converter (build-plan item 1: "SKILLS ARE JUST SMs") -------------------------
# Isaac 2026-06-20: "make an SM that retrieves the skill's info (the SM IS the skill)"; globally-
# available SMs get listed in the system prompt FROM THE GRAPH (the item-2 graph->system-prompt
# generator reads these). v0 = the DEGENERATE SHOW-Sm_Chain: a skill concept gets a Sm_Chain holding ONE
# show-SM whose entry step has NO required_pattern, so sm_chain_visit treats it as OFF (serves the skill,
# requires nothing) = the default "1 step = show = off". ACTIVATION (Isaac: a Sm_Chain with >1 SM in its
# stack is ON) is added later by PROGRAMMING the skill -- adding gated SMs/steps -- which is coupled to
# the deferred multi-SM SM_CHAIN_RUNS advance increment (which SM gates + how the stack advances). So this
# converter is purely ADDITIVE + idempotent (MERGE): giving a skill its SM representation never gates it.
def skill_to_sm(skill_concept: str,
                run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]],
                *, show_text: Optional[str] = None) -> Dict[str, Any]:
    """Give `skill_concept` its SM representation (the SM IS the skill). Idempotently MERGE-creates:
        <skill> -HAS_SM_CHAIN-> Sm_Chain_<skill> -SM_CHAIN_RUNS{order:0}-> Sm_<skill> -HAS_STEP-> Step_<skill>_Show
    The show step carries NO required_pattern, so the Sm_Chain is OFF by default (sm_chain_visit serves the
    concept and requires nothing). Returns {sm_id, sm_chain_id, entry_id, show_text}."""
    sm_chain_id = f"{T_SM_CHAIN}_{skill_concept}"
    sm_id = f"Sm_{skill_concept}"
    entry_id = f"Step_{skill_concept}_Show"
    text = show_text or f"Show skill {skill_concept}: retrieve its content / what-when."
    run(f"""
        MERGE (sk:Wiki {{n: $skill}})
        MERGE (core:Wiki {{n: $sm_chain_id}}) MERGE (core)-[:IS_A]->(:Wiki {{n: '{T_SM_CHAIN}'}})
        MERGE (sm:Wiki {{n: $sm_id}}) MERGE (sm)-[:IS_A]->(:Wiki {{n: '{T_STATE_MACHINE}'}})
        MERGE (es:Wiki {{n: $entry_id}}) MERGE (es)-[:IS_A]->(:Wiki {{n: '{T_TRAVERSAL_STEP}'}})
        SET es.text = $text
        MERGE (sk)-[:{R_HAS_SM_CHAIN}]->(core)
        MERGE (core)-[r:{R_SM_CHAIN_RUNS}]->(sm) SET r.order = 0
        MERGE (sm)-[:{R_HAS_STEP}]->(es)
    """, {"skill": skill_concept, "sm_chain_id": sm_chain_id, "sm_id": sm_id,
          "entry_id": entry_id, "text": text})
    return {"sm_id": sm_id, "sm_chain_id": sm_chain_id, "entry_id": entry_id, "show_text": text}


# --- The GENERIC SM-creation factory (the first-class build path: program a full Sm_Chain stack) ------
# skill_to_sm is the DEGENERATE case (one show-SM, one step, no requirement). create_sm_chain is the
# GENERAL factory: it abstracts the EXACT proven cypher that tests/test_sm_core_e2e.py:_program MERGEs by
# hand (concept -HAS_SM_CHAIN-> Sm_Chain -SM_CHAIN_RUNS{order}-> State_Machine -HAS_STEP-> Traversal_Step
# {required_pattern,text}, with NEXT_STEP between consecutive steps) into ONE reusable function, so a caller
# programs an arbitrary ordered STACK of SMs (each with its own ordered steps) instead of writing raw cypher.
# Idempotent (MERGE-on-names, exactly like skill_to_sm + the test): re-running with the same node names
# never duplicates. The stack-size ACTIVATION rule is unchanged (sm_chain_visit owns it): a >1-SM stack is
# GATED, a single SM is the OFF show-SM — so `gated` in the return is just len(state_machines) > 1.
#
# BRANCHING (step 1 of the SM-branching build, 2026-07-04 — Isaac's decided requirement: the traversing
# agent must make a REAL decision among multiple candidate next-steps, evaluated against its current
# input, not just auto-follow one fixed path; and branch weights must CHANGE based on which routes
# actually get taken, persisted on the graph). A step's outgoing moves are now its `branches` list (see
# `_step_branches` + the docstring below); `select_branch` (further down this file) is the pure decision
# function step 2 will wire into `auto_progress` to actually CHOOSE among them at traversal time — this
# function only builds the DATA MODEL (the graph), it does not yet change how a live traversal moves.
def _step_branches(step: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The outgoing branches of one step spec passed to `create_sm_chain` — the backward-compat shim.

    A step spec written in the NEW form carries its own `"branches"` list (each entry a dict with
    `to`, `required_pattern`, `weight`) and is returned as-is (`step.get("branches") or []`).

    A step spec still written in the OLD form (only a `"next": <step id or None>` key, no `"branches"`
    key at all) is translated into the single-branch shorthand
    `[{"to": next, "required_pattern": None, "weight": 1.0}]` when `next` is truthy, or `[]` when `next`
    is falsy/absent — i.e. exactly the one edge the OLD `create_sm_chain` always built for a `next`-only
    step (that old code built the edge with NO properties on it at all; this shim's
    `required_pattern=None` + `weight=1.0` are the NEW edge-build loop's neutral defaults, so the
    resulting edge is functionally identical to before: still the single unconditional candidate,
    still selected every time). This is what keeps every existing caller of `create_sm_chain`
    (`_sm_graph_to_factory` in both `heaven_tree_repl/node_sync.py` and `dragonbones/db_carton.py`,
    `substrate_projector.project_state_machine`, and every test in this repo's `tests/` dir) unaffected.
    """
    if "branches" in step:
        return step.get("branches") or []
    nxt = step.get("next")
    if not nxt:
        return []
    return [{"to": nxt, "required_pattern": None, "weight": 1.0}]


def _title_case_node_name(raw: str) -> str:
    """Title_Case_With_Underscores a raw token for use as a :Wiki node name (the graph's naming
    convention — same segment-capitalize-and-rejoin approach `_identity_node_name` already uses in
    this file). `personal_domain` values arrive lowercase (paiab/sanctum/cave/misc/personal per
    PERSONAL_DOMAINS); this file's raw-Cypher MERGE calls do NOT go through the daemon's
    normalize_concept_name, so without this the Sm_Chain's has_personal_domain target would land as
    a stray lowercase node (e.g. 'cave') instead of the Title_Cased node the rest of the graph uses
    for that same tag (e.g. 'Cave', per `merge_optional_domain_fields`'s live-verified behavior)."""
    base = (raw or "").strip().replace(" ", "_")
    return "_".join(seg.capitalize() for seg in base.split("_") if seg)


def create_sm_chain(concept_name: str,
                    state_machines: List[Dict[str, Any]],
                    run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]],
                    *, sm_chain_name: Optional[str] = None,
                    domain: str = None, subdomain: str = None,
                    personal_domain: str = None,
                    produces: Optional[List[str]] = None) -> Dict[str, Any]:
    """Idempotently create/attach an SM stack (Sm_Chain) on a concept — the generic SM factory.

    concept_name: the concept whose retrieval the SM gates (it gets the HAS_SM_CHAIN edge).
    state_machines: ordered list; each = {"name": <sm node name>,
        "steps": [{"id": <step node name>, "required_pattern": <regex str or None>,
                   "text": <instruction str>,
                   "branches": [{"to": <step id>, "required_pattern": <regex str or None>,
                                 "weight": <float, default 1.0>}, ...]}, ...]}.
        The SM's order on SM_CHAIN_RUNS = its index in this list (0 = first/show-SM, 1+ = gating per the
        stack-size rule). A step's `branches` list is its set of candidate outgoing moves — zero, one, or
        several — each becoming its OWN NEXT_STEP edge, independently pattern-gated and weighted.
        BACKWARD COMPATIBILITY: a step spec that still has the OLD `"next": <step id or None>` key and NO
        `"branches"` key is accepted unchanged (see `_step_branches`) — existing callers keep working.
    run: the cypher runner (query, params) -> list of dict rows (the shape the tests use).
    sm_chain_name: the Sm_Chain node name; defaults to f"{concept_name}_Sm_Chain".
    domain, subdomain, personal_domain: REQUIRED (Isaac 2026-07-04, verbatim: "sm_gate should require
        it for the abstraction about the sm" — unlike `add_concept_tool_func`'s task-58 fields, which
        stayed OPTIONAL because making them required there would break ~8 existing internal callers
        across the whole monorepo; `create_sm_chain` is this session's own new capability with exactly
        4 known callers, all updated in the same change, so requiring them here carries none of that
        risk). Tag the Sm_Chain node itself — the ONE per-gated-concept umbrella container, NOT every
        State_Machine/Traversal_Step (which would redundantly repeat the same 3 edges onto potentially
        dozens of step nodes for no query benefit; the whole abstraction is reachable from the tagged
        Sm_Chain via HAS_SM_CHAIN/SM_CHAIN_RUNS/HAS_STEP traversal). `personal_domain` IS enum-validated
        against `PERSONAL_DOMAINS` (imported from `carton_mcp.add_concept_tool`, the canonical source —
        never duplicated). Raises `Exception` if any of the three is missing or if `personal_domain` is
        invalid — this function requires them unconditionally, it does not merely accept them optionally.
    produces: OPTIONAL (Isaac's instruction named domain/subdomain/personal_domain specifically, not
        produces — an SM abstraction's "product" is less naturally a single target than what it IS/
        where it belongs). Merged onto the Sm_Chain node as PRODUCES edges if given.

    Builds, idempotently (MERGE on names, like skill_to_sm + the test):
      (c:Wiki{n:concept_name})-[:HAS_SM_CHAIN]->(core:Wiki IS_A Sm_Chain)
      (core)-[:HAS_DOMAIN]->(domain) ; (core)-[:HAS_SUBDOMAIN]->(subdomain) ;
      (core)-[:HAS_PERSONAL_DOMAIN]->(personal_domain) ; (core)-[:PRODUCES]->(each produces target)
      (core)-[:SM_CHAIN_RUNS{order:i}]->(sm:Wiki IS_A State_Machine)   for each SM (order = its index)
      (sm)-[:HAS_STEP]->(step:Wiki IS_A Traversal_Step) with required_pattern + text set per step
      (stepA)-[:NEXT_STEP{required_pattern, weight}]->(stepB) for EVERY branch a step declares (via
        `_step_branches`, so a `next`-only step still produces exactly its one edge)

    Returns {"concept", "sm_chain", "sms": [sm names], "steps": [step names],
             "gated": len(state_machines) > 1}.
    """
    if not domain or not subdomain or not personal_domain:
        raise Exception(
            "create_sm_chain REQUIRES domain, subdomain, and personal_domain (Isaac 2026-07-04: "
            "'sm_gate should require it for the abstraction about the sm') — got "
            f"domain={domain!r} subdomain={subdomain!r} personal_domain={personal_domain!r}"
        )
    from carton_mcp.add_concept_tool import PERSONAL_DOMAINS
    # CASE-INSENSITIVE (Isaac 2026-07-04, caught live during E2E verification of
    # project_state_machine): a caller reading a personal_domain value BACK OFF THE GRAPH gets a
    # Title_Cased NODE NAME (e.g. 'Cave' — the daemon Title-Cases every relationship target it
    # writes), not the raw lowercase enum value ('cave') a fresh caller supplies. Both are legitimate
    # — validate against .lower() so either form is accepted, then Title_Case for the node write below
    # regardless of which form arrived (so the stored node name is always consistent either way).
    if personal_domain.lower() not in PERSONAL_DOMAINS:
        raise Exception(
            f"Invalid personal_domain {personal_domain!r}. Must be one of: {', '.join(PERSONAL_DOMAINS)}"
        )

    sm_chain_id = sm_chain_name or f"{concept_name}_Sm_Chain"
    # 1) concept -HAS_SM_CHAIN-> Sm_Chain (idempotent attach of the stack node), tagged with its
    #    REQUIRED domain/subdomain/personal_domain (Title_Cased to match the graph's naming
    #    convention — see `_title_case_node_name`).
    run(f"""
        MERGE (c:Wiki {{n: $concept}})
        MERGE (core:Wiki {{n: $sm_chain_id}}) MERGE (core)-[:IS_A]->(:Wiki {{n: '{T_SM_CHAIN}'}})
        MERGE (c)-[:{R_HAS_SM_CHAIN}]->(core)
        MERGE (dom:Wiki {{n: $domain}})
        MERGE (core)-[:HAS_DOMAIN]->(dom)
        MERGE (sub:Wiki {{n: $subdomain}})
        MERGE (core)-[:HAS_SUBDOMAIN]->(sub)
        MERGE (pd:Wiki {{n: $personal_domain}})
        MERGE (core)-[:HAS_PERSONAL_DOMAIN]->(pd)
    """, {"concept": concept_name, "sm_chain_id": sm_chain_id,
          "domain": _title_case_node_name(domain), "subdomain": _title_case_node_name(subdomain),
          "personal_domain": _title_case_node_name(personal_domain)})
    for target in (produces or []):
        run(f"""
            MATCH (core:Wiki {{n: $sm_chain_id}})
            MERGE (t:Wiki {{n: $target}})
            MERGE (core)-[:PRODUCES]->(t)
        """, {"sm_chain_id": sm_chain_id, "target": target})

    sm_names: List[str] = []
    step_names: List[str] = []
    for order, sm in enumerate(state_machines):
        sm_id = sm["name"]
        sm_names.append(sm_id)
        # 2) Sm_Chain -SM_CHAIN_RUNS{order}-> State_Machine (order = index in the list).
        run(f"""
            MATCH (core:Wiki {{n: $sm_chain_id}})
            MERGE (sm:Wiki {{n: $sm_id}}) MERGE (sm)-[:IS_A]->(:Wiki {{n: '{T_STATE_MACHINE}'}})
            MERGE (core)-[r:{R_SM_CHAIN_RUNS}]->(sm) SET r.order = $order
        """, {"sm_chain_id": sm_chain_id, "sm_id": sm_id, "order": order})
        # 3) State_Machine -HAS_STEP-> Traversal_Step (each step carries required_pattern + text).
        for step in sm.get("steps", []):
            step_id = step["id"]
            step_names.append(step_id)
            run(f"""
                MATCH (sm:Wiki {{n: $sm_id}})
                MERGE (es:Wiki {{n: $step_id}}) MERGE (es)-[:IS_A]->(:Wiki {{n: '{T_TRAVERSAL_STEP}'}})
                SET es.required_pattern = $required_pattern, es.text = $text
                MERGE (sm)-[:{R_HAS_STEP}]->(es)
            """, {"sm_id": sm_id, "step_id": step_id,
                  "required_pattern": step.get("required_pattern"),
                  "text": step.get("text")})
        # 4) stepA -NEXT_STEP{required_pattern, weight}-> stepB for EVERY branch a step declares
        #    (`_step_branches` handles the old-`next`-only backward-compat shorthand).
        for step in sm.get("steps", []):
            for branch in _step_branches(step):
                to = branch.get("to")
                if not to:
                    continue
                run(f"""
                    MATCH (a:Wiki {{n: $a}})-[:IS_A]->(:Wiki {{n: '{T_TRAVERSAL_STEP}'}})
                    MATCH (b:Wiki {{n: $b}})-[:IS_A]->(:Wiki {{n: '{T_TRAVERSAL_STEP}'}})
                    MERGE (a)-[r:{R_NEXT_STEP}]->(b)
                    SET r.required_pattern = $required_pattern, r.weight = $weight
                """, {"a": step["id"], "b": to,
                      "required_pattern": branch.get("required_pattern"),
                      "weight": float(branch.get("weight", 1.0))})

    return {"concept": concept_name, "sm_chain": sm_chain_id,
            "sms": sm_names, "steps": step_names,
            "gated": len(state_machines) > 1}


# --- The SELF-CONTAINED live factory (the library-function entry external callers use) ----------------
# create_sm_chain takes an injected `run` (PURE w.r.t. the live MCP — unit-testable, never opens a
# connection). External callers (dragonbones) must NOT manage a neo4j connection: per the nuclear
# dragonbones-must-call-library-functions rule, the library function handles EVERYTHING — the caller
# passes only the spec. create_sm_chain_live is that entry: it opens its OWN neo4j connection from env
# (via the shared _open_live_run() helper — the EXACT proven pattern in tests/test_sm_factory_e2e.py:
# _conn/_mk_run — KnowledgeGraphBuilder + _ensure_connection + execute_query wrapped into a run closure),
# then delegates to create_sm_chain. This is purely ADDITIVE: create_sm_chain (and every other function)
# is untouched.
def create_sm_chain_live(concept_name, state_machines, *, sm_chain_name=None,
                         domain=None, subdomain=None, personal_domain=None, produces=None):
    """Self-contained create_sm_chain: opens its own neo4j connection from env, calls create_sm_chain.

    The library-function entry that external callers (dragonbones) use — they pass only the spec,
    never a connection (per the nuclear dragonbones-must-call-library-functions rule: the library
    function handles everything). Connection-open is the shared _open_live_run() helper (same defaults
    as the tests: bolt://host.docker.internal:7687 / neo4j / password). Returns create_sm_chain's dict.

    domain, subdomain, personal_domain: REQUIRED, straight passthrough to create_sm_chain (which
    raises if any is missing or personal_domain is invalid) — see its docstring. produces: OPTIONAL,
    same passthrough.
    """
    run = _open_live_run()

    return create_sm_chain(concept_name, state_machines, run, sm_chain_name=sm_chain_name,
                           domain=domain, subdomain=subdomain, personal_domain=personal_domain,
                           produces=produces)


# --- SM branching: pure decision + weight reinforcement (step 1 of the SM-branching build, 2026-07-04) --
# Isaac's decided requirement (do not redesign): the traversing agent must be able to make a real DECISION
# among multiple candidate next-steps (branching, based on a condition evaluated against its current
# input) — not just auto-follow one fixed path; and branch weights must CHANGE based on which routes
# actually get taken (a learning mechanism), persisted on the graph (not in-memory). `select_branch` is
# the PURE decision function (no neo4j, no I/O — onion architecture, exactly like `_compute_d2_coverage`
# in `add_concept_tool.py` is this repo's existing exemplar of that discipline); `reinforce_transition` is
# the thin neo4j write-back that persists the learning. The softmax-selection math in `select_branch` is
# PORTED from `manifold.py`'s `SoftmaxBanditSelector` (`manifold.py:160-210`) — that module stays PURE
# IN-MEMORY (no `to_carton`/persistence anywhere in it) and is NOT imported here; only its ~30 lines of
# math are re-derived as this module's own function, per this task's explicit scope (no import dependency
# between the two files). NEITHER function is wired into `auto_progress`/`gate_call` yet — that wiring is
# step 2, a separate future task; this is the data + selection logic step 2 will consume, built and
# unit-tested standalone (see tests/test_sm_branching.py).
def select_branch(candidates: List[Dict[str, Any]], call_text: str) -> Optional[str]:
    """Choose which branch's `to` step id an agent's current call is routed to.

    `candidates` is the current step's outgoing branches (each a dict `{"to", "required_pattern",
    "weight"}` — the shape `_step_branches` returns / `create_sm_chain`'s `branches` list uses).
    `call_text` is the agent's current call's canonical text (the same text `gate_call` already checks
    a single `required_pattern` against).

    FILTER: a branch is ELIGIBLE iff its `required_pattern` is None OR `re.search(required_pattern,
    call_text)` matches. Zero eligible branches returns None (this function never raises — the caller,
    not built in this task, decides how to refuse a zero-eligible call).

    SELECT: a single eligible branch is returned deterministically (just its `to`, no randomness
    involved). Two or more eligible branches are chosen by SOFTMAX SAMPLING over `weight` — ported from
    `manifold.py`'s `SoftmaxBanditSelector.probabilities` (`manifold.py:182-194`, the numerically-stable
    softmax: shift by the max weight before `exp`, normalize) and `SoftmaxBanditSelector.__call__`
    (`manifold.py:196-210`, sample a uniform draw against the cumulative distribution, with the same
    float-rounding fallthrough to the last candidate as that method's last line). This port fixes
    `selection_pressure` at 1.0 and carries no explore/mutation term — the two knobs `manifold.py`'s
    dynamical layer exposes that this port does not (yet) surface. A branch with no `weight` key
    defaults to `1.0` (uniform), matching `Edge.weight`'s own default in `manifold.py`.
    """
    eligible = [c for c in candidates
                if c.get("required_pattern") is None or re.search(c["required_pattern"], call_text)]
    if not eligible:
        return None
    if len(eligible) == 1:
        return eligible[0].get("to")
    # softmax over weight (ported from manifold.py:182-210, selection_pressure fixed at 1.0)
    betas = [float(c.get("weight", 1.0)) for c in eligible]
    mx = max(betas)
    exps = [math.exp(b - mx) for b in betas]
    total = sum(exps) or 1.0
    probs = [w / total for w in exps]
    r = random.random()
    acc = 0.0
    for c, p in zip(eligible, probs):
        acc += p
        if r <= acc:
            return c.get("to")
    return eligible[-1].get("to")  # float-rounding fallthrough (manifold.py:210's own comment)


def reinforce_transition(curr_id: str, next_id: str, delta: float,
                         run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]) -> None:
    """+delta onto the NEXT_STEP edge's weight property from curr_id to next_id.

    Thin, synchronous, direct write — the SCRATCH-LANE pattern this file already uses throughout (no
    try/except, no SOMA trail, same shape as `_lock_into_sm_chain`'s direct MERGE/SET writes): `weight`
    is exactly the automation/work-state class of property `the-property-layer-doctrine` rule keeps on
    the fast, SOMA-free scratch lane (never load-bearing for MEANING — the ontological fact here is the
    NEXT_STEP edge's existence, built by `create_sm_chain`; `weight` is just the learning-signal tuning
    it). Requires the `curr_id --NEXT_STEP--> next_id` edge to already exist; if it does not, the MATCH
    finds nothing and this is a silent no-op (the same MATCH-only-no-op shape every other write in this
    file that assumes prior structure uses, e.g. `auto_progress`'s CURRENT_STEP move). Not wired into
    `auto_progress` yet — that is step 2, a separate future task.
    """
    run(f"""
        MATCH (a:Wiki {{n: $curr_id}})-[r:{R_NEXT_STEP}]->(b:Wiki {{n: $next_id}})
        SET r.weight = coalesce(r.weight, 1.0) + $delta
    """, {"curr_id": curr_id, "next_id": next_id, "delta": delta})


# --- The batch skill->SM converter (build-plan item 1 follow-through: POPULATE the graph) ------------
# generate_system_prompt's "globally-available SMs from the graph" listing is only real once skill->SM
# nodes EXIST. This batches skill_to_sm over a SET of skills to populate them. SCOPE IS EXPLICIT + CAPPED:
# pass `skills` (exact names) or a `limit` (query Skill concepts, bounded); with NEITHER it converts
# NOTHING — so it can never blast the whole skill corpus by accident. WHICH skills become "globally
# available" is a POLICY decision (reserved for Isaac); this is just the tool, the caller owns the policy.
# Idempotent (skill_to_sm is MERGE); a single bad skill is skipped, never fatal.
def convert_skills_to_sms(run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]],
                          *, skills: Optional[List[str]] = None,
                          limit: Optional[int] = None) -> Dict[str, Any]:
    """Batch `skill_to_sm` over `skills` (explicit names) or over `IS_A Skill` concepts capped by `limit`.
    Neither given => converts nothing (safe default). Idempotent. Returns {"converted": [sm_ids], "count"}.
    """
    targets = list(skills) if skills else []
    if not targets and limit:
        rows = run(f"MATCH (s:Wiki)-[:IS_A]->(:Wiki {{n: 'Skill'}}) RETURN s.n AS n ORDER BY s.n LIMIT $lim",
                   {"lim": int(limit)})
        targets = [r.get("n") for r in rows if r.get("n")]
    converted: List[str] = []
    for name in targets:
        try:
            converted.append(skill_to_sm(name, run)["sm_id"])
        except Exception as e:
            logger.error(f"convert_skills_to_sms: skill_to_sm({name}) failed (skipped): {e}", exc_info=True)
    return {"converted": converted, "count": len(converted)}


# --- The graph->system-prompt GENERATOR (build-plan item 2: emit the system prompt FROM the graph) ----
# Isaac 2026-06-20 (Claude_P_And_Build_Plan): claude -p / the Agent SDK CONTROLS the system prompt, so the
# system prompt is REBUILT FROM CARTON between turns. "globally-available SMs go in the system prompt
# exactly like skills now BUT listed FROM THE GRAPH." This generator assembles the prompt from graph reads:
# the HEADLINE = the globally-available SM listing; plus the active identity's PERSONA FRAME (its role /
# system-prompt text), the actor's current location SM, and the WORK/DEV-mode region.
# (NAMING: scientific / agent-engineering terms only — "persona frame" = the persona's role text, "actor" =
# the acting agent/identity. We do NOT carry CCC's narrative vocabulary [Ghost/Shell/Cybernet/Jani] into
# the contract; the port mirrors CCC's FUNCTIONALITY under research-field names, per Isaac 2026-06-20.)
# PURITY / WHERE THE PERSONA FRAME LIVES: the persona frame lives in skill-manager's persona store as
# Persona.frame, NOT carton (verified 2026-06-20: zero frame-carrier nodes). So the generator takes it as
# an INJECTED param — the equip path (PersonaManager.activate_persona) already holds persona.frame and is
# the natural caller. Frame-in-carton is a DEFERRED carton-architecture decision (reserved for Isaac), NOT
# guessed here. Everything else IS read from the graph.
# SAFETY: v0 is PURE + READ-ONLY (injected run; never writes; never installs the prompt — the host-side
# claude -p launch inside SANCREV OPERA is the separate deferred step, exactly as the gate/Sm_Chain were staged
# read-first then wired). FAILS SOFT: a missing section degrades to a short marker, never an exception.

def list_globally_available_sms(run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]
                                ) -> List[Dict[str, Any]]:
    """The globally-available SMs = the skill->SM nodes (a State_Machine reachable from a backing concept
    via HAS_SM_CHAIN->SM_CHAIN_RUNS, i.e. what `skill_to_sm` builds), each with its backing skill's when/what as the
    trigger line. Listed FROM THE GRAPH so the system prompt advertises them exactly like skills are
    advertised now (Claude_P_And_Build_Plan). Returns an ordered list of {sm_id, skill, trigger}. Excludes
    incidental `IS_A State_Machine` nodes that have no backing Sm_Chain (e.g. legacy Omnisanc_* SMs)."""
    return run(f"""
        MATCH (sk:Wiki)-[:{R_HAS_SM_CHAIN}]->(:Wiki)-[:{R_SM_CHAIN_RUNS}]->(sm:Wiki)-[:IS_A]->(:Wiki {{n: '{T_STATE_MACHINE}'}})
        RETURN sm.n AS sm_id, sk.n AS skill,
               coalesce(sk.has_when, sk.has_what, substring(coalesce(sk.d, ''), 0, 160)) AS trigger
        ORDER BY sk.n ASC
    """, {})


def _execution_region(actor: str, run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]]
                      ) -> Optional[str]:
    """The region the actor's Execution_State currently points at (Claude_P_And_Build_Plan: WORK/DEV
    switching re-points Execution_State.region). None if unset (=> default WORK in the generator)."""
    rows = run(f"""
        MATCH (a:Wiki {{n: $actor}})-[:{R_HAS_LIFECYCLE}]->(s:Wiki)-[:IS_A]->(:Wiki {{n: '{T_EXECUTION_STATE}'}})
        RETURN s.region AS region LIMIT 1
    """, {"actor": actor})
    return (rows[0].get("region") if rows else None) or None


def generate_system_prompt(actor: str,
                           run: Callable[[str, Dict[str, Any]], List[Dict[str, Any]]],
                           *, persona_frame: Optional[str] = None,
                           mode: Optional[str] = None,
                           region: Optional[str] = None,
                           max_sms: Optional[int] = None) -> Dict[str, Any]:
    """Assemble the GNOSYS system prompt FROM the graph for `actor` (build-plan item 2).

    Sections (breadth-complete, coarse-to-fine / SOT):
      (1) PERSONA — the injected `persona_frame` (the persona's role / system-prompt text = skill-manager
          Persona.frame) if given; else the active identity name + its Identity_Collection pointer.
          (Frame-in-carton is deferred; the equip path supplies the frame.)
      (2) GLOBALLY-AVAILABLE SMs — the skill->SM nodes, listed FROM THE GRAPH (the headline capability).
      (3) CURRENT-LOCATION SM — where `actor`'s Execution_State is locked (the active step + its required
          next move), or "(not in any flow)".
      (4) WORK/DEV MODE — the region the Execution_State points at: DEV (region == self / the AIOS) vs WORK
          (region == an external domain). `mode`/`region` params override the graph read.

    PURE + READ-ONLY: injected `run`; never writes; never installs the prompt (host-side claude -p deferred).
    Returns {"prompt": <text>, "sections": {...}, "identity": <name>, "mode": <work|dev>}.
    FAILS SOFT — any section that errors degrades to a short marker; the function never raises.
    """
    def _safe(fn, default):
        try:
            return fn()
        except Exception as e:
            logger.error(f"generate_system_prompt section fault (soft-degrade): {e}", exc_info=True)
            return default

    identity = actor or get_active_identity() or "Gnosys"

    # (1) PERSONA (the persona's role / system-prompt frame)
    if persona_frame:
        persona_block = persona_frame.strip()
    else:
        coll = _safe(lambda: run(
            f"MATCH (c:Wiki)-[:IS_A]->(:Wiki {{n: 'Identity_Collection'}}) "
            f"WHERE toLower(c.n) CONTAINS toLower($id) RETURN c.n AS coll LIMIT 1", {"id": identity}), [])
        coll_name = coll[0]["coll"] if coll else None
        persona_block = (f"You are {identity}." + (
            f" Your identity collection is {coll_name} "
            f"(get_concept it for your owned-concepts set)." if coll_name else
            " (No persona frame was supplied and none is stored in carton — equip a persona to set it.)"))

    # (2) GLOBALLY-AVAILABLE SMs (the headline — listed FROM THE GRAPH)
    sms = _safe(lambda: list_globally_available_sms(run), [])
    if max_sms is not None:
        sms = sms[:max_sms]
    if sms:
        sm_lines = "\n".join(
            f"  - {s.get('sm_id')}  (visit {s.get('skill')} — {s.get('trigger') or 'no trigger text'})"
            for s in sms)
        sm_block = (f"GLOBALLY-AVAILABLE STATE MACHINES ({len(sms)}, from the graph). Visiting the backing "
                    f"concept activates the SM:\n{sm_lines}")
    else:
        sm_block = ("GLOBALLY-AVAILABLE STATE MACHINES (0). None programmed yet — run the skill->SM "
                    "converter over the skills to populate this listing from the graph.")

    # (3) CURRENT-LOCATION SM
    active = _safe(lambda: get_active_step(identity, run), None)
    if active:
        req = active.get("required_pattern")
        loc_block = (f"CURRENT LOCATION: locked at step '{active.get('id')}'. "
                     + (f"Your NEXT move is REQUIRED to match: {req}"
                        f" — {active.get('text') or ''}".rstrip()
                        if req else "No required pattern at this step (free move)."))
    else:
        loc_block = "CURRENT LOCATION: not in any flow (free to act / no SM is gating your next move)."

    # (4) WORK/DEV MODE
    eff_region = region or _safe(lambda: _execution_region(identity, run), None)
    if mode:
        eff_mode = mode.strip().lower()
    elif eff_region:
        eff_mode = "dev" if eff_region.strip().lower() in ("self", identity.lower(), "aios") else "work"
    else:
        eff_mode = "work"
    mode_block = (f"MODE: {eff_mode.upper()} — "
                  + ("developing the AIOS itself (region = self)." if eff_mode == "dev"
                     else f"working an external domain (region = {eff_region or 'unset'})."))

    prompt = "\n\n".join([persona_block, sm_block, loc_block, mode_block])
    return {"prompt": prompt,
            "sections": {"persona": persona_block, "sms": sm_block,
                         "location": loc_block, "mode": mode_block},
            "identity": identity, "mode": eff_mode}
