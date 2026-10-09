#!/usr/bin/env python3
"""test_carton_api — CartON's SDK over HTTP: the one door, the one call, over a REAL socket.

    python3 knowledge/carton-mcp/test_carton_api.py            # every case
    python3 knowledge/carton-mcp/test_carton_api.py t_a t_b    # only the named cases

Run as a SCRIPT. The package under test is THIS directory, loaded as `carton_mcp` from the file
system; heaven-framework comes from the monorepo beside it or from PYTHONPATH. The client here is
`call_carton` against `serve_in_thread`, never two mocks agreeing.

WHAT IT PINS:
  t_a  the enum IS the registry — every CartonOperation is a registered tool and the reverse
  t_b  an unset key leaves a loopback server open; with a key, absence and wrongness are both 401,
       checked before the body is read; the right key gets through
  t_c  the credentials come from the ENVIRONMENT, with no arguments passed — how MCP settings deliver them
  t_d  ⛔ a non-local bind with no key REFUSES TO START
  t_e  an unknown operation is refused by name; an operation's own error is a 400 carrying its message
  t_f  the metering seam: CARTON_CALL_GATE refuses with 402; unset, there is no gate; a bad spec fails loud
  t_g  call_carton with no CARTON_URL runs in-process; with one, it crosses the wire and the server's
       HEAVEN_DATA_DIR is the one written — the two-machine split: the box writes, the client never does
  t_h  every MCP tool is call_carton(<its name>, <its arguments>) + a render; the result is the server's
  t_j  the host's flags (the SM gate's files) and identity (the persona file) cross as headers and
       live only for the request that carried them
  t_k  the tools that touch the host's disk — equip_frame, the GPS flag, substrate_projector,
       add_document_concept's path guard — run on the host and never reach the box
  t_l  the retry stash is keyed by the caller when served
  t_i  a real operation end to end: add_concept over the wire lands in the SERVER's queue and
       query_wiki_graph answers rows (ladybug; skipped without it)
"""
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="carton_api_")
SERVER_HOME = os.path.join(TMP, "server")
CLIENT_HOME = os.path.join(TMP, "client")
os.makedirs(SERVER_HOME)
os.makedirs(CLIENT_HOME)
# The SERVER side of this process: an embedded graph of its own, no neo4j, no SOMA, no chroma.
os.environ.update({
    "HEAVEN_DATA_DIR": SERVER_HOME, "GRAPH_BACKEND": "kuzu", "KUZU_DB_PATH": os.path.join(SERVER_HOME, "graph"),
    "HEAVEN_ALLOW_STDOUT": "1", "CHROMA_DAEMON_PORT": "9", "SOMA_URL": "http://127.0.0.1:9/event",
})
for _k in ("CARTON_URL", "CARTON_KEY", "CARTON_USER", "CARTON_CALL_GATE", "CARTON_HOST", "NEO4J_URI"):
    os.environ.pop(_k, None)
_HF = os.path.join(HERE, "..", "..", "base", "heaven-framework")
if os.path.isdir(_HF):
    sys.path.insert(0, _HF)

_spec = importlib.util.spec_from_file_location("carton_mcp", os.path.join(HERE, "__init__.py"),
                                               submodule_search_locations=[HERE])
_pkg = importlib.util.module_from_spec(_spec)
sys.modules["carton_mcp"] = _pkg
_spec.loader.exec_module(_pkg)

from carton_mcp import carton_api as api  # noqa: E402

PASS, FAIL, SKIP = [], [], []


def _has_ladybug():
    try:
        import ladybug  # noqa: F401
        return True
    except ImportError:
        return False


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(url, path, body, key=None):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    if key is not None:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode())


def _status(fn):
    """The HTTP status a refused call came back with, or None when it was answered."""
    try:
        fn()
        return None
    except urllib.error.HTTPError as exc:
        return exc.code
    except api.CartonError as exc:
        return exc.status


def _echo(operation, params):
    """A stand-in dispatcher: answers what it was asked, so the WIRE is what is under test."""
    if operation == "boom":
        raise ValueError("the operation's own message")
    return {"operation": operation, "params": params, "home": os.environ.get("HEAVEN_DATA_DIR")}


def _serve(dispatch=_echo, **kw):
    port = _free_port()
    server, _ = api.serve_in_thread(port, host="127.0.0.1", dispatch=dispatch, **kw)
    return server, f"http://127.0.0.1:{port}"


def t_a_the_enum_is_the_registry():
    tools = api.operations()
    assert set(tools) == {op.value for op in api.CartonOperation}, sorted(tools)
    assert len(tools) == 31, len(tools)


