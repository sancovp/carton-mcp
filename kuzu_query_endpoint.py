"""The localhost query endpoint the kuzu-owning process serves — the other half of KuzuHttpStore.

WHY THIS EXISTS. The engine (ladybug, Kuzu's continuation) is embedded: the process that opens the
database directory holds it, a second read-write open is refused by the lock, and a second
read_only open is served a stale snapshot. carton is not one process: the MCP server, the worker daemon and each
agent's stdio subprocess all read the graph. So exactly ONE process owns the file and the rest
ask it. That owner is the WORKER, because it is already the only writer (the queue drain), and
this module is what it serves.

It is the pattern carton already runs twice — SOMA on :8091, the chroma daemon on :8190 — and is
deliberately small: it exposes the four methods `GraphStore` defines and nothing else. There is no
query builder here and no dialect knowledge; the store it wraps has all of that already, so this
file cannot drift away from what an in-process caller would have got.

⭐ THIS IS THE BOX'S SERVICE SURFACE — the routes a client calls, with a key on them. A tenant
puts their user and key in their MCP settings; their MCP runs on their own machine and CALLS IN
here; `KuzuHttpStore` is the client half. There is no other listener: the carton MCP gateway that
used to hold that role is REMOVED (an MCP server is driven by an agent, and a box contains none —
see `carton_transport.py`).

⛔ HOST AND KEY MOVE TOGETHER, and `serve_in_thread` enforces it. Unauthenticated, this executes
arbitrary Cypher against the tenant's whole graph, which is safe ONLY on a bind that cannot be
reached from outside the box. So 127.0.0.1 with no key stays exactly what it always was — the
private in-box wire — and opening the host without setting `CARTON_KEY` REFUSES TO START rather
than publishing the graph while looking perfectly healthy.

A FAILED QUERY IS A 400 CARRYING THE ENGINE'S OWN MESSAGE, never a 500 or a swallowed empty
result: a binder or catalog error has to arrive at the caller readable as itself, or every dialect
delta in this port becomes invisible again at exactly the seam that was built to expose them.
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8192


def handle(store, path: str, body: dict) -> dict:
    """Dispatch one request against the owning process's store. Pure — no HTTP in here."""
    if path == "/query":
        return {"ok": True, "result": store.execute(body.get("query") or "", body.get("params") or {})}
    if path == "/set_properties":
        store.set_properties(body.get("concept_name"), body.get("properties") or {})
        return {"ok": True, "result": None}
    if path == "/remove_properties":
        store.remove_properties(body.get("concept_name"), body.get("keys") or [])
        return {"ok": True, "result": None}
    if path == "/find_by_properties":
        return {"ok": True, "result": store.find_by_properties(body.get("where") or {},
                                                               int(body.get("limit") or 25))}
    if path == "/enqueue":
        return {"ok": True, "result": enqueue(body.get("entry") or {}, body.get("suffix") or "")}
    if path == "/health":
        return {"ok": True, "result": {"backend": "kuzu", "owner": "worker"}}
    return {"ok": False, "error": f"unknown path {path!r}"}


def enqueue(entry: dict, suffix: str = "") -> str:
    """Write one queue entry into THIS host's queue dir; return its filename.

    The queue belongs to the machine whose worker drains it. A client writing the file
    locally instead produces a file nobody reads and a success message.
    """
    import uuid as _uuid
    from datetime import datetime as _dt

    from carton_mcp.add_concept_tool import get_observation_queue_dir

    name = f"{_dt.now().strftime('%Y%m%d_%H%M%S')}_{str(_uuid.uuid4())[:8]}{suffix}.json"
    path = get_observation_queue_dir() / name
    with open(path, "w") as fh:
        json.dump(entry, fh, indent=2)
    return name


def load_gate(env=None):
    """The OPTIONAL request gate, named by env as "module:function". None when unset.

    WHY A HOOK AND NOT A POLICY. Something has to be able to refuse a request before it
    reaches the store — a hosted box meters its tenants. But this file is part of the
    OPEN-SOURCE carton library, and billing logic does not belong in the thing being sold
    to the person paying: a limit a tenant can read, unset or edit is not a limit. So the
    library provides the SEAM and knows nothing about the policy; the operator names their
    own module in `CARTON_QUERY_GATE`, and it lives wherever they keep it. Unset — every
    local, self-hosted and developer box — means no gate and no import, exactly as before.

    IT RESOLVES ONCE, AT STARTUP, AND FAILS LOUD. A gate named but unimportable must stop
    the endpoint rather than be skipped: silently serving ungated because a module path had
    a typo is the failure that looks completely healthy while the meter is off.
    """
    import importlib
    import os

    spec = ((env if env is not None else os.environ).get("CARTON_QUERY_GATE") or "").strip()
    if not spec:
        return None
    if ":" not in spec:
        raise RuntimeError(
            f"CARTON_QUERY_GATE must be 'module:function', got {spec!r}"
        )
    module_name, _, func_name = spec.partition(":")
    module = importlib.import_module(module_name)
    gate = getattr(module, func_name, None)
    if not callable(gate):
        raise RuntimeError(f"CARTON_QUERY_GATE {spec!r} does not name a callable")
    return gate


