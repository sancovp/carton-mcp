"""Node-quota enforcement for hosted carton boxes — the carton-saas metering
gate (monorepo `designs/carton-saas-DESIGN.md` §4).

One capability, one module (this repo's convention — the carton_kv /
split_content precedent): the pure logic lives here; `add_concept_tool.py`
gains ONE guarded call at the `add_concept_tool_func` chokepoint (the audited
single path every concept-creation caller passes through — the add_concept
tool, dragonbones, sm_gate, split_content, migrations).

LAWS:
1. **OPT-IN, no-op unless `CARTON_MAX_NODES` is set** — unset (the local /
   self-hosted default) means byte-identical behavior, zero queries. A quota
   never appears on anyone's carton uninvited.
2. **Refuse growth, not refinement** — at/over quota, edits to EXISTING
   concepts still pass (add_concept is also the update path via
   desc_update_mode); only NEW nodes are refused, with an actionable error.
   The existence query runs ONLY on the rare over-quota branch.
3. **The LIVE path is the enforced path** — the check fires BEFORE the queue
   write in add_concept_tool_func, so a rejection provably never reaches the
   graph (the lesson of the optional-fields build: validating on a derived
   view while the queue write proceeds is the documented silent failure).
4. **Enforcement reads the live count; telemetry only observes** — the
   BLACKBOX `carton.node_count` gauge is a separate lane and never meters.
5. **Bounded cost** — the count is TTL-cached (default 60s,
   `CARTON_QUOTA_TTL_S`): one count query per window, not per write.

Known bound (named, accepted): daemon-side auto-created relationship-target
stubs don't pass this chokepoint, so a box can drift slightly past the limit;
the front door still blocks all deliberate growth, and the nightly gauge
shows true counts. Daemon-side enforcement is a separate capability with its
own dev-flow if ever needed.
"""

import os
import threading
import time

DEFAULT_TTL_S = 60.0

_cache = {"count": None, "at": 0.0}
_lock = threading.Lock()


class QuotaExceeded(RuntimeError):
    """Raised when a NEW concept would exceed CARTON_MAX_NODES."""


def quota_limit(env=None):
    """None when unset/empty (the no-op law); int otherwise; loud on garbage
    (a misconfigured limit must never silently mean 'unlimited')."""
    env = os.environ if env is None else env
    raw = (env.get("CARTON_MAX_NODES") or "").strip()
    if not raw:
        return None
    try:
        limit = int(raw)
    except ValueError:
        raise RuntimeError(
            f"CARTON_MAX_NODES must be an integer, got {raw!r} — refusing to "
            "guess (a broken limit must not silently mean unlimited)"
        )
    if limit < 0:
        raise RuntimeError(f"CARTON_MAX_NODES must be >= 0, got {limit}")
    return limit


def invalidate_cache():
    with _lock:
        _cache["count"] = None
        _cache["at"] = 0.0


def _count_nodes(shared_connection=None) -> int:
    from carton_mcp.carton_utils import CartOnUtils

    utils = CartOnUtils(shared_connection=shared_connection)
    rows = utils.query_wiki_graph(
        "MATCH (c:Wiki) RETURN count(c) AS n", {}
    )
    if not rows:
        return 0
    first = rows[0]
    return int(first["n"] if isinstance(first, dict) else first)


def _concept_exists(concept_name: str, shared_connection=None) -> bool:
    from carton_mcp.carton_utils import CartOnUtils

    utils = CartOnUtils(shared_connection=shared_connection)
    rows = utils.query_wiki_graph(
        "MATCH (c:Wiki {n: $name}) RETURN count(c) AS n", {"name": concept_name}
    )
    if not rows:
        return False
    first = rows[0]
    return int(first["n"] if isinstance(first, dict) else first) > 0


def check_quota(
    concept_name: str,
    shared_connection=None,
    env=None,
    count_fn=None,
    exists_fn=None,
    ttl_s=None,
) -> None:
    """The gate. Returns silently when allowed; raises QuotaExceeded when a
    NEW concept would exceed the limit. count_fn/exists_fn are injectable for
    tests; production uses the live :Wiki queries."""
    limit = quota_limit(env)
    if limit is None:
        return  # law 1 — unset means untouched

    env = os.environ if env is None else env
    if ttl_s is None:
        ttl_s = float(env.get("CARTON_QUOTA_TTL_S", str(DEFAULT_TTL_S)))

    now = time.monotonic()
    with _lock:
        cached = _cache["count"]
        fresh = cached is not None and (now - _cache["at"]) < ttl_s
    if fresh:
        count = cached
    else:
        count = (count_fn or _count_nodes)(shared_connection)
        with _lock:
            _cache["count"] = count
            _cache["at"] = now

    if count < limit:
        return
    # law 2 — over-quota: refinement passes, growth is refused
    if (exists_fn or _concept_exists)(concept_name, shared_connection):
        return
    raise QuotaExceeded(
        f"carton node quota reached: {count} >= {limit} :Wiki nodes "
        f"(CARTON_MAX_NODES={limit}). Editing EXISTING concepts still works; "
        f"creating NEW concepts needs a higher tier (carton-saas-DESIGN §3) "
        f"or a raised limit."
    )
