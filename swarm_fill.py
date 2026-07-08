"""swarm_fill — the emergent placement filler (2026-07-07, Isaac's ruling).

⚠️ PLACEMENT IS PROVISIONAL + THE WHOLE ARC IS TABLED (Isaac, 2026-07-07).
This module sits in carton-mcp ONLY because add_concept_tool_func is Python-import-only
(no HTTP surface), which forces the lifter to be Python-next-to-carton. carton is the
SUBSTRATE here, not the owner. The DECIDED-but-TABLED clean home: give carton add_concept
a thin HTTP endpoint (= the carton-SaaS build) so the swarm can live in CB (swarm-agent.ts)
doing two HTTP calls (brain /fill → carton add_concept) with NO python-import coupling.
Isaac tabled that because it is a real build with real per-model-call cost, and there is
an easier CB-fill route (minimax ralphs with carton inspecting everything). DO NOT treat
carton-mcp as this module's settled home; resume when the carton SaaS / HTTP add_concept
endpoint is built. See the swarm-fill journal.


THE POINT (Isaac, verbatim): "why wouldnt we have 200 siblings that are redundant?
the point would be to PUT THEM IN THE RIGHT PLACE SOMEHOW ... IF YOU SAY SOMETHING BAD,
IT GOES TO THE PLACE WHERE YOU SAID BAD THINGS. that is EMERGENT."

So this does NOT filter, dedup, or gate. It generates candidates for a slot and calls
carton `add_concept` on EVERY one — the placement IS the sorting:
  - a valid candidate lands at its CB coordinate (its address = what it is; redundant
    siblings co-locate, and that co-location is the emergent signal);
  - a mereo_error (own is_a undefined) is saved as SOUP (the not-quite-right place);
  - a contradiction is rejected by carton and recorded in the Rejection_Ledger
    (soma_rejections.jsonl) — literally "the place where you said bad things".
Nothing is thrown away. The geometry self-organizes by where things land.

Each candidate's CORE SENTENCE is what derives its address: the label `is_a` the slot
(the dimension it fills) and `part_of` the kernel (the space it belongs to). carton's
add_concept validates via SOMA and fans to CB (`_cb_place` → /api/cb/store), returning
the verdict + coordinate — so we call it and WAIT for each return (this is a background
process; nothing blocks on it except when a caller explicitly needs the placements).

Generation transport: brain-agent POST /fill (base/brain-agent, the flat sibling-filler
returning {label, rationale, confidence 0-10}). add_concept transport: direct import of
add_concept_tool_func (this module lives in carton-mcp beside it — no subprocess).
"""

import json
import logging
import os
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BRAIN_URL = os.environ.get("HBRAIN_URL", "http://127.0.0.1:8177")


# ---------------------------------------------------------------------------
# Generation: brain-agent /fill (the flat sibling-filler)
# ---------------------------------------------------------------------------

def fill_slot_via_brain(
    slot_label: str,
    parent_label: Optional[str] = None,
    siblings: Optional[List[str]] = None,
    space_context: Optional[str] = None,
    n: int = 12,
    brain_url: Optional[str] = None,
    timeout: int = 300,
) -> List[Dict[str, Any]]:
    """POST /fill and return the raw candidates [{label, rationale, confidence}].

    NO FALLBACKS: a non-2xx status or a malformed body raises loudly (never a
    fabricated candidate). An empty candidate list is a valid answer, not an error.
    """
    url = (brain_url or BRAIN_URL).rstrip("/") + "/fill"
    body = {"slot_label": slot_label, "n": n}
    if parent_label is not None:
        body["parent_label"] = parent_label
    if siblings is not None:
        body["siblings"] = siblings
    if space_context is not None:
        body["space_context"] = space_context
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
    data = json.loads(raw)
    cands = data.get("candidates")
    if not isinstance(cands, list):
        raise RuntimeError(f"brain /fill returned no candidates array: {raw[:300]}")
    out: List[Dict[str, Any]] = []
    for c in cands:
        if not isinstance(c, dict) or not str(c.get("label", "")).strip():
            continue
        out.append({
            "label": str(c["label"]).strip(),
            "rationale": str(c.get("rationale", "")),
            "confidence": c.get("confidence", 0),
        })
    logger.info("swarm_fill: brain /fill '%s' -> %d candidates", slot_label, len(out))
    return out