def t_b_a_key_is_demanded_of_everyone_or_no_one():
    server, url = _serve(key="")
    try:
        code, ans = _post(url, "/call", {"operation": "query_wiki_graph", "params": {"x": 1}})
        assert code == 200 and ans["ok"] and ans["result"]["params"] == {"x": 1}, ans
    finally:
        server.shutdown(); server.server_close()
    server, url = _serve(key="secret")
    try:
        assert _status(lambda: _post(url, "/call", {"operation": "query_wiki_graph", "params": {}})) == 401
        assert _status(lambda: _post(url, "/call", {"operation": "query_wiki_graph", "params": {}}, key="nope")) == 401
        assert _status(lambda: _post(url, "/call", {"operation": "boom", "params": {}}, key="nope")) == 401, \
            "a wrong key reached the dispatcher — the key must be checked before the body"
        code, ans = _post(url, "/call", {"operation": "get_concept", "params": {"concept_name": "X"}}, key="secret")
        assert code == 200 and ans["result"]["operation"] == "get_concept", ans
        assert _status(lambda: urllib.request.urlopen(url + "/health", timeout=5)) == 401
    finally:
        server.shutdown(); server.server_close()


def t_c_the_credentials_come_from_the_environment():
    server, url = _serve(key="secret")
    prev = {k: os.environ.get(k) for k in ("CARTON_URL", "CARTON_KEY", "CARTON_USER")}
    try:
        os.environ.update(CARTON_URL=url, CARTON_KEY="secret", CARTON_USER="isaac")
        # NO arguments: exactly what a tenant's MCP settings produce.
        ans = api.call_carton("get_concept", {"concept_name": "X"})
        assert ans["operation"] == "get_concept" and ans["params"] == {"concept_name": "X"}, ans
        assert api.required_key() == "secret" and api.remote()
        os.environ["CARTON_KEY"] = "wrong"
        assert _status(lambda: api.call_carton("get_concept", {"concept_name": "X"})) == 401
    finally:
        server.shutdown(); server.server_close()
        for k, v in prev.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def t_d_a_non_local_bind_with_no_key_refuses_to_start():
    try:
        api.serve_in_thread(_free_port(), host="0.0.0.0", key="", dispatch=_echo)
        raise AssertionError("IT STARTED: an open bind with no key published the graph")
    except RuntimeError as exc:
        assert "without CARTON_KEY" in str(exc), exc


def t_e_unknown_operations_and_operation_errors_are_400_with_the_message():
    server, url = _serve(key="")
    try:
        code = _status(lambda: _post(url, "/call", {"operation": "boom", "params": {}}))
        assert code == 400, code
        try:
            _post(url, "/call", {"operation": "boom", "params": {}})
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode())
            assert "the operation's own message" in body["error"], body
        assert _status(lambda: _post(url, "/call", {"operation": 7, "params": {}})) == 400
        assert _status(lambda: _post(url, "/nowhere", {})) == 404
        # the real dispatcher refuses an unknown name BY NAME, before touching any tool
        try:
            api.execute("drop_everything", {})
            raise AssertionError("an unknown operation was dispatched")
        except api.CartonError as exc:
            assert exc.status == 400 and "drop_everything" in str(exc) and "add_concept" in str(exc), exc
    finally:
        server.shutdown(); server.server_close()


def t_f_the_metering_seam():
    gate_mod = os.path.join(TMP, "a_gate.py")
    with open(gate_mod, "w") as fh:
        fh.write("def gate(operation, params):\n"
                 "    if operation == 'add_concept' and params.get('concept_name', '').startswith('New_'):\n"
                 "        raise RuntimeError('node quota reached: growth refused, edits still pass')\n")
    sys.path.insert(0, TMP)
    prev = os.environ.get("CARTON_CALL_GATE")
    try:
        assert api.load_gate({}) is None, "an unset gate imported something"
        for bad in ("a_gate", "no_such_module:gate", "a_gate:nothing"):
            try:
                api.load_gate({"CARTON_CALL_GATE": bad})
                raise AssertionError(f"a bad gate spec {bad!r} did not fail loud")
            except (RuntimeError, ModuleNotFoundError):
                pass
        os.environ["CARTON_CALL_GATE"] = "a_gate:gate"
        server, url = _serve(key="")
        try:
            code = _status(lambda: _post(url, "/call", {"operation": "add_concept", "params": {"concept_name": "New_X"}}))
            assert code == 402, code
            code, ans = _post(url, "/call", {"operation": "add_concept", "params": {"concept_name": "Old_X"}})
            assert code == 200 and ans["ok"], ans
        finally:
            server.shutdown(); server.server_close()
    finally:
        sys.path.remove(TMP)
        os.environ.pop("CARTON_CALL_GATE", None) if prev is None else os.environ.__setitem__("CARTON_CALL_GATE", prev)


