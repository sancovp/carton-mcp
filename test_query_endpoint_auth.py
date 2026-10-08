"""test_query_endpoint_auth — credentials on the graph query endpoint.

Run: python3 test_query_endpoint_auth.py     (exit 0 = pass)

THE SHAPE THIS PINS. A tenant puts their user + key in their MCP settings; the
client reads them from the environment and sends them to the server; the server
checks the key. Nothing is negotiated, minted or stored — that is the whole
protocol, and each half is tested against the other over a real socket rather
than as two mocks agreeing with each other.

WHY EACH CASE IS HERE:

  - UNSET KEY MUST BE BYTE-IDENTICAL. The in-box wire between the worker and the
    other processes has no credentials and needs none; it is unreachable from
    outside. If adding auth changed that path, every existing box would break on
    upgrade for a feature none of them asked for.
  - A KEY MUST REFUSE BOTH ABSENCE AND WRONGNESS. "Sometimes authenticated" is
    indistinguishable from unauthenticated.
  - THE ENV PATH IS THE REAL PATH. The client must authenticate with NO arguments
    passed, because that is how MCP settings deliver it — anything that only works
    when a caller remembers to pass a key is not the feature.
  - ⛔ THE LOAD-BEARING ONE: a non-local bind with no key must REFUSE TO START.
    That combination publishes the tenant's entire graph to the network
    unauthenticated, and it is the only failure here that looks completely healthy
    while it is happening.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/GOD/gnosys-plugin-v2/base/heaven-framework")

import kuzu_query_endpoint as ep  # noqa: E402
from heaven_base.tool_utils.graph_store import KuzuHttpStore  # noqa: E402

PASS = FAIL = 0
ROWS = [{"n": "A"}]


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label} {detail}")


class _Store:
    def execute(self, query, params):
        return ROWS


def _refused(fn):
    """True if the call was refused with a 401 rather than answered."""
    try:
        fn()
        return False
    except Exception as exc:
        return "401" in str(exc) or "unauthorized" in str(exc).lower()


def main():
    print("== an unset key leaves the in-box wire UNCHANGED ==")
    server, _ = ep.serve_in_thread(_Store(), port=18811, host="127.0.0.1", key="")
    try:
        store = KuzuHttpStore("http://127.0.0.1:18811", user="", key="")
        check("no credentials, still answers", store.execute("MATCH (n) RETURN n", {}) == ROWS)
    finally:
        server.shutdown()

    print("== with a key, absence and wrongness are both refused ==")
    server, _ = ep.serve_in_thread(_Store(), port=18812, host="127.0.0.1", key="secret")
    try:
        check("no key -> 401", _refused(
            lambda: KuzuHttpStore("http://127.0.0.1:18812", user="", key="").execute("q", {})))
        check("wrong key -> 401", _refused(
            lambda: KuzuHttpStore("http://127.0.0.1:18812", user="", key="nope").execute("q", {})))
        check("right key gets through", KuzuHttpStore(
            "http://127.0.0.1:18812", user="isaac", key="secret").execute("q", {}) == ROWS)
    finally:
        server.shutdown()

    print("== the credentials come from the ENVIRONMENT (MCP settings) ==")
    prev = {k: os.environ.get(k) for k in ("CARTON_USER", "CARTON_KEY")}
    os.environ["CARTON_USER"], os.environ["CARTON_KEY"] = "isaac", "secret"
    server, _ = ep.serve_in_thread(_Store(), port=18813, host="127.0.0.1", key="secret")
    try:
        # NO arguments: exactly what a tenant's MCP settings produce.
        check("env-configured client authenticates with no args",
              KuzuHttpStore("http://127.0.0.1:18813").execute("q", {}) == ROWS)
        check("and the server read its key from the env too", ep.required_key() == "secret")
    finally:
        server.shutdown()
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print("== a non-local bind with NO key REFUSES to start ==")
    try:
        ep.serve_in_thread(_Store(), port=18814, host="0.0.0.0", key="")
        check("refused to publish an unauthenticated graph", False, "IT STARTED")
    except RuntimeError as exc:
        check("refused to publish an unauthenticated graph",
              "without CARTON_KEY" in str(exc), str(exc)[:90])

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
