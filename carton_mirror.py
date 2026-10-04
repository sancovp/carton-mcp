"""carton_mirror — an outside system's records, mirrored INTO the tenant's graph (one capability, one module).

The GHL wrapper (not-unified/business-runtime/ghl-wrapper) records every call it makes to GHL. On a tenant's box that
record lands here, in the tenant's own graph, as :Wiki concepts the tenant can open like any other:

    Ghl_<Kind>_<id>            the record as it is now (role 'record'): its JSON, its kind, its GHL id, its version
    Ghl_<Kind>_<id>_V<n>       each version it has had (role 'version'), linked (record)-[:HAS_VERSION]->(version)
    Ghl_<Kind>                 its type: (record)-[:IS_A]->(type)
    Ghl_Sub_Account_<id>       the GHL sub-account it came from: (record)-[:PART_OF]->(sub-account)
    Ghl_Call_<n>               every call, raw: the function, what was sent, each HTTP exchange, what GHL answered
    Ghl_Event_<n> · Ghl_Pass_<n>   GHL's events and the full passes over the sub-account

A new version is written only when the SAME function's answer for the record changed, or its deleted state did — the
rule of the wrapper's mirror.py, kept here. Every node is written already linked (`linked = true`) with source
'ghl_mirror', so CartON's background linker never rewrites a record's text.

Two entry points, both called by the MCP tools `mirror_write` and `mirror_read`: `write(conn, op, payload)` and
`read(conn, op, args)`. `conn` is the server's shared Neo4j connection. Payload values are already plain JSON and
already free of secrets — the wrapper redacts before it sends.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

SOURCE = "ghl_mirror"
_ready = False


def _key(s: str) -> str:
    """a Title_Underscore-safe piece of a name"""
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(s)).strip("_")
    return "_".join(p[:1].upper() + p[1:] for p in s.split("_") if p) or "X"


def type_name(kind: str) -> str:
    return "Ghl_" + _key(kind)


def record_name(kind: str, rid: str) -> str:
    """case-safe: two GHL ids that differ only in letter case never share a concept"""
    digest = hashlib.sha1(str(rid).encode()).hexdigest()[:6]
    return f"{type_name(kind)}_{_key(str(rid).lower())}_{digest}"


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _describe(kind: str, rid: str, rec: Any, deleted: bool) -> str:
    title = ""
    if isinstance(rec, dict):
        for k in ("name", "contactName", "title", "firstName", "email", "subject", "body"):
            if rec.get(k):
                title = str(rec[k])[:120]
                break
    head = f"GHL {kind} {rid}" + (f" — {title}" if title else "") + (" (deleted in GHL)" if deleted else "")
    return head + "\n\n" + json.dumps(rec, indent=2, ensure_ascii=False)[:20000]


def _tx(conn, fn: Callable):
    conn._ensure_connection()
    with conn.driver.session() as session:
        return session.execute_write(fn)


def _rows(conn, query: str, params: dict) -> List[dict]:
    conn._ensure_connection()
    with conn.driver.session() as session:
        return [dict(r) for r in session.run(query, params)]


def _ensure_indexes(conn) -> None:
    global _ready
    if _ready:
        return
    for prop in ("ghl_role", "ghl_kind", "ghl_id", "ghl_call"):
        _rows(conn, f"CREATE INDEX wiki_{prop} IF NOT EXISTS FOR (c:Wiki) ON (c.{prop})", {})
    _ready = True


def _next(tx, counter: str) -> int:
    return tx.run("MERGE (c:GhlMirrorCounter {n: 'counters'}) "
                  f"SET c.{counter} = coalesce(c.{counter}, 0) + 1 RETURN c.{counter} AS n").single()["n"]


_BASE = {"linked": True, "source": SOURCE, "system_generated": True}


def _put(tx, now: float, kind: str, rid: str, rec: Any, location: Optional[str], call: int, source: Optional[str],
         tombstone: bool = False) -> bool:
    """a new version of one record, when this source's answer for it changed (or it was deleted); True if written"""
    name = record_name(kind, rid)
    cur = tx.run("MATCH (c:Wiki {n: $n}) RETURN c.ghl_version AS v, c.ghl_deleted AS d, c.ghl_json AS j, "
                 "c.ghl_location AS loc", n=name).single()
    if tombstone:
        if not cur or cur["d"]:
            return False
        data, deleted, location = cur["j"], True, cur["loc"]
    else:
        data = _canon(rec)
        deleted = isinstance(rec, dict) and rec.get("deleted") is True
        if cur:
            same = tx.run("MATCH (:Wiki {n: $n})-[:HAS_VERSION]->(v:Wiki) WHERE v.ghl_from = $s "
                          "RETURN v.ghl_json AS j ORDER BY v.ghl_version DESC LIMIT 1", n=name, s=source).single()
            if bool(cur["d"]) == deleted and same and same["j"] == data:
                return False
    version = (cur["v"] or 0) + 1 if cur else 1
    record = json.loads(data) if data else None
    props = {**_BASE, "ghl_kind": kind, "ghl_id": str(rid), "ghl_location": location, "ghl_version": version,
             "ghl_deleted": deleted, "ghl_at": now, "ghl_from": source, "ghl_call": call, "ghl_json": data,
             "d": _describe(kind, rid, record, deleted), "t": now}
    tx.run("MERGE (t:Wiki {n: $type}) ON CREATE SET t += $tprops "
           "MERGE (c:Wiki {n: $n}) SET c += $props, c.ghl_role = 'record' "
           "MERGE (c)-[:IS_A]->(t) "
           "CREATE (v:Wiki {n: $vn}) SET v += $props, v.ghl_role = 'version', "
           "  v.d = 'Version ' + toString($version) + ' of ' + $n + '\\n\\n' + $props.d "
           "MERGE (c)-[:HAS_VERSION]->(v) "
           "WITH c CALL (c) { "
           "  WITH c WHERE $loc IS NOT NULL "
           "  MERGE (s:Wiki {n: 'Ghl_Sub_Account_' + $lockey}) ON CREATE SET s += $sprops, s.ghl_location = $loc "
           "  MERGE (c)-[:PART_OF]->(s) } ",
           type=type_name(kind), n=name, vn=f"{name}_V{version}", version=version, props=props, loc=location,
           lockey=_key(location or ""), tprops={**_BASE, "d": f"The kind of GHL record '{kind}', mirrored."},
           sprops={**_BASE, "d": f"The GHL sub-account {location}, mirrored."})
    return True