def load_extra_routes(env=None):
    """The OPTIONAL extra-routes hook, named by env as "module:function". None when unset.

    THE SAME SEAM SHAPE AS `load_gate`, FOR THE SAME REASON: a hosted box needs to serve
    capabilities beyond the four GraphStore methods (first case: the TreeKanban HTTP surface —
    cards ARE :Wiki nodes, so the board belongs on the box, per the 2026-08-16 one-listener
    ruling), but this file is part of the OPEN-SOURCE carton library and product-specific routes
    do not belong in it. The library provides the seam; the operator stages their routes module
    into the box and names it in `CARTON_EXTRA_ROUTES`. Unset — every local, self-hosted and
    developer box — means no extra routes and no import, exactly as before.

    The named function's contract: `fn(path, method, args, body) -> (payload, status) | None`,
    where `args` is the parsed query dict (single values) and `body` is the parsed JSON body or
    None. Returning None falls through to the endpoint's own 404. Auth is enforced BEFORE the
    hook is consulted — an extra route can never widen access.

    IT RESOLVES ONCE, AT STARTUP, AND FAILS LOUD — same law as the gate: silently serving
    without the operator's routes because a module path had a typo is the failure that looks
    completely healthy while the capability is missing.
    """
    import importlib
    import os

    spec = ((env if env is not None else os.environ).get("CARTON_EXTRA_ROUTES") or "").strip()
    if not spec:
        return None
    if ":" not in spec:
        raise RuntimeError(
            f"CARTON_EXTRA_ROUTES must be 'module:function', got {spec!r}"
        )
    module_name, _, func_name = spec.partition(":")
    module = importlib.import_module(module_name)
    fn = getattr(module, func_name, None)
    if not callable(fn):
        raise RuntimeError(f"CARTON_EXTRA_ROUTES {spec!r} does not name a callable")
    return fn


def required_key(env=None):
    """The key this endpoint demands, or "" for the in-box localhost wire.

    UNSET MEANS UNCHANGED. The private wire behind the box has no credentials and
    needs none — it is unreachable from outside. Setting `CARTON_KEY` is what turns
    this endpoint into a network-facing one, and from that moment every request
    must carry it. There is deliberately no middle state: a key is either demanded
    of everyone or of no one, because "sometimes authenticated" is indistinguishable
    from "unauthenticated" to an attacker and to a reader of this code.
    """
    import os
    return (env if env is not None else os.environ).get("CARTON_KEY", "")


