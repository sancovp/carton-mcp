"""Tests for the CARTON_EXTRA_ROUTES seam on kuzu_query_endpoint (run as a SCRIPT, repo root).

Client against server over a REAL socket — never two mocks agreeing (the repo's own law from
test_query_endpoint_auth.py). Covers: fall-through unchanged with no hook; GET/POST/PUT/DELETE
routing with parsed args/body; auth checked BEFORE the hook; hook exception -> 400 with the
message; hook None -> 404; bad spec fails loud at startup; core routes untouched.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kuzu_query_endpoint import load_extra_routes, serve_in_thread  # noqa: E402

RESULTS = []


def check(name, cond):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)


class DummyStore:
    def execute(self, query, params):
        return [{"echo": query}]

    def set_properties(self, name, props):
        pass

    def remove_properties(self, name, keys):
        pass

    def find_by_properties(self, where, limit):
        return []


def _req(port, path, method="GET", body=None, key=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# The extra hook under test: echoes routing facts; raises on demand; None on /api/none.
def extra(path, method, args, body):
    if path == "/api/none":
        return None
    if path == "/api/boom":
        raise ValueError("kaboom")
    if path == "/api/list":
        # A BARE-LIST payload — the shape the real kanban clients consume
        # (HeavenBMLSQLiteClient iterates response.json() for GET cards).
        return [{"id": "a"}, {"id": "b"}], 200
    if path.startswith("/api/"):
        return {"routed": True, "path": path, "method": method,
                "args": args, "body": body}, 200
    return None


def main():
    # 1. NO hook configured: behaviour is byte-identical to before the seam.
    os.environ.pop("CARTON_EXTRA_ROUTES", None)
    os.environ.pop("CARTON_KEY", None)
    server, _ = serve_in_thread(DummyStore(), port=0, host="127.0.0.1", key="")
    port = server.server_address[1]
    s, b = _req(port, "/api/anything")
    check("no-hook GET non-health 404", s == 404)
    s, b = _req(port, "/api/anything", method="POST", body={})
    check("no-hook POST unknown path 400", s == 400 and "unknown path" in b.get("error", ""))
    s, b = _req(port, "/api/anything", method="PUT", body={})
    check("no-hook PUT 404", s == 404)
    server.shutdown()

    # 2. Hook configured (this very module provides `extra`): all four methods route.
    os.environ["CARTON_EXTRA_ROUTES"] = "test_extra_routes:extra"
    server, _ = serve_in_thread(DummyStore(), port=0, host="127.0.0.1", key="")
    port = server.server_address[1]
    s, b = _req(port, "/api/sqlite/cards?board=b1")
    check("GET routed with parsed args", s == 200 and b["routed"] and b["args"] == {"board": "b1"})
    s, b = _req(port, "/api/sqlite/cards", method="POST", body={"title": "t"})
    check("POST routed with body", s == 200 and b["method"] == "POST" and b["body"] == {"title": "t"})
    s, b = _req(port, "/api/sqlite/cards/7", method="PUT", body={"lane": "build"})
    check("PUT routed", s == 200 and b["method"] == "PUT" and b["body"] == {"lane": "build"})
    s, b = _req(port, "/api/sqlite/cards/7", method="DELETE")
    check("DELETE routed", s == 200 and b["method"] == "DELETE")
    s, b = _req(port, "/api/list")
    check("bare-list payload passes through VERBATIM (never wrapped)",
          s == 200 and b == [{"id": "a"}, {"id": "b"}])
    s, b = _req(port, "/api/none")
    check("hook None falls through to 404", s == 404)
    s, b = _req(port, "/api/boom")
    check("hook exception -> 400 with message", s == 400 and "kaboom" in b.get("error", ""))
    s, b = _req(port, "/query", method="POST", body={"query": "Q"})
    check("core /query untouched", s == 200 and b["ok"] and b["result"] == [{"echo": "Q"}])
    s, b = _req(port, "/health")
    check("core /health untouched", s == 200 and b["ok"])
    server.shutdown()

    # 3. Auth precedes the hook: with a key set, an extra route without the key is 401.
    server, _ = serve_in_thread(DummyStore(), port=0, host="127.0.0.1", key="sekrit")
    port = server.server_address[1]
    s, b = _req(port, "/api/sqlite/cards?board=b1")
    check("keyed server: extra route without key 401", s == 401)
    s, b = _req(port, "/api/sqlite/cards?board=b1", key="sekrit")
    check("keyed server: extra route with key routes", s == 200 and b["routed"])
    server.shutdown()

    # 4. Bad spec fails LOUD at startup (never silently serves without the routes).
    os.environ["CARTON_EXTRA_ROUTES"] = "no_such_module_xyz:fn"
    try:
        load_extra_routes()
        check("bad spec raises", False)
    except Exception:
        check("bad spec raises", True)
    os.environ["CARTON_EXTRA_ROUTES"] = "test_extra_routes"  # no colon
    try:
        load_extra_routes()
        check("colonless spec raises", False)
    except RuntimeError:
        check("colonless spec raises", True)
    os.environ.pop("CARTON_EXTRA_ROUTES", None)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
