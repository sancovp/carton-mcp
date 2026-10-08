"""
carton_bounded_walk — the bounded collection-activation walk (GitHub issue #203; onion arch,
one-capability-one-module, matching the `carton_split_content.py` precedent).

THE PROBLEM (issue #203, recorded 2026-08-26 journal 17:14:33): `activate_collection` drives
`CartOnUtils.get_collection_concepts`, whose Cypher walked `HAS_PART*1..10` with NO stop logic —
and its `max_depth` param was DEAD (accepted, logged, never interpolated). Any member that is
itself a hub (an axis node, a big collection, an untyped TAG node that owns its entries) imported
its ENTIRE subtree into context. The writer-side law in `docmirror-collect` (leaf-ish membership,
no member typed collection/axis, no member with a `HAS_PART*1..4` subtree over 30) was the only
defense; the primitive belongs READ-side so that law becomes defense-in-depth.

THE RULINGS (cold-test comment on issue #203 — binding for this module):
- ONE Cypher execution (G8): no N+1 on a 640k-node graph. This module is the PURE half — the
  plan-builder (`build_walk_plan`) and the row-classifier (`classify_rows` /
  `build_activation_result`), both stdlib-only, no neo4j, no I/O, unit-tested on synthetic rows
  (test_carton_bounded_walk.py). The Cypher executor stays thin in `carton_utils.py`.
- BOUNDARY = type-list UNION hub-cap (G6): the type-list is docmirror-collect's read-side list
  (DEFAULT_BOUNDARY_TYPES below); the hub-cap (`HAS_PART*1..4` path count > 30, write-side
  parity) is MANDATORY because untyped hub TAG nodes — the issue's own headline case — carry
  none of the boundary types; only the cap stops them.
- THE CAP IS SCOPED TO UNTYPED MEMBERS (reconciling G6 with G4): G4 requires the DMN
  conversation-ladder shapes (`activate_collection` on a `Conversation_<ts>` and on a
  `Raw_Conversation_Timeline_<date>`) to return their FULL ladders unchanged — and a live
  `Conversation_<ts>` measured `HAS_PART*1..4` count 807 (2026-08-28, read-only probe), so a cap
  applied to typed members would clip every ladder. G4 rules "if a ladder intermediate trips the
  boundary, the BOUNDARY LIST is wrong, not the ladder" — and G6's stated reason for the cap is
  the UNTYPED hub. So: a member with any outgoing IS_A or INSTANTIATES edge is stopped only by
  the type-list; a member with NEITHER (a tag node) is stopped by the cap. Both knobs stay
  tunable via args (G9): `max_depth` (default 1: the collection's own members only, Isaac
  2026-09-29; a ladder returns whole when the caller passes the depth it needs), `hub_cap`
  (default 30), `boundary_types`.
- INCLUDE-BUT-DO-NOT-DESCEND (G7): a boundary member appears in `concepts` as a leaf AND in the
  `stopped` report with its reason. The Cypher never traverses THROUGH a boundary node
  (`ALL(x IN nodes(path)[1..-1] ...)` — the terminal member itself is never filtered).
- NO SILENT CAPS (G2, binding though not a rule file): EVERY truncation — type-boundary,
  hub-cap, depth — is reported in the return.
- THE REPORT LEADS THE PAYLOAD (G10): `_fmt` in server_fastmcp.py truncates at 10k chars and
  drops empty/None fields. `build_activation_result` therefore inserts `truncation_report` (a
  compact string) and `stopped` (structured) BEFORE `concepts` in the dict, and uses non-empty
  shapes only when non-zero: zero stops => truncation_report=None and stopped=[], which `_fmt`
  drops — making the zero-stop rendering byte-identical to the pre-#203 output (the G4
  byte-compat requirement).

IS-vs-VISION: everything in this file is CODE and pure (stdlib only). The thin executor
(`CartOnUtils.get_collection_concepts`) and the MCP tool (`activate_collection`) are verified
against the live surface by the integrator's live-test script
(live_test_bounded_activation.sh, written per issue #203, deliverable 3), not unit tests.
"""
from typing import Dict, List, Optional

# docmirror-collect's read-side boundary list (doc-mirror-system/plugin/bin/docmirror-collect,
# Q_INBOUND/Q_WEB — the write-side law this primitive mirrors). A member whose direct IS_A hits any
# of these is a boundary: included, never descended. Domain is the type of every domain node, the
# journal's domain and subdomain axis nodes included; Hwss_Domain is the type of the four roots,
# Health, Wealth, Social and Spiritual (card 726).
DEFAULT_BOUNDARY_TYPES: List[str] = [
    "Carton_Collection",
    "Local_Collection",
    "Identity_Collection",
    "Global_Collection",
    "Hypercluster",
    "Doc_Mirror_Repo",
    "Hwss_Domain",
    "Domain",
]