# ---------------------------------------------------------------------------------------------------------------- write
def write(conn, op: str, payload: dict, clock=time.time) -> dict:
    _ensure_indexes(conn)
    now = clock()
    if op == "record_call":
        def fn(tx):
            n = _next(tx, "calls")
            tx.run("CREATE (c:Wiki {n: $name}) SET c += $props, c.ghl_role = 'call'",
                   name=f"Ghl_Call_{n}", props={
                       **_BASE, "ghl_call": n, "ghl_at": now, "ghl_function": payload.get("function"),
                       "ghl_location": payload.get("location"), "ghl_status": int(payload.get("status") or 0),
                       "ghl_ok": bool(payload.get("ok")), "ghl_error": payload.get("error"),
                       "ghl_ms": int(payload.get("ms") or 0), "ghl_args": _canon(payload.get("args")),
                       "ghl_exchanges": _canon(payload.get("exchanges") or []),
                       "ghl_answer": _canon(payload.get("answer")), "t": now,
                       "d": f"GHL call {n}: {payload.get('function')} -> {payload.get('status')}"
                            + (f" ({payload.get('error')})" if payload.get("error") else "")})
            written = 0
            for kind, rid, rec in payload.get("records") or []:
                written += _put(tx, now, kind, str(rid), rec, payload.get("location") or (rec or {}).get("locationId"),
                                n, payload.get("function"))
            gone = payload.get("gone")
            if gone:
                written += _put(tx, now, gone[0], str(gone[1]), None, None, n, None, tombstone=True)
            return {"n": n, "written": written}
        return _tx(conn, fn)
    if op == "mark_deleted":
        return {"removed": bool(_tx(conn, lambda tx: _put(tx, now, payload["kind"], str(payload["id"]), None, None, 0,
                                                          None, tombstone=True)))}
    if op == "record_event":
        def fn(tx):
            row = tx.run("MATCH (e:Wiki {n: $n}) RETURN e.ghl_read AS r", n=f"Ghl_Event_{int(payload['n'])}").single()
            if row is None:
                ev = payload.get("event") or {}
                tx.run("CREATE (e:Wiki {n: $name}) SET e += $props, e.ghl_role = 'event'",
                       name=f"Ghl_Event_{int(payload['n'])}", props={
                           **_BASE, "ghl_event": int(payload["n"]), "ghl_at": now, "ghl_type": str(ev.get("type") or ""),
                           "ghl_location": ev.get("locationId") or payload.get("location"), "ghl_json": _canon(ev),
                           "t": now, "d": f"GHL event {ev.get('type')} for {ev.get('locationId')}"})
            return {"new": row is None or row["r"] is None}
        return _tx(conn, fn)
    if op == "event_read":
        _rows(conn, "MATCH (e:Wiki {n: $n}) SET e.ghl_read = $r", {"n": f"Ghl_Event_{int(payload['n'])}",
                                                                   "r": _canon(payload.get("read"))})
        return {}
    if op == "record_pass":
        def fn(tx):
            n = _next(tx, "passes")
            rep = payload.get("report") or {}
            tx.run("CREATE (p:Wiki {n: $name}) SET p += $props, p.ghl_role = 'pass'", name=f"Ghl_Pass_{n}", props={
                **_BASE, "ghl_pass": n, "ghl_started": rep.get("started"), "ghl_finished": now,
                "ghl_children": rep.get("children"), "ghl_json": _canon(rep), "t": now,
                "d": f"GHL full pass {n} ({rep.get('children')}): {rep.get('calls')} calls, {rep.get('records')} records"})
            return {"n": n}
        return _tx(conn, fn)
    raise ValueError(f"unknown mirror write '{op}'")