def _make_handler(store, key="", gate=None, extra=None):
    class _Handler(BaseHTTPRequestHandler):
        def _try_extra(self, method: str, body=None) -> bool:
            """Consult the operator's extra-routes hook (auth ALREADY checked by the caller).
            Returns True when the hook served the request; False falls through to 404.
            A hook exception is a 400 carrying its message — same law as a failed query:
            the error must arrive at the caller readable as itself, never a swallowed 500."""
            if extra is None:
                return False
            from urllib.parse import urlparse, parse_qs

            parsed = urlparse(self.path)
            args = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            try:
                result = extra(parsed.path, method, args, body)
            except Exception as exc:  # noqa: BLE001 — see docstring
                logger.exception("extra route %s %s failed", method, parsed.path)
                self._send(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
                return True
            if result is None:
                return False
            payload, status = result
            # THE HOOK'S PAYLOAD IS THE RESPONSE BODY, VERBATIM — dict OR list. The clients of
            # an extra route were written against the surface it replaces, and those contracts
            # use bare lists: HeavenBMLSQLiteClient's readers iterate response.json() directly
            # for GET /api/sqlite/cards (the original TreeKanban bridge returned a bare list).
            # Wrapping a list in {"result": ...} here broke every one of those readers with
            # 'str' object has no attribute 'get' — while this seam's own tests passed, because
            # both sides of the wrap were written together. The contract is the CLIENT'S.
            self._send(int(status), payload)
            return True

        def _read_json_body(self):
            """Parse the request body as JSON, or None on absence/garbage (the extra hook
            decides whether a missing body matters for its route)."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length) or b"null")
            except Exception:  # noqa: BLE001 — a bad body on an extra route is the hook's call
                return None
        def _authorized(self) -> bool:
            if not key:
                return True
            return self.headers.get("Authorization", "") == f"Bearer {key}"

        def _refuse(self):
            # No detail: an unauthenticated caller learns that it is unauthorized and
            # nothing whatsoever about the graph, the tenant, or why.
            self._send(401, {"ok": False, "error": "unauthorized"})

        def _send(self, code: int, obj: dict):
            # `default=str` because a row can carry a value json does not know (a timestamp, a
            # kuzu internal id). Dropping it would silently change what a caller sees compared
            # with an in-process store, which is the one thing this endpoint must not do.
            payload = json.dumps(obj, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if not self._authorized():
                self._refuse()
                return
            if self.path == "/health":
                self._send(200, handle(store, "/health", {}))
            elif self._try_extra("GET"):
                return
            else:
                self._send(404, {"ok": False, "error": "GET is only for /health"})

        def do_PUT(self):
            # PUT/DELETE exist ONLY for extra routes (the core surface is GET /health +
            # POST methods); without a hook they 404 exactly as before this seam existed.
            if not self._authorized():
                self._refuse()
                return
            if not self._try_extra("PUT", self._read_json_body()):
                self._send(404, {"ok": False, "error": "unknown path"})

        def do_DELETE(self):
            if not self._authorized():
                self._refuse()
                return
            if not self._try_extra("DELETE", self._read_json_body()):
                self._send(404, {"ok": False, "error": "unknown path"})

        def do_POST(self):
            # BEFORE the body is even read: an unauthenticated caller must not be
            # able to hand this process arbitrary input to parse.
            if not self._authorized():
                self._refuse()
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:
                self._send(400, {"ok": False, "error": f"bad request body: {exc}"})
                return
            # Non-core paths go to the operator's extra routes (the core set below is the
            # GraphStore surface + /enqueue + /health — exactly what `handle` dispatches).
            if self.path.split("?", 1)[0] not in (
                "/query", "/set_properties", "/remove_properties",
                "/find_by_properties", "/enqueue", "/health",
            ):
                if self._try_extra("POST", body):
                    return
                self._send(400, {"ok": False, "error": f"unknown path {self.path!r}"})
                return
            if gate is not None:
                try:
                    gate(self.path, body, store)
                except Exception as exc:
                    # 402: the request was understood and authenticated, and the operator's
                    # gate declined it. Distinct from 400 so a caller can tell "your query
                    # is wrong" from "you have hit a limit".
                    self._send(402, {"ok": False, "error": f"{exc}"})
                    return
            try:
                result = handle(store, self.path, body)
            except Exception as exc:
                # The engine's message, verbatim, at 400 — see the module docstring. The SERVER
                # keeps the traceback (this is the only place it exists); the caller gets the
                # readable message, since a stack from another process helps it not at all.
                logger.exception("kuzu endpoint %s failed", self.path)
                self._send(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
                return
            self._send(200 if result.get("ok") else 400, result)

        def log_message(self, *args):
            """Silence per-request logging: this serves every graph read in the box."""

    return _Handler


def serve_in_thread(store, port: int = DEFAULT_PORT, host=None, key=None):
    """Start the endpoint on a daemon thread and return (server, thread).

    Returned rather than hidden so the owner can shut it down deterministically in a test; a
    daemon thread so it can never hold the worker open on exit.

    ⛔ HOST AND KEY MOVE TOGETHER. Binding anywhere but 127.0.0.1 without a key would
    hand the tenant's whole graph to the network unauthenticated, so that exact
    combination REFUSES TO START rather than starting and being wrong — the one
    failure here that cannot be noticed by looking at it working.
    """
    import os
    host = host if host is not None else os.environ.get("CARTON_QUERY_HOST", "127.0.0.1")
    key = key if key is not None else required_key()
    if host != "127.0.0.1" and not key:
        raise RuntimeError(
            f"refusing to serve the graph on {host} without CARTON_KEY — a non-local "
            "bind with no key publishes the tenant's entire graph unauthenticated."
        )
    gate = load_gate()  # resolved once, at startup; a bad spec raises here
    extra = load_extra_routes()  # same law: resolved once, fails loud on a bad spec
    server = ThreadingHTTPServer((host, port), _make_handler(store, key, gate, extra))
    thread = threading.Thread(target=server.serve_forever, name="kuzu-query-endpoint", daemon=True)
    thread.start()
    logger.info("kuzu query endpoint serving on %s:%s (auth: %s, gate: %s, extra_routes: %s)",
                host, port, "on" if key else "off (local only)",
                "on" if gate else "off", "on" if extra else "off")
    return server, thread