def t_g_call_carton_is_in_process_without_a_url_and_the_box_writes_with_one():
    # in-process: no URL, the dispatcher is `execute` — an unknown operation proves the path without a graph
    os.environ.pop("CARTON_URL", None)
    try:
        api.call_carton("not_an_operation", {})
        raise AssertionError("call_carton accepted a name that is not an operation")
    except ValueError:
        pass
    # over the wire: the server answers with ITS HEAVEN_DATA_DIR, the client never writes
    server, url = _serve(key="k")
    try:
        ans = api.call_carton("get_concept", {"concept_name": "X"}, url=url, key="k")
        assert ans["home"] == SERVER_HOME, ans
        try:
            api.call_carton("get_concept", {}, url="http://127.0.0.1:9", key="k", timeout=2)
            raise AssertionError("an unreachable box answered")
        except api.CartonError as exc:
            assert "unreachable" in str(exc), exc
    finally:
        server.shutdown(); server.server_close()


def t_h_every_tool_is_call_carton_plus_rendering():
    """With CARTON_URL set, a tool's body crosses the wire with exactly its arguments and renders the
    server's answer; the operation of the same name is what the server runs. No tool reaches a graph."""
    from carton_mcp import server_fastmcp
    import asyncio

    seen = []

    def dispatch(operation, params):
        seen.append((operation, params))
        if operation == "set_properties":
            return {"success": True, "updated_keys": sorted(params["properties"]), "trail": "scratch-lane"}
        if operation == "query_wiki_graph":
            return {"success": True, "data": [{"n": "Row", "gone": None}]}
        return f"served {operation}"

    server, url = _serve(dispatch=dispatch, key="k")
    prev = {k: os.environ.get(k) for k in ("CARTON_URL", "CARTON_KEY")}
    try:
        os.environ.update(CARTON_URL=url, CARTON_KEY="k")
        # the tool, called as the MCP calls it: arguments validated, then its body
        tool = server_fastmcp.mcp._tool_manager.get_tool("set_properties")
        out = asyncio.run(tool.run({"concept_name": "X", "properties": {"a": 1}}))
        assert out == "✅ X: set a\ntrail: scratch-lane", out
        assert seen[-1] == ("set_properties", {"concept_name": "X", "properties": {"a": 1}, "mode": "merge"}), seen[-1]
        # a read renders the server's rows; the server, not the tool, held the graph
        out = asyncio.run(server_fastmcp.mcp._tool_manager.get_tool("query_wiki_graph").run(
            {"cypher_query": "MATCH (c:Wiki) RETURN c.n AS n"}))
        assert "Row" in out, out
        assert seen[-1][0] == "query_wiki_graph" and seen[-1][1]["cypher_query"].startswith("MATCH"), seen[-1]
        # a pydantic argument crosses the wire as JSON
        asyncio.run(server_fastmcp.mcp._tool_manager.get_tool("add_concept").run(
            {"concept_name": "X", "is_a": ["T"], "part_of": [], "instantiates": [], "produces": [],
             "domain": "D", "subdomain": "S", "personal_domain": "misc",
             "relationships": [{"relationship": "has_part", "related": ["P"]}]}))
        assert seen[-1][0] == "add_concept", seen[-1]
        assert seen[-1][1]["relationships"] == [{"relationship": "has_part", "related": ["P"]}], seen[-1]
        assert seen[-1][1]["concept"] is None and seen[-1][1]["desc_update_mode"] == "append", seen[-1]
        # every tool has its operation, and the operation carries the tool's signature
        import inspect
        for name, fn in api.operations().items():
            tool = server_fastmcp.mcp._tool_manager.get_tool(name)
            assert list(inspect.signature(fn).parameters) == list(inspect.signature(tool.fn).parameters), name
    finally:
        server.shutdown(); server.server_close()
        for k, v in prev.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def t_j_the_hosts_flags_and_identity_cross_as_headers_and_live_only_for_the_request():
    """A flag on the agent's machine (the SM gate's enable file) and the persona it declared travel
    as headers; the serving thread reads them through request_flag/request_user for that request
    and nothing else; a second caller without them is served without them."""
    seen = []

    def dispatch(operation, params):
        seen.append((operation, api.request_user(), api.request_flag("sm_gate")))
        return "ok"

    server, url = _serve(dispatch=dispatch, key="")
    on_flag = os.path.join(TMP, "sm_on")
    off_flag = os.path.join(TMP, "sm_off")
    id_file = os.path.join(TMP, "active_identity")
    prev = {k: os.environ.get(k) for k in ("CARTON_URL", "CARTON_KEY", "CARTON_USER", "CARTON_SM_GATE_ENABLED",
                                           "CARTON_SM_GATE_DISABLED", "CARTON_SM_ACTIVE_IDENTITY", "AGENT_IDENTITY")}
    try:
        os.environ.update(CARTON_URL=url, CARTON_KEY="", CARTON_SM_GATE_ENABLED=on_flag,
                          CARTON_SM_GATE_DISABLED=off_flag, CARTON_SM_ACTIVE_IDENTITY=id_file)
        os.environ.pop("CARTON_USER", None); os.environ.pop("AGENT_IDENTITY", None)
        for f in (on_flag, off_flag, id_file):
            if os.path.exists(f):
                os.remove(f)
        # nothing on the host: no flag, no identity
        assert api.host_flags() == {"sm_gate": False}
        assert api.host_identity() == ""
        api.call_carton("get_concept", {"concept_name": "X"})
        assert seen[-1] == ("get_concept", "", False), seen[-1]
        # the host switches the gate on and a persona declares itself (sm_gate's own file)
        with open(on_flag, "w") as fh:
            fh.write("1")
        from carton_mcp import sm_gate
        import importlib
        importlib.reload(sm_gate)   # it reads CARTON_SM_ACTIVE_IDENTITY at import
        sm_gate.set_active_identity("starship_pilot")
        assert api.host_flags() == {"sm_gate": True}
        assert api.host_identity() == "starship_pilot"
        api.call_carton("get_concept", {"concept_name": "X"})
        assert seen[-1] == ("get_concept", "starship_pilot", True), seen[-1]
        # the kill switch on the host wins
        with open(off_flag, "w") as fh:
            fh.write("1")
        api.call_carton("get_concept", {"concept_name": "X"})
        assert seen[-1] == ("get_concept", "starship_pilot", False), seen[-1]
        # outside a request the serving thread holds nothing
        assert api.request_user() == "" and api.request_flag("sm_gate") is False
        # CARTON_USER names the caller over the persona
        os.environ["CARTON_USER"] = "acct-4"
        api.call_carton("get_concept", {"concept_name": "X"})
        assert seen[-1][1] == "acct-4", seen[-1]
    finally:
        server.shutdown(); server.server_close()
        for k, v in prev.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        from carton_mcp import sm_gate
        import importlib
        importlib.reload(sm_gate)


