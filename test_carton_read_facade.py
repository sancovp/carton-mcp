"""Issue 483 — the carton READ FACADE: every read arrives plain, and the MCP server cannot return a link.

Isaac 2026-09-06, verbatim: "CARTON SHOULD NOT EVER AGAIN, EVER HAVE ANY FUNCTIONS AT ALL IN THE SDK THAT
RENDER THE MARKDOWN LINKS. THERE IS A UTIL. MAKE SURE IT IS USED IN CARTON."

Six surfaces, each pinned here:
  1. the stripper (carton_utils.strip_wiki_links / deep_strip_wiki_links) — every link form, including a
     substring cut INSIDE the link target (`[Name](..`), leaves no `](` and no `_itself` behind;
  2. the words (card 812) — every character outside the link markup arrives as stored: `vault()` keeps its
     parentheses, a run of spaces stays a run, and a link to a name holding parentheses such as
     `[doc(m)](../Doc(M)/Doc(M)_itself.md)` gives back `doc(m)`, so the doc(m) wait and the projector
     read what was written;
  3. the facade's validator (CartOnUtils._validate_query_safety) — accepts every label in READ_LABELS
     (the :Wiki namespace and the context-alignment code graph that shares this neo4j) and refuses a
     query naming none, and any write;
  4. the MCP return chokepoint (server_fastmcp._tool_stripped installed on mcp.tool) — a tool registered
     the ordinary way, sync or async, returns its value stripped, with FastMCP's is_async still truthful;
  5. the answer render (server_fastmcp._fmt over carton_render.render_answer, card 766) — scalars lead,
     every collection follows as one record per block;
  6. the refs (card 770) — each repeated sequence, a path or an identifier, is said once as @N through
     answer_refs.encode_refs, the one encoder seem and the gnosys router share.

Run as a SCRIPT from the repo root AFTER `pip install --no-deps .` (the repo's convention: the tests resolve
the INSTALLED package): python3 test_carton_read_facade.py   (expect: 7 markers, all pass)
"""
import asyncio
import inspect

from carton_mcp.carton_utils import CartOnUtils, READ_LABELS, deep_strip_wiki_links, strip_wiki_links

LINKED = "[BLOCKED](../Blocked/Blocked_itself.md) on [Task_1](../Task_1/Task_1_itself.md) and cut [X](../X/X_i"
CUT_INSIDE_TARGET = "see [Github_Issue_475](.."          # left(d, 600) can land here — the leak of 2026-09-06 01:xx


def t_stripper_handles_every_truncation():
    out = strip_wiki_links(LINKED)
    assert "](" not in out and "_itself" not in out, out
    assert out == "BLOCKED on Task_1 and cut X", out
    cut = strip_wiki_links(CUT_INSIDE_TARGET)
    assert cut == "see Github_Issue_475", cut
    nested = deep_strip_wiki_links({"rows": [{"d": LINKED}, [CUT_INSIDE_TARGET]], "n": 3})
    assert nested["n"] == 3
    assert "](" not in nested["rows"][0]["d"] and "](" not in nested["rows"][1][0], nested
    print("  MARKER: STRIPPER_HANDLES_EVERY_TRUNCATION_OK")


DOCM = ("**Module:** `seal_kind.py`  •  **Mirrors:** it\n\nvault() names it; f( ) stays\n"
        "    @1 = an indented line\n")


def t_the_words_arrive_verbatim():
    """Card 812, issue 1272. Measured 2026-10-03 23:06: carton stores `vault() names it` and the facade
    returned `vault names it`, so the doc(m) wait never matched and every projection lost its `()`."""
    out = strip_wiki_links(DOCM)
    assert out == DOCM, (
        "INVARIANT: the read facade returns every character outside the auto-linker markup as stored; "
        "the doc(m) wait and the projector read the stored doc(m) through it. FIX: strip_wiki_links "
        "removes link markup only, never empty parentheses or runs of spaces across the whole text. "
        f"got {out!r}")
    assert deep_strip_wiki_links([{"content": DOCM}]) == [{"content": DOCM}], (
        "INVARIANT: the shared read primitive returns doc(m) rows verbatim. FIX: as above.")
    linked = strip_wiki_links("call [Vault](../Vault/Vault_itself.md)() now")
    assert linked == "call Vault() now", (
        "INVARIANT: a link to a function name keeps the call parentheses that follow it. FIX: as above. "
        f"got {linked!r}")
    gaps = [strip_wiki_links(s) for s in ("see (../X/X_itself.md) here", "a ( ../X/X_itself.md ) b",
                                          "see ../X/X_itself.md here", "cut (../X/X_it")]
    assert gaps == ["see here", "a b", "see here", "cut"], (
        "INVARIANT: removing a link target leaves no gap where it stood. FIX: each removal takes the "
        f"space before it with it. got {gaps!r}")
    print("  MARKER: THE_WORDS_ARRIVE_VERBATIM_OK")


