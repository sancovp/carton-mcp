"""Issue #801: every CRITICAL line of a SOMA verdict reaches the add_concept result; card 702: the DEATH block
rides on the result; card 710: the result's first line says the DO lines at the end are the instructions, the
middle carries every feature (Files and Neo4j, MEREO, SOUP, CODE, SYSTEM_TYPE, D2, CB, FILL, SOMA error, CRITICAL,
DEATH, PROMPTER, the soma_run_id note), one SOMA help line, and the DO lines last; get_concept shows the event
name and d-chain counts only with details.

Run as a script from this directory, one MARKER line per test.
"""

import os
import tempfile

import add_concept_tool as act
import carton_mcp.add_concept_tool as installed_act
import carton_mcp.carton_breaker as breaker
import carton_mcp.carton_utils as cu
import carton_mcp.server_fastmcp as server_fastmcp
from soma_prolog import soup_system_type_scream as scream

CRIT = ("CRITICAL vaulted_not_code=1: vaulting makes a thing code, and these vaulted registrations "
        "are not code: dchain_x. Each is vaulted wrong: its d-chains do not work, it cannot acquire "
        "d-chains, and mereo does not run on it. Re-vault it until it grades code.")
FIRST = f"✅ Zz_Relay_801: CartON Files queued, Neo4j queued. {act.SOMA_INSTRUCTIONS_POINTER}"


class _NoGraph:
    def __init__(self, *a, **k):
        pass

    def query_wiki_graph(self, *a, **k):
        return {"success": True, "data": []}


def _run(verdict, soma_up=True, hide_youknow=False, description="a relay probe", cb=None, soma_raises=None):
    queued = []

    def _validate(**k):
        if soma_raises:
            raise RuntimeError(soma_raises)
        return {"result": verdict}

    act._soma_up = lambda: soma_up
    act.soma_validate = _validate
    act.submit_queue_entry = lambda entry, suffix="": queued.append(entry) or "q.json"
    act.CARTON_CB_STORE = cb is not None
    act._cb_place = lambda *a, **k: cb
    breaker.check_breaker = lambda **k: None
    cu.CartOnUtils = _NoGraph
    os.environ["HEAVEN_DATA_DIR"] = tempfile.mkdtemp()
    out = act.add_concept_tool_func(
        "Zz_Relay_801", description,
        [{"relationship": "is_a", "related": ["Thing"]}, {"relationship": "part_of", "related": ["Probe"]}],
        hide_youknow=hide_youknow, cb_guidance=cb is not None)
    return out, queued


def _do_tail(out):
    """The lines from the first DO line on; asserts each of them is a DO line."""
    lines = out.rstrip().split("\n")
    at = next((i for i, line in enumerate(lines) if line.startswith("DO ")), len(lines))
    assert all(line.startswith("DO ") for line in lines[at:]), out
    return lines[at:]


def t_pure_keeps_every_critical_line_verbatim_in_order():
    verdict = f"event=e1 source=s\nstatus=a:code\n  {CRIT}\nCRITICAL second: other"
    assert act.soma_critical_lines(verdict) == f"{CRIT}\nCRITICAL second: other"
    assert act.soma_critical_lines("event=e1\nstatus=a:code\ncritical lowercase is not it") == ""
    assert act.soma_critical_lines("") == "" and act.soma_critical_lines(None) == ""
    print("  MARKER: PURE_CRITICAL_LINES_OK")


def t_first_line_names_the_write_the_store_and_the_instructions():
    out, queued = _run("event=e1 source=agent\nstatus=zz_relay_801:code")
    assert out.split("\n")[0] == FIRST, out
    assert len(queued) == 1
    print("  MARKER: FIRST_LINE_POINTER_OK")


def t_code_and_system_type_carry_the_d_chain_count():
    code, _ = _run("event=e1 deduction_chains_fired=2 unmet=3\nstatus=zz_relay_801:code")
    system_type, queued = _run("event=e1 deduction_chains_fired=2 unmet=0\nstatus=zz_relay_801:code")
    assert "\nSOMA: CODE, 3 d-chains pending.\n" in code, code
    assert "\nSOMA: SYSTEM_TYPE, all d-chains satisfied.\n" in system_type and queued[0]["is_system_type"] is True
    print("  MARKER: CODE_AND_SYSTEM_TYPE_OK")