# ---------------------------------------------------------------------------
# Placement: add_concept EVERY candidate (emergent — no filter, no dedup)
# ---------------------------------------------------------------------------

def _candidate_relationships(slot_label: str, kernel_name: Optional[str]) -> List[Dict[str, Any]]:
    """The candidate's CORE SENTENCE = what derives its address: it IS_A the slot
    (the dimension it fills) and PART_OF the kernel (the space it belongs to)."""
    rels: List[Dict[str, Any]] = [{"relationship": "is_a", "related": [slot_label]}]
    if kernel_name:
        rels.append({"relationship": "part_of", "related": [kernel_name]})
    return rels


def swarm_fill_and_place(
    slot_label: str,
    kernel_name: Optional[str] = None,
    parent_label: Optional[str] = None,
    siblings: Optional[List[str]] = None,
    space_context: Optional[str] = None,
    n: int = 12,
    source: str = "swarm_fill",
    brain_url: Optional[str] = None,
    shared_connection: Any = None,
    _add_concept: Any = None,
) -> Dict[str, Any]:
    """Fill a slot's spectrum and PLACE every candidate via carton add_concept.

    For each candidate (NO filter, NO dedup — redundancy co-locates, bad output
    routes to soup / the Rejection_Ledger), call add_concept_tool_func with the
    candidate's core sentence and WAIT for its return (SOMA verdict + CB placement).
    Returns {slot, kernel, n_candidates, placements:[{label, confidence, result}]}.

    `_add_concept` is injectable for tests; default is the real add_concept_tool_func.
    """
    if _add_concept is None:
        from carton_mcp.add_concept_tool import add_concept_tool_func as _add_concept

    candidates = fill_slot_via_brain(
        slot_label, parent_label=parent_label, siblings=siblings,
        space_context=space_context, n=n, brain_url=brain_url)

    placements: List[Dict[str, Any]] = []
    rels = _candidate_relationships(slot_label, kernel_name)
    for c in candidates:
        # add_concept EVERY candidate — await each return (verdict + placement).
        # A failure to place one candidate must not abort the rest of the fill.
        try:
            result = _add_concept(
                c["label"],
                description="",
                relationships=rels,
                source=source,
                shared_connection=shared_connection,
            )
        except Exception as e:  # noqa: BLE001 — one bad placement never kills the fill
            logger.error("swarm_fill: add_concept('%s') failed (non-fatal): %s",
                         c["label"], e, exc_info=True)
            result = f"ERROR: {e}"
        placements.append({
            "label": c["label"],
            "confidence": c["confidence"],
            "rationale": c["rationale"],
            "result": result,
        })

    logger.info("swarm_fill: placed %d/%d candidates for slot '%s'",
                len(placements), len(candidates), slot_label)
    return {
        "slot": slot_label,
        "kernel": kernel_name,
        "n_candidates": len(candidates),
        "placements": placements,
    }


if __name__ == "__main__":  # tiny CLI for the bg process / smoke runs
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="swarm_fill: brain /fill -> add_concept every candidate")
    ap.add_argument("slot_label")
    ap.add_argument("--kernel")
    ap.add_argument("--parent")
    ap.add_argument("--siblings", nargs="*", default=[])
    ap.add_argument("--context")
    ap.add_argument("-n", type=int, default=12)
    ap.add_argument("--source", default="swarm_fill")
    args = ap.parse_args()
    out = swarm_fill_and_place(
        args.slot_label, kernel_name=args.kernel, parent_label=args.parent,
        siblings=args.siblings, space_context=args.context, n=args.n, source=args.source)
    print(json.dumps({"slot": out["slot"], "kernel": out["kernel"],
                      "n_candidates": out["n_candidates"],
                      "placements": [{"label": p["label"], "result": str(p["result"])[:200]}
                                     for p in out["placements"]]}, indent=2))
