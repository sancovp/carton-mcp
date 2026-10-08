"""The webbing agent's write guard at the CartON front door (card 703, issue 1009).

A system type is code: its shape comes from its declaration with params, through vault or the
declare-a-soma-type skill. The webbing agent adds structure to prose it was served and mints new child
concepts; it never writes onto a declared system type and never declares one. A merged label no longer
exists: the label it was merged into records it in ``merged_from``, and the webbing agent neither writes
the merged label nor names it as an is_a or instantiates target.
"""
import re

WEBBING_SOURCE = "webbing_agent"
_SYSTEM_TYPE_KEY = "systemtype"
_TYPE_RELS = ("is_a", "instantiates")
CARTON_UNREADABLE = "carton_unreadable"


def _key(name) -> str:
    return re.sub(r"[\s_\-]+", "", str(name)).lower()


def declares_system_type(relationships) -> bool:
    """True when the relationships carry ``is_a System_Type`` in any spelling."""
    for rel in relationships or []:
        if str(rel.get("relationship", "")).lower() != "is_a":
            continue
        related = rel.get("related") or []
        related = related if isinstance(related, list) else [related]
        if any(_key(t.get("value", t) if isinstance(t, dict) else t) == _SYSTEM_TYPE_KEY for t in related):
            return True
    return False


def named_labels(concept_name, relationships) -> list:
    """The concept name and every is_a or instantiates target the write names."""
    names = [str(concept_name)]
    for rel in relationships or []:
        if str(rel.get("relationship", "")).lower() not in _TYPE_RELS:
            continue
        related = rel.get("related") or []
        for t in related if isinstance(related, list) else [related]:
            names.append(str(t.get("value", t) if isinstance(t, dict) else t))
    return names


def webbing_write_refusal(source: str, concept_name: str, relationships, is_declared_system_type: bool,
                          merged_into=None) -> str:
    """The refusal a webbing-agent write gets, or an empty string when the write may proceed.

    Args:
        source: The add_concept source; only ``webbing_agent`` is ever refused here.
        concept_name: The concept being written.
        relationships: The add_concept relationship list.
        is_declared_system_type: Whether CartON already holds ``concept_name`` IS_A System_Type.
        merged_into: Each merged label the write names, lowercased, mapped to the label it was merged
            into; ``CARTON_UNREADABLE`` when CartON could not be read; ``None`` when none is named.

    Returns:
        A refusal message naming the concept and the rule, or ``""``.
    """
    if source != WEBBING_SOURCE:
        return ""
    if is_declared_system_type:
        return (f"❌ REFUSED (not written): {concept_name} is a declared system type. A system type is code: its "
                f"shape comes from its declaration with params, so the webbing agent never writes onto one. "
                f"Leave it as it is and continue with the concepts you were served.")
    if declares_system_type(relationships):
        return (f"❌ REFUSED (not written): the webbing agent may not declare {concept_name} is_a System_Type. "
                f"A system type is declared with params through vault or the declare-a-soma-type skill. Write "
                f"{concept_name} without is_a System_Type.")
    if merged_into == CARTON_UNREADABLE:
        return (f"❌ REFUSED (not written): CartON could not be read to check {concept_name} and its is_a and "
                f"instantiates targets against the merged labels. Retry the write.")
    for name in named_labels(concept_name, relationships):
        right = (merged_into or {}).get(name.lower())
        if right:
            return (f"❌ REFUSED (not written): the label {name} was merged into {right} and no longer exists. "
                    f"Write {right} in its place.")
    return ""


def is_declared_system_type(concept_name: str, shared_connection=None) -> bool:
    """Whether CartON holds ``concept_name``, as passed or as the writer normalizes it, IS_A System_Type.

    The write lands on the normalized name, so a case variant of a declared type is that type. A failed
    read answers True, so the webber is refused.
    """
    from carton_mcp import carton_utils
    from carton_mcp.add_concept_tool import normalize_concept_name
    names = sorted({concept_name, normalize_concept_name(concept_name)})
    res = carton_utils.CartOnUtils(shared_connection=shared_connection).query_wiki_graph(
        "MATCH (c:Wiki)-[:IS_A]->(:Wiki {n: 'System_Type'}) WHERE c.n IN $names RETURN count(c) > 0 AS declared",
        {"names": names})
    if not (isinstance(res, dict) and res.get("success")):
        return True
    rows = res.get("data") or []
    return bool(rows and rows[0].get("declared"))


def merged_labels_named(concept_name: str, relationships, shared_connection=None):
    """The merged labels the write names, lowercased, each mapped to the label it was merged into.

    Reads the merged-label map carton_merged_labels keeps from ``merged_from``, matching each named label
    as passed and as normalize_concept_name writes it. A map never read answers ``CARTON_UNREADABLE``, so
    the webber is refused.
    """
    from carton_mcp.add_concept_tool import normalize_concept_name
    from carton_mcp.carton_merged_labels import merged_label_map
    merged = merged_label_map(shared_connection)
    if merged is None:
        return CARTON_UNREADABLE
    named = {}
    for n in named_labels(concept_name, relationships):
        right = merged.get(n.lower()) or merged.get(normalize_concept_name(n).lower())
        if right:
            named[n.lower()] = right
    return named
