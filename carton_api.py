"""CartON's SDK over HTTP — the ONE door a box serves, and the ONE call everything else holds.

THE SHAPE. The SDK's operations are the MCP's tools (`server_fastmcp.py`): the MCP is the SDK plus
rendering, so its tool list IS the SDK's function list, and `CartonOperation` names exactly those.
The worker — the process that owns the graph file and drains the queue — is CartON's server: it
serves every operation on

    POST /call  {"operation": "<CartonOperation>", "params": {...}}   → {"ok": true, "result": ...}
    GET  /health                                                       → {"ok": true, "result": {...}}

behind the account's key, and a caller holds one function:

    call_carton(operation, params) -> the operation's result

Self-hosted (no `CARTON_URL`): `call_carton` runs the operation in this process. Hosted: it POSTs to
the box. Every MCP tool's body is exactly `call_carton(<tool>, <its arguments>)` plus the rendering
of the answer, so on a tenant's own machine the MCP holds no CartON logic; Ribcage and every other
program call the same door. Everything an operation touches — the graph, SOMA, the queue, the wiki
files, chroma — is in the box, so every operation runs there and a call crosses the wire once.
Each operation is registered beside its tool in `server_fastmcp.py` with `@operation(name)`: the
same signature, no rendering, answering the SDK's data (a read answers the facade's envelope of rows;
a write answers the SDK's text).

THE LAWS, each pinned in `test_carton_api.py`:
  - HOST AND KEY MOVE TOGETHER: binding anywhere but 127.0.0.1 with no `CARTON_KEY` REFUSES TO START.
  - the key is checked before the body is read; an absent key and a wrong key are both 401.
  - only a `CartonOperation` is dispatched — anything else is a 400 naming the operation.
  - an operation's own failure arrives as a 400 carrying its message, never a swallowed 500.
  - THE METERING SEAM: `CARTON_CALL_GATE` names `module:function`; `gate(operation, params)` raises
    to refuse (402). Billing is the operator's and never enters this open-source package; unset
    means no gate and no import.
  - the client sends `Authorization: Bearer <CARTON_KEY>` and `X-Carton-User: <CARTON_USER>` from
    the environment — that is how MCP settings deliver them; nothing is negotiated, minted or
    stored.
  - the registry and the enum agree: every `CartonOperation` is a registered tool and every
    registered tool is a `CartonOperation`.

Env — the client: `CARTON_URL` (the box; unset = in-process) · `CARTON_KEY` · `CARTON_USER` ·
`CARTON_TIMEOUT_S` (default 120). The server: `CARTON_HOST` (default 127.0.0.1) · `CARTON_PORT`
(default 8192) · `CARTON_KEY` · `CARTON_CALL_GATE`.
"""
from __future__ import annotations

import asyncio
import enum
import inspect
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8192
DEFAULT_TIMEOUT_S = 120.0

# True in the process that serves `/call` — the worker. `carton_management(restart_bg_server)`
# reads it: the server cannot restart itself from inside one of its own requests.
SERVING = False


