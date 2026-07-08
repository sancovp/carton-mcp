#!/usr/bin/env python3
"""
backfill_timeline_is_a.py — one-time, idempotent backfill of `is_a` on TIMELINE nodes.

WHY (Isaac 2026-06-20): "user message etc on timeline have no is_a even though we know the
is_a is that they are user messages, tool uses, agent messages, etc. those should be fixed
they are obvious." The conversation-ingestion source writers (carton_precompact.py) DO set
is_a for every node they write as a SOURCE. But a timeline node referenced ONLY as a
relationship TARGET (summarizes/surfaced_from/part_of) — whose own source-write never lands —
is born as a bare AUTO-CREATED stub by observation_worker_daemon.batch_create_concepts_neo4j
(the rel UNWIND `MERGE (target) ON CREATE SET target.d='AUTO CREATED...'`) with NO is_a. That
leak is fixed at the source by the timeline-stub-typing pass in batch_create_concepts_neo4j
(going forward); THIS script repairs the ~9.5k pre-existing untyped timeline nodes.

WHAT it does: for each timeline name-prefix, MERGE `(n)-[:IS_A]->(type)` (+ the HAS_INSTANCES
inverse, matching the writer's inverse_map) on every node lacking is_a. Idempotent (MERGE),
ADDITIVE ONLY — it NEVER touches n.d, NEVER deletes, NEVER modifies the accumulated stub
content (Isaac: "leave the accumulation alone" — this only ADDS the obvious type edge).

ORDER is load-bearing: 'Iteration_Summary_' is typed BEFORE 'Iteration_' (the latter's prefix
matches the former), and 'Iteration_' is run LAST with an explicit exclusion of the overlap.

Safe to re-run (MERGE). Connection via the same KnowledgeGraphBuilder the daemon uses.
Run:  NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... python3 scripts/backfill_timeline_is_a.py
"""
import os
import sys

# (prefix, type) — unambiguous prefixes first; 'Iteration_' handled separately LAST (overlap).
PREFIX_TYPES = [
    ("Iteration_Summary_",       "Iteration_Summary"),   # BEFORE 'Iteration_'
    ("User_Message_",            "User_Message"),
    ("Agent_Message_",           "Agent_Message"),
    ("Tool_Call_",               "Tool_Call"),
    ("Conversation_",            "Conversation"),
    ("Unnamed_Conversation_At_", "Conversation"),
]


def _conn():
    from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
    c = KnowledgeGraphBuilder(
        uri=os.getenv("NEO4J_URI", "bolt://host.docker.internal:7687"),
        user=os.getenv("NEO4J_USER", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )
    c._ensure_connection()
    return c


def _lack_count(conn, where: str) -> int:
    rows = conn.execute_query(
        f"MATCH (n:Wiki) WHERE {where} AND NOT (n)-[:IS_A]->() RETURN count(n) AS c"
    )
    rec = rows[0] if isinstance(rows, list) else (rows[0] if rows else None)
    if rec is None:
        return -1
    return rec["c"] if isinstance(rec, dict) else rec.get("c", -1)


def _type_prefix(conn, prefix: str, typ: str, extra_where: str = "") -> int:
    where = f"n.n STARTS WITH '{prefix}'" + (f" AND {extra_where}" if extra_where else "")
    before = _lack_count(conn, where)
    conn.execute_query(
        f"""
        MATCH (n:Wiki) WHERE {where} AND NOT (n)-[:IS_A]->()
        MERGE (t:Wiki {{n: $typ}})
        MERGE (n)-[:IS_A]->(t)
        MERGE (t)-[:HAS_INSTANCES]->(n)
        """,
        {"typ": typ},
    )
    after = _lack_count(conn, where)
    typed = before - after if (before >= 0 and after >= 0) else -1
    print(f"  {prefix:<26} -> IS_A {typ:<20} | lacked {before}, now lack {after}  (typed {typed})")
    return typed if typed >= 0 else 0


def main():
    conn = _conn()
    if conn is None:
        print("FATAL: no neo4j connection", file=sys.stderr)
        sys.exit(1)
    print("Backfilling timeline is_a (idempotent, additive — no n.d touched, no deletes)\n")
    total = 0
    for prefix, typ in PREFIX_TYPES:
        total += _type_prefix(conn, prefix, typ)
    # Iteration_ LAST, EXCLUDING the Iteration_Summary_ overlap:
    total += _type_prefix(conn, "Iteration_", "Iteration",
                          extra_where="NOT n.n STARTS WITH 'Iteration_Summary_'")
    print(f"\nDONE. Total IS_A edges added: {total}")
    # Final proof: zero untyped timeline nodes remain (per prefix).
    print("\nVERIFY (should all be 0):")
    for prefix, _ in PREFIX_TYPES:
        where = "n.n STARTS WITH '" + prefix + "'"
        print(f"  {prefix:<26} lack_isa = {_lack_count(conn, where)}")
    iter_where = "n.n STARTS WITH 'Iteration_' AND NOT n.n STARTS WITH 'Iteration_Summary_'"
    print(f"  {'Iteration_ (non-summary)':<26} lack_isa = {_lack_count(conn, iter_where)}")


if __name__ == "__main__":
    main()