DEFAULT_MAX_DEPTH = 1    # Isaac 2026-09-29: "only ever pull network 1 ie only the concepts IN the collection"
DEFAULT_HUB_CAP = 30     # write-side parity: docmirror-collect's `size([(m)-[:HAS_PART*1..4]->() | 1]) <= 30`
HUB_CAP_PROBE_DEPTH = 4  # the *1..4 in the subtree-size probe (write-side parity; fixed, not a knob)
_MAX_ALLOWED_DEPTH = 100  # sanity ceiling on the interpolated depth (depth is interpolated, so it is
                          # validated as a bounded int — never a string — before touching the query text)

# The chars the pre-#203 code used for a member with a NULL/empty description — preserved verbatim
# (byte-compat, G4).
MISSING_DESC = "[MISSING CONCEPT - NOT YET DEFINED]"


def build_walk_plan(
    collection_name: str,
    max_depth: int = DEFAULT_MAX_DEPTH,
    boundary_types: Optional[List[str]] = None,
    hub_cap: int = DEFAULT_HUB_CAP,
) -> Dict[str, object]:
    """PURE plan-builder: returns the ONE Cypher execution (G8) + its parameters. No I/O.

    The query walks `HAS_PART*1..{max_depth}` from the collection root and prunes every path
    whose INTERMEDIATE nodes include a boundary (type-list hit, or untyped hub over the cap) —
    the terminal member is never filtered, which is exactly include-but-do-not-descend (G7).
    Per distinct member it returns the row fields `classify_rows` needs to classify and report:
    boundary_type_hits, untyped, subtree_count, min_depth, has_children.

    `max_depth` is the ONLY interpolated value (Cypher cannot parameterize a var-length bound);
    it is validated as an int in [1, 100] here, so the interpolation is injection-safe. The
    collection name, type-list, and cap ride as parameters.

    Returns {"cypher": str, "parameters": dict, "max_depth": int, "hub_cap": int,
    "boundary_types": list}.  Raises ValueError on a bad depth/cap.
    """
    if not isinstance(max_depth, int) or isinstance(max_depth, bool):
        raise ValueError(f"max_depth must be an int, got {type(max_depth).__name__}")
    if not (1 <= max_depth <= _MAX_ALLOWED_DEPTH):
        raise ValueError(f"max_depth must be in [1, {_MAX_ALLOWED_DEPTH}], got {max_depth}")
    if not isinstance(hub_cap, int) or isinstance(hub_cap, bool) or hub_cap < 0:
        raise ValueError(f"hub_cap must be a non-negative int, got {hub_cap!r}")
    types = list(boundary_types) if boundary_types is not None else list(DEFAULT_BOUNDARY_TYPES)

    # One execution. Boundary predicate on INTERMEDIATES only (nodes(path)[1..-1]): a direct
    # member that is itself a boundary still arrives as a length-1 path (empty intermediate
    # list => ALL() is true) — included, not descended. Constructions (pattern comprehension,
    # EXISTS { MATCH ... }) mirror docmirror-collect's proven-on-this-server Cypher.
    cypher = f"""
    MATCH path = (collection:Wiki {{n: $collection_name}})-[:HAS_PART*1..{max_depth}]->(member:Wiki)
    WHERE ALL(x IN nodes(path)[1..-1] WHERE
          NOT EXISTS {{ MATCH (x)-[:IS_A]->(bt:Wiki) WHERE bt.n IN $boundary_types }}
          AND NOT ( NOT EXISTS {{ MATCH (x)-[:IS_A|INSTANTIATES]->(:Wiki) }}
                    AND size([(x)-[:HAS_PART*1..{HUB_CAP_PROBE_DEPTH}]->() | 1]) > $hub_cap ) )
    WITH member, min(length(path)) AS min_depth
    RETURN member.n AS name, member.d AS description,
           [(member)-[:IS_A]->(bt:Wiki) WHERE bt.n IN $boundary_types | bt.n] AS boundary_type_hits,
           NOT EXISTS {{ MATCH (member)-[:IS_A|INSTANTIATES]->(:Wiki) }} AS untyped,
           size([(member)-[:HAS_PART*1..{HUB_CAP_PROBE_DEPTH}]->() | 1]) AS subtree_count,
           min_depth AS min_depth,
           EXISTS {{ MATCH (member)-[:HAS_PART]->(:Wiki) }} AS has_children
    ORDER BY name
    """

    return {
        "cypher": cypher,
        "parameters": {
            "collection_name": collection_name,
            "boundary_types": types,
            "hub_cap": hub_cap,
        },
        "max_depth": max_depth,
        "hub_cap": hub_cap,
        "boundary_types": types,
    }


