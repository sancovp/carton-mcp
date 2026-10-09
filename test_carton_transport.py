"""test_carton_transport — the transport law after the gateway was removed.

Run: python3 test_carton_transport.py     (exit 0 = pass)

THIS REPLACES test_network_gateway.py. That suite was 10/10 and most of it tested a thing
that no longer exists: a pure-ASGI bearer gate around a streamable-HTTP listener. Keeping it
green would have meant keeping the listener, and keeping the listener would have meant a box
serving an MCP nobody can drive. So the gate cases are DELETED rather than ported — there is
nothing left for them to be about.

WHAT SURVIVES IS THE PART THAT WAS NEVER ABOUT THE GATEWAY: stdio is the only transport, and
SSE is refused by name. That rule predates the gateway, protects the path actually used, and
is enforced in exactly one place.

⛔ AND THE ONE GENUINELY NEW CASE: `http` must be REFUSED, not silently downgraded to stdio.
An operator whose config still says `http` is carrying a stale configuration from when the
gateway existed; answering it with a working stdio server would start something that looks
network-configured and is unreachable on the network — which is the failure this whole
removal exists to end, re-created one level down.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import carton_transport as ct  # noqa: E402

PASS = FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label} {detail}")


def refusal(env):
    """The refusal message, or None if the call was answered instead."""
    try:
        ct.resolve_transport(env)
        return None
    except RuntimeError as exc:
        return str(exc)


def main():
    print("== stdio is the default and the only thing that works ==")
    check("unset -> stdio", ct.resolve_transport({}) == ct.STDIO)
    check("explicit stdio -> stdio", ct.resolve_transport({"CARTON_TRANSPORT": "stdio"}) == ct.STDIO)
    check("whitespace and case are tolerated",
          ct.resolve_transport({"CARTON_TRANSPORT": "  STDIO "}) == ct.STDIO)

    print("== SSE is refused BY NAME, with its reason ==")
    msg = refusal({"CARTON_TRANSPORT": "sse"})
    check("sse is refused", msg is not None, "IT WAS ANSWERED")
    check("and the refusal carries the reason, not just a no",
          msg is not None and "broken pipes" in msg, (msg or "")[:90])

    print("== the removed network transports are REFUSED, never downgraded ==")
    for value in ("http", "streamable-http"):
        msg = refusal({"CARTON_TRANSPORT": value})
        check(f"{value} is refused", msg is not None, "IT WAS SILENTLY ACCEPTED")
        check(f"{value}'s refusal says the gateway was REMOVED",
              msg is not None and "REMOVED" in msg, (msg or "")[:90])
        # The refusal has to leave the reader somewhere to go, or they will simply
        # unset the variable and wonder why their remote graph is empty.
        check(f"{value}'s refusal names the surface that replaced it",
              msg is not None and "CARTON_URL" in msg and "/call" in msg, (msg or "")[:90])

    print("== an unknown value errors rather than falling through ==")
    msg = refusal({"CARTON_TRANSPORT": "carrier-pigeon"})
    check("unknown is refused", msg is not None, "IT WAS ANSWERED")
    check("and it is named in the message",
          msg is not None and "carrier-pigeon" in msg, (msg or "")[:90])

    print("== the gateway module is GONE, not merely unused ==")
    try:
        import network_gateway  # noqa: F401
        check("network_gateway no longer imports", False, "IT STILL EXISTS")
    except ImportError:
        check("network_gateway no longer imports", True)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
