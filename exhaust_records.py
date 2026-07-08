"""exhaust_records — the CANONICAL Pydantic shapes of carton's P0 exhaust-ledger records.

The three P0 exhaust patches (Griess-Neural-Surrogate, 2026-07-06) append JSONL records:
  - soma_rejections.jsonl   (add_concept_tool.record_soma_rejection — oracle-labeled hard negatives)
  - sm_episodes.jsonl       (sm_gate._record_sm_episode — SM-gate trajectory events, CCC's bandit_choices)
  - soma_fired_chains.jsonl (add_concept_tool's fired_chains= verdict parse — Chain_Prioritizer substrate)

These models DECLARE those record shapes as code, and are what gnosys-vault vault()s into SOMA
(gnosys_vault/carton_exhaust.py) so the exhaust record types are DEFINED system types — per the
vault keystone, the code is the ONLY type source. The ledger writers themselves stay plain
best-effort dict appends (a pydantic import in the hot gate path buys nothing); the coherence
between writer dicts and these models is pinned by tests/test_p0_exhaust_ledgers.py's shape
assertions — if a writer gains/renames a key, update the model in the same change.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SomaRejectionRecord(BaseModel):
    """One oracle-labeled hard negative: a claim-structure SOMA's verdict rejected/flagged.

    verdict_kind: 'contradiction' (Type-2 geometric reject — carton never saved the node) or
    'mereo_error' (Type-1 undefined-is_a fill signal — saved as soup, still a negative example
    of a well-formed claim). The training gold Slot_Fill_Ranker consumes.
    """
    concept: str
    relationships: List[Dict[str, Any]]
    verdict_kind: str
    timestamp: str
    reason: str = ""


class SmEpisodeRecord(BaseModel):
    """One SM-gate trajectory event (the CCC bandit_choices analogue).

    event names the trajectory-event kind: lock / lock_trigger / branch_chosen /
    advance_explicit / terminal_unlock / refusal_no_branch / refusal_pattern. branch_chosen
    carries the full decision context (candidates with pattern+weight, the call text, the
    pick, the reinforcement applied) — the Policy_Network_Sm_Selector training substrate.
    """
    event: str
    timestamp: str
    actor: Optional[str] = None
    state_id: Optional[str] = None
    curr_step: Optional[str] = None
    chosen: Optional[str] = None
    candidates: Optional[List[Dict[str, Any]]] = None
    call_text: Optional[str] = None
    required_pattern: Optional[str] = None
    reinforce_delta: Optional[float] = None
    concept: Optional[str] = None
    sm_id: Optional[str] = None
    entry_step: Optional[str] = None


class FiredChainsRecord(BaseModel):
    """One event's fired-deduction-chain names (from SOMA's fired_chains= verdict block).

    WHICH chains fired for the event that validated `concept`, not just a count — the
    Chain_Prioritizer training substrate. status carries the concept's own verdict level
    when known (soup/code/mereo_error/...).
    """
    concept: str
    fired_chains: List[str]
    timestamp: str
    status: Optional[str] = None