def classify_rows(
    rows: List[dict],
    max_depth: int = DEFAULT_MAX_DEPTH,
    hub_cap: int = DEFAULT_HUB_CAP,
) -> Dict[str, list]:
    """PURE row-classifier (G8): stdlib-only, over already-fetched rows. No I/O.

    Each row: {name, description, boundary_type_hits, untyped, subtree_count, min_depth,
    has_children} (the `build_walk_plan` RETURN shape). Produces:
      concepts — every member (boundary members included as leaves, G7), sorted by name,
                 each {"name", "description"} with the pre-#203 MISSING_DESC substitution.
      stopped  — [{"name", "reason"}] for every member the walk did not descend below,
                 with WHY (G2 no-silent-caps). Reason precedence: boundary_type > hub_cap
                 > depth. hub_cap applies ONLY to untyped members (see module docstring —
                 the G4/G6 reconciliation). depth applies when a non-boundary member sits
                 at max_depth with children below it.
      missing  — names of members with NULL/empty description (feeds the legacy warning).

    Defensive against the executor: duplicate names are deduped (first row wins, min_depth
    kept as the minimum seen) — a cycle in the graph cannot duplicate or loop here, mirroring
    Cypher's per-path relationship-uniqueness upstream.
    """
    by_name: Dict[str, dict] = {}
    for row in rows:
        name = row.get("name")
        if name is None:
            continue
        if name in by_name:
            prev = by_name[name]
            prev_d = prev.get("min_depth")
            cur_d = row.get("min_depth")
            if isinstance(cur_d, int) and (not isinstance(prev_d, int) or cur_d < prev_d):
                prev["min_depth"] = cur_d
            continue
        by_name[name] = dict(row)

    concepts: List[dict] = []
    stopped: List[dict] = []
    missing: List[str] = []

    for name in sorted(by_name):
        row = by_name[name]
        description = row.get("description")
        if description is None or description == "":
            missing.append(name)
            concepts.append({"name": name, "description": MISSING_DESC})
        else:
            concepts.append({"name": name, "description": description})

        type_hits = row.get("boundary_type_hits") or []
        untyped = bool(row.get("untyped"))
        subtree_count = row.get("subtree_count") or 0
        min_depth = row.get("min_depth")
        has_children = bool(row.get("has_children"))

        if type_hits:
            stopped.append({
                "name": name,
                "reason": f"boundary_type: {', '.join(type_hits)}",
            })
        elif untyped and subtree_count > hub_cap:
            stopped.append({
                "name": name,
                "reason": (
                    f"hub_cap: untyped hub with HAS_PART*1..{HUB_CAP_PROBE_DEPTH} "
                    f"subtree {subtree_count} > {hub_cap}"
                ),
            })
        elif has_children and isinstance(min_depth, int) and min_depth >= max_depth:
            stopped.append({
                "name": name,
                "reason": f"depth: reached max_depth {max_depth} with children below",
            })

    return {"concepts": concepts, "stopped": stopped, "missing": missing}


def build_stop_report(
    stopped: List[dict],
    max_depth: int,
    hub_cap: int,
    inline_limit: int = 40,
) -> Optional[str]:
    """PURE: the compact truncation-report string that LEADS the payload (G10).

    None when nothing stopped (so `_fmt` drops the field and the zero-stop rendering stays
    byte-identical to pre-#203). When the stop list is long, only `inline_limit` entries are
    enumerated inline and the elision is ITSELF reported (G2: even the report's own cap is
    not silent) — the full list always follows in the structured `stopped` field.
    """
    if not stopped:
        return None
    shown = stopped[:inline_limit]
    entries = "; ".join(f"{s['name']} [{s['reason']}]" for s in shown)
    more = len(stopped) - len(shown)
    tail = f"; ... and {more} more (full list in the stopped field)" if more > 0 else ""
    return (
        f"BOUNDED-WALK TRUNCATION: {len(stopped)} member(s) stopped the walk "
        f"(each is included as a leaf, NOT descended; max_depth={max_depth}, "
        f"hub_cap={hub_cap}): {entries}{tail}"
    )


def build_activation_result(
    collection_name: str,
    rows: List[dict],
    max_depth: int = DEFAULT_MAX_DEPTH,
    hub_cap: int = DEFAULT_HUB_CAP,
) -> Dict[str, object]:
    """PURE: the final `get_collection_concepts` return dict, report-first (G10).

    Key INSERTION ORDER is load-bearing: `_fmt` renders dict fields in insertion order and
    truncates at 10k chars, so `truncation_report` and `stopped` are inserted BEFORE
    `concepts`. With zero stops both are empty shapes (`None`/`[]`) that `_fmt` drops,
    making the rendering byte-identical to the pre-#203 shape (G4).

    The empty-collection case reproduces the legacy shape exactly (message + empty concepts).
    The legacy `warning` string for missing-description members is preserved verbatim.
    """
    if not rows:
        return {
            "success": True,
            "collection_name": collection_name,
            "concepts": [],
            "total_count": 0,
            "warning": None,
            "message": f"Collection '{collection_name}' is empty or does not exist",
        }

    classified = classify_rows(rows, max_depth=max_depth, hub_cap=hub_cap)
    concepts = classified["concepts"]
    stopped = classified["stopped"]
    missing = classified["missing"]

    warning_message = None
    if missing:
        warning_message = (
            f"⚠️ Warnings: [{', '.join(missing)}] are in {collection_name} "
            f"but are not defined, themselves."
        )

    return {
        "success": True,
        "collection_name": collection_name,
        "truncation_report": build_stop_report(stopped, max_depth=max_depth, hub_cap=hub_cap),
        "stopped": stopped,
        "concepts": concepts,
        "total_count": len(concepts),
        "warning": warning_message,
    }
