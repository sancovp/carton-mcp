"""
carton_disclose — the PURE half of `progressively_disclose` (task 176, issue 212).

ISAAC 2026-09-03 04:35, verbatim: "WE NEED A NEW TOOL IN CARTON CALLED PROGRESSIVELY_DISCLOSE
AND THIS LETS YOU CHOOSE A STARTING LEVEL OF THE GRAPH OR SHOW YOU THE DIAGRAM OF THE
CATEGORIES/LEVELS OF THE GRAPH. THAT IS IT. NOTHING ELSE."

So there are exactly two modes and no third: no level -> the DIAGRAM of the levels; a level ->
the MEMBERS at that level.

THE LEVELS ARE NOT INVENTED HERE. `carton_bounded_walk.DEFAULT_BOUNDARY_TYPES` already lists the
eight axis types, and that module's binding law is that a member whose direct IS_A hits one of
them is a BOUNDARY -- included as a leaf, never descended. That is carton stating, in code, which
nodes are LEVELS rather than leaves, and it mirrors `docmirror-collect`'s write-side membership
law, so the read side and the write side already agree on the ladder. This module IMPORTS that
constant and never restates it: a hand-copied list of eight names is the defect that produced
issue 617, where a faithfully-transcribed table row under-described its own feature by three
modules. If the ladder changes there, it changes here, with nothing to keep in step by hand.

ONION, copying THIS PACKAGE'S OWN precedent rather than a general principle -- `carton_bounded_walk`
says of itself: "This module is the PURE half -- the plan-builder and the row-classifier, both
stdlib-only, no neo4j, no I/O, unit-tested on synthetic rows. The Cypher executor stays thin."
Everything here is that same pure half: it BUILDS the one query and it RENDERS already-fetched
rows. Nothing in this file opens a socket, and it is unit-tested on synthetic rows
(test_carton_disclose.py). The executor is the thin MCP tool in server_fastmcp.py.

LOUD ON GARBAGE, this repo's own stated law in the breaker, the quota and the pathguard: an
unrecognised level raises ValueError naming the legal set, because a navigation surface that
silently returns nothing for a typo is indistinguishable from a level that is genuinely empty.

A ZERO IS REPORTED, NEVER DROPPED. The counting query uses OPTIONAL MATCH so a declared level with
no members renders as 0 rather than vanishing -- "this level exists and is empty" and "this level
does not exist" are different facts, and a diagram that cannot tell them apart is the
filtered-view-omission defect built into a tool.
"""
from typing import Dict, List, Optional

try:                                             # installed as the carton_mcp package
    from carton_mcp.carton_bounded_walk import DEFAULT_BOUNDARY_TYPES
except ImportError:                              # run as a script from the repo root
    from carton_bounded_walk import DEFAULT_BOUNDARY_TYPES

# The ladder, in the source constant's own order. Never a second list of names.
LEVELS: List[str] = list(DEFAULT_BOUNDARY_TYPES)

DEFAULT_MEMBER_LIMIT = 50
_MAX_MEMBER_LIMIT = 500

# The stored description slice the member query asks for. Wider than the rendered summary on
# purpose: the renderer cuts to SUMMARY_CHARS on a WORD boundary, so a mid-word truncation like
# the one filed as issue 576 cannot happen on this surface.
_DESC_SLICE = 400
SUMMARY_CHARS = 160


def normalize_level(level: str) -> str:
    """Resolve a caller's level string to one of LEVELS, or raise ValueError naming the set.

    Matching is case-insensitive and treats '-' and ' ' as '_', so `hypercluster`,
    `Hypercluster` and `doc mirror domain` all land. Anything else raises rather than
    returning an empty result that would read as an empty level.
    """
    if not isinstance(level, str) or not level.strip():
        raise ValueError(
            f"level must be a non-empty string naming one of: {', '.join(LEVELS)}"
        )
    key = level.strip().replace("-", "_").replace(" ", "_").lower()
    for known in LEVELS:
        if known.lower() == key:
            return known
    raise ValueError(
        f"unknown level {level!r}. The levels of the graph are: {', '.join(LEVELS)}"
    )


def build_levels_plan() -> Dict[str, object]:
    """PURE: the ONE Cypher counting members per level, plus its parameters. No I/O.

    OPTIONAL MATCH keeps a declared-but-empty level in the result at 0 instead of dropping it.
    Returns {"cypher": str, "parameters": {"levels": [...]}} .
    """
    cypher = """
    UNWIND $levels AS lvl
    OPTIONAL MATCH (m:Wiki)-[:IS_A]->(:Wiki {n: lvl})
    RETURN lvl AS level, count(DISTINCT m) AS members
    """
    return {"cypher": cypher, "parameters": {"levels": list(LEVELS)}}