def t_mereo_keeps_its_reason_and_its_instruction_names_it():
    claim = "zz_relay_801 is_a zz_kind (not a known/defined type)"
    out, queued = _run(f"event=e1\nstatus=zz_relay_801:mereo_error\nmereo_errors=1\n  - {claim}")
    assert ("SOMA: MEREO: not validly the type it claims, its execution failed; CartON keeps the write so it can "
            "be seen.") in out and f"MEREO[1]: {claim}" in out, out
    assert _do_tail(out) == ["DO MEREO[1]: this is important to fill next, but only if Zz_Kind is inside the meaning "
                             "you meant: define Zz_Kind (add_concept Zz_Kind with is_a, part_of, produces and "
                             "instantiates); otherwise drop the is_a Zz_Kind claim."], out
    assert len(queued) == 1
    print("  MARKER: MEREO_KEPT_OK")


SOMA_SOUP_CLAUSE = ("It is not validly that type: its execution failed. The part it names is important to fill next "
                    "only if it is inside the meaning the writer meant.")
GAPS = [f"zz_relay_801 claims to be skill. skill requires {p} (string_value). zz_relay_801 does not have {p}. "
        f"Provide it. {SOMA_SOUP_CLAUSE}" for p in ("has_content", "has_description", "has_domain", "has_name")]
MARKER_GAP = "Tool call zz_relay_801 references unknown needs_domains: domain_list. Explain it."
TAGS_GAP = ("[Soma_Verdict, Verdict_Readability] all claim to be hwss_domain and are missing undefined_type_ref "
            "(hwss_domain). Provide it.")


def t_soup_keeps_every_gap_and_collapses_only_repeated_sentences():
    skill_gap = "SKILL: No domain assignment. Assign via has_domains."
    gaps = "\n".join(f"  - {g}" for g in GAPS + [MARKER_GAP, skill_gap, TAGS_GAP])
    out, _ = _run(f"event=e1 unmet=2\nstatus=zz_relay_801:soup\nsoup_gaps=7\n{gaps}")
    assert "\nSOMA: SOUP, 2 d-chains pending: not validly the type it claims, its execution failed.\n" in out, out
    assert ("SOUP[1]: zz_relay_801 claims to be skill. skill requires has_content, has_description, has_domain, "
            "has_name (each string_value). zz_relay_801 does not have them, so zz_relay_801 is not validly skill: "
            "its execution failed.") in out, out
    assert f"SOUP[2]: {MARKER_GAP}" in out and f"SOUP[3]: {skill_gap}" in out and f"SOUP[4]: {TAGS_GAP}" in out, out
    assert out.count("claims to be skill") == 1, out
    assert _do_tail(out) == [
        "DO SOUP[1]: this is important to fill next, but only if it is inside the meaning you meant: add_concept "
        "Zz_Relay_801 with properties has_content, has_description, has_domain and has_name, each filled from what "
        "Zz_Relay_801 is; otherwise drop the is_a Skill claim.",
        "DO SOUP[2], SOUP[3]: this is important to fill next, but only if it is inside the meaning you meant for "
        "Zz_Relay_801: do what it says; otherwise leave it.",
        "DO SOUP[4]: leave it: undefined_type_ref means Hwss_Domain was not loaded as a type for this write, so "
        "nothing can be given."], out
    print("  MARKER: SOUP_EVERY_GAP_OK")


FILL = ("zz_relay_801 is_a zz_kind, which is not a defined type. The claim does not demote zz_relay_801, a "
        "declared system type. Define zz_kind: give it is_a, part_of, produces and instantiates.")


def t_fill_keeps_soma_words_and_names_its_token():
    other = FILL.replace("zz_relay_801", "zz_other_type")
    assert act.soma_isa_fill_lines(f"system_type_isa_fills=2\n  - {FILL}\n  - {other}", "Zz_Relay_801") == [FILL]
    out, queued = _run(f"event=e1\nstatus=zz_relay_801:code\nsystem_type_isa_fills=1\n  - {FILL}")
    assert f"FILL[1]: {FILL}" in out and "SOMA: SYSTEM_TYPE, all d-chains satisfied." in out, out
    assert _do_tail(out) == ["DO FILL[1]: this is important to fill next, but only if Zz_Kind is inside the meaning "
                             "you meant: define Zz_Kind (add_concept Zz_Kind with is_a, part_of, produces and "
                             "instantiates); otherwise drop the is_a Zz_Kind claim."], out
    assert queued[0]["is_system_type"] is True
    print("  MARKER: FILL_KEPT_OK")


