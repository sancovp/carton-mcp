#!/usr/bin/env python3
"""Read-only raw Cypher against the carton neo4j. Returns stored n.d bytes WITHOUT the read facade's
wiki-link strip and double-space collapse, which destroy code indentation. Needs no run config.
Usage: rawq.py '<cypher>' [params-json]  -> prints JSON rows."""
import json
import os
import sys

from neo4j import GraphDatabase, READ_ACCESS


def main():
    q = sys.argv[1]
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    drv = GraphDatabase.driver(os.environ.get("NEO4J_URI", "bolt://host.docker.internal:7687"),
                               auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "password")))
    with drv.session(default_access_mode=READ_ACCESS) as s:
        rows = [dict(r) for r in s.run(q, **params)]
    drv.close()
    print(json.dumps(rows, default=str, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
