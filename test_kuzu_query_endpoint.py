#!/usr/bin/env python3
"""THE SINGLE-WRITER GATE — one process owns the kuzu file, another reads it over localhost.

    python3 knowledge/carton-mcp/test_kuzu_query_endpoint.py

Run as a SCRIPT (this repo's convention — the repo root IS the `carton_mcp` package).

WHY A SECOND PROCESS IS THE ONLY HONEST TEST. The owner holds the database directory: a second
read-write open is refused by the lock, and a second read_only open is refused (kuzu 0.11.3) or
served a stale snapshot (ladybug), which is the entire reason this endpoint exists. A test
that serves and queries inside ONE process proves nothing about that: it would pass just as well
if the client were quietly opening the file itself. So the client here is a genuine subprocess
that is given ONLY `KUZU_QUERY_URL` — never `KUZU_DB_PATH` — and the assertion is that it reads
and writes the owner's data anyway.

It also pins the property that makes the design structural rather than remembered: a process
holding a `KuzuHttpStore` has `driver is None` and no file handle, so it CANNOT open a second
handle by accident.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "base", "heaven-framework"))

from kuzu_query_endpoint import serve_in_thread  # noqa: E402
from heaven_base.tool_utils.graph_store import KuzuStore, KuzuHttpStore, make_store  # noqa: E402

PASS, FAIL = [], []
PORT = 8199  # not the default, so a real worker's endpoint is never touched by the gate


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  PASS  {name}")
    except AssertionError as exc:
        FAIL.append(name)
        print(f"  FAIL  {name}\n        {exc}")
    except Exception:
        import traceback
        FAIL.append(name)
        print(f"  ERROR {name}\n{traceback.format_exc()}")


def _has_kuzu():
    """Whether the engine the seam imports (`ladybug`) is installed."""
    try:
        from heaven_base.tool_utils.graph_store import _engine
        _engine()
        return True
    except ImportError:
        return False


def test_ENGINE_UNDER_TEST():
    """Names the engine this run proved, so a green run says what it was green ON."""
    if not _has_kuzu():
        raise AssertionError("ladybug is not installed — this gate cannot verify the thing it exists for")
    from heaven_base.tool_utils.graph_store import _engine
    eng = _engine()
    print(f"ENGINE {eng.__name__} {eng.__version__}")


CLIENT = r'''
import os, sys, json
sys.path.insert(0, os.environ["HF"])
from heaven_base.tool_utils.graph_store import make_store
# This subprocess is given KUZU_QUERY_URL and NOT KUZU_DB_PATH: it physically cannot open the file.
store = make_store("", "", "")
print("STORE " + type(store).__name__)
print("DRIVER " + repr(store.driver))
rows = store.execute("MATCH (c:Wiki) RETURN count(c) AS n", {})
print("COUNT " + json.dumps(rows, default=str))
store.execute("MERGE (x:Wiki {n:$n}) ON CREATE SET x.d=$d", {"n": "From_Client", "d": "written over http"})
store.set_properties("From_Client", {"status": "open"})
found = store.find_by_properties({"status": "open"}, 5)
print("FOUND " + json.dumps(found, default=str))
'''


def test_a_SEPARATE_PROCESS_reads_and_writes_the_owners_database_over_localhost():
    if not _has_kuzu():
        raise AssertionError("ladybug is not installed — this gate cannot verify the thing it exists for")
    tmp = tempfile.mkdtemp(prefix="kuzu_endpoint_gate_")
    server = None
    try:
        owner = KuzuStore(os.path.join(tmp, "db"))
        owner.execute("MERGE (a:Wiki {n:'Owned_A'}) ON CREATE SET a.d='seeded by the owner'", {})
        owner.execute("MERGE (b:Wiki {n:'Owned_B'}) ON CREATE SET b.d='also the owner'", {})
        server, _ = serve_in_thread(owner, PORT)

        env = dict(os.environ, GRAPH_BACKEND="kuzu",
                   KUZU_QUERY_URL=f"http://127.0.0.1:{PORT}",
                   HF=os.path.join(HERE, "..", "..", "base", "heaven-framework"))
        env.pop("KUZU_DB_PATH", None)  # the point: the client is never told where the file is
        proc = subprocess.run([sys.executable, "-c", CLIENT], capture_output=True, text=True, env=env)
        assert proc.returncode == 0, f"client failed:\n{proc.stdout}\n{proc.stderr[-1500:]}"
        # BOTH STREAMS. Importing heaven_base REASSIGNS sys.stdout to stderr (stdio-MCP hygiene —
        # a stray print would corrupt the protocol on that transport), so the client's output
        # arrives on stderr and reading stdout alone finds an empty string. This is the same trap
        # the parity harnesses document, and this test walked into it on its first run: the
        # client was working perfectly and the assertion failed with a blank message.
        out = (proc.stdout or "") + (proc.stderr or "")

        assert "STORE KuzuHttpStore" in out, out
        assert "DRIVER None" in out, f"a client must hold NO driver and no file handle:\n{out}"
        count = json.loads(out.split("COUNT ", 1)[1].split("\n", 1)[0])
        assert count and count[0]["n"] == 2, f"the client did not see the owner's 2 nodes: {count}"
        found = json.loads(out.split("FOUND ", 1)[1].split("\n", 1)[0])
        assert any(r.get("n") == "From_Client" for r in found), found

        # …and the OWNER sees what the client wrote, which is the round trip closing.
        back = owner.execute("MATCH (c:Wiki {n:'From_Client'}) RETURN c.n AS n, c.status AS s", {})
        assert back and back[0]["n"] == "From_Client", back
        assert back[0]["s"] == "open", f"the property write did not reach the owner: {back}"
        owner.close()
    finally:
        if server is not None:
            server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_FAILED_QUERY_arrives_as_the_ENGINES_OWN_MESSAGE_not_a_bare_status():
    """Every dialect delta in this port was found by reading an engine error. If the endpoint
    flattened them to a status code, the seam built to expose them would hide them instead."""
    if not _has_kuzu():
        raise AssertionError("ladybug is not installed")
    tmp = tempfile.mkdtemp(prefix="kuzu_endpoint_err_")
    server = None
    try:
        owner = KuzuStore(os.path.join(tmp, "db"))
        server, _ = serve_in_thread(owner, PORT + 1)
        client = KuzuHttpStore(f"http://127.0.0.1:{PORT + 1}")
        try:
            client.execute("MATCH (c:Wiki) RETURN valueType(c.t) AS vt", {})
        except RuntimeError as exc:
            assert "VALUETYPE" in str(exc).upper(), f"the engine's own message was lost: {exc}"
            owner.close()
            return
        raise AssertionError("a catalog error was not surfaced to the client at all")
    finally:
        if server is not None:
            server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_UNREACHABLE_endpoint_says_WHY_rather_than_failing_obscurely():
    client = KuzuHttpStore("http://127.0.0.1:9")  # discard port: nothing listens, ever
    try:
        client.execute("MATCH (c:Wiki) RETURN 1", {})
    except RuntimeError as exc:
        assert "unreachable" in str(exc), exc
        assert "worker owns the database file" in str(exc), f"the message must name the cause: {exc}"
        return
    raise AssertionError("an unreachable endpoint did not raise")


def test_KUZU_QUERY_URL_WINS_over_a_path_so_a_told_process_never_opens_the_file():
    prev = {k: os.environ.get(k) for k in ("GRAPH_BACKEND", "KUZU_QUERY_URL", "KUZU_DB_PATH")}
    os.environ.update(GRAPH_BACKEND="kuzu", KUZU_QUERY_URL="http://127.0.0.1:9",
                      KUZU_DB_PATH="/tmp/should-never-be-opened")
    try:
        store = make_store("", "", "")
        assert isinstance(store, KuzuHttpStore), type(store)
        assert store.driver is None
    finally:
        for key, value in prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_an_EMPTY_query_url_means_OWNER_which_is_how_the_WORKER_opts_OUT():
    """⛔ THE HAZARD THIS EXISTS TO CLOSE, found while wiring the box (2026-08-12).

    In the box, all three supervisord programs share the container's environment. If
    `KUZU_QUERY_URL` is set container-wide — the obvious way to tell the MCP server and the
    ontology check where to ask — then the WORKER reads it too, becomes a client of ITSELF, and
    NOBODY OPENS THE FILE. The box would come up with every process politely asking an endpoint
    that no process is serving.

    The escape is that the worker's own program sets `KUZU_QUERY_URL=""`, and an EMPTY url means
    OWNER. That is one falsy check in `make_store`, which is exactly the kind of thing that gets
    "tidied" into `is not None` by someone who cannot see why it matters — so it is pinned here,
    with the reason, rather than left as an implementation detail.
    """
    prev = {k: os.environ.get(k) for k in ("GRAPH_BACKEND", "KUZU_QUERY_URL", "KUZU_DB_PATH")}
    tmp = tempfile.mkdtemp(prefix="kuzu_owner_optout_")
    os.environ.update(GRAPH_BACKEND="kuzu", KUZU_QUERY_URL="",
                      KUZU_DB_PATH=os.path.join(tmp, "db"))
    try:
        store = make_store("", "", "")
        assert isinstance(store, KuzuStore), (
            f"an empty KUZU_QUERY_URL must mean OWNER, got {type(store).__name__} — "
            "the worker would have become a client of itself and nothing would own the file")
        store.close()
    finally:
        for key, value in prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_endpoint_binds_LOOPBACK_BY_DEFAULT_so_an_existing_box_is_unchanged():
    """The DEFAULT bind, which is the whole backward-compatibility guarantee.

    ⚠ THE NAME OF THIS TEST USED TO END "...because it has no authentication", and that
    reason is now FALSE: the endpoint DOES authenticate — `CARTON_KEY` is checked before the
    body is read, and a non-local bind without one refuses to start (test_query_endpoint_auth).
    What is still true, and what this pins, is the DEFAULT: unset host and unset key give the
    private in-box wire exactly as before, so upgrading a box changes nothing until an operator
    deliberately opens it. Left renamed rather than deleted — a test whose name tells the next
    reader the opposite of the truth keeps passing while misinforming them.
    """
    if not _has_kuzu():
        raise AssertionError("ladybug is not installed")
    tmp = tempfile.mkdtemp(prefix="kuzu_endpoint_bind_")
    server = None
    try:
        owner = KuzuStore(os.path.join(tmp, "db"))
        server, _ = serve_in_thread(owner, PORT + 2)
        assert server.server_address[0] == "127.0.0.1", server.server_address
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT + 2}/health", timeout=5) as resp:
            body = json.loads(resp.read().decode())
        assert body["ok"] and body["result"]["backend"] == "kuzu", body
        owner.close()
    finally:
        if server is not None:
            server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    print("kuzu query endpoint gate (single-writer)\n")
    for name, fn in sorted((k, v) for k, v in list(globals().items()) if k.startswith("test_")):
        check(name, fn)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    raise SystemExit(1 if FAIL else 0)
