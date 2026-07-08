"""
Function-level test for STEP 3 linker fence-opacity: auto_link_description must leave
every <CartonObj ...>...</CartonObj> span (open tag + body) BYTE-IDENTICAL while still
linkifying prose around it. Proves the two corruptions the commander observed live are
fixed: (a) the open tag's name= / Title_Case words get linkified; (b) JSON array brackets
get EATEN because [x] is markdown-link syntax.

Runs against the INSTALLED package (auto_link_description uses relative imports).
Run: python3 test_linker_fence_opacity.py
"""
import os

os.environ.setdefault("HEAVEN_DATA_DIR", "/tmp/heaven_data")
from carton_mcp.add_concept_tool import auto_link_description  # noqa: E402

try:
    import ahocorasick  # noqa: F401
    HAVE_AHO = True
except ImportError:
    HAVE_AHO = False

_FENCE = (
    '<CartonObj name=Unit_Registry schema=Reg_Schema>'
    '{"repo": Cave_Repo, "steps": ["clone", "install"], "tier": 2, '
    '"nested": {"arr": [A_Unit, B_Unit]}}'
    "</CartonObj>"
)
_CACHE = ["Free_Tier", "Cave_Repo", "A_Unit", "B_Unit", "Unit_Registry", "Some_Concept"]


def test_fence_is_byte_identical():
    desc = f"This Free_Tier plan uses Cave_Repo. {_FENCE} Trailing Free_Tier note."
    out = auto_link_description(desc, "/tmp", "Current_Concept", concept_cache=_CACHE)
    # the ENTIRE fence span survives verbatim
    assert _FENCE in out, "fence was mutated by the linker"
    # specifics the commander saw corrupted:
    assert "<CartonObj name=Unit_Registry schema=Reg_Schema>" in out      # open tag name= not linkified
    assert '["clone", "install"]' in out                                   # JSON array brackets NOT eaten
    assert "[A_Unit, B_Unit]" in out                                       # bare-ref array brackets preserved
    assert '"repo": Cave_Repo' in out                                      # bare ref stays bare (no md link)
    assert "_itself.md" not in _FENCE  # sanity: fence has no links to begin with


def test_prose_still_links_outside_fence():
    if not HAVE_AHO:
        print("  (ahocorasick absent — skipping prose-link assertion)")
        return
    desc = f"Intro mentions Some_Concept here. {_FENCE} And Free_Tier after."
    out = auto_link_description(desc, "/tmp", "Current_Concept", concept_cache=_CACHE)
    # fence preserved
    assert _FENCE in out
    # prose OUTSIDE the fence got linked (Some_Concept and/or Free_Tier)
    outside = out.replace(_FENCE, "")
    assert ("_itself.md)" in outside), "prose was not linked — wrapper disabled linking"
    # and the linkified prose did NOT bleed into the fence
    assert _FENCE in out


def test_no_fence_still_links_normally():
    if not HAVE_AHO:
        return
    desc = "Plain prose about Some_Concept and Free_Tier, no fences here."
    out = auto_link_description(desc, "/tmp", "Current_Concept", concept_cache=_CACHE)
    assert "_itself.md)" in out  # normal linking still works when there is no fence (regression guard)


def test_multiple_fences_all_preserved():
    f2 = '<CartonObj name=Other>{"k": [1, 2, 3], "ref": Cave_Repo}</CartonObj>'
    desc = f"A {_FENCE} between Free_Tier {f2} end."
    out = auto_link_description(desc, "/tmp", "Current_Concept", concept_cache=_CACHE)
    assert _FENCE in out
    assert f2 in out
    assert "[1, 2, 3]" in out  # numeric array brackets preserved in the 2nd fence


if __name__ == "__main__":
    import sys
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{passed + failed} passed, {failed} failed  (ahocorasick={'yes' if HAVE_AHO else 'no'})")
    sys.exit(1 if failed else 0)
