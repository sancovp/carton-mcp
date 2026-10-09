"""test_worker_env — the worker demands the STORE'S OWN variables: the Ladybug file's path on kuzu, the three
NEO4J_* on neo4j — never neo4j's on a Ladybug box (the first driver-made box exited on exactly that).
Run: python3 test_worker_env.py   (exit 0 = pass). The function is pure; it is loaded from the source so the test
needs none of the worker's imports."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "observation_worker_daemon.py")).read()
i = src.index("def store_env_missing"); j = src.index('if __name__ == "__main__":', i)
ns = {}; exec(src[i:j], ns); m = ns["store_env_missing"]
checks = [
    ("a driver-made box: kuzu + the path, no neo4j", m({"GRAPH_BACKEND": "kuzu", "KUZU_DB_PATH": "/data/heaven/kuzu"}) == []),
    ("kuzu is the default backend", m({"KUZU_DB_PATH": "/x"}) == []),
    ("kuzu without its path is refused", m({"GRAPH_BACKEND": "kuzu"}) == ["KUZU_DB_PATH"]),
    ("neo4j demands its three", sorted(m({"GRAPH_BACKEND": "neo4j"})) == ["NEO4J_PASSWORD", "NEO4J_URI", "NEO4J_USER"]),
    ("neo4j with its three passes", m({"GRAPH_BACKEND": "neo4j", "NEO4J_URI": "b", "NEO4J_USER": "u", "NEO4J_PASSWORD": "p"}) == []),
]
fails = [name for name, ok in checks if not ok]
for name, ok in checks: print(("  PASS  " if ok else "  FAIL  ") + name)
print(f"{len(checks)-len(fails)} passed, {len(fails)} failed"); sys.exit(1 if fails else 0)
