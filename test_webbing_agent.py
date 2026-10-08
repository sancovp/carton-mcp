#!/usr/bin/env python3
"""Unit tests for the webbing_agent PURE (onion-arch inner-layer) functions.

Pure library-level tests — NO Neo4j, no MCP, no SDNAC, no daemon. `_is_underdeveloped` and
`_build_batch_goal` take plain Python values and return plain Python values; they do no I/O, so this
is the onion-architecture INNER layer test: it must pass standing alone, before anything wraps it.
Matches this repo's established convention (test_description_rollup.py / test_sm_branching.py): plain
asserts, a __main__ runner, no pytest framework dependency.

`call_webber`, `loop`, and `main` are NOT unit-tested here — they require a live neo4j graph + a real
SDNAC/heaven-agent run (exactly like Sophia's analogous `call_sophia`/`loop`/`main` have no unit tests
either). Those are covered by the live E2E test against the real running graph (see
`edit-the-webbing-agent`'s Part-3 test / the live verification run for this build).
"""

from carton_mcp.webbing_agent import (
    _is_underdeveloped,
    _build_batch_goal,
    _format_rels,
    BASE_RELS_EXCLUDED,
    DOMAIN_AXIS_LAW,
    WEBBER_SYSTEM_PROMPT,
    _webber_run_config,
)

# Each SOMA result the agent meets, as the text it sees, paired with the action it must take.
MEREO_FILL = "DO MEREO[n]: this is important to fill next, but only if Y is inside the meaning you meant: "
SOUP_FILL = "DO SOUP[n]: this is important to fill next, but only if it is inside the meaning you meant: "
SOMA_SCENARIO_ACTIONS = [
    ("DEATH block", "read past them"),
    ("not validly the type it claims: its execution failed", "CartON keeps the write so it can be seen"),
    ("only if it is inside the meaning you meant", "Never expand past that prose"),
    (MEREO_FILL + "define Y", "give Y its four lists"),
    (MEREO_FILL + "define Y", "drop the claim"),
    (MEREO_FILL + "declare Y a type", "declaring a type is not"),
    (SOUP_FILL + "add_concept X with properties", "supply it"),
    (SOUP_FILL + "add_concept X with properties", "drop the claim"),
    ("DO SOUP[n]: leave it", "leave it"),
    ("REFUSED (not written)", "leave that concept alone"),
    ("REJECTED", "leave that concept alone"),
]


# ── _is_underdeveloped ───────────────────────────────────────────────────────────────────────────

def test_low_description_score_is_underdeveloped():
    # "xyzzy plugh quux" shares nothing with the concept_cache tokens -> score is low (0) -> True
    # regardless of rel count.
    result = _is_underdeveloped("xyzzy plugh quux", ["Some_Other_Concept"], other_rel_count=10,
                                score_threshold=50, min_rel_count=2)
    assert result is True, "a description scoring near-0 must be flagged under-structured"
    print("✓ low description score alone -> under-structured")


def test_high_description_score_and_enough_rels_is_not_underdeveloped():
    concept_cache = ["Giint_Project_Foo", "Giint_Feature_Bar", "Component_Baz"]
    desc = "giint project foo feature bar component baz"  # every meaningful word matches the cache
    result = _is_underdeveloped(desc, concept_cache, other_rel_count=3,
                                score_threshold=50, min_rel_count=2)
    assert result is False, "a well-scored description with enough real rels must NOT be flagged"
    print("✓ high description score + enough rels -> NOT under-structured")


def test_low_rel_count_alone_is_underdeveloped_even_with_good_score():
    concept_cache = ["Giint_Project_Foo"]
    desc = "giint project foo"  # scores 100% against the cache
    result = _is_underdeveloped(desc, concept_cache, other_rel_count=0,
                                score_threshold=50, min_rel_count=2)
    assert result is True, "even a perfectly-scored description with 0 real rels must be flagged"
    print("✓ good description score but too few rels -> still under-structured (OR semantics)")


def test_empty_description_is_underdeveloped():
    result = _is_underdeveloped("", [], other_rel_count=0)
    assert result is True
    print("✓ empty description -> under-structured")