PAREN_NAMED = {                                     # measured in the live graph 2026-10-03 23:3x
    "[doc(m)](../Doc(M)/Doc(M)_itself.md)": "doc(m)",
    "[add() method](../Add()_Method/Add()_Method_itself.md)": "add() method",
    "[MOV (Memories of Olivus Victory)](../Mov_(Memories_Of_Olivus_Victory)/"
    "Mov_(Memories_Of_Olivus_Victory)_itself.md)": "MOV (Memories of Olivus Victory)",
    "[(0](../(0/(0_itself.md)": "(0",
}


def t_a_link_to_a_name_holding_parentheses_gives_back_its_words():
    """Card 812. Measured 2026-10-03 23:3x: 16423 nodes hold an auto-linker link whose concept name
    ends in `)`; the linker rewrote a doc(m) content node with `[doc(m)](../Doc(M)/Doc(M)_itself.md)`
    and the facade returned `doc(m)/Doc(M)`, so the doc(m) wait timed out on a write that had landed."""
    got = {link: strip_wiki_links(f"a {link}: b") for link in PAREN_NAMED}
    want = {link: f"a {words}: b" for link, words in PAREN_NAMED.items()}
    assert got == want, (
        "INVARIANT: every auto-linker link gives back exactly its words, whatever its concept name "
        "holds. FIX: strip_wiki_links matches the linker's own shape, [words](../Name/Name_itself.md), "
        "with the name repeated by back-reference, before the generic link pattern whose target stops "
        f"at the first close parenthesis. got {got!r}")
    print("  MARKER: A_LINK_TO_A_NAME_HOLDING_PARENTHESES_GIVES_BACK_ITS_WORDS_OK")


def t_facade_accepts_every_read_label_and_refuses_the_rest():
    v = CartOnUtils.__new__(CartOnUtils)                 # the validator is pure; no connection is opened
    assert v._validate_query_safety("MATCH (c:Wiki) RETURN c.n")["success"]
    assert v._validate_query_safety("UNWIND $paths AS p OPTIONAL MATCH (f:File {path: p}) RETURN f")["success"]
    assert v._validate_query_safety("MATCH (fn:Function) RETURN fn.name")["success"]
    for label in READ_LABELS:
        assert label.startswith(":"), label
        assert v._validate_query_safety(f"MATCH (x{label}) RETURN x")["success"], label
    unlabeled = v._validate_query_safety("MATCH (n) RETURN n LIMIT 1")
    assert not unlabeled["success"] and "readable label" in unlabeled["error"], unlabeled
    assert ":File" in unlabeled["error"] and ":Wiki" in unlabeled["error"], unlabeled
    write = v._validate_query_safety("MATCH (c:Wiki) DETACH DELETE c")
    assert not write["success"] and "Write" in write["error"], write
    print("  MARKER: FACADE_ACCEPTS_READ_LABELS_OK")


def t_every_mcp_tool_return_is_plain():
    from mcp.types import TextContent
    from carton_mcp import server_fastmcp as srv
    assert srv.mcp.tool is srv._tool_stripped, "the return chokepoint is not installed on mcp.tool"

    @srv.mcp.tool(name="zz_test_linked_return_483")
    def zz_test_linked_return_483(n: str) -> str:
        """test tool: returns a linked string"""
        return f"{n}: {LINKED}"

    @srv.mcp.tool(name="zz_test_linked_return_483_async")
    async def zz_test_linked_return_483_async(n: str) -> dict:
        """test tool: returns a linked dict, asynchronously"""
        return {"n": n, "d": CUT_INSIDE_TARGET}

    sync_tool = srv.mcp._tool_manager.get_tool("zz_test_linked_return_483")
    async_tool = srv.mcp._tool_manager.get_tool("zz_test_linked_return_483_async")
    assert sync_tool is not None and async_tool is not None
    assert sync_tool.is_async is False and async_tool.is_async is True, (sync_tool.is_async, async_tool.is_async)
    assert list(inspect.signature(sync_tool.fn).parameters) == ["n"], "the wrapper must keep the tool's signature"
    out = sync_tool.fn(n="A")
    assert out == "A: BLOCKED on Task_1 and cut X", out
    out_async = asyncio.run(async_tool.fn(n="B"))
    assert out_async == {"n": "B", "d": "see Github_Issue_475"}, out_async
    tc = srv._plain_return(TextContent(type="text", text=LINKED))
    assert isinstance(tc, TextContent) and "](" not in tc.text, tc
    assert srv._plain_return([LINKED, {"x": CUT_INSIDE_TARGET}]) == ["BLOCKED on Task_1 and cut X", {"x": "see Github_Issue_475"}]
    assert srv._plain_return(7) == 7
    print("  MARKER: EVERY_MCP_TOOL_RETURN_IS_PLAIN_OK")


