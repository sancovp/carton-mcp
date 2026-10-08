#!/usr/bin/env python3
"""Print the delinked raw description of CartON nodes whose name starts with a prefix, in name order,
between two name bounds. Read-only; needs no run config.
Usage: nodes.py <prefix> [from_name] [to_name]   e.g. nodes.py Tool_Call_2026_09_16T19"""
import os
import sys

from neo4j import GraphDatabase, READ_ACCESS

from delink import delink, residue

prefix = sys.argv[1]
lo = sys.argv[2] if len(sys.argv) > 2 else ""
hi = sys.argv[3] if len(sys.argv) > 3 else "￿"
drv = GraphDatabase.driver(os.environ.get("NEO4J_URI", "bolt://host.docker.internal:7687"),
                           auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "password")))
with drv.session(default_access_mode=READ_ACCESS) as s:
    rows = list(s.run(
        "MATCH (n:Wiki) WHERE n.n STARTS WITH $p AND n.n >= $lo AND n.n <= $hi "
        "RETURN n.n AS n, n.d AS d ORDER BY n.n", p=prefix, lo=lo, hi=hi))
drv.close()
for r in rows:
    d = delink(r["d"] or "")
    print("=" * 30, r["n"], f"(len {len(d)}, residue {residue(d)})")
    print(d)
print(f"[{len(rows)} nodes]")