class CartonOperation(str, enum.Enum):
    """The SDK's operations — the MCP's tools, by name. Nothing else is dispatchable."""

    ADD_CONCEPT = "add_concept"
    EDIT_CARTON_OBJ = "edit_carton_obj"
    VALIDATE_CARTON_OBJ = "validate_carton_obj"
    SPLIT_CONTENT_CONCEPT = "split_content_concept"
    CREATE_BRANCHING_SM = "create_branching_sm"
    SET_PROPERTIES = "set_properties"
    QUERY_BY_PROPERTIES = "query_by_properties"
    REMOVE_RELATIONSHIP = "remove_relationship"
    ADD_DOCUMENT_CONCEPT = "add_document_concept"
    ADD_OBSERVATION_BATCH = "add_observation_batch"
    OBSERVE_FROM_IDENTITY_POV = "observe_from_identity_pov"
    CARTON_MANAGEMENT = "carton_management"
    RENAME_CONCEPT = "rename_concept"
    QUERY_WIKI_GRAPH = "query_wiki_graph"
    QUERY_CB_MATH = "query_cb_math"
    GET_CONCEPT_NETWORK = "get_concept_network"
    GET_CONCEPT = "get_concept"
    YOUKNOW_SPARQL = "youknow_sparql"
    GET_HISTORY_INFO = "get_history_info"
    LIST_MISSING_CONCEPTS = "list_missing_concepts"
    CREATE_MISSING_CONCEPTS = "create_missing_concepts"
    GET_RECENT_CONCEPTS = "get_recent_concepts"
    CALCULATE_MISSING_CONCEPTS = "calculate_missing_concepts"
    EQUIP_FRAME = "equip_frame"
    CHROMA_QUERY = "chroma_query"
    QUERY_GRAPH_FROM_RAG_RESULT = "query_graph_from_rag_result"
    CREATE_COLLECTION = "create_collection"
    ACTIVATE_COLLECTION = "activate_collection"
    ADD_TO_COLLECTION = "add_to_collection"
    LIST_COLLECTIONS = "list_collections"
    SUBSTRATE_PROJECTOR = "substrate_projector"


class CartonError(RuntimeError):
    """The server refused or failed a call. `status` is the HTTP status it answered with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def remote() -> bool:
    """Whether this process calls a box instead of running CartON itself."""
    return bool((os.environ.get("CARTON_URL") or "").strip())


# ----------------------------------------------------------------------------------------------
# THE OPERATIONS — registered by server_fastmcp with @operation(name), one beside each tool
# ----------------------------------------------------------------------------------------------

# name → the operation function: the SDK's function behind the tool of that name, with the tool's
# signature and NO rendering. The tool of the same name is `call_carton(name, args)` + rendering.
OPERATIONS: Dict[str, Callable[..., Any]] = {}


def operation(name: str):
    """Register the function behind the tool `name`. The name must be a `CartonOperation`."""
    CartonOperation(name)

    def _register(fn):
        OPERATIONS[name] = fn
        return fn
    return _register


_tools_cache: Optional[Dict[str, Any]] = None
_tools_lock = threading.Lock()


def _tools() -> Dict[str, Any]:
    """`{name: Tool}` for every tool `server_fastmcp` registers — their argument models validate a
    call's params. Imported lazily: the MCP module builds its graph connection at import, and a
    client process importing this module must not."""
    global _tools_cache
    if _tools_cache is None:
        with _tools_lock:
            if _tools_cache is None:
                from carton_mcp import server_fastmcp

                _tools_cache = {t.name: t for t in server_fastmcp.mcp._tool_manager.list_tools()}
    return _tools_cache


def operations() -> Dict[str, Callable[..., Any]]:
    """The registry, and the proof that it is the enum and the tool list: an operation the enum does
    not name, a tool with no operation, or an enum member nothing registers is refused here rather
    than discovered by a caller."""
    tools = _tools()
    named = {op.value for op in CartonOperation}
    registered = set(OPERATIONS)
    if not (named == registered == set(tools)):
        raise RuntimeError(
            "CartonOperation, the registered operations and the MCP's tools disagree — "
            f"named but not registered: {sorted(named - registered)}; "
            f"registered but not named: {sorted(registered - named)}; "
            f"tools without an operation: {sorted(set(tools) - registered)}; "
            f"operations without a tool: {sorted(registered - set(tools))}"
        )
    return OPERATIONS


def _as_result(value: Any) -> Any:
    """What an operation returned, as JSON can carry it: a TextContent is its text."""
    text = getattr(value, "text", None)
    if text is not None and getattr(value, "type", None) == "text":
        return text
    if isinstance(value, list):
        return [_as_result(v) for v in value]
    if isinstance(value, (str, int, float, bool, dict)) or value is None:
        return value
    return str(value)


def execute(operation: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Run one operation IN THIS PROCESS: the params validated exactly as the MCP validates the
    tool's arguments, then the operation's function. The server calls this for every `/call`; a
    self-hosted `call_carton` calls it directly."""
    try:
        name = CartonOperation(operation).value
    except ValueError:
        raise CartonError(400, f"unknown operation {operation!r}; the operations are "
                               + ", ".join(op.value for op in CartonOperation)) from None
    fn = operations()[name]
    meta = _tools()[name].fn_metadata
    # A None is "not given": a tool's body forwards every argument, including the ones left at
    # their None default, and the MCP's argument model takes an omitted argument, not a null.
    given = {k: v for k, v in dict(params or {}).items() if v is not None}
    parsed = meta.arg_model.model_validate(meta.pre_parse_json(given))
    kwargs = parsed.model_dump_one_level()
    result = fn(**kwargs)
    if inspect.iscoroutine(result):
        result = asyncio.run(result)
    return _as_result(result)