def test_threshold_is_a_strict_less_than_boundary():
    # score exactly AT the threshold should NOT trigger (score < threshold, not <=)
    concept_cache = ["Aaa", "Bbb", "Ccc", "Ddd"]
    # craft a description whose score lands exactly at 50: 2 of 4 meaningful words match
    desc = "aaa bbb zzz yyy"
    result = _is_underdeveloped(desc, concept_cache, other_rel_count=5,
                                score_threshold=50, min_rel_count=2)
    assert result is False, "a score exactly at the threshold must NOT trigger (strict <)"
    print("✓ score-threshold boundary is strictly less-than, not less-than-or-equal")


# ── _build_batch_goal / _format_rels ─────────────────────────────────────────────────────────────

def test_format_rels_empty_dict():
    result = _format_rels({})
    assert result.startswith("(none besides housekeeping"), result
    print("✓ empty relationships dict -> the housekeeping-only placeholder text")


def test_format_rels_sorted_and_joined():
    rels = {"produces": ["Fix_Commit"], "is_a": ["Bug_Report"]}
    result = _format_rels(rels)
    assert result == "is_a: [Bug_Report]; produces: [Fix_Commit]", result
    print("✓ relationships are sorted by key and joined with '; '")


def test_build_batch_goal_serves_every_concept_name_and_description():
    batch = [
        {"n": "Concept_A", "d": "a raw description", "t": "2026-07-01T00:00:00"},
        {"n": "Concept_B", "d": "", "t": "2026-07-01T00:00:01"},
    ]
    rels_by_concept = {"Concept_A": {"is_a": ["Foo"]}}
    goal = _build_batch_goal(batch, rels_by_concept)
    assert "Concept_A" in goal and "Concept_B" in goal
    assert "a raw description" in goal
    assert "(empty)" in goal   # Concept_B's blank description renders as (empty), not a raw ''
    assert "is_a: [Foo]" in goal
    assert "(none besides housekeeping" in goal  # Concept_B has no served relationships
    assert "ATOMIZE this batch of 2" in goal
    assert "GOAL ACCOMPLISHED" in goal
    print("✓ the goal serves every concept's name, description, and relationships")


def test_build_batch_goal_states_the_never_touch_description_law():
    batch = [{"n": "Concept_A", "d": "x", "t": "2026-07-01T00:00:00"}]
    goal = _build_batch_goal(batch, {})
    assert "OMIT the" in goal and "concept" in goal
    assert "source='webbing_agent'" in goal
    assert "NEVER delete" in goal
    assert "declared system type" in goal and "System_Type in an is_a list" in goal
    print("✓ the goal explicitly states the never-touch-description / additive-only / source-tag / "
          "no-system-type laws")


def test_prompt_and_goal_carry_every_soma_scenario_and_its_action():
    goal = _build_batch_goal([{"n": "Concept_A", "d": "x", "t": "2026-07-01T00:00:00"}], {})
    for where, text in (("WEBBER_SYSTEM_PROMPT", WEBBER_SYSTEM_PROMPT), ("the batch goal", goal)):
        for scenario, action in SOMA_SCENARIO_ACTIONS:
            assert scenario in text, f"{where} does not name the SOMA result {scenario!r}"
            assert action in text, f"{where} does not state the action {action!r}"
    print("✓ the system prompt and the goal both name every SOMA result and the action for it")


def test_the_do_lines_add_concept_writes_start_as_the_prompt_names_them():
    from carton_mcp.add_concept_tool import soma_result_lines
    verdict = ("mereo_errors=2\n  - zz_x is_a zz_type (not a known/defined type)\n"
               "  - zz_x is_a zz_other (defined but not DECLARED)\n"
               "soup_gaps=2\n  - zz_x claims to be skill. skill requires has_content (string_value). zz_x does "
               "not have has_content. Provide it.\n  - paiab claims to be personal_domain. personal_domain requires "
               "undefined_type_ref (personal_domain). paiab does not have undefined_type_ref. Provide it.")
    _, mereo = soma_result_lines(verdict, "Zz_X", "mereo_error")
    _, soup = soma_result_lines(verdict, "Zz_X", "soup")
    meant = "this is important to fill next, but only if {} is inside the meaning you meant: "
    shapes = [(mereo[0], "DO MEREO[1]: " + meant.format("Zz_Type") + "define Zz_Type"),
              (mereo[1], "DO MEREO[2]: " + meant.format("Zz_Other") + "declare Zz_Other a type"),
              (soup[0], "DO SOUP[1]: " + meant.format("it") + "add_concept Zz_X with properties has_content"),
              (soup[1], "DO SOUP[2]: leave it")]
    for line, prefix in shapes:
        assert line.startswith(prefix), (line, prefix)
    for named in (MEREO_FILL + "define Y", MEREO_FILL + "declare Y a type", SOUP_FILL + "add_concept X with properties",
                  "DO SOUP[n]: leave it"):
        assert named in WEBBER_SYSTEM_PROMPT, named
    assert soup[0].endswith("otherwise drop the is_a Skill claim."), soup[0]
    print("✓ each DO line add_concept writes starts with a shape the prompt names")