def t_every_answer_renders_one_record_per_block():
    """Card 766, issue 1113. Isaac 2026-10-01: "WTF AM I LOOKING AT IN ALL THESE RIDICULOUS CARTON OUTPUTS
    THEY NEVER GOT THE FUCKING RENDERER TREATMENT" and "you should also go encode carton returns the same
    way". Measured before: a list joined its members with ", ", so activate_collection read as one
    run-on string, and every path was written whole."""
    from carton_mcp import server_fastmcp as srv
    d = "/home/GOD/gnosys-plugin-v2/doc-mirror-system/plugin/bin/"
    answer = {"success": True, "collection_name": "C",
              "concepts": [{"name": "A", "description": f"one\nsee {d}journal"},
                           {"name": "B", "description": f"{d}docmirror-task and {d}goal"}],
              "total_count": 2}
    out = srv._fmt(answer)
    assert out == "\n".join([
        "refs (1):",
        f"    @1 = {d.rstrip('/')}",
        "success: True",
        "collection_name: C",
        "total_count: 2",
        "concepts (2):",
        "    - name: A",
        "      description:",
        "          one",
        "          see @1/journal",
        "    - name: B",
        "      description: @1/docmirror-task and @1/goal",
    ]), out
    rows = srv._fmt([{"n.n": "X", "t": "2026"}, {"n.n": "Y", "t": "2027"}])
    assert rows == "rows (2):\n    - n.n: X\n      t: 2026\n    - n.n: Y\n      t: 2027", rows
    assert srv._fmt({"names": ["a", "b"]}) == "names (2):\n    - a\n    - b"
    assert srv._fmt([]) == "(none)"
    from carton_mcp.carton_render import render_answer
    assert render_answer({"result": "plain"}) == "plain"
    reused = render_answer({"result": f"{d}a {d}b {d}c see @1/x.py"})
    assert reused.startswith(f"refs (1):\n    @2 = {d.rstrip('/')}\n") and "see @1/x.py" in reused, reused
    print("  MARKER: EVERY_ANSWER_RENDERS_ONE_RECORD_PER_BLOCK_OK")


def t_a_repeated_identifier_is_said_once_as_a_ref():
    """Card 770, issue 1117. Isaac 2026-10-01: "sorry but did you only make `@` refs for *paths*?" and
    "no they are repeated sequence refs that encode the string. it's like huffman encoding". Measured: the
    Conversation_2026_10_01T06_27_06_Journals answer said each coordinate prefix whole on every entry."""
    from answer_refs import decode_refs
    from carton_mcp import server_fastmcp as srv
    c = "Knowledge_Carton_Mcp_Carton_Read_Facade_Carton_Return_Render_2026_10_01T07"
    answer = {"concepts": [{"name": f"{c}_13_58"}, {"name": f"{c}_30_59"}, {"name": f"{c}_44_02"}]}
    out = srv._fmt(answer)
    assert out.splitlines()[:2] == ["refs (1):", f"    @1 = {c}"], out
    assert "    - name: @1_30_59" in out, out
    full = decode_refs(out)
    assert all(f"    - name: {c}_{s}" in full for s in ("13_58", "30_59", "44_02")), full
    print("  MARKER: A_REPEATED_IDENTIFIER_IS_SAID_ONCE_AS_A_REF_OK")


TESTS = [
    t_stripper_handles_every_truncation,
    t_the_words_arrive_verbatim,
    t_a_link_to_a_name_holding_parentheses_gives_back_its_words,
    t_facade_accepts_every_read_label_and_refuses_the_rest,
    t_every_mcp_tool_return_is_plain,
    t_every_answer_renders_one_record_per_block,
    t_a_repeated_identifier_is_said_once_as_a_ref,
]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\nall {len(TESTS)} passed" if not failed else f"\n{failed}/{len(TESTS)} FAILED")
    raise SystemExit(1 if failed else 0)