def t_k_the_tools_that_touch_the_hosts_disk_run_on_the_host():
    """With CARTON_URL set: equip_frame reads this machine's frames file, carton_management's GPS
    flag is this machine's file, substrate_projector's instructions and add_document_concept's path
    guard run here — none of them reaches the box; carton_management's other flags still do."""
    from carton_mcp import server_fastmcp
    import asyncio
    seen = []

    def dispatch(operation, params):
        seen.append((operation, params))
        return "served"

    server, url = _serve(dispatch=dispatch, key="")
    frames = os.path.join(TMP, "frames.json")
    data_dir = os.path.join(TMP, "heaven_data_k")
    prev = {k: os.environ.get(k) for k in ("CARTON_URL", "CARTON_KEY", "CARTON_FRAMES_PATH", "HEAVEN_DATA_DIR")}
    try:
        os.environ.update(CARTON_URL=url, CARTON_KEY="", CARTON_FRAMES_PATH=frames, HEAVEN_DATA_DIR=data_dir)
        with open(frames, "w") as fh:
            json.dump({"my_frame": "Observe: the thing"}, fh)
        run = lambda name, args: asyncio.run(server_fastmcp.mcp._tool_manager.get_tool(name).run(args))  # noqa: E731
        out = run("equip_frame", {"frame": "my_frame"})
        assert "Observe: the thing" in out and seen == [], (out, seen)
        out = run("carton_management", {"enable_gps": True, "get_gps_status": True})
        assert "ENABLED" in out and os.path.exists(os.path.join(data_dir, "carton_gps_enabled")) and seen == [], (out, seen)
        out = run("carton_management", {"disable_gps": True, "get_carton_dir": True})
        assert "disabled" in out and "served" in out and seen[-1][0] == "carton_management", (out, seen)
        assert seen[-1][1]["get_carton_dir"] is True and seen[-1][1]["disable_gps"] is False, seen[-1]
        seen.clear()
        out = run("substrate_projector", {"get_instructions": True})
        assert "substrate" in out.lower() and seen == [], (out[:80], seen)
        out = run("add_document_concept", {"concept_name": "Doc_X", "description": "d", "canonical_path": "/nowhere/outside/doc.md"})
        assert out.startswith("❌ REFUSED") and seen == [], (out, seen)
        inside = os.path.join(data_dir, "docs", "doc.md")
        run("add_document_concept", {"concept_name": "Doc_X", "description": "d", "canonical_path": inside})
        assert seen[-1][0] == "add_document_concept" and seen[-1][1]["canonical_path"] == inside, seen[-1]
    finally:
        server.shutdown(); server.server_close()
        for k, v in prev.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def t_l_the_stash_is_the_callers_when_served():
    from carton_mcp import server_fastmcp
    prev = api.SERVING
    try:
        api.SERVING = False
        assert server_fastmcp._stash_key("X") == "X"
        api.SERVING = True
        api._set_request("alice", {})
        assert server_fastmcp._stash_key("X") == ("alice", "X")
        api._set_request("bob", {})
        assert server_fastmcp._stash_key("X") == ("bob", "X")
    finally:
        api._clear_request()
        api.SERVING = prev