def t_d2_shows_its_percent_every_untraced_name_and_the_full_case():
    partial, _ = _run("event=e1\nstatus=zz_relay_801:code", description="a relay check")
    full, _ = _run("event=e1\nstatus=zz_relay_801:code", description="a relay probe naming Thing and Probe")
    assert "D2: 0% of the declared relationships are traced in the description; not mentioned: Thing, Probe." \
        in partial, partial
    assert "D2: 100%, every declared relationship is traced in the description." in full, full
    print("  MARKER: D2_KEPT_OK")


def t_cb_region_coordinate_and_prompter_block_are_shown():
    out, _ = _run("event=e1\nstatus=zz_relay_801:code", cb=(1, 0.5, "0.123", "CB PROMPTER: flow and griess"))
    assert "CB: region=system_type coord=0.123." in out and "CB PROMPTER: flow and griess" in out, out
    print("  MARKER: CB_KEPT_OK")


def t_soma_error_is_shown_and_the_write_is_saved():
    out, queued = _run("", soma_raises="connection refused")
    assert "SOMA error: connection refused. The write was not graded." in out and len(queued) == 1, out
    print("  MARKER: SOMA_ERROR_KEPT_OK")


DEATH = scream.block({"zz_soup_type": "is_a zz_kind, which is not a known type"})


def t_saved_result_order_death_after_line_one_then_info_then_help_then_do():
    gaps = "\n".join(f"  - {g}" for g in GAPS)
    out, _ = _run(f"{DEATH}\nevent=e1 source=agent\nstatus=zz_relay_801:soup\n{CRIT}\nsoup_gaps=4\n{gaps}")
    lines = out.split("\n")
    death_at = next(i for i, line in enumerate(lines) if line.startswith(DEATH.split("\n")[0]))
    do = _do_tail(out)
    assert lines[0] == FIRST and death_at == 1, out
    assert lines.index(CRIT) < lines.index(act.SOMA_HELP_POINTER) == len(lines) - len(do) - 1, out
    assert len(do) == 1 and "zz_soup_type" not in out.split(scream.HEADER)[0], out
    print("  MARKER: SAVED_ORDER_OK")


def t_rejected_result_order_and_its_reason():
    out, queued = _run(f"{DEATH}\nevent=e1 source=agent\nstatus=zz_relay_801:contradiction\n"
                       f"contradictions=1\n  - zz_relay_801 is_a both endurant and perdurant\n{CRIT}")
    lines = out.split("\n")
    assert lines[0].startswith("❌ Zz_Relay_801 REJECTED: geometric contradiction; CartON did not store it.") \
        and act.SOMA_INSTRUCTIONS_POINTER in lines[0], out
    assert DEATH in out and CRIT in out and "would decohere the geometry even as soup" in out, out
    assert "CONTRADICTION: " in out and _do_tail(out)[0].startswith("DO CONTRADICTION: remove") and queued == []
    assert lines[-2] == act.SOMA_HELP_POINTER, out
    print("  MARKER: REJECTED_ORDER_OK")


def t_the_mcp_result_keeps_line_one_first_death_next_and_the_do_lines_last():
    gaps = "\n".join(f"  - {g}" for g in GAPS)
    raw, _ = _run(f"{DEATH}\nevent=e1\nstatus=zz_relay_801:soup\nsoup_gaps=4\n{gaps}")
    shown = server_fastmcp._format_concept_result("Zz_Relay_801", raw, note="✅ accepted compose-suggestion r1")
    lines = shown.split("\n")
    assert lines[0] == FIRST and lines[1] == "✅ accepted compose-suggestion r1" and lines[2] == DEATH.split("\n")[0]
    assert shown.count(scream.HEADER) == 1 and _do_tail(shown) == _do_tail(raw), shown
    plain = server_fastmcp._format_concept_result("Zz_Relay_801", _run("event=e1\nstatus=zz_relay_801:code")[0])
    assert plain.split("\n")[0] == FIRST and scream.HEADER not in plain, plain
    print("  MARKER: MCP_ORDER_OK")


