"""Merged labels at the CartON front door (issue 1009).

A label merged into another no longer exists: the label it was merged into records it in ``merged_from``.
``add_concept_tool_func`` writes the right label in place of every merged label it is handed, as the
concept written and as every relationship target, so no writer re-mints a merged label as an auto stub.
"""
import logging
import time

logger = logging.getLogger(__name__)

MAP_TTL_S = 60
_CACHE = {"at": 0.0, "map": None}


def redirect_merged(concept_name, relationships, merged, normalize=None):
    """PURE: the write with each merged label replaced by the label it was merged into.

    Args:
        concept_name: The concept being written.
        relationships: The add_concept relationship list; each ``related`` item is a name or a
            ``{"value": name, ...}`` dict.
        merged: Each merged label, lowercased, mapped to the label it was merged into.
        normalize: The writer's name normalizer, so a spelling the writer would land on the merged
            label is caught too.

    Returns:
        ``(concept_name, relationships, redirects)``, redirects listing each ``(merged, right)`` applied.
    """
    redirects = []

    def sub(name):
        if not isinstance(name, str) or not merged:
            return name
        right = merged.get(name.lower()) or (normalize and merged.get(normalize(name).lower()))
        if right and right != name:
            redirects.append((name, right))
            return right
        return name

    new_name = sub(concept_name)
    new_rels = []
    for rel in relationships or []:
        related = rel.get("related")
        items = related if isinstance(related, list) else [related]
        subbed = [{**t, "value": sub(t.get("value"))} if isinstance(t, dict) else sub(t) for t in items]
        new_rels.append({**rel, "related": subbed if isinstance(related, list) else subbed[0]})
    return new_name, new_rels, redirects


HWSS_ROOTS = ("Health", "Wealth", "Social", "Spiritual")


def confine_hwss_domain(concept_name, relationships, normalize=None):
    """PURE: a write that says a concept other than the four roots is_a Hwss_Domain says it is_a Domain.

    Isaac 2026-09-29: "ONLY FOUR NODES CAN BE ISA HWSS_DOMAIN ... EVERY DOMAIN THAT IS NOT ISA HWSS DOMAIN
    MUST FUCKING BE PART OF ANOTHER DOMAIN THAT EVENTUALLY IS AN HWSS DOMAIN, ITSELF."

    Args:
        concept_name: The concept being written.
        relationships: The add_concept relationship list, as redirect_merged returns it.
        normalize: The writer's name normalizer.

    Returns:
        ``(relationships, confined)``, confined True when an is_a Hwss_Domain became is_a Domain.
    """
    norm = normalize or (lambda n: n)

    def key(name):
        return norm(name).lower() if isinstance(name, str) else None

    if key(concept_name) in {r.lower() for r in HWSS_ROOTS}:
        return relationships, False
    confined = False
    out = []
    for rel in relationships or []:
        if str(rel.get("relationship", "")).lower() != "is_a":
            out.append(rel)
            continue
        related = rel.get("related")
        items = related if isinstance(related, list) else [related]
        kept = []
        for t in items:
            name = t.get("value") if isinstance(t, dict) else t
            if key(name) == "hwss_domain":
                confined = True
                t = {**t, "value": "Domain"} if isinstance(t, dict) else "Domain"
            if (t.get("value") if isinstance(t, dict) else t) not in [
                    (k.get("value") if isinstance(k, dict) else k) for k in kept]:
                kept.append(t)
        out.append({**rel, "related": kept if isinstance(related, list) else kept[0]})
    return out, confined


def merged_label_map(shared_connection=None, now=None):
    """Every merged label, lowercased, mapped to the label it was merged into, read from CartON.

    Cached for MAP_TTL_S seconds. A failed read answers the last map read, or ``None`` when none has
    been read yet.
    """
    now = time.time() if now is None else now
    if _CACHE["map"] is not None and now - _CACHE["at"] < MAP_TTL_S:
        return _CACHE["map"]
    from carton_mcp import carton_utils
    res = carton_utils.CartOnUtils(shared_connection=shared_connection).query_wiki_graph(
        "MATCH (r:Wiki) WHERE r.merged_from IS NOT NULL UNWIND r.merged_from AS left RETURN left, r.n AS right")
    if not (isinstance(res, dict) and res.get("success")):
        logger.warning("merged_label_map: CartON read failed, answering the last map read")
        return _CACHE["map"]
    _CACHE["map"] = {str(row["left"]).lower(): row["right"] for row in res.get("data") or []}
    _CACHE["at"] = now
    return _CACHE["map"]
