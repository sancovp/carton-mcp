"""CartON's transport law — stdio is the only transport, and SSE is forbidden.

⛔ THIS FILE WAS `network_gateway.py`, AND THE GATEWAY IS GONE. It held a bearer-gated
streamable-HTTP listener (`BearerGateMiddleware` wrapping the SDK's `streamable_http_app()`
under uvicorn, fail-closed on `CARTON_API_KEY`) whose one purpose was to let something dial
INTO a carton MCP server running inside a hosted box.

An MCP server exists to be driven by an agent; a tenant's box contains no agent, so a listener
there had no caller. The tenant runs carton's MCP on their own machine, and every one of its
tools is `call_carton(<tool>, <args>)` to the box's one door — CartON's SDK on `POST /call`
(`carton_api.py` — the operations by name, a key from their MCP settings, the operations'
own results back).

⚠ AND THE BOX'S HTTP LISTENER IS A DIFFERENT LISTENER. "The SaaS listens on HTTP" is correct
and unchanged — that is the SDK's door. The box had TWO listeners and only one of them was
ever the service.

WHAT SURVIVED, AND WHY IT IS NOT MERELY A LEFTOVER: the transport decision predates the
gateway and protects the LOCAL path, which is the path actually used. `resolve_transport` is
called by `server_fastmcp.main()` on every launch, and it is the only place the no-SSE rule
is enforced. Deleting this file wholesale to be rid of the gateway would take that rule with
it and leave `CARTON_TRANSPORT=sse` passing straight through unauthenticated again — which is
exactly the state that existed before the module was written.

THE LAWS (held in code, not prose):
1. **SSE IS FORBIDDEN** (`.claude/rules/carton-mcp-transport.md`, Mar 13 2026: SSE degraded
   over long sessions into Errno-32 broken pipes; fully reversed). Refused by name.
2. **NETWORK MODE NO LONGER EXISTS.** `http` is refused too — not silently ignored, and not
   quietly downgraded to stdio. A caller asking for a network transport is asking for the
   removed gateway, and the refusal says so and names what to use instead. A silent downgrade
   would start a server that looks configured for the network and is not reachable on it.
3. **Nothing blocking at import** (the same rule's startup-timeout lesson): env reads only.

Env surface (all optional; unset == stdio, which is the only thing that works):
  CARTON_TRANSPORT   'stdio' (default). 'sse' and 'http'/'streamable-http' are REFUSED.
"""

import os

STDIO = "stdio"

# Named so the refusal can name them. `http` and its alias are not "unknown" — they were real
# until the gateway was removed, and a caller using one is carrying a stale configuration
# rather than making a typo. The two cases deserve different messages.
_REMOVED = ("http", "streamable-http")
_FORBIDDEN = ("sse",)


def resolve_transport(env=None) -> str:
    """The one transport decision. Always stdio, or a loud refusal."""
    env = os.environ if env is None else env
    transport = env.get("CARTON_TRANSPORT", STDIO).strip().lower()
    if transport in _FORBIDDEN:
        raise RuntimeError(
            "CARTON_TRANSPORT='sse' is FORBIDDEN "
            "(.claude/rules/carton-mcp-transport.md, Mar 13 2026: SSE degraded over long "
            "sessions -> Errno 32 broken pipes; fully reversed). carton runs on stdio."
        )
    if transport in _REMOVED:
        raise RuntimeError(
            f"CARTON_TRANSPORT={transport!r} refers to the network gateway, which has been "
            "REMOVED: an MCP server is driven by an agent, and there is no agent in a hosted "
            "box, so nothing ever dialled it. Run carton on stdio where your agent is, and "
            "point it at your box with CARTON_URL + CARTON_KEY (+ CARTON_USER) — every tool "
            "then calls the SDK the box serves on POST /call, which is the one door a box has."
        )
    if transport != STDIO:
        raise RuntimeError(
            f"unknown CARTON_TRANSPORT {transport!r} — carton runs on 'stdio' (the default)"
        )
    return STDIO