def t_one_help_line_on_every_verdict_and_none_without_one():
    saved, _ = _run("event=e1 source=agent\nstatus=zz_relay_801:code")
    rejected, _ = _run("event=e1 source=agent\nstatus=zz_relay_801:contradiction\ncontradictions=1\n"
                       "  - zz_relay_801 is_a both")
    assert saved.count(act.SOMA_HELP_POINTER) == 1 and rejected.count(act.SOMA_HELP_POINTER) == 1
    assert act.SOMA_HELP_POINTER == "SOMA help: use the soma-help skill if you have not used it yet."
    hidden, _ = _run("event=e1\nstatus=zz_relay_801:soup", hide_youknow=True)
    down, _ = _run("event=e1\nstatus=zz_relay_801:soup", soma_up=False)
    for out in (hidden, down):
        assert act.SOMA_HELP_POINTER not in out and "SOMA" not in out.split("\n", 1)[1] and out.startswith(FIRST), out
    print("  MARKER: ONE_HELP_LINE_OK")


class _OneConcept:
    def query_wiki_graph(self, *a, **k):
        return {"success": True, "data": [{
            "name": "Zz_Relay_801", "description": "a relay probe", "score": 40,
            "props": {"n": "Zz_Relay_801", "status": "open"},
            "relationships": [{"type": "IS_A", "target": "Skill"}, {"type": "PART_OF", "target": "Probe"}]}]}


def t_get_concept_default_and_details():
    calls = []
    gaps = "\n".join(f"  - {g}" for g in GAPS)
    installed_act.SOMA_AVAILABLE = True
    installed_act.soma_validate = lambda **k: calls.append(k) or {
        "result": f"event=get_concept_e9 source=get_concept\ntriples=2 deduction_chains_fired=3 unmet=1\n"
                  f"status=zz_relay_801:soup\nsoup_gaps=4\n{gaps}"}
    server_fastmcp.utils = _OneConcept()
    get_concept = getattr(server_fastmcp.get_concept, "fn", server_fastmcp.get_concept)
    plain = get_concept("Zz_Relay_801").text
    lines = plain.split("\n")
    assert lines[0] == f"Name: Zz_Relay_801. {installed_act.SOMA_INSTRUCTIONS_POINTER}", plain
    assert "Description [40% description coverage]: a relay probe" in plain and 'Props:{status: "open"}' in plain
    assert "is_a Skill" in plain and "part_of Probe" in plain and ("SOMA: SOUP, 1 d-chain pending: not validly the "
                                                                   "type it claims, its execution failed.") in plain
    assert "SOUP[1]: " in plain and lines[-1].startswith("DO SOUP[1]: this is important to fill next, but only if "
                                                         "it is inside the meaning you meant: add_concept Zz_Relay_801")
    assert lines[-2] == installed_act.SOMA_HELP_POINTER and plain.count(installed_act.SOMA_HELP_POINTER) == 1
    for hidden in ("event=", "deduction_chains_fired", "get_concept_e9"):
        assert hidden not in plain, (hidden, plain)
    full = get_concept("Zz_Relay_801", details=True).text
    assert "event=get_concept_e9" in full and "deduction_chains_fired=3" in full, full
    assert full.split("\n")[-1] == lines[-1] and len(calls) == 2, full
    print("  MARKER: GET_CONCEPT_DEFAULT_AND_DETAILS_OK")


if __name__ == "__main__":
    tests = [t_pure_keeps_every_critical_line_verbatim_in_order,
             t_first_line_names_the_write_the_store_and_the_instructions,
             t_code_and_system_type_carry_the_d_chain_count, t_mereo_keeps_its_reason_and_its_instruction_names_it,
             t_soup_keeps_every_gap_and_collapses_only_repeated_sentences, t_fill_keeps_soma_words_and_names_its_token,
             t_d2_shows_its_percent_every_untraced_name_and_the_full_case,
             t_cb_region_coordinate_and_prompter_block_are_shown, t_soma_error_is_shown_and_the_write_is_saved,
             t_saved_result_order_death_after_line_one_then_info_then_help_then_do,
             t_rejected_result_order_and_its_reason,
             t_the_mcp_result_keeps_line_one_first_death_next_and_the_do_lines_last,
             t_one_help_line_on_every_verdict_and_none_without_one, t_get_concept_default_and_details]
    for t in tests:
        t()
    print(f"ALL {len(tests)} PASS")