def t_i_a_real_operation_end_to_end_on_ladybug():
    if not _has_ladybug():
        SKIP.append("t_i (no ladybug)")
        return
    from carton_mcp import server_fastmcp
    from carton_mcp.add_concept_tool import get_observation_queue_dir

    port = _free_port()
    server, _ = api.serve_in_thread(port, host="127.0.0.1", key="k")   # the REAL dispatcher
    url = f"http://127.0.0.1:{port}"
    prev = {k: os.environ.get(k) for k in ("CARTON_URL", "CARTON_KEY")}
    try:
        assert api.SERVING
        queue = get_observation_queue_dir()
        before = set(p.name for p in queue.glob("*.json"))
        text = api.call_carton("add_concept", {
            "concept_name": "Api_Probe", "concept": "a probe over the wire", "is_a": ["Probe"], "part_of": [],
            "instantiates": [], "produces": [], "domain": "Carton_Api", "subdomain": "Test", "personal_domain": "misc",
            "hide_youknow": True}, url=url, key="k")
        assert isinstance(text, str) and "Api_Probe" in text and not text.startswith("❌"), text
        new = set(p.name for p in queue.glob("*.json")) - before
        assert len(new) == 1, f"add_concept over the wire did not write ONE entry into the server's queue: {new}"
        assert not os.listdir(CLIENT_HOME), "the client's disk was written"
        graph = server_fastmcp._graph_conn()
        graph.execute_query("MERGE (c:Wiki {n: 'Api_Row'}) ON CREATE SET c.d = 'row'", {})
        # a program reads DATA through the door: the operation answers the facade's envelope, rows with their
        # null columns — the rendering is the TOOL's, on the caller's side
        env = api.call_carton("query_wiki_graph", {"cypher_query": "MATCH (c:Wiki {n: 'Api_Row'}) RETURN c.n AS n, c.nothing AS gone"},
                              url=url, key="k")
        assert env["success"] and env["data"][0] == {"n": "Api_Row", "gone": None}, env
        rendered = server_fastmcp.query_wiki_graph("MATCH (c:Wiki {n: 'Api_Row'}) RETURN c.n AS n, c.nothing AS gone")
        assert isinstance(rendered, str) and "Api_Row" in rendered, rendered
        # the read facade refuses a write verb: there is no Cypher pipe through this door
        env = api.call_carton("query_wiki_graph", {"cypher_query": "MERGE (c:Wiki {n: 'Api_Pipe'}) RETURN c"}, url=url, key="k")
        assert env["success"] is False and "add_concept" in env["error"], env
        # the worker cannot restart itself from inside its own request
        said = api.call_carton("carton_management", {"restart_bg_server": True}, url=url, key="k")
        assert "supervisor" in said, said
    finally:
        server.shutdown(); server.server_close()
        for k, v in prev.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


if __name__ == "__main__":
    only = set(sys.argv[1:])
    print("carton's SDK over HTTP\n")
    try:
        for name, fn in sorted((k, v) for k, v in list(globals().items()) if k.startswith("t_")):
            if only and not any(name.startswith(o) for o in only):
                continue
            try:
                fn()
                if any(s.startswith(name.split("_")[0] + "_") for s in SKIP):
                    print(f"  SKIP  {name}")
                else:
                    PASS.append(name)
                    print(f"  PASS  {name}")
            except AssertionError as exc:
                FAIL.append(name)
                print(f"  FAIL  {name}\n        {exc}")
            except Exception:
                import traceback
                FAIL.append(name)
                print(f"  ERROR {name}\n{traceback.format_exc()}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped")
    raise SystemExit(1 if FAIL else 0)