# ----------------------------------------------------------------------------------------------------------------- read
_CUR = "MATCH (c:Wiki) WHERE c.ghl_role = 'record' AND NOT coalesce(c.ghl_deleted, false)"


def read(conn, op: str, args: dict) -> Any:
    _ensure_indexes(conn)
    a = args or {}
    loc = " AND c.ghl_location = $loc" if a.get("location") else ""
    if op == "current":
        page = " SKIP $offset LIMIT $limit" if a.get("limit") is not None else ""
        return [json.loads(r["j"]) for r in _rows(conn, f"{_CUR} AND c.ghl_kind = $kind{loc} RETURN c.ghl_json AS j "
                                                  f"ORDER BY c.ghl_id{page}",
                                                  {"kind": a["kind"], "loc": a.get("location"),
                                                   "offset": int(a.get("offset") or 0), "limit": int(a.get("limit") or 0)})]
    if op == "current_ids":
        return {r["i"]: r["at"] for r in _rows(conn, f"{_CUR} AND c.ghl_kind = $kind{loc} RETURN c.ghl_id AS i, "
                                               "c.ghl_at AS at", {"kind": a["kind"], "loc": a.get("location")})}
    if op == "changed_since":
        return [[r["k"], r["i"]] for r in _rows(conn, "MATCH (v:Wiki) WHERE v.ghl_role = 'version' AND v.ghl_call > $n "
                                                "RETURN DISTINCT v.ghl_kind AS k, v.ghl_id AS i", {"n": int(a["call"])})]
    if op == "kinds":
        return {r["k"]: r["c"] for r in _rows(conn, f"{_CUR} RETURN c.ghl_kind AS k, count(*) AS c", {})}
    if op == "kinds_from":
        return [r["k"] for r in _rows(conn, "MATCH (v:Wiki) WHERE v.ghl_role = 'version' AND v.ghl_from = $s "
                                      "RETURN DISTINCT v.ghl_kind AS k", {"s": a["source"]})]
    if op == "learned_from":
        return [[r["k"], r["i"], r["f"], r["at"]] for r in _rows(
            conn, f"{_CUR} AND c.ghl_from IN $s RETURN c.ghl_kind AS k, c.ghl_id AS i, c.ghl_from AS f, c.ghl_at AS at",
            {"s": list(a.get("sources") or [])})]
    if op == "kinds_of":
        return [r["k"] for r in _rows(conn, f"{_CUR} AND c.ghl_id = $id RETURN c.ghl_kind AS k", {"id": str(a["id"])})]
    if op == "versions":
        return [{"version": r["v"], "at": r["at"], "deleted": bool(r["d"]), "call": r["c"],
                 "data": json.loads(r["j"]) if r["j"] else None}
                for r in _rows(conn, "MATCH (:Wiki {n: $n})-[:HAS_VERSION]->(v:Wiki) RETURN v.ghl_version AS v, "
                               "v.ghl_at AS at, v.ghl_deleted AS d, v.ghl_call AS c, v.ghl_json AS j ORDER BY v",
                               {"n": record_name(a["kind"], str(a["id"]))})]
    if op == "calls":
        fn = " AND c.ghl_function = $f" if a.get("function") else ""
        rows = _rows(conn, f"MATCH (c:Wiki) WHERE c.ghl_role = 'call'{fn} RETURN c ORDER BY c.ghl_call DESC LIMIT $l",
                     {"f": a.get("function"), "l": int(a.get("limit") or 100)})
        out = []
        for r in rows:
            c = r["c"]
            out.append({"n": c["ghl_call"], "at": c["ghl_at"], "function": c["ghl_function"],
                        "location": c.get("ghl_location"), "args": json.loads(c["ghl_args"]),
                        "exchanges": json.loads(c["ghl_exchanges"]), "status": c["ghl_status"], "ok": c["ghl_ok"],
                        "error": c.get("ghl_error"), "answer": json.loads(c["ghl_answer"]), "ms": c["ghl_ms"]})
        return out
    if op == "events":
        return [{"n": e["ghl_event"], "at": e["ghl_at"], "type": e["ghl_type"], "location": e.get("ghl_location"),
                 "event": json.loads(e["ghl_json"]), "read": json.loads(e["ghl_read"]) if e.get("ghl_read") else None}
                for e in (r["e"] for r in _rows(conn, "MATCH (e:Wiki) WHERE e.ghl_role = 'event' RETURN e "
                                                "ORDER BY e.ghl_event DESC LIMIT $l", {"l": int(a.get("limit") or 100)}))]
    if op == "passes":
        ch = " AND p.ghl_children = $ch" if a.get("children") else ""
        return [{"n": p["ghl_pass"], "started": p.get("ghl_started"), "finished": p["ghl_finished"],
                 "children": p.get("ghl_children"), "report": json.loads(p["ghl_json"])}
                for p in (r["p"] for r in _rows(conn, f"MATCH (p:Wiki) WHERE p.ghl_role = 'pass'{ch} RETURN p "
                                                "ORDER BY p.ghl_pass DESC LIMIT $l",
                                                {"ch": a.get("children"), "l": int(a.get("limit") or 10)}))]
    raise ValueError(f"unknown mirror read '{op}'")
