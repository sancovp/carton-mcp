"""
test_carton_disclose — the unit gate for progressively_disclose's PURE half (task 176, issue 212).

Run as a SCRIPT from the repo root (`python3 test_carton_disclose.py`) — the repo root IS the
`carton_mcp` package, which is this repo's own convention (see test_carton_pathguard.py,
test_carton_breaker.py and the .claude rules that name it).

Every case runs on SYNTHETIC ROWS. Nothing here opens a socket, which is the point: if any of
these ever needs a graph, the module has stopped being the pure half.
"""
import sys

import carton_disclose as cd
from carton_bounded_walk import DEFAULT_BOUNDARY_TYPES

FAILURES = []


def check(marker, condition, detail=""):
    if condition:
        print(f"  ✅ {marker}")
    else:
        print(f"  ❌ {marker} — {detail}")
        FAILURES.append(marker)


def m1_levels_are_the_imported_constant_not_a_copy():
    """The ladder is carton_bounded_walk's list, in its order. A second hand-typed list here is
    the issue-617 faithful-transcriber defect, so this pins that it cannot drift."""
    check("M1 levels == DEFAULT_BOUNDARY_TYPES, same order",
          cd.LEVELS == list(DEFAULT_BOUNDARY_TYPES),
          f"{cd.LEVELS} != {list(DEFAULT_BOUNDARY_TYPES)}")
    check("M1 levels is eight, Hwss_Domain and Domain among them",
          len(cd.LEVELS) == 8 and {"Hwss_Domain", "Domain"} <= set(cd.LEVELS), f"got {cd.LEVELS}")


def m2_normalize_level_accepts_the_real_spellings():
    check("M2 exact", cd.normalize_level("Hypercluster") == "Hypercluster")
    check("M2 lowercase", cd.normalize_level("hypercluster") == "Hypercluster")
    check("M2 spaces", cd.normalize_level("hwss domain") == "Hwss_Domain")
    check("M2 dashes", cd.normalize_level("doc-mirror-repo") == "Doc_Mirror_Repo")
    check("M2 surrounding whitespace", cd.normalize_level("  Global_Collection  ")
          == "Global_Collection")


def m3_normalize_level_is_loud_on_garbage():
    """A navigation surface that silently returns nothing for a typo is indistinguishable from
    a level that is genuinely empty — so an unknown level RAISES, and names the legal set."""
    for bad in ["Nonsense_Level", "", "   ", None, 7]:
        try:
            cd.normalize_level(bad)
            check(f"M3 raises on {bad!r}", False, "it returned instead of raising")
        except ValueError as exc:
            named = all(lvl in str(exc) for lvl in cd.LEVELS) or "non-empty string" in str(exc)
            check(f"M3 raises on {bad!r} and names the set", named, f"message was {exc}")
        except Exception as exc:            # a TypeError would be the wrong contract
            check(f"M3 raises ValueError on {bad!r}", False, f"raised {type(exc).__name__}")


def m4_levels_plan_is_one_query_that_keeps_zeros():
    plan = cd.build_levels_plan()
    check("M4 has cypher + parameters", "cypher" in plan and "parameters" in plan)
    check("M4 passes the ladder as a parameter",
          plan["parameters"]["levels"] == cd.LEVELS)
    check("M4 uses OPTIONAL MATCH so an empty level is not dropped",
          "OPTIONAL MATCH" in plan["cypher"],
          "a plain MATCH silently drops a declared-but-empty level")
    check("M4 is ONE execution", plan["cypher"].upper().count("RETURN") == 1)


def m5_level_plan_resolves_and_bounds():
    plan = cd.build_level_plan("hypercluster")
    check("M5 resolves the level into the parameters",
          plan["parameters"]["level"] == "Hypercluster")
    check("M5 limit rides as a parameter",
          plan["parameters"]["limit"] == cd.DEFAULT_MEMBER_LIMIT)
    check("M5 asks for a WIDER slice than it renders",
          plan["parameters"]["slice"] > cd.SUMMARY_CHARS,
          "the word-boundary clip needs slack to cut inside")
    for bad in [0, -1, 10_000, "50", True]:
        try:
            cd.build_level_plan("Hypercluster", limit=bad)
            check(f"M5 refuses limit={bad!r}", False, "it accepted the limit")
        except ValueError:
            check(f"M5 refuses limit={bad!r}", True)
    try:
        cd.build_level_plan("Nope")
        check("M5 an unknown level raises before any query is built", False)
    except ValueError:
        check("M5 an unknown level raises before any query is built", True)


