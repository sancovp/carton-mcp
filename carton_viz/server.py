"""carton_viz — CartON's OWN frontend (the first one; seeds the carton-saas UI tier).

A dependency-free sidecar (stdlib http.server — the OM conversations-sidecar precedent)
serving a self-contained graph visualizer over the LIVE CartON neo4j:

    GET /                       → viz.html (the whole frontend, one file, no build step)
    GET /api/search?q=          → concept names matching q (name CONTAINS, cheap)
    GET /api/network?concept=&depth=&limit=   → {nodes, links} for the force graph
    GET /api/concept?name=      → one concept's detail (description, labels, degree)
    GET /health

Transport = neo4j's HTTP tx endpoint (same env contract as onionmorph's carton_kanban:
NEO4J_HTTP_URL [http://localhost:7474] · NEO4J_USER · NEO4J_PASSWORD) — no bolt driver,
no carton_mcp import, runs on any python3. READ-ONLY by construction: every query here
is a MATCH; there is no write path.

Run:  python3 -m carton_viz.server            (port CARTON_VIZ_PORT, default 8794)
OM iframes it as the 🕸 CartON panel (DESIGN §31).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("CARTON_VIZ_PORT", "8794"))
NEO4J_HTTP_URL = os.environ.get("NEO4J_HTTP_URL", "http://localhost:7474")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")
_TX = f"{NEO4J_HTTP_URL}/db/neo4j/tx/commit"
HTML = Path(__file__).parent / "viz.html"


def _cypher(query: str, params: dict) -> list:
    """One statement against the HTTP tx endpoint → list of row dicts (keyed by RETURN names)."""
    body = json.dumps({"statements": [{"statement": query, "parameters": params}]}).encode()
    req = urllib.request.Request(_TX, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Basic " + base64.b64encode(f"{NEO4J_USER}:{NEO4J_PASSWORD}".encode()).decode(),
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.loads(r.read())
    if payload.get("errors"):
        raise RuntimeError(payload["errors"][0].get("message", "neo4j error"))
    res = payload["results"][0]
    cols = res["columns"]
    return [dict(zip(cols, row["row"])) for row in res["data"]]


def api_search(q: str) -> dict:
    if not q or len(q) < 2:
        return {"results": []}
    rows = _cypher(
        "MATCH (n:Wiki) WITH n, coalesce(n.name, n.n) AS nm "
        "WHERE nm IS NOT NULL AND toLower(nm) CONTAINS toLower($q) "
        "RETURN nm AS name, left(coalesce(n.description, n.d, ''), 140) AS blurb "
        "ORDER BY size(nm) LIMIT 25", {"q": q})
    return {"results": rows}


def api_network(concept: str, depth: int, limit: int) -> dict:
    depth = max(1, min(3, depth))
    limit = max(10, min(800, limit))
    # edges: distinct relationships on paths out to `depth` hops (bounded — hub nodes exist)
    rels = _cypher(
        "MATCH (start:Wiki) WHERE coalesce(start.name, start.n) = $name "
        f"MATCH path = (start)-[*1..{depth}]-(:Wiki) "
        f"WITH relationships(path) AS rs LIMIT {limit * 4} "
        "UNWIND rs AS r "
        "MATCH (a)-[r]->(b) "   # endpoints as VARIABLES (startNode(r).name nulls over the HTTP tx endpoint)
        "WITH DISTINCT coalesce(a.name, a.n) AS source, type(r) AS rel, coalesce(b.name, b.n) AS target "
        "WHERE source IS NOT NULL AND target IS NOT NULL "
        f"RETURN source, rel, target LIMIT {limit}", {"name": concept})
    names = {concept} | {r["source"] for r in rels} | {r["target"] for r in rels}
    nodes = _cypher(
        "MATCH (n) WITH n, coalesce(n.name, n.n) AS nm WHERE nm IN $names "
        "RETURN DISTINCT nm AS name, left(coalesce(n.description, n.d, ''), 160) AS blurb, "
        "labels(n) AS labels", {"names": list(names)})   # degree = client-side from links
    return {"concept": concept, "depth": depth,
            "nodes": nodes, "links": rels,
            "truncated": len(rels) >= limit}


def api_concept(name: str) -> dict:
    rows = _cypher(
        "MATCH (n:Wiki) WHERE coalesce(n.name, n.n) = $name "
        "OPTIONAL MATCH (n)-[r]-(m) "
        "WITH n, type(r) AS rel, coalesce(m.name, m.n) AS neighbor LIMIT 80 "
        "RETURN coalesce(n.name, n.n) AS name, coalesce(n.description, n.d) AS description, "
        "labels(n) AS labels, collect({rel: rel, neighbor: neighbor}) AS neighbors", {"name": name})
    if not rows:
        return {"error": f"no concept named {name!r}"}
    row = rows[0]
    row["neighbors"] = [x for x in (row.get("neighbors") or []) if x.get("neighbor")]
    return row


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/" or u.path == "/index.html":
                body = HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/health":
                self._json({"status": "ok", "neo4j": NEO4J_HTTP_URL})
            elif u.path == "/api/search":
                self._json(api_search(q.get("q", "")))
            elif u.path == "/api/network":
                self._json(api_network(q.get("concept", ""), int(q.get("depth", "1")),
                                       int(q.get("limit", "200"))))
            elif u.path == "/api/concept":
                self._json(api_concept(q.get("name", "")))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 500)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"carton_viz on http://127.0.0.1:{PORT} (neo4j: {NEO4J_HTTP_URL})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