def build_level_plan(level: str, limit: int = DEFAULT_MEMBER_LIMIT) -> Dict[str, object]:
    """PURE: the ONE Cypher listing the members at one level, plus its parameters. No I/O.

    `level` is resolved through normalize_level first, so an unknown level raises here rather
    than producing a query that returns nothing. `limit` is validated as an int in
    [1, 500] and rides as a parameter.
    """
    resolved = normalize_level(level)
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError(f"limit must be an int, got {type(limit).__name__}")
    if not (1 <= limit <= _MAX_MEMBER_LIMIT):
        raise ValueError(f"limit must be in [1, {_MAX_MEMBER_LIMIT}], got {limit}")
    cypher = """
    MATCH (m:Wiki)-[:IS_A]->(:Wiki {n: $level})
    RETURN m.n AS name, substring(coalesce(m.d, ''), 0, $slice) AS summary
    ORDER BY m.n
    LIMIT $limit
    """
    return {
        "cypher": cypher,
        "parameters": {"level": resolved, "slice": _DESC_SLICE, "limit": limit},
        "level": resolved,
        "limit": limit,
    }


class DiscloseStoreError(RuntimeError):
    """The store could not answer. Never rendered as an empty graph."""


def rows_or_raise(result) -> List[dict]:
    """PURE: unwrap the `query_wiki_graph` envelope to rows, or RAISE. Never returns [].

    `{'success': ..., 'data': [rows]}` is the envelope. A FAILED query must never unwrap to an
    empty list, because on THIS surface an empty list renders as every level at zero -- i.e.
    "the graph has no levels" -- when the truth is "the store did not answer". That is the
    fail-open this package already refused in the quota gate, whose rule states it directly: a
    meter that cannot count must never fail open into 'unlimited'. An unrecognised envelope
    raises for the same reason, because a shape nobody planned for is not evidence of an empty
    graph either.
    """
    if isinstance(result, dict):
        if result.get("success") is False:
            raise DiscloseStoreError(
                f"the store could not answer: {result.get('error') or 'no error given'}"
            )
        if "data" in result:
            return list(result.get("data") or [])
        raise DiscloseStoreError(f"unrecognised query envelope, keys: {sorted(result)}")
    if isinstance(result, list):
        return list(result)
    raise DiscloseStoreError(f"unrecognised query result of type {type(result).__name__}")


def _clip(text: str, width: int = SUMMARY_CHARS) -> str:
    """PURE: cut `text` to at most `width` chars on a WORD boundary, with an ellipsis."""
    flat = " ".join((text or "").split())
    if len(flat) <= width:
        return flat
    cut = flat[:width].rsplit(" ", 1)[0]
    return (cut if cut else flat[:width]) + "..."


def render_diagram(rows: List[dict]) -> str:
    """PURE: the diagram of the graph's categories and levels, from already-fetched count rows.

    Each row: {"level": str, "members": int} (the build_levels_plan RETURN shape). Levels are
    rendered in LEVELS order, not row order, so the ladder reads the same every time; a level
    absent from the rows renders as 0 rather than being skipped. The bar is proportional to the
    largest count, so it is a shape rather than a unit.
    """
    counts = {str(r.get("level")): int(r.get("members") or 0) for r in rows or []}
    ordered = [(lvl, counts.get(lvl, 0)) for lvl in LEVELS]
    widest = max((len(lvl) for lvl in LEVELS), default=0)
    biggest = max((n for _, n in ordered), default=0)

    out = [
        "CARTON — THE LEVELS OF THE GRAPH",
        "",
        "The axis types the bounded walk refuses to descend through: a node whose",
        "direct IS_A hits one of these is a LEVEL, not a leaf (carton_bounded_walk).",
        "",
    ]
    for lvl, n in ordered:
        bar = "█" * int(round(24 * n / biggest)) if biggest else "—"
        out.append(f"  {lvl.ljust(widest)} · {str(n).rjust(6)} · {bar}")
    out += [
        "",
        f"  {'TOTAL'.ljust(widest)} · {str(sum(n for _, n in ordered)).rjust(6)}",
        "",
        "Descend by naming one:  progressively_disclose(level=\"<one of the above>\")",
    ]
    return "\n".join(out)


def render_members(level: str, rows: List[dict], limit: int = DEFAULT_MEMBER_LIMIT) -> str:
    """PURE: the members at one level, from already-fetched rows.

    Each row: {"name": str, "summary": str} (the build_level_plan RETURN shape). Summaries are
    clipped on a word boundary. When the row count reaches `limit` the listing says so, because
    a truncated list that does not announce its truncation reads as a complete one.
    """
    resolved = normalize_level(level)
    if not rows:
        return (
            f"{resolved} — 0 members.\n\n"
            "That is an EMPTY level, not a missing one: it is one of the declared axis types.\n"
            f"The levels of the graph are: {', '.join(LEVELS)}"
        )
    out = [f"{resolved} — {len(rows)} member(s) shown", ""]
    for row in rows:
        name = str(row.get("name") or "")
        summary = _clip(str(row.get("summary") or ""))
        out.append(f"  {name}" + (f"\n      {summary}" if summary else ""))
    if len(rows) >= limit:
        out += [
            "",
            f"  ...listing stopped at limit={limit}. There may be more members at this level;"
            " raise the limit to see further.",
        ]
    return "\n".join(out)