def test_prompt_and_goal_carry_the_domain_axis_law():
    # Card 726 condition 6: the webber reuses the served concept's domain and subdomain, and a name that is not
    # yet a domain node goes through the front door's about params; rooting is part_of, never an hwss_rooted edge.
    for phrase in ("HAS_DOMAIN and HAS_SUBDOMAIN", "pass subdomain_about", "domain_about and domain_part_of",
                   "not validly a Domain, its execution failed", "never write an hwss_rooted relationship",
                   "did not name new this run is not yours; leave it"):
        assert phrase in DOMAIN_AXIS_LAW, phrase
    goal = _build_batch_goal([{"n": "Concept_A", "d": "x", "t": "2026-07-01T00:00:00"}], {})
    for where, text in (("WEBBER_SYSTEM_PROMPT", WEBBER_SYSTEM_PROMPT), ("the batch goal", goal)):
        assert DOMAIN_AXIS_LAW in text, f"{where} does not carry DOMAIN_AXIS_LAW"
    print("✓ the system prompt and the goal both carry the domain axis law")


def test_one_run_is_three_iterations_of_200_tool_calls_and_ends_on_the_fenced_signal():
    # max_turns is heaven's iteration count; max_tool_calls reaches the agent constructor only as
    # HeavenAgentArgs.max_tool_calls (extra_agent_kwargs drops it, leaving heaven's 10 per iteration);
    # heaven ends agent mode only on the fenced GOAL ACCOMPLISHED, so both texts ask for exactly that.
    cfg = _webber_run_config("the goal", "a-model", {})
    assert cfg.max_turns == 3
    assert cfg.heaven_inputs.agent.max_tool_calls == 200
    assert "max_tool_calls" not in cfg.heaven_inputs.agent.extra_agent_kwargs
    goal = _build_batch_goal([{"n": "Concept_A", "d": "x", "t": "2026-07-01T00:00:00"}], {})
    for where, text in (("WEBBER_SYSTEM_PROMPT", WEBBER_SYSTEM_PROMPT), ("the batch goal", goal)):
        assert "```GOAL ACCOMPLISHED```" in text, f"{where} does not ask for the fenced completion"
    print("✓ one run is 3 iterations of up to 200 tool calls and ends on the fenced completion")


def test_base_rels_excluded_does_not_include_instantiates_or_produces():
    # instantiates/produces are REAL content structure and must count toward "other_rel_count" —
    # only the housekeeping/administrative edges are excluded.
    assert "INSTANTIATES" not in BASE_RELS_EXCLUDED
    assert "PRODUCES" not in BASE_RELS_EXCLUDED
    assert "IS_A" in BASE_RELS_EXCLUDED
    assert "PART_OF" in BASE_RELS_EXCLUDED
    print("✓ BASE_RELS_EXCLUDED excludes only housekeeping edges, never instantiates/produces")


if __name__ == "__main__":
    print("Testing webbing_agent PURE functions (_is_underdeveloped / _build_batch_goal / _format_rels)")
    print("=" * 70)
    test_low_description_score_is_underdeveloped()
    test_high_description_score_and_enough_rels_is_not_underdeveloped()
    test_low_rel_count_alone_is_underdeveloped_even_with_good_score()
    test_empty_description_is_underdeveloped()
    test_threshold_is_a_strict_less_than_boundary()
    test_format_rels_empty_dict()
    test_format_rels_sorted_and_joined()
    test_build_batch_goal_serves_every_concept_name_and_description()
    test_build_batch_goal_states_the_never_touch_description_law()
    test_prompt_and_goal_carry_every_soma_scenario_and_its_action()
    test_the_do_lines_add_concept_writes_start_as_the_prompt_names_them()
    test_prompt_and_goal_carry_the_domain_axis_law()
    test_one_run_is_three_iterations_of_200_tool_calls_and_ends_on_the_fenced_signal()
    test_base_rels_excluded_does_not_include_instantiates_or_produces()
    print("=" * 70)
    print("ALL WEBBING_AGENT UNIT TESTS PASSED")