# ----------------------------------------------------------------------------------------------
# THE CLIENT — call_carton
# ----------------------------------------------------------------------------------------------

def _jsonable(value: Any) -> Any:
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return str(value)


def call_carton(operation: str, params: Optional[Dict[str, Any]] = None, *,
                url: Optional[str] = None, key: Optional[str] = None, user: Optional[str] = None,
                timeout: Optional[float] = None) -> Any:
    """CartON's one call. In-process when no box is configured; otherwise `POST /call` on the box.

    `url`, `key` and `user` default to `CARTON_URL`, `CARTON_KEY` and `CARTON_USER` — the
    environment, which is where a tenant's MCP settings put them. Raises `CartonError` with the
    server's status and message on a refusal or a failure.
    """
    name = CartonOperation(operation).value
    params = dict(params or {})
    url = (url if url is not None else os.environ.get("CARTON_URL", "")).strip().rstrip("/")
    if not url:
        return execute(name, params)
    import urllib.error
    import urllib.request

    key = key if key is not None else os.environ.get("CARTON_KEY", "")
    user = user if user is not None else os.environ.get("CARTON_USER", "")
    if timeout is None:
        timeout = float(os.environ.get("CARTON_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    body = json.dumps({"operation": name, "params": params}, default=_jsonable).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if user:
        headers["X-Carton-User"] = user
    req = urllib.request.Request(f"{url}/call", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            answer = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error") or detail
        except ValueError:
            pass
        raise CartonError(exc.code, f"carton {exc.code}: {detail[:600]}") from None
    except urllib.error.URLError as exc:
        raise CartonError(0, f"carton unreachable at {url} ({exc.reason})") from None
    if not answer.get("ok"):
        raise CartonError(400, str(answer.get("error")))
    return answer.get("result")


def as_text(result: Any) -> str:
    """An operation's result as the text a tool returns: a string as itself, anything else as JSON."""
    if isinstance(result, str):
        return result
    return json.dumps(result, default=str)


# ----------------------------------------------------------------------------------------------
# THE SERVER — what the worker serves
# ----------------------------------------------------------------------------------------------

def required_key(env=None) -> str:
    """The key this server demands, or "" for a private loopback. UNSET MEANS LOOPBACK ONLY: a
    key is either demanded of everyone or of no one — "sometimes authenticated" is
    indistinguishable from unauthenticated to an attacker and to a reader of this code."""
    return (env if env is not None else os.environ).get("CARTON_KEY", "")


def load_gate(env=None) -> Optional[Callable[[str, Dict[str, Any]], None]]:
    """The OPTIONAL metering hook, `module:function`, resolved ONCE at startup and loud on a bad
    spec. `gate(operation, params)` raises to refuse. The library provides the seam and knows
    nothing of the policy: a limit a tenant can read, unset or edit is not a limit."""
    import importlib

    spec = ((env if env is not None else os.environ).get("CARTON_CALL_GATE") or "").strip()
    if not spec:
        return None
    if ":" not in spec:
        raise RuntimeError(f"CARTON_CALL_GATE must be 'module:function', got {spec!r}")
    module_name, _, func_name = spec.partition(":")
    gate = getattr(importlib.import_module(module_name), func_name, None)
    if not callable(gate):
        raise RuntimeError(f"CARTON_CALL_GATE {spec!r} does not name a callable")
    return gate


def _make_handler(key: str, gate, dispatch: Callable[[str, Dict[str, Any]], Any], names):
    class _Handler(BaseHTTPRequestHandler):
        def _authorized(self) -> bool:
            if not key:
                return True
            return self.headers.get("Authorization", "") == f"Bearer {key}"

        def _send(self, code: int, obj: dict) -> None:
            payload = json.dumps(obj, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _refuse(self) -> None:
            # No detail: an unauthenticated caller learns it is unauthorized and nothing else.
            self._send(401, {"ok": False, "error": "unauthorized"})

        def do_GET(self):
            if not self._authorized():
                return self._refuse()
            if self.path.split("?", 1)[0] == "/health":
                return self._send(200, {"ok": True, "result": {"service": "carton", "operations": names}})
            self._send(404, {"ok": False, "error": "GET is only for /health"})

        def do_POST(self):
            # Before the body is read: an unauthenticated caller hands this process nothing to parse.
            if not self._authorized():
                return self._refuse()
            if self.path.split("?", 1)[0] != "/call":
                return self._send(404, {"ok": False, "error": f"unknown path {self.path!r}; the door is POST /call"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                operation = body.get("operation")
                params = body.get("params") or {}
                if not isinstance(operation, str) or not isinstance(params, dict):
                    raise ValueError("a call is {\"operation\": <name>, \"params\": {...}}")
            except Exception as exc:  # noqa: BLE001 — the caller's body, reported as itself
                return self._send(400, {"ok": False, "error": f"bad request body: {exc}"})
            if gate is not None:
                try:
                    gate(operation, params)
                except Exception as exc:  # noqa: BLE001 — 402: understood, authenticated, declined
                    return self._send(402, {"ok": False, "error": f"{exc}"})
            try:
                result = dispatch(operation, params)
            except CartonError as exc:
                return self._send(exc.status or 400, {"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001 — the operation's own message, readable as itself
                logger.exception("carton operation %s failed", operation)
                return self._send(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            self._send(200, {"ok": True, "result": result})

        def log_message(self, *args):
            """Silence per-request logging: this serves every read of the graph."""

    return _Handler


def serve_in_thread(port: int = DEFAULT_PORT, host: Optional[str] = None, key: Optional[str] = None,
                    dispatch: Optional[Callable[[str, Dict[str, Any]], Any]] = None):
    """Serve CartON's SDK on a daemon thread; return (server, thread).

    ⛔ HOST AND KEY MOVE TOGETHER: a non-loopback bind with no key would publish the account's whole
    graph unauthenticated and look healthy, so that combination refuses to start. `dispatch`
    defaults to `execute` (the real operations); a test may hand in its own.
    """
    global SERVING
    host = host if host is not None else os.environ.get("CARTON_HOST", "127.0.0.1")
    key = key if key is not None else required_key()
    if host != "127.0.0.1" and not key:
        raise RuntimeError(
            f"refusing to serve CartON on {host} without CARTON_KEY — a non-local bind with no key "
            "publishes the account's entire graph unauthenticated."
        )
    gate = load_gate()
    if dispatch is None:
        dispatch = execute
        names = sorted(operations())  # loads the MCP's module now: a failure stops the server, loudly
        SERVING = True
        # The overflow file is written where the AGENT is: the whole text travels to the caller,
        # whose tool applies the rule on its own disk.
        from carton_mcp import server_fastmcp
        server_fastmcp.WRITE_OVERFLOW_FILES = False
    else:
        names = sorted(op.value for op in CartonOperation)
    server = ThreadingHTTPServer((host, port), _make_handler(key, gate, dispatch, names))
    thread = threading.Thread(target=server.serve_forever, name="carton-api", daemon=True)
    thread.start()
    logger.info("carton api serving on %s:%s (auth: %s, gate: %s, %d operations)",
                host, port, "on" if key else "off (loopback only)", "on" if gate else "off", len(names))
    return server, thread
