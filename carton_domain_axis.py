"""The domain axis at the CartON front door (card 726 condition 6, issue 1009).

Every domain and subdomain a write names is a domain node: is_a Domain (or, for Health, Wealth, Social and Spiritual,
is_a Hwss_Domain), carrying has_about, part_of a domain node that roots into one of the four. A name that is not yet a
domain node is written as one before the concept lands, from the params the writer supplies: its about, and for a
domain its parent. Nothing is refused. Isaac 2026-09-29: "THERE IS NO WAY TO ENTER SOMETHING INTO CARTON AND HAVE IT
FAIL ON THE BASIS OF MEANING. IT FUCKING INGESTS EVERYTHING", so a name written without its params lands as said and
SOMA grades it: "the missing param IS THE FUCKING REJECTION".
"""
import logging

logger = logging.getLogger(__name__)

DOMAIN_TYPES = ("Domain", "Hwss_Domain")


def axis_targets(relationships):
    """PURE: the domain and subdomain names a relationship list states, each in first-seen order.

    Args:
        relationships: The add_concept relationship list; ``related`` items are names or ``{"value": name}`` dicts.

    Returns:
        ``(domains, subdomains)``.
    """
    found = {"has_domain": [], "has_subdomain": []}
    for rel in relationships or []:
        key = str(rel.get("relationship", "")).lower()
        if key not in found:
            continue
        related = rel.get("related")
        for t in related if isinstance(related, list) else [related]:
            name = t.get("value") if isinstance(t, dict) else t
            if isinstance(name, str) and name and name not in found[key]:
                found[key].append(name)
    return found["has_domain"], found["has_subdomain"]


def plan_domain_axis(domains, subdomains, is_domain_node, domain_about=None, domain_part_of=None,
                     subdomain_about=None, normalize=None):
    """PURE: the domain nodes a write lands first, from the params it supplies.

    Args:
        domains: The has_domain names of the write.
        subdomains: The has_subdomain names of the write.
        is_domain_node: Callable answering whether a name is already a domain node.
        domain_about: What the one new domain is about.
        domain_part_of: The domain node the new domain is part of.
        subdomain_about: What the one new subdomain is about; its parents are the write's domains.
        normalize: The writer's name normalizer.

    Returns:
        ``(writes, notes)``: writes is a list of ``(name, about, parents)`` to land in order; notes name each supplied
        param that landed nothing and why.
    """
    norm = normalize or (lambda n: n)
    writes, notes = [], []
    for axis, names, about, parents in (("domain", domains, domain_about, [domain_part_of] if domain_part_of else []),
                                        ("subdomain", subdomains, subdomain_about, list(domains))):
        about = (about or "").strip()
        if not about:
            if axis == "domain" and domain_part_of:
                notes.append("domain_part_of unused: it places the new domain named with domain_about, and none was")
            continue
        new = [n for n in names if not is_domain_node(norm(n))]
        if len(new) == 1:
            writes.append((new[0], about, parents))
        elif new:
            notes.append(f"{axis}_about names one new {axis}; this write names {len(new)} that are not domain "
                         f"nodes ({', '.join(new)}), so none was written as a domain node")
        else:
            notes.append(f"{axis}_about unused: every {axis} this write names is already a domain node")
    return writes, notes


def domain_axis_relationships(parents):
    """PURE: the relationships a landed domain node is written with: is_a Domain and part_of each parent."""
    rels = [{"relationship": "is_a", "related": ["Domain"]}]
    if parents:
        rels.append({"relationship": "part_of", "related": list(parents)})
    return rels


def land_domain_axis(relationships, write, read_domain_nodes, domain_about=None, domain_part_of=None,
                     subdomain_about=None, normalize=None):
    """Write first each domain node the plan names, and return the lines the concept's result carries about it.

    Args:
        relationships: The write's relationship list.
        write: ``write(name, about, relationships) -> str``, the add_concept result of landing one domain node.
        read_domain_nodes: ``read(names) -> set`` of the names that are domain nodes.
        domain_about: What the one new domain is about.
        domain_part_of: The domain node the new domain is part of.
        subdomain_about: What the one new subdomain is about.
        normalize: The writer's name normalizer.

    Returns:
        One ``DOMAIN AXIS:`` line per landed node and per unused param; empty when no param was supplied.
    """
    if not any((domain_about, domain_part_of, subdomain_about)):
        return []
    domains, subdomains = axis_targets(relationships)
    if not (domains or subdomains):
        return ["DOMAIN AXIS: domain params supplied, and this write names no domain or subdomain; nothing written"]
    norm = normalize or (lambda n: n)
    try:
        known = read_domain_nodes({norm(n) for n in domains + subdomains})
    except Exception as e:
        logger.warning(f"domain axis read failed: {e}", exc_info=True)
        return [f"DOMAIN AXIS: the domain node read failed ({e}); nothing was written first"]
    writes, notes = plan_domain_axis(domains, subdomains, lambda n: n in known, domain_about, domain_part_of,
                                     subdomain_about, norm)
    lines = []
    for name, about, parents in writes:
        result = write(name, about, domain_axis_relationships(parents)) or ""
        head = [ln for ln in result.splitlines() if ln.strip()][:1]
        grade = [ln for ln in result.splitlines() if ln.startswith("SOMA:")][:1]
        placed = f" part_of {', '.join(parents)}" if parents else ""
        lines.append(f"DOMAIN AXIS: {name} written first as is_a Domain{placed} with has_about: "
                     + " ".join(head + grade))
    return lines + [f"DOMAIN AXIS: {n}" for n in notes]


def domain_node_reader(shared_connection=None):
    """A callable answering which names are domain nodes, from ONE CartON read per name set.

    Returns:
        ``read(names) -> set`` of the names that exist and are is_a Domain or is_a Hwss_Domain; a failed read raises.
    """
    def read(names):
        from carton_mcp import carton_utils
        res = carton_utils.CartOnUtils(shared_connection=shared_connection).query_wiki_graph(
            "MATCH (d:Wiki)-[:IS_A]->(t:Wiki) WHERE d.n IN $names AND t.n IN $types RETURN DISTINCT d.n AS n",
            {"names": list(names), "types": list(DOMAIN_TYPES)})
        if not (isinstance(res, dict) and res.get("success")):
            raise RuntimeError(f"domain axis read failed: {res}")
        return {row["n"] for row in res.get("data") or []}
    return read