def m6_diagram_renders_every_level_in_order_including_zeros():
    """Partial rows are the realistic case (a level with no members returns 0, and a row could
    be missing entirely). The diagram must still show every level, in ladder order."""
    rows = [{"level": "Hypercluster", "members": 65},
            {"level": "Carton_Collection", "members": 4210},
            {"level": "Global_Collection", "members": 0}]
    out = cd.render_diagram(rows)
    for lvl in cd.LEVELS:
        check(f"M6 names {lvl}", lvl in out)
    check("M6 renders a zero for a level with no members", " 0  " in out or "     0" in out)
    order = [out.index(lvl) for lvl in cd.LEVELS]
    check("M6 renders in LEVELS order, not row order", order == sorted(order),
          "the ladder must read the same every time")
    check("M6 carries the total", "TOTAL" in out)
    check("M6 says how to descend", "progressively_disclose(level=" in out)


def m7_diagram_survives_empty_and_junk_rows():
    check("M7 empty rows still render the ladder",
          all(lvl in cd.render_diagram([]) for lvl in cd.LEVELS))
    check("M7 None rows still render the ladder",
          all(lvl in cd.render_diagram(None) for lvl in cd.LEVELS))


def m8_members_clip_on_a_word_boundary():
    """Issue 576 is a mid-word 160-char slice. This surface cuts on a space instead."""
    long_summary = ("the quick brown fox jumps over the lazy dog " * 12).strip()
    rows = [{"name": "Some_Concept", "summary": long_summary}]
    out = cd.render_members("Hypercluster", rows)
    body = [ln for ln in out.splitlines() if "quick brown" in ln][0].strip()
    check("M8 clipped", body.endswith("..."), f"tail was {body[-20:]!r}")
    check("M8 did not cut mid-word", not body.rstrip(".").endswith(("quic", "brow", "jump")),
          f"tail was {body[-20:]!r}")
    check("M8 clip is bounded", len(body) <= cd.SUMMARY_CHARS + 4, f"len {len(body)}")


def m9_members_announce_their_own_truncation():
    rows = [{"name": f"C{i}", "summary": "x"} for i in range(5)]
    out = cd.render_members("Hypercluster", rows, limit=5)
    check("M9 a full page says it stopped at the limit", "limit=5" in out)
    fewer = cd.render_members("Hypercluster", rows[:2], limit=5)
    check("M9 a short page does not claim truncation", "limit=5" not in fewer)


def m10_empty_level_reads_as_empty_not_missing():
    out = cd.render_members("Global_Collection", [])
    check("M10 says EMPTY explicitly", "EMPTY level" in out)
    check("M10 does not read as unknown", "unknown" not in out.lower())


def m11_the_module_is_pure():
    src = open(cd.__file__).read()
    for banned in ["import neo4j", "GraphDatabase", "urllib", "requests", "subprocess"]:
        check(f"M11 no {banned}", banned not in src, "the pure half must not do I/O")


def m12_a_failed_query_raises_instead_of_rendering_an_empty_graph():
    """THE FAIL-OPEN THIS SURFACE MUST NOT HAVE. If a failed query unwrapped to [], the diagram
    would render every level at zero — "the graph has no levels" — when the truth is "the
    store did not answer". The quota gate's rule says it directly: a meter that cannot count
    must never fail open into 'unlimited'."""
    check("M12 a good envelope unwraps",
          cd.rows_or_raise({"success": True, "data": [{"level": "Hypercluster", "members": 3}]})
          == [{"level": "Hypercluster", "members": 3}])
    check("M12 a genuinely empty result is still []",
          cd.rows_or_raise({"success": True, "data": []}) == [])
    check("M12 a bare list passes through", cd.rows_or_raise([{"a": 1}]) == [{"a": 1}])
    for bad, label in [({"success": False, "error": "connection refused"}, "failed query"),
                       ({"nonsense": 1}, "unrecognised envelope"),
                       ("a string", "wrong type"),
                       (None, "None")]:
        try:
            cd.rows_or_raise(bad)
            check(f"M12 raises on {label}", False, "it returned rows instead of raising")
        except cd.DiscloseStoreError:
            check(f"M12 raises on {label}", True)
    try:
        cd.rows_or_raise({"success": False, "error": "connection refused"})
    except cd.DiscloseStoreError as exc:
        check("M12 the refusal carries the store's own error",
              "connection refused" in str(exc), f"message was {exc}")


def main():
    for fn in [m1_levels_are_the_imported_constant_not_a_copy,
               m2_normalize_level_accepts_the_real_spellings,
               m3_normalize_level_is_loud_on_garbage,
               m4_levels_plan_is_one_query_that_keeps_zeros,
               m5_level_plan_resolves_and_bounds,
               m6_diagram_renders_every_level_in_order_including_zeros,
               m7_diagram_survives_empty_and_junk_rows,
               m8_members_clip_on_a_word_boundary,
               m9_members_announce_their_own_truncation,
               m10_empty_level_reads_as_empty_not_missing,
               m11_the_module_is_pure,
               m12_a_failed_query_raises_instead_of_rendering_an_empty_graph]:
        print(f"\n{fn.__name__}")
        fn()
    print("\n" + ("=" * 60))
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} — {', '.join(FAILURES)}")
        return 1
    print("ALL MARKERS GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
