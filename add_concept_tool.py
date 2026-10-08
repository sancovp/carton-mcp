# add_concept_tool.py


### HEAVEN CONVERSION
# (removed 2026-06-25) The heaven-tool wrapper import `from heaven_base import BaseHeavenTool,
# ToolArgsSchema, ToolResult` was pulling langchain_core (~53 MB into EVERY carton process) ONLY to
# define the AddConceptTool/RenameConceptTool BaseHeavenTool wrappers at the bottom of this file — which
# NOTHING imports (carton exposes its tools via FastMCP/the MCP, not heaven's tool system; ToolResult was
# never even referenced). The MCP uses add_concept_tool_func / rename_concept_func DIRECTLY. heaven_base's
# package init is light (+0 MB) and the lazy `heaven_base.tool_utils.neo4j_utils` import is light (+4 MB),
# so dropping this import + the unused wrapper classes makes carton import zero langchain. (Verified live.)
from pathlib import Path
from typing import Optional, Dict, Any, List
import subprocess
import shutil
import json
import re
import os
import sys
import time
import traceback
from difflib import get_close_matches
import logging

import urllib.request as _urllib_request  # used by the SOMA integration below
from urllib.parse import urlparse as _urlparse
# YOUKNOW removed 2026-06-15: YOUKNOW (:8102) is DEAD CODE — SOMA (:8091) is THE
# validator now (system-type/ontology validation belongs only in SOMA). The old
# youknow_validate / _check_youknow_available / YOUKNOW_AVAILABLE health-check block
# had ZERO live callers and fired a spurious error log on every import; removed.

# SOMA integration - calls the SOMA HTTP daemon (port 8091).
# SOMA has ONE entrypoint: POST /event. Replaces YOUKNOW for concept validation.
#
# ⚠ THIS CALL IS THE DIRECTION OF TRUTH, AND READING EITHER SIDE MUST TEACH YOU BOTH
# (the counterpart note is soma_prolog/vault.py's module header — keep them in step).
#
#   CARTON IS THE TOTAL STORE. SOMA's quadstore is its ~10x-faster REFLECTION: the
#   thing SOMA deduces from, not itself the record (Isaac, 2026-08-11). A concept
#   ENTERS here — the carton write — and this POST is what reflects it into SOMA.
#   That is why the write and the POST live in one function and not two.
#
#   ⇒ THE COROLLARY THAT KEEPS BEING MISSED: anything that POSTs to /event WITHOUT
#   coming through carton — vault(), add_dchain, register_foundation — populates the
#   REFLECTION ONLY, and the record never learns about it. That is not a bug in those
#   callers; SOMA is deliberately separable as a library (see vault.py) so it can
#   outlive carton. But we never SHIP them separated, so in any running system a
#   /event-only write leaves the two stores disagreeing, and the parity law (Isaac
#   2026-08-03: their concept counts must never differ) is violated from that moment.
#   MEASURED: a fresh box with 165 SOMA subjects against 41 carton nodes.
# ENV-OVERRIDABLE (2026-06-27): set SOMA_URL to reach a REMOTE (containerized) SOMA,
# e.g. SOMA_URL=http://soma-container:8091/event. Default = local daemon. vault.py is
# already env-ready (vault.py:58); this makes the carton add_concept path match so the
# whole system can point at a mem-isolated SOMA container.
SOMA_URL = os.environ.get("SOMA_URL", "http://localhost:8091/event")

# STORE-PARITY GUARD, carton side (Isaac's ruling 2026-08-03): SOMA never
# touches neo4j by design — CARTON has the connection — so each event POST
# carries carton's :Wiki node count as an EPHEMERAL parity observation
# ({"name": "tc_carton_parity", "carton_node_count": N}). SOMA's core.py pops
# it before the pipeline (it never reaches Prolog or the store) and SCREAMS a
# store_parity= block in the verdict when its mirror's distinct-subject count
# diverges catastrophically (the Jul-5 silent-reset class). TTL-cached count
# (the counted-window discipline: one count query per window, never per
# write); an attach failure logs LOUD and skips — a missing count is absence
# of signal for that event, never a wrong signal, and the SOMA-side sentinel
# guard covers the catastrophe class structurally.
_PARITY_COUNT_TTL_S = 300.0
_parity_count_cache = {"at": 0.0, "count": None}


def _carton_node_count():
    """TTL-cached carton :Wiki node count for the parity observation, or None."""
    now = time.monotonic()
    if (_parity_count_cache["count"] is not None
            and now - _parity_count_cache["at"] <= _PARITY_COUNT_TTL_S):
        return _parity_count_cache["count"]
    try:
        from carton_mcp.carton_utils import CartOnUtils as _ParityUtils
        row = _ParityUtils().query_wiki_graph(
            "MATCH (c:Wiki) RETURN count(c) AS n", {})
        data = (row.get("data") or []) if isinstance(row, dict) else []
        n = int(data[0]["n"]) if data else None
        if n is not None:
            _parity_count_cache["count"] = n
            _parity_count_cache["at"] = now
        return n
    except Exception as e:
        logging.getLogger(__name__).warning(
            "store-parity: carton node count unavailable (guard skipped this "
            "window): %s", e)
        return None


def soma_validate(source, observations, domain="default", timeout=120):
    """timeout: urlopen socket timeout (seconds). Default 120 fits the ordinary
    single-concept event. A MULTI-observation event (the vault lane's atomic step 1)
    must pass more: the pipeline cost scales with the event, the daemon serializes
    requests, and a too-short timeout closes the socket mid-response — the server
    keeps working while the caller reports SOMA_UNREACHABLE (measured 2026-08-18 on
    the boot-register: chunk step-1 events timing out at 120s behind earlier chunks)."""
    # Attach the parity observation WITHOUT mutating the caller's list. Only
    # the list shape carries it (the dict observation_data shape has no place
    # for it and core.py's extractor only scans lists).
    obs_out = observations
    if isinstance(observations, list):
        n = _carton_node_count()
        if n is not None:
            obs_out = list(observations) + [{
                "name": "tc_carton_parity",
                "carton_node_count": n,
                "relationships": [],
            }]
    body = json.dumps({"source": source, "observations": obs_out, "domain": domain}).encode()
    req = _urllib_request.Request(SOMA_URL, data=body,
                                  headers={"Content-Type": "application/json"})
    with _urllib_request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data


def soma_critical_lines(soma_result: str) -> str:
    """The CRITICAL lines of a SOMA verdict, verbatim and newline-joined.

    Args:
        soma_result: The verdict string SOMA returned for the event.

    Returns:
        str: Every line that starts with "CRITICAL ", in verdict order, or '' when none does.
    """
    return "\n".join(line.strip() for line in (soma_result or "").splitlines()
                     if line.strip().startswith("CRITICAL "))


SOMA_ISA_FILLS_HEADER = "system_type_isa_fills="


def soma_isa_fill_lines(soma_result: str, concept_name: str) -> list:
    """The fill signals SOMA gave for ``concept_name`` in the system_type_isa_fills block of a verdict.

    Each names an undefined ``is_a`` target of a declared system type, which keeps its grade.

    Args:
        soma_result: The verdict string SOMA returned for the event.
        concept_name: The concept written, matched to SOMA's normalized name without underscores or case.

    Returns:
        list: Each fill line naming the concept, without its ``- `` bullet, in verdict order.
    """
    key = concept_name.lower().replace("_", "")
    fills, inside = [], False
    for line in (soma_result or "").splitlines():
        if line.startswith(SOMA_ISA_FILLS_HEADER):
            inside = True
            continue
        if not inside:
            continue
        body = line.strip()
        if not body.startswith("- "):
            break
        if body[2:].split(" is_a ", 1)[0].lower().replace("_", "") == key:
            fills.append(body[2:])
    return fills


def split_soma_death_block(text: str) -> tuple:
    """Split off the DEATH block SOMA opens a verdict with while any system type is soup.

    Args:
        text: A SOMA verdict, or an add_concept result that carries one.

    Returns:
        tuple: ``(block, rest)`` — the block verbatim, or '' when there is none, and the text without it.
    """
    try:
        from soma_prolog import soup_system_type_scream as _scream
    except ImportError:
        logger.warning("soma_prolog is not importable here: a DEATH block cannot be lifted\n%s",
                       traceback.format_exc())
        return "", text or ""
    block = _scream.extract(text)
    return block, (_scream.without(text) if block else (text or ""))


SOMA_HELP_POINTER = "SOMA help: use the soma-help skill if you have not used it yet."
SOMA_INSTRUCTIONS_POINTER = "Any lines starting DO at the end are the instructions and must be followed."

_SOMA_REQUIRES = re.compile(
    r"^(\S+) claims to be (\S+)\. \2 requires (\S+) \(([^)]+)\)\. \1 does not have \3\. Provide it\.(?: .*)?$")
_SOMA_ALL_MISSING = re.compile(
    r"^\[(.+)\] all claim to be (\S+) and are missing (\S+) \(([^)]+)\)\. Provide it\.(?: .*)?$")
_SOMA_FAILED = "not validly the type it claims, its execution failed"
_SOMA_IF_MEANT = "this is important to fill next, but only if"
_SOMA_PROPERTY_KINDS = {"string_value": "", "int_value": "an integer", "float_value": "a number",
                        "bool_value": "true or false", "list_value": "a list", "dict_value": "a mapping"}


def _soma_key(name: str) -> str:
    return (name or "").lower().replace("_", "")


def _verdict_block_items(soma_result: str, header: str) -> list:
    """The ``- `` items under one block header of a SOMA verdict, without their bullet, in verdict order."""
    items, inside = [], False
    for line in (soma_result or "").splitlines():
        if line.startswith(header):
            inside = True
            continue
        if inside:
            body = line.strip()
            if not body.startswith("- "):
                break
            items.append(body[2:].strip())
    return items


def _soma_join(items: list) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def soma_concept_status(soma_result: str, concept_name: str) -> Optional[str]:
    """The grade a ``status=<concept>:<grade>`` line of a SOMA verdict gives one concept, names compared without
    underscores or case; None when no status line names it."""
    for line in (soma_result or "").splitlines():
        if line.startswith("status="):
            for entry in line[len("status="):].split(","):
                name, sep, grade = entry.strip().rpartition(":")
                if sep and _soma_key(name) == _soma_key(concept_name):
                    return grade.strip().lower()
    return None


def soma_grade_flags(status: Optional[str], unmet: int, has_soup: bool, all_core_met: bool) -> tuple:
    """(is_soup, is_code, is_system_type) for one concept: from SOMA's status= grade when it gave one (a mereo_error is
    soup; system_type, an instance with exactly the shape of its system type, is SYSTEM_TYPE; code and ont are
    SYSTEM_TYPE with no unmet d-chain and CODE otherwise), else from the soup gaps and core requirements of the
    verdict."""
    if status in ("soup", "mereo_error"):
        return True, False, False
    if status == "system_type":
        return False, False, True
    if status in ("code", "ont"):
        return False, unmet > 0, unmet == 0
    return has_soup, (not has_soup) and all_core_met and unmet > 0, (not has_soup) and all_core_met and unmet == 0


def soma_grade_line(status: Optional[str], unmet: int, flags: tuple, error: str = "") -> str:
    """The SOMA line of a result: MEREO, SOUP, CODE or SYSTEM_TYPE with the d-chain count, or the SOMA error."""
    if error:
        return f"SOMA error: {error}. The write was not graded."
    is_soup, is_code, is_system_type = flags
    pending = f", {unmet} d-chain{'' if unmet == 1 else 's'} pending" if unmet else ""
    if status == "mereo_error":
        return f"SOMA: MEREO{pending}: {_SOMA_FAILED}; CartON keeps the write so it can be seen."
    if is_soup:
        return f"SOMA: SOUP{pending}: {_SOMA_FAILED}."
    if is_system_type:
        return "SOMA: SYSTEM_TYPE, all d-chains satisfied."
    if is_code:
        return f"SOMA: CODE{pending}."
    return f"SOMA: {status.upper() if status else 'not graded'}{pending}."


def _soma_type_do(claim: str, concept_name: str) -> str:
    """The instruction for an is_a claim naming a type SOMA does not know or that is not declared."""
    if " is_a " not in claim:
        return f"{_SOMA_IF_MEANT} it is inside the meaning you meant for {concept_name}: do what it says; otherwise leave it."
    name = normalize_concept_name(re.split(r"[\s,(]", claim.split(" is_a ", 1)[1].strip(), 1)[0])
    if "not DECLARED" in claim:
        return (f"{_SOMA_IF_MEANT} {name} is inside the meaning you meant: declare {name} a type (it is defined; add "
                f"System_Type to its is_a); otherwise drop the is_a {name} claim.")
    return (f"{_SOMA_IF_MEANT} {name} is inside the meaning you meant: define {name} (add_concept {name} with is_a, "
            f"part_of, produces and instantiates); otherwise drop the is_a {name} claim.")


def _soma_params_text(params: list) -> str:
    """SOMA's words for the params one type requires: each param with its kind."""
    if len({k for _, k in params}) == 1:
        return f"{', '.join(p for p, _ in params)} ({'each ' if len(params) > 1 else ''}{params[0][1]})"
    return ", ".join(f"{p} ({k})" for p, k in params)


def _soma_how(params: list) -> str:
    """How add_concept gives each (param, kind): a value kind as a property, a concept kind as a relationship."""
    props = [p + (f" ({_SOMA_PROPERTY_KINDS[k]})" if _SOMA_PROPERTY_KINDS[k] else "")
             for p, k in params if k in _SOMA_PROPERTY_KINDS]
    rels = [f"{p} to {'an existing' if k == 'concept_ref' else 'a ' + normalize_concept_name(k)} concept"
            for p, k in params if k not in _SOMA_PROPERTY_KINDS]
    return " and ".join(([f"properties {_soma_join(props)}"] if props else [])
                        + ([f"relationships {_soma_join(rels)}"] if rels else []))


def _soma_gap_units(concept_name: str, gaps: list) -> list:
    """(text, instruction) per soup gap sentence, in verdict order; the requirement sentences one type states about one
    concept become one unit that keeps every param and its kind."""
    groups, order = {}, []
    for gap in gaps:
        m = _SOMA_REQUIRES.match(gap)
        if m and m.group(3) != "undefined_type_ref":
            key = (m.group(1), m.group(2))
            if key not in groups:
                groups[key] = []
                order.append(key)
            if (m.group(3), m.group(4)) not in groups[key]:
                groups[key].append((m.group(3), m.group(4)))
        else:
            order.append(gap)
    units = []
    for item in order:
        if isinstance(item, tuple):
            subject, type_name = item
            params = groups[item]
            text = (f"{subject} claims to be {type_name}. {type_name} requires {_soma_params_text(params)}. "
                    f"{subject} does not have {'them' if len(params) > 1 else 'it'}, so {subject} is not validly "
                    f"{type_name}: its execution failed.")
            if _soma_key(subject) == _soma_key(concept_name):
                do = (f"{_SOMA_IF_MEANT} it is inside the meaning you meant: add_concept {concept_name} with "
                      f"{_soma_how(params)}, {'each ' if len(params) > 1 else ''}filled from what {concept_name} is; "
                      f"otherwise drop the is_a {normalize_concept_name(type_name)} claim.")
            else:
                do = (f"{_SOMA_IF_MEANT} {normalize_concept_name(subject)} is inside the meaning you meant: add_concept "
                      f"{normalize_concept_name(subject)} with {_soma_how(params)}; otherwise leave it.")
            units.append((text, do))
            continue
        requires, missing = _SOMA_REQUIRES.match(item), _SOMA_ALL_MISSING.match(item)
        if (requires or missing) and (requires or missing).group(3) == "undefined_type_ref":
            do = (f"leave it: undefined_type_ref means {normalize_concept_name((requires or missing).group(2))} was not "
                  f"loaded as a type for this write, so nothing can be given.")
        elif missing:
            subjects = _soma_join([normalize_concept_name(s.strip()) for s in missing.group(1).split(",")])
            do = (f"{_SOMA_IF_MEANT} {subjects} {'are' if ' and ' in subjects else 'is'} inside the meaning you meant: "
                  f"give {subjects} {_soma_how([(missing.group(3), missing.group(4))])}; otherwise leave it.")
        else:
            do = f"{_SOMA_IF_MEANT} it is inside the meaning you meant for {concept_name}: do what it says; otherwise leave it."
        units.append((item, do))
    return units


def soma_result_lines(soma_result: str, concept_name: str, status: Optional[str]) -> tuple:
    """SOMA's verdict on one write as a result shows it: numbered information lines, and one DO line per information
    line naming it by the same token.

    Args:
        soma_result: The verdict SOMA returned for the write, without its DEATH block.
        concept_name: The concept written, as CartON names it.
        status: SOMA's grade for the concept from its ``status=`` line, or None when the verdict has none.

    Returns:
        tuple: (info, do), each a list of lines in verdict order. MEREO[n] is an is_a claim of this concept naming a
        type SOMA does not know (when the grade is mereo_error); FILL[n] a declared system type's is_a fill; SOUP[n]
        a soup gap (when the grade is soup, unvalidated or absent), the requirement sentences one type states about
        one concept collapsed into one line that keeps every param and its kind. ``DO SOUP[n]: ...`` is the fill or
        drop for SOUP[n].
    """
    info, tokens_by_instruction, counts, seen = [], {}, {}, set()

    def add(tag, text, instruction):
        if (tag, text) in seen:
            return
        seen.add((tag, text))
        counts[tag] = counts.get(tag, 0) + 1
        info.append(f"{tag}[{counts[tag]}]: {text}")
        tokens_by_instruction.setdefault(instruction, []).append(f"{tag}[{counts[tag]}]")

    if status == "mereo_error":
        for claim in _verdict_block_items(soma_result, "mereo_errors="):
            if _soma_key(claim.split(" is_a ", 1)[0]) == _soma_key(concept_name):
                add("MEREO", claim, _soma_type_do(claim, concept_name))
    for fill in soma_isa_fill_lines(soma_result, concept_name):
        add("FILL", fill, _soma_type_do(fill, concept_name))
    if status in (None, "soup", "unvalidated"):
        for text, instruction in _soma_gap_units(concept_name, _verdict_block_items(soma_result, "soup_gaps=")):
            add("SOUP", text, instruction)
    do = [f"DO {', '.join(tokens)}: {instruction}" for instruction, tokens in tokens_by_instruction.items()]
    return info, do


# CARTON → CRYSTAL BALL fan-out (2026-07-02, canon/CORE-SENTENCE-SPECTRAL-SEQUENCE.md).
# carton SAYS the core sentence, SOMA ENFORCES it (soma_validate above), CB ADDRESSES it
# (places it as a coordinate). carton fans the SAME said sentence to BOTH — no CB→SOMA
# wire — and JOINS {cb_coordinate, cb_encoded, soma_region} onto the one node as PROPERTIES.
# Best-effort: a CB miss NEVER blocks the carton write (fail loud, keep the soup). Default on.
CARTON_CB_STORE = os.environ.get("CARTON_CB_STORE", "1") not in ("0", "false", "False", "")
CARTON_CB_STORE_URL = os.environ.get("CARTON_CB_STORE_URL", "http://localhost:3000/api/cb/store")
CARTON_CB_FLOW_URL = os.environ.get("CARTON_CB_FLOW_URL", "http://localhost:3000/api/cb/flow")
CARTON_CB_KEY_FILE = os.environ.get("CARTON_CB_KEY_FILE", "/tmp/heaven_data/cb_api_key.txt")

def _cb_trace(e) -> str:
    """The traceback to append to a CB failure log, or '' when the trace carries nothing.

    A CB failure is logged LOUD and that stays true — but loud is about SIGNAL, and a transport
    error to a service that is simply not running has none beyond its own message: the urllib
    stack is the same nine frames every time and says only that urlopen could not connect. Two
    of those per carton write is what a seal or a commit prints hundreds of lines of, which is a
    real cost, because it pushes every reader toward piping these CLIs through a trimmer — and a
    pipe that trims is one keystroke from a pipe that discards.

    Args:
        e: The exception caught around the CB call.

    Returns:
        str: '' for a transport error (OSError covers urllib's URLError and ConnectionRefusedError
            alike), else a newline plus the full traceback — so an UNEXPECTED failure, which is the
            case the loudness exists for, is still reported in full.
    """
    return "" if isinstance(e, OSError) else f"\n{traceback.format_exc()}"


_CB_QUIET_S = 600
_cb_state = {"last_said": None, "unsaid": 0}


def cb_failure_note(e, label, last_said, unsaid, now, quiet_s=_CB_QUIET_S):
    """PURE: the warning one CB failure earns, and the state after it (card 767, issue 1114).

    A transport error to a CB service that is not running is said ONCE per quiet window: the first
    is said, every repeat within `quiet_s` seconds is counted instead, and the first after the window
    is said again carrying that count. Any other failure is always said, with its traceback.

    Args:
        e: The exception caught around the CB call.
        label: What failed, e.g. "CB store" or "CB flow-guidance".
        last_said: When a transport failure was last said, epoch seconds, or None.
        unsaid: How many transport failures went unsaid since then.
        now: The current time, epoch seconds.
        quiet_s: The window within which a repeat is counted, not said.

    Returns:
        tuple: (line or None, last_said, unsaid); None means stay quiet.
    """
    if not isinstance(e, OSError):
        return f"{label} failed (carton write unaffected): {e}{_cb_trace(e)}", last_said, unsaid
    if last_said is not None and now - last_said < quiet_s:
        return None, last_said, unsaid + 1
    more = f" ({unsaid} more since the last report)" if unsaid else ""
    return (f"{label} failed (carton write unaffected): {e}{more}; repeats in this answer are counted, "
            f"not printed", now, 0)


def _cb_note(e, label):
    """Log what cb_failure_note gives for this failure. The said-at time lives in this process and in
    CARTON_CB_SAID_AT, which every child process of this CLI answer inherits."""
    last = _cb_state["last_said"]
    if last is None:
        try:
            last = float(os.environ["CARTON_CB_SAID_AT"])
        except (KeyError, ValueError):
            last = None
    line, last, unsaid = cb_failure_note(e, label, last, _cb_state["unsaid"], time.time())
    _cb_state.update(last_said=last, unsaid=unsaid)
    if line:
        logger.warning(line)
        if isinstance(e, OSError):
            os.environ["CARTON_CB_SAID_AT"] = str(last)


def _cb_reached():
    """CB answered: the outage is over, so the next one is said again."""
    _cb_state.update(last_said=None, unsaid=0)
    os.environ.pop("CARTON_CB_SAID_AT", None)


def _cb_place(concept_name, relationship_dict, soma_region, want_guidance=False):
    """Best-effort fan-out to Crystal Ball: place the said core sentence as a coordinate.

    Returns (cb_x, cb_y, cb_encoded, guidance_block_or_None). The CB coordinate is a
    2-D PLANE POINT, not the bare local fragment: cb_x = the kernel's global/column id,
    cb_y = the plane position (0.<encoded>, decodes back to (kernelId, localCoord)).
    NEVER raises — a CB failure is logged loud and returns (None, None, '', None) so the
    carton write is unaffected. Default path: POST /api/cb/store (no-auth local lane) →
    the point. When want_guidance: POST the `store` verb over the authed /api/cb/flow,
    which places AND returns the four-layer PROMPTER block (folded into the response).
    """
    rels = {str(k): [str(t) for t in (v or [])] for k, v in (relationship_dict or {}).items()}

    if want_guidance:
        try:
            key = ""
            try:
                with open(CARTON_CB_KEY_FILE) as _f:
                    key = _f.read().strip()
            except Exception:
                key = ""
            # The store VERB sentence: "store <Name> <pred> <targets…> … region <grade>".
            parts = [concept_name]
            for pred in ("is_a", "part_of", "has_part", "has_domain", "instantiates", "produces"):
                ts = rels.get(pred, [])
                if ts:
                    parts.append(pred)
                    parts.extend(ts)
            sentence = "store " + " ".join(parts) + (f" region {soma_region}" if soma_region else "")
            body = json.dumps({"input": sentence}).encode()
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            req = _urllib_request.Request(CARTON_CB_FLOW_URL, data=body, headers=headers)
            with _urllib_request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            store = (data.get("data") or {}).get("store") or {}
            view = data.get("view") or ""
            _cb_reached()
            return store.get("x"), store.get("y"), str(store.get("encoded", "")), (view or None)
        except Exception as e:
            _cb_note(e, "CB flow-guidance")
            # fall through to the plain store so the coordinate still lands as a property

    try:
        body = json.dumps({
            "conceptName": concept_name,
            "relationships": rels,
            "region": soma_region,
            "source": "carton",
        }).encode()
        req = _urllib_request.Request(CARTON_CB_STORE_URL, data=body,
                                      headers={"Content-Type": "application/json"})
        with _urllib_request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        _cb_reached()
        return data.get("x"), data.get("y"), str(data.get("encoded", "")), None
    except Exception as e:
        _cb_note(e, "CB store")
        return None, None, "", None

def _check_soma_available():
    try:
        # SOMA only exposes POST /event. A GET returns 404 — a 404 means the daemon
        # is up and responding. ConnectionRefusedError means the daemon is down.
        #
        # ⚠ PROBE THE URL WE ACTUALLY POST TO (fixed 2026-08-11). This hardcoded
        # localhost:8091 while validation POSTs to SOMA_URL, so the gate and the call
        # could read DIFFERENT DAEMONS — measured both directions: in the SaaS box the
        # gate found nothing on the carton container's own localhost and validation was
        # SILENTLY SKIPPED (saved unvalidated, no verdict, no error, no stash marker);
        # and the composite smoke went green against a throwaway :8098 only because an
        # unrelated daemon answered :8091 for the gate.
        req = _urllib_request.Request(SOMA_URL, method="GET")
        _urllib_request.urlopen(req, timeout=2)
        return True
    except _urllib_request.HTTPError:
        # 404 from SOMA means daemon is up and responding
        return True
    except Exception as e:
        # A TIMEOUT means UP-BUT-BUSY, not down (2026-07-06): the daemon SERIALIZES
        # events, so whenever any event is in flight a 2s GET loses the race — which
        # is most of the time under the observation daemon's continuous drain. Only
        # a fast failure (connection refused / unreachable) means genuinely down.
        # Before this, a fresh carton process importing during any in-flight event
        # froze SOMA_AVAILABLE=False and silently skipped validation FOREVER.
        if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
            return True
        return False

RESTART_SOMA_SCRIPT = (
    "/home/GOD/gnosys-plugin-v2/base/soma-prolog/.claude/skills/restart-soma/scripts/restart-soma.sh"
)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_SOMA_API_DEFAULT_PORT = 8091


def soma_url_is_local(soma_url: str) -> bool:
    """Whether a SOMA URL names a daemon on this host.

    Args:
        soma_url: The URL validation POSTs to.

    Returns:
        bool: True when its hostname is a loopback or any-address name.
    """
    return (_urlparse(soma_url).hostname or "") in _LOCAL_HOSTS


def soma_argv_port(argv: list):
    """The port a process serves SOMA on, read from its argv.

    Args:
        argv: The process's argv tokens.

    Returns:
        int | None: The --port value (8091, soma_prolog.api's default, when absent) for a python
            process running soma_prolog.api; None for any other process.
    """
    if not any("python" in tok for tok in argv[:1]) or "soma_prolog.api" not in argv:
        return None
    for i, tok in enumerate(argv):
        if tok == "--port" and i + 1 < len(argv) and argv[i + 1].isdigit():
            return int(argv[i + 1])
        if tok.startswith("--port=") and tok[len("--port="):].isdigit():
            return int(tok[len("--port="):])
    return _SOMA_API_DEFAULT_PORT


def local_soma_pids(port: int) -> list:
    """Pids of the python processes on this host serving soma_prolog.api on one port, from /proc.

    Args:
        port: The port the SOMA URL names.

    Returns:
        list: The pids as strings, excluding this process; empty when none serves that port.
    """
    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or entry == str(os.getpid()):
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as fh:
                argv = fh.read().decode(errors="replace").split("\0")
        except OSError:
            continue
        if soma_argv_port(argv) == port:
            pids.append(entry)
    return pids


def soma_down_warning(soma_url: str, soma_pids, restart_script: str = RESTART_SOMA_SCRIPT) -> str:
    """The warning logged when SOMA refuses the availability probe.

    Args:
        soma_url: The URL the probe was refused at.
        soma_pids: Pids of live soma_prolog.api processes on this host, or None when soma_url
            names another host and this host's processes say nothing about it.
        restart_script: The one sanctioned SOMA restart.

    Returns:
        str: The warning text for that case.
    """
    head = (f"SOMA DOES NOT ANSWER at {soma_url} (the connection was refused), so every concept "
            f"this process writes is stored UNGRADED until it does.")
    if soma_pids is None:
        return (f"{head} {soma_url} names another host: this process cannot see or restart that "
                f"daemon. Restart it on the host that runs it.")
    if soma_pids:
        return (f"{head} A soma_prolog.api process IS alive (pid {', '.join(soma_pids)}): it is "
                f"booting or has lost its socket. Do NOT restart it now: {restart_script} kills the "
                f"live process first, and every boot re-mints the registered types. Run "
                f"sophia-status, and only if its SOMA block still reads DOWN after the script's "
                f"180s readiness bound, run bash {restart_script} in the background.")
    return (f"{head} No soma_prolog.api process is running, and nothing on this box restarts SOMA "
            f"(issue 687). Run the one sanctioned restart NOW, in the background: bash "
            f"{restart_script} ; then run sophia-status and confirm its SOMA block reads UP.")


SOMA_AVAILABLE = _check_soma_available()
if not SOMA_AVAILABLE:
    logging.getLogger(__name__).error(soma_down_warning(
        SOMA_URL,
        local_soma_pids(_urlparse(SOMA_URL).port or 80) if soma_url_is_local(SOMA_URL) else None))


def _soma_up() -> bool:
    """Call-time SOMA availability: memoized-UPGRADE re-check (2026-07-06).

    The import-time SOMA_AVAILABLE snapshot could freeze False for the process
    LIFETIME (e.g. carton imported during a SOMA restart window) — silently
    skipping validation on every subsequent add_concept. Re-check on each call
    while False; once True it stays True (soma_validate's own try/except handles
    a later outage loudly per-call, and a down SOMA fails FAST — refused — so
    attempting is cheap).
    """
    global SOMA_AVAILABLE
    if SOMA_AVAILABLE:
        return True
    SOMA_AVAILABLE = _check_soma_available()
    if SOMA_AVAILABLE:
        logging.getLogger(__name__).info("SOMA daemon now reachable — validation re-enabled.")
    return SOMA_AVAILABLE

logger = logging.getLogger(__name__)

# Import the concept config helpers locally
from carton_mcp.concept_config import ConceptConfig
# Removed: queue, threading, atexit - no background threads in MCP

# Module-level shared Neo4j connection (lazy initialized)
_module_neo4j_conn = None

def _get_module_connection():
    """Get or create module-level shared Neo4j connection."""
    global _module_neo4j_conn
    if _module_neo4j_conn is None:
        try:
            from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
            config = ConceptConfig()
            _module_neo4j_conn = KnowledgeGraphBuilder(
                uri=config.neo4j_url,
                user=config.neo4j_username,
                password=config.neo4j_password
            )
            _module_neo4j_conn._ensure_connection()
            logger.info("add_concept_tool: Module-level Neo4j connection established")
        except Exception as e:
            logger.warning(f"Failed to create module Neo4j connection: {e}")
            return None
    return _module_neo4j_conn

# Valid observation tags
OBSERVATION_TAGS = {
    "insight_moment",
    "struggle_point",
    "daily_action",
    "implementation",
    "emotional_state"
}

# PERSONAL DOMAIN ENUM — which stratum of the USER'S LIFE a concept is USED IN. This is a
# different axis from `domain` (what a concept is ABOUT) and from `region` (what SOMA SAID
# about it); the three must never substitute for each other.
#
# ⚠ THE COMMENTS BELOW WERE WRONG FROM ~2026-01-23 UNTIL 2026-08-26, AND THIS FILE IS WHERE
# EVERY OTHER READER GOT THEM. They previously read: paiab "building AI/agents", sanctum
# "philosophy/life architecture", cave "business/funnels". Those were written when the 5-value
# enum was introduced — SIX MONTHS BEFORE Isaac ever stated what the values mean — so they were
# a pre-definition inference sitting in the canonical source being read as authoritative.
# `cave` was the worst of the three: "business/funnels" conflates the discipline with the
# marketing funnel, and the record contains no instance of Isaac saying it.
#
# THE REAL DEFINITIONS — THE THREE DISCIPLINES. Isaac verbatim 2026-07-30 (journal
# Scalable_Publishing_Publishing_Video_Studio_Framework_Definition_2026_07_30T04_22_02):
# "part of the religion is AGENT ENGINEERING, RITUAL ENGINEERING, AND BUSINESS ENGINEERING.
# Thats what it fucking is." — and, in the same entry, mapped onto THIS enum by name:
# "AGENT ENGINEERING = PAIAB, RITUAL ENGINEERING = SANCTUM (...), BUSINESS ENGINEERING = CAVE;
# they are the carton has_personal_domain enum (paiab/sanctum/cave)". They are the three strata
# that have organized the entire system from the beginning, and are simultaneously this enum,
# the community tier names, and the need-chain stations.
#
# ⚠ EACH OF THE FIRST THREE ALSO NAMES A PIECE OF SOFTWARE. CAVE the software is the Code Agent
# Virtualization Environment; paia-builder and sanctum-builder are mini-games. The software
# sense is NOT the life stratum, and letting it define the stratum is precisely how the wrong
# comments above were produced.
#
# ⚠ STORED Title_Case, WRITTEN lowercase. CartON normalizes relationship targets, so the graph
# holds Cave/Paiab/Sanctum/Misc/Personal. ANY comparison against this list MUST fold case —
# 604 legal values are stored Title_Case and a literal `in` check refuses every one of them.
# See validate_personal_domain_value below, which is the enforcing path.
PERSONAL_DOMAINS = [
    "paiab",      # AGENT ENGINEERING — building, training and deploying agents
    "sanctum",    # RITUAL ENGINEERING — engineering the repeated practices that shape a day
                  # (add_ritual(name, domain, frequency, duration) IS this discipline as code)
    "cave",       # BUSINESS ENGINEERING — building the livelihood/monetization around the system
    "misc",       # the CATEGORY TERM: real things outside the three disciplines (Isaac's example:
                  # "STARSYSTEM the Game"). NOT a junk bucket — a genuine stratum of use.
    "personal"    # a SUBSET of misc — "the important ones out all the stuff that accumulates"
]

# The keys of an observation-shaped queue file that are NOT observation tags.
# ONE home (issue #198): parse_queue_file_to_concepts (the daemon's live lane)
# and observation_validation_errors below both consume this set — a second copy
# would silently drift the two consumers apart.
OBSERVATION_NON_TAG_KEYS = {
    'confidence', 'hide_youknow', 'desc_update_mode', 'raw_concept',
    'fixed', 'error_message', 'error_traceback',
}


def observation_validation_errors(data: dict) -> list:
    """PURE. The four-required-rels observation validation, LIVE (issue #198).

    This is the faithful port of the validator that sat in _add_observation_worker
    (the raise at the all_part_concepts loop) — DEAD CODE on the runtime path,
    because that worker is only reachable from the dead process_queue_file branch
    while the daemon routes every file through the UNWIND lane, which validated
    nothing. The 2026-08-29 precedent-deconfab ruling on issue #198 resurrects it
    as a LOUD DEAD-LETTER: the daemon calls this per queue file BEFORE parsing;
    a non-empty return dead-letters the file with the reasons named, and the
    drain continues.

    Scope, kept identical to the dead validator:
      - observation-shaped files ONLY (raw_concept / concept_name / concepts-list
        / timeline_merge files return [] untouched);
      - a part with an EMPTY relationships list is SKIPPED (not an error);
      - a part with relationships must carry ALL FOUR: is_a, part_of,
        has_personal_domain, has_actual_domain;
      - every has_personal_domain value must be in PERSONAL_DOMAINS.

    Returns a list of human-readable error strings naming concept + tag + gap —
    [] when the file is valid or not an observation.
    """
    if not isinstance(data, dict):
        return []
    if (data.get('raw_concept') or data.get('concept_name')
            or (isinstance(data.get('concepts'), list) and data.get('concepts'))
            or data.get('timeline_merge')):
        return []
    errors = []
    required = ('is_a', 'part_of', 'has_personal_domain', 'has_actual_domain')
    for tag, tag_concepts in data.items():
        if tag in OBSERVATION_NON_TAG_KEYS or not isinstance(tag_concepts, list):
            continue
        for concept_data in tag_concepts:
            if not isinstance(concept_data, dict):
                continue
            name = concept_data.get('name') or '(unnamed)'
            user_relationships = concept_data.get('relationships') or []
            if not isinstance(user_relationships, list) or not user_relationships:
                continue  # the dead validator's own scope: empty rels skip
            present = {rel.get('relationship') for rel in user_relationships
                       if isinstance(rel, dict)}
            missing = [r for r in required if r not in present]
            if missing:
                errors.append(
                    f"Concept '{name}' (tag '{tag}') missing required "
                    f"relationships: {', '.join(missing)}"
                )
            for rel in user_relationships:
                if isinstance(rel, dict) and rel.get('relationship') == 'has_personal_domain':
                    for pd_value in (rel.get('related') or []):
                        if pd_value not in PERSONAL_DOMAINS:
                            errors.append(
                                f"Concept '{name}' (tag '{tag}') invalid "
                                f"personal_domain '{pd_value}' — must be one of: "
                                f"{', '.join(PERSONAL_DOMAINS)}"
                            )
    return errors


# UARL LIVES IN SOMA, NOT HERE (deleted 2026-08-21, Isaac's ruling).
#
# A hardcoded UARL_PREDICATES set, get_uarl_predicates() and classify_compression_type()
# used to sit here, plus a design comment for an "origination stack" validator that was
# never built. Isaac, verbatim: "the UARL_PREDICATES in carton is a leftover from when we
# sketched out UARL *the very first time* LOL years ago! not real. should not be active in
# any way... Strong vs Weak already happens in SOMA... Theres no way for carton to do these
# operations at all."
#
# It was a nine-name Python set that never read uarl.owl, and it even expanded the acronym
# differently from the real ontology ("Universal Alignment Relationship Language" here vs
# "Universal Axiomatic Reality Language" in uarl.owl) — a divergent early sketch, and its
# own header already said "CURRENT STATE: STATIC HARDCODED LIST (WRONG)".
#
# WHERE IT ACTUALLY LIVES: strong-vs-weak compression is SOMA's, decided by the recursive
# walker find_weak_compression_target/2,/3 + check_convention(weak_compression_detector)
# in soma_prolog/soma_partials.pl, against the StrongCompressionPattern /
# WeakCompressionPattern classes in soma_prolog/uarl.owl. Carton's role is to CALL SOMA
# and to be the store canon — it does not classify.

# ============================================================================
# File-based queue for observations
def get_observation_queue_dir():
    """Get observation queue directory path"""
    heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    queue_dir = Path(heaven_data_dir) / 'carton_queue'
    queue_dir.mkdir(parents=True, exist_ok=True)
    return queue_dir


def submit_queue_entry(entry: dict, suffix: str = "") -> str:
    """Queue one entry and return its filename.

    REMOTE when KUZU_QUERY_URL names a carton box: the entry is POSTed and the BOX writes
    it, because the queue belongs to the machine whose worker drains it. Writing it here
    would leave a file on the caller's own disk that nothing ever reads, and still report
    success. LOCAL when the url is empty — the owner/self-hosted case, unchanged.
    """
    import uuid as _uuid
    from datetime import datetime as _dt

    url = (os.getenv("KUZU_QUERY_URL") or "").strip()
    if url:
        from heaven_base.tool_utils.graph_store import KuzuHttpStore
        return KuzuHttpStore(url)._post("/enqueue", {"entry": entry, "suffix": suffix})
    name = f"{_dt.now().strftime('%Y%m%d_%H%M%S')}_{str(_uuid.uuid4())[:8]}{suffix}.json"
    with open(get_observation_queue_dir() / name, "w") as fh:
        json.dump(entry, fh, indent=2)
    return name


# ============================================================================
# P0 REJECTION_LEDGER (Griess-Neural-Surrogate exhaust patch #1, 2026-07-06).
# Type-2 contradictions and mereo_error verdicts were DROPPED the moment SOMA
# returned them — logged + relayed to the caller, never persisted. But they are
# oracle-labeled HARD NEGATIVES (SOMA, the symbolic oracle, judged this exact
# claim-structure inadmissible) — the training gold Slot_Fill_Ranker needs, which
# most KG-completion projects have to FAKE by corrupting real triples. This
# ledger captures them as a byproduct of normal operation, continuously, for
# free. Append-only JSONL, same park-file idiom as soma_fillers' human queue.
# BEST-EFFORT: a ledger fault is logged and swallowed — recording a rejection
# must never affect the add_concept verdict path itself.
def rejection_ledger_path() -> str:
    """The SOMA-rejection ledger file (dir created if absent)."""
    base = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'soma_rejections.jsonl')


def record_soma_rejection(concept_name: str, relationships, verdict_kind: str,
                          reason: str) -> None:
    """Append one oracle-labeled hard negative to the rejection ledger. NEVER raises.

    Shape per record: {concept, relationships, verdict_kind, reason, timestamp} —
    the claim-structure SOMA rejected, labeled by WHICH verdict rejected it
    (contradiction = Type-2 geometric reject; mereo_error = Type-1 undefined-is_a
    fill-signal — saved as soup by carton, but still a negative example of a
    well-formed claim) and SOMA's own reason line.
    """
    from datetime import datetime
    try:
        record = {
            "concept": concept_name,
            "relationships": relationships,
            "verdict_kind": verdict_kind,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }
        with open(rejection_ledger_path(), 'a') as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        logger.error(f"rejection ledger append failed (non-fatal): {e}", exc_info=True)


# REMOVED: All Neo4j in-memory queue and threading code
# Threads don't work in MCP isolation - Neo4j writes now happen synchronously


# ── Issue #200: metacharacter SANITIZATION inside the one normalization chokepoint ──
# RULING (2026-08-28, reversible): SANITIZE, do not reject. Every writer inherits this
# because every writer routes names through normalize_concept_name — the add_concept
# queue path (observation_worker_daemon.py normalizes concept_name + every relationship
# target) AND the auto-stub side door (the daemon's target MERGE) hit this same function.
#
# Two metachar classes, handled differently:
#   QUOTE chars ─ ' " ` and the smart quotes — STRIPPED in place (intra-word punctuation:
#                 "Isaac's_Idea" -> "Isaacs_Idea", not "Isaac_S_Idea").
#   SEPARATOR chars ─ slashes (/ \), brackets ([ ] ( ) { } < >), newlines/CR/tab and all
#                 other C0 control chars — each RUN replaced by ONE underscore, then the
#                 edges stripped ("/path/to/x" -> "path_to_x").
# Length is capped at MAX_CONCEPT_NAME_LENGTH (200) AFTER normalization (transcript-blob
# names). Every sanitization and every truncation is LOGGED LOUDLY (logger.warning) with
# before/after so nothing lands silently. Clean names never warn and are byte-identical
# to the pre-#200 behavior.
_NAME_QUOTE_CHARS = re.compile("['\"`‘’“”]+")
_NAME_SEPARATOR_CHARS = re.compile(r"[/\\\[\]\(\)\{\}<>\x00-\x1f]+")
MAX_CONCEPT_NAME_LENGTH = 200


def normalize_concept_name(name: str) -> str:
    """
    Normalize concept name to Title_Case_With_Underscores format.

    This is the single source of truth for concept name normalization.
    Used for filesystem paths, Neo4j node names, and all concept references.

    Sanitization (issue #200): quote characters are stripped; slashes, brackets,
    newlines and other control characters are each replaced (per run) with one
    underscore; the result is capped at MAX_CONCEPT_NAME_LENGTH (200) chars.
    Every sanitization/truncation is logged at WARNING with before/after.
    A name that sanitizes to nothing returns "" (callers already skip empties).

    Args:
        name: Raw concept name (can have spaces, any casing)

    Returns:
        Normalized name in Title_Case_With_Underscores format

    Examples:
        "my cool concept" -> "My_Cool_Concept"
        "NEURAL NETWORK" -> "Neural_Network"
        "hello_world" -> "Hello_World"
        "path/to/thing" -> "Path_To_Thing"   (sanitized, logged)
    """
    raw = name
    # SANITIZE metacharacters (issue #200 — sanitize, never reject; see block comment above).
    sanitized = _NAME_QUOTE_CHARS.sub("", raw)
    sanitized = _NAME_SEPARATOR_CHARS.sub("_", sanitized)
    if sanitized != raw:
        sanitized = sanitized.strip("_ ")
        logger.warning(
            "normalize_concept_name SANITIZED metacharacters: %r -> %r", raw, sanitized
        )
    name = sanitized
    # Replace hyphens with underscores first (UUIDs, session IDs)
    name = name.replace("-", "_")
    # Replace underscores with spaces for title casing
    name_with_spaces = name.replace("_", " ")
    # Apply title case (capitalizes each word)
    title_cased = name_with_spaces.title()
    # Replace spaces with underscores
    result = title_cased.replace(" ", "_")
    # LENGTH CAP (issue #200): transcript-blob names must not land as nodes.
    if len(result) > MAX_CONCEPT_NAME_LENGTH:
        truncated = result[:MAX_CONCEPT_NAME_LENGTH].rstrip("_ ")
        logger.warning(
            "normalize_concept_name TRUNCATED %d-char name to %d chars: %r -> %r",
            len(result), len(truncated), raw, truncated,
        )
        result = truncated
    return result


def run_git_command(cmd: list[str], cwd: str) -> Dict[str, str]:
    """Run a git command synchronously."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False  # Changed: removed check=True to prevent false failures
        )
        # Changed: check return code manually instead of relying on check=True
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return {"output": result.stdout.strip()}
    except Exception as e:
        # Changed: catch all exceptions instead of just CalledProcessError
        return {"error": str(e)}

def setup_git_repo(config: ConceptConfig, base_path: str) -> Dict[str, str]:
    """Setup git repo - clone if doesn't exist, use existing if it does."""
    base_path_obj = Path(base_path)

    # Check if repo already exists with valid .git directory
    if base_path_obj.exists() and (base_path_obj / ".git").exists():
        # Repo exists - use it as-is (no pull needed, we're only writing)
        print("Repo exists, using local copy...", file=sys.stderr)
        return {"output": "Using existing repo"}

    # Repo doesn't exist - do fresh clone
    print("Cloning fresh repo...", file=sys.stderr)

    # 1. Remove any partial/corrupted state
    shutil.rmtree(base_path, ignore_errors=True)

    # 2. Set up git credentials BEFORE cloning
    auth_url = f"https://{config.github_pat}@github.com"
    credentials_path = Path.home() / ".git-credentials"
    credentials_path.write_text(auth_url + "\n")

    # 3. Prepare the clean remote URL (no PAT in URL since we use credential helper)
    repo_url = config.private_wiki_url
    if not repo_url.endswith(".git"):
        repo_url += ".git"

    # 4. Clone the latest remote repo into base_path
    result = run_git_command(["git", "clone", repo_url, base_path], ".")
    if "error" in result:
        return {"error": f"Git clone failed: {result['error']}"}

    # 5. Configure identity for future commits
    commands = [
        ["git", "config", "user.email", "bot@example.com"],
        ["git", "config", "user.name", "Concept Bot"],
        ["git", "config", "credential.helper", "store"],
    ]
    for cmd in commands:
        r = run_git_command(cmd, base_path)
        if "error" in r:
            return {"error": f"Git config failed: {r['error']}"}

    return {"output": "Git repo cloned successfully"}

def sync_with_remote(config: ConceptConfig, base_path: str) -> Dict[str, str]:
    """Synchronize local repository with remote."""
    auth_url = f"https://{config.github_pat}@github.com"
    credentials_path = Path.home() / ".git-credentials"
    credentials_path.write_text(auth_url + "\n")

    result = run_git_command(["git", "fetch", "origin"], base_path)
    if "error" in result:
        return {"error": f"Git fetch failed: {result['error']}"}

    result = run_git_command(
        ["git", "pull", "--no-rebase", "origin", config.private_wiki_branch], base_path
    )
    if "error" in result:
        return {"error": f"Git pull failed: {result['error']}"}

    return {"output": "Sync successful"}


def auto_link_description(description: str, base_path: str, current_concept: str, concept_cache: List[str] = None, _automaton_cache: dict = {}) -> str:
    """Public auto-linker with CartON KV FENCE-OPACITY.

    A `<CartonObj name=..>{ JSON-with-bare-refs }</CartonObj>` fence stored in n.d must NEVER
    be touched by linkification: the linker would otherwise (a) linkify the open tag's `name=`
    and every Title_Case word, and (b) EAT JSON array brackets because `[x]` is markdown-link
    syntax (`["clone","install"]` -> `"clone", "[install](..)"`). So before linking we MASK each
    full fence span (open tag + body) with an opaque private-use sentinel char (zero alnum chars
    -> immune to the concept automaton AND to the bracket-strip regexes), run the real linker on
    the rest, then RESTORE the fences VERBATIM. Hooking here covers ALL callers (linker_thread,
    intra-observation linking, retroactive_autolink). The actual linking logic lives in
    _auto_link_core below; this wrapper only adds the mask/restore.
    """
    try:
        from .carton_kv import find_carton_objs
        fences = find_carton_objs(description)
    except Exception:
        fences = []  # carton_kv unavailable -> degrade to plain linking (never crash the linker)

    if not fences:
        return _auto_link_core(description, base_path, current_concept, concept_cache, _automaton_cache)

    # Mask right-to-left (so earlier spans' offsets stay valid); one unique private-use char per fence.
    masked = description
    restore = []
    for i, f in enumerate(sorted(fences, key=lambda x: x.span[0], reverse=True)):
        placeholder = chr(0xE000 + i)  # Private Use Area: not alnum, not [](), not in any concept name
        restore.append((placeholder, description[f.span[0]:f.span[1]]))
        masked = masked[:f.span[0]] + placeholder + masked[f.span[1]:]

    linked = _auto_link_core(masked, base_path, current_concept, concept_cache, _automaton_cache)

    for placeholder, original in restore:
        linked = linked.replace(placeholder, original)  # restore each fence VERBATIM
    return linked


def _auto_link_core(description: str, base_path: str, current_concept: str, concept_cache: List[str] = None, _automaton_cache: dict = {}) -> str:
    """
    Convert concept name mentions in description to markdown links.
    
    Uses Aho-Corasick algorithm for O(text_length) matching instead of O(n*text_length).
    Builds automaton once and caches it for reuse across calls.
    
    Args:
        description: Text to scan for concept mentions
        base_path: Wiki base path for link generation
        current_concept: Concept being processed (exclude from linking)
        concept_cache: List of concept names to match
        _automaton_cache: Internal cache for automaton (mutable default for persistence)
    
    Returns:
        Description with markdown links added
    """
    try:
        import ahocorasick
    except ImportError:
        print("[auto_link] ahocorasick not installed, skipping auto-linking", file=sys.stderr)
        return description

    # Strip existing wiki links FIRST to prevent recursive nesting.
    # Wiki links end with _itself.md) — use that as the literal end anchor.
    # URLs may contain ( ) when concept names have parens (e.g. Orient()), so we
    # cannot delimit the URL with [^)]. Label class excludes [ and ] so the regex
    # matches innermost-first when nested; iterate until idempotent.
    # Also handles orphan residue from prior partial strips (bracketless chains
    # like /X/X_itself.md) and trailing _itself.md) tails with no preceding (.
    import re as _re
    for _ in range(200):
        prev = description
        # Well-formed wiki links: [label](../X_itself.md) → label
        description = _re.sub(r"\[([^\[\]]*?)\]\(\.\./.+?_itself\.md\)", r"\1", description)
        # Orphan parenthesized URL: (../X_itself.md) → empty
        description = _re.sub(r"\(\.\./.+?_itself\.md\)", "", description)
        # Bracketless orphan chain: /<concept>_itself.md)+ residue from prior partial strips
        description = _re.sub(r"/[^/\s]*?_itself\.md\)+", "", description)
        # Bare trailing _itself.md) with no preceding slash
        description = _re.sub(r"_itself\.md\)+", "", description)
        if description == prev:
            break
    description = _re.sub(r"\[([^\[\]]*?)\]", r"\1", description)
    description = _re.sub(r"[\[\]]", "", description)
    description = _re.sub(r"  +", " ", description)

    # Get all existing concept names (use cache if provided, otherwise query Neo4j)
    if concept_cache is not None:
        existing_concepts = [c for c in concept_cache if c != current_concept]
    else:
        from .carton_utils import CartOnUtils
        utils = CartOnUtils(shared_connection=_get_module_connection())
        existing_concepts = utils.get_all_concept_names(exclude_concept=current_concept)
    
    if not existing_concepts:
        return description
    
    # Build or get cached automaton. Time-bucket key (rebuild at most once per 300s):
    # the old key was the concept COUNT — but the worker itself ingests concepts, so the
    # count moved almost every batch and the ~573k-pattern automaton rebuilt continuously
    # (the 2026-07-12 CPU storm + RSS growth). New concepts wait <=300s to enter the linker.
    cache_key = int(time.time() // 300)
    if cache_key not in _automaton_cache:
        _automaton_cache.clear()  # Evict old automatons to prevent memory accumulation
        # LABEL BOTH VALUES HONESTLY. This line used to read "for {cache_key} concepts" — printing
        # the TIME BUCKET (int(time.time() // 300), a ~5.96-million-and-climbing epoch quotient) with
        # the word "concepts" after it. It reads as a concept count, it is not one, and it has now
        # independently misled TWO readers into reporting a ~6M-term automaton rebuild per batch
        # (2026-08-25: me, and a subagent, neither of whom had read line 596). The real population
        # is len(existing_concepts); the bucket is just the rebuild-at-most-once-per-300s key.
        print(f"[auto_link] Building Aho-Corasick automaton over {len(existing_concepts)} concepts "
              f"(cache bucket {cache_key}, rebuilds at most once per 300s)...", file=sys.stderr)
        
        A = ahocorasick.Automaton()
        
        # Add each concept and its variations to the automaton
        for concept in existing_concepts:
            if len(concept) <= 1:
                continue
            
            # Generate variations for matching
            variations = [
                concept,                              # Original
                concept.replace('_', ' '),            # Underscores to spaces
                concept.replace('_', ' ').title(),    # Title case
                concept.lower(),                      # Lowercase
                concept.replace('_', ' ').lower(),    # Lowercase with spaces
                concept.upper(),                      # Uppercase
                concept.replace('_', ' ').upper(),    # Uppercase with spaces
            ]
            
            # Add each variation pointing to the canonical concept name
            for var in set(variations):  # dedupe
                if len(var) > 1:
                    # Store (variation, canonical_concept) so we can rebuild the link
                    A.add_word(var.lower(), (var, concept))
        
        A.make_automaton()
        _automaton_cache[cache_key] = A
        print(f"[auto_link] Automaton built", file=sys.stderr)
    
    A = _automaton_cache[cache_key]
    
    # Find all matches in the description (case-insensitive by lowercasing input)
    desc_lower = description.lower()
    matches = []
    
    for end_idx, (matched_text, canonical_concept) in A.iter(desc_lower):
        start_idx = end_idx - len(matched_text) + 1
        
        # Check word boundaries (don't match inside words)
        before_ok = start_idx == 0 or not desc_lower[start_idx - 1].isalnum()
        after_ok = end_idx + 1 >= len(desc_lower) or not desc_lower[end_idx + 1].isalnum()
        
        if before_ok and after_ok:
            # Check if this concept is already linked
            if f"[{canonical_concept}]" not in description:
                matches.append((start_idx, end_idx + 1, matched_text, canonical_concept))
    
    if not matches:
        return description
    
    # Sort by position (reverse) and apply replacements
    # Use longest match when overlapping
    matches.sort(key=lambda x: (-x[0], -(x[1] - x[0])))
    
    # Track replaced ranges to avoid overlaps
    replaced_ranges = []
    result = description
    offset = 0
    
    # Sort by start position for proper offset handling
    matches.sort(key=lambda x: x[0])
    
    for start_idx, end_idx, matched_text, canonical_concept in matches:
        # Check for overlap with already replaced ranges
        overlaps = False
        for r_start, r_end in replaced_ranges:
            if not (end_idx <= r_start or start_idx >= r_end):
                overlaps = True
                break
        
        if overlaps:
            continue
        
        # Get the actual text from original description (preserve case)
        actual_text = description[start_idx:end_idx]
        replacement = f"[{actual_text}](../{canonical_concept}/{canonical_concept}_itself.md)"
        
        # Apply replacement with offset
        adj_start = start_idx + offset
        adj_end = end_idx + offset
        result = result[:adj_start] + replacement + result[adj_end:]
        
        # Update offset for next replacement
        offset += len(replacement) - (end_idx - start_idx)
        replaced_ranges.append((start_idx, end_idx))
    
    return result

def find_auto_relationships(content: str, base_path: str, current_concept: str, concept_cache: List[str] = None) -> List[str]:
    """Find ALL concept mentions in content using the same fuzzy matching as auto-linking."""
    # Get all existing concept names (use cache if provided, otherwise query Neo4j)
    if concept_cache is not None:
        existing_concepts = [c for c in concept_cache if c != current_concept]
    else:
        from .carton_utils import CartOnUtils
        utils = CartOnUtils()
        existing_concepts = utils.get_all_concept_names(exclude_concept=current_concept)
    
    mentioned_concepts = []
    for concept in existing_concepts:
        # Skip single-character concepts (noise from auto-detection)
        if len(concept) <= 1:
            continue

        # Generate the same formatting variations as auto-linking
        variations = set()
        variations.add(concept)
        concept_with_spaces = concept.replace('_', ' ')
        variations.add(concept_with_spaces)
        variations.add(concept_with_spaces.title())
        variations.add(concept.upper())
        variations.add(concept_with_spaces.upper())
        variations.add(concept.lower())
        variations.add(concept_with_spaces.lower())
        
        # Check if any variation appears in content
        import re
        for variation in variations:
            pattern = r'\b' + re.escape(variation) + r'\b'
            if re.search(pattern, content, re.IGNORECASE):
                mentioned_concepts.append(concept)
                break  # Found this concept, don't need to check other variations
    
    return mentioned_concepts


def infer_relationships_for_missing_concept(missing_concept: str, concepts_dir: Path) -> Dict[str, List[str]]:
    """Infer what relationships a missing concept should have based on existing references to it."""
    relationship_inverses = {
        'is_a': 'has_instances',
        'part_of': 'has_parts',
        'depends_on': 'supports',
        'instantiates': 'has_instances',
        'relates_to': 'relates_to',  # bidirectional
        'has_tag': 'has_concepts',  # tag metadata
        'has_personal_domain': 'contains_concepts',  # personal domain categorization (enum)
        'has_actual_domain': 'contains_concepts',  # actual domain categorization (flexible)
        'has_subdomain': 'contains_concepts',  # subdomain categorization
        'has_subsubdomain': 'contains_concepts'  # subsubdomain categorization
    }

    inferred_relationships = {}
    
    # Scan all existing concept relationship files
    for concept_dir in concepts_dir.iterdir():
        if not concept_dir.is_dir():
            continue
            
        components_dir = concept_dir / "components"
        if not components_dir.exists():
            continue
            
        # Check each relationship type directory
        for rel_dir in components_dir.iterdir():
            if not rel_dir.is_dir() or rel_dir.name == "description":
                continue
                
            rel_type = rel_dir.name
            if rel_type not in relationship_inverses:
                continue
                
            # Check relationship files for references to missing concept
            for rel_file in rel_dir.glob("*.md"):
                content = rel_file.read_text(encoding="utf-8")

                # Look for links to the missing concept (../concept/ format)
                link_pattern = re.compile(rf"\[.*?\]\(\.\./({re.escape(missing_concept)})/[^)]*\)")
                if link_pattern.search(content):
                    # Found a reference! Infer the inverse relationship
                    inverse_rel = relationship_inverses[rel_type]
                    if inverse_rel not in inferred_relationships:
                        inferred_relationships[inverse_rel] = []
                    inferred_relationships[inverse_rel].append(concept_dir.name)
    
    return inferred_relationships


def check_missing_concepts_and_manage_file(base_path: str, current_concept: str, concept_cache: List[str] = None) -> List[str]:
    """Check for missing concepts and manage missing_concepts.md file with relationship inference."""
    # Get all existing concept names (use cache if provided, otherwise query Neo4j)
    if concept_cache is not None:
        all_concept_names = concept_cache
    else:
        from .carton_utils import CartOnUtils
        utils = CartOnUtils()
        all_concept_names = utils.get_all_concept_names()
    existing_concepts = {name.lower(): name for name in all_concept_names}

    # Still need filesystem for markdown file scanning
    concepts_dir = Path(base_path) / "concepts"
    if not concepts_dir.exists():
        return []
    
    # Find broken links in markdown files - look for relative path format ../concept_name/
    link_pattern = re.compile(r"\[.*?\]\(\.\./([^/]+)/[^)]*\)")
    missing_concepts = set()
    
    for md_file in concepts_dir.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        for match in link_pattern.findall(content):
            concept_name = match  # match is just the concept_name
            if concept_name.lower() not in existing_concepts:
                missing_concepts.add(concept_name)
    
    # Remove the current concept if it was just created
    if current_concept:
        missing_concepts.discard(current_concept)
        # Also remove case variations
        missing_concepts = {c for c in missing_concepts if c.lower() != current_concept.lower()}
    
    # Path to missing concepts file
    missing_file = Path(base_path) / "missing_concepts.md"
    
    processed = []
    
    if missing_concepts:
        # Create content with relationship inference
        content = ["# Missing Concepts", ""]
        content.append("The following concepts are referenced but don't exist yet.")
        content.append("Relationships are inferred from existing references:")
        content.append("")
        
        for concept_name in sorted(missing_concepts):
            # Infer relationships for this missing concept
            inferred_rels = infer_relationships_for_missing_concept(concept_name, concepts_dir)
            
            # Find similar concepts for suggestions
            suggestions = get_close_matches(
                concept_name.lower(), 
                existing_concepts.keys(), 
                n=3, 
                cutoff=0.6
            )
            suggestion_names = [existing_concepts[s] for s in suggestions]
            
            content.append(f"## {concept_name}")
            
            if inferred_rels:
                content.append("**Inferred relationships:**")
                for rel_type, related_concepts in inferred_rels.items():
                    content.append(f"- {rel_type}: {', '.join(related_concepts)}")
                content.append("")
            
            if suggestion_names:
                content.append(f"**Similar existing concepts:** {', '.join(suggestion_names)}")
            else:
                content.append("**Similar existing concepts:** None")
            content.append("")
        
        missing_file.write_text("\n".join(content))
        processed.append(f"Updated missing_concepts.md with {len(missing_concepts)} missing concepts and inferred relationships")
    else:
        # Remove file if no missing concepts
        if missing_file.exists():
            missing_file.unlink()
            processed.append("Removed missing_concepts.md - all concepts now exist")
        else:
            processed.append("No missing concepts found")
    
    return processed

def commit_and_push(config: ConceptConfig, base_path: str, commit_msg: str) -> Dict[str, str]:
    """Commit and push changes to the remote repository."""
    commands = [
        ["git", "add", "."],
        ["git", "commit", "-m", commit_msg],
        ["git", "push", "origin", config.private_wiki_branch],
    ]

    for cmd in commands:
        result = run_git_command(cmd, base_path)
        if "error" in result:
            return {"error": f"Git command failed: {result['error']}"}
    return {"output": "Changes pushed successfully"}


def check_part_of_cycle(config: ConceptConfig, source: str, target: str) -> Dict[str, Any]:
    """Check if adding (source)-[:PART_OF]->(target) would create a cycle."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Check if source is reachable from target via PART_OF
        # If target can reach source, then adding source->target would create a cycle
        cycle_check_query = """
        MATCH (source:Wiki {n: $source})
        MATCH (target:Wiki {n: $target})
        MATCH path = (target)-[:PART_OF*]->(source)
        RETURN COUNT(path) > 0 as has_cycle
        """

        result = graph.execute_query(cycle_check_query, {'source': source, 'target': target})
        graph.close()

        if result and result[0].get('has_cycle', False):
            return {"error": f"Cycle detected: adding part_of from {source} to {target} would create cycle"}

        return {"valid": True}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Cycle check failed: {str(e)}"}


def check_is_a_cycle(config: ConceptConfig, source: str, target: str) -> Dict[str, Any]:
    """Check if adding (source)-[:IS_A]->(target) would create a cycle."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Check if source is reachable from target via IS_A
        # If target can reach source, then adding source->target would create a cycle
        cycle_check_query = """
        MATCH (source:Wiki {n: $source})
        MATCH (target:Wiki {n: $target})
        MATCH path = (target)-[:IS_A*]->(source)
        RETURN COUNT(path) > 0 as has_cycle
        """

        result = graph.execute_query(cycle_check_query, {'source': source, 'target': target})
        graph.close()

        if result and result[0].get('has_cycle', False):
            return {"error": f"Cycle detected: adding is_a from {source} to {target} would create cycle"}

        return {"valid": True}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Cycle check failed: {str(e)}"}


def is_concept_instantiated(config: ConceptConfig, concept_name: str) -> bool:
    """Check if concept has any instantiates relationships pointing to it."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        instantiation_query = """
        MATCH ()-[:INSTANTIATES]->(c:Wiki {n: $concept_name})
        RETURN COUNT(*) > 0 as is_instantiated
        """

        result = graph.execute_query(instantiation_query, {'concept_name': concept_name})
        graph.close()

        return result and result[0].get('is_instantiated', False)

    except Exception as e:
        traceback.print_exc()
        return False


def check_instantiates_completeness(config: ConceptConfig, source: str, target: str, source_parts: List[str] = None) -> Dict[str, Any]:
    """
    Check if source has all parts required to instantiate target label.

    INSTANTIATES is reification: source claims to be a concrete instance of target's abstract pattern.
    Target is defined by IS_A relationships. Each IS_A target has PART_OF requirements.
    Source must have PART_OF to ALL parts from ALL IS_A definitions to instantiate target.

    Args:
        source_parts: Optional list of parts being added. If None, queries Neo4j for existing parts.
    """
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Get what target is defined as (all IS_A relationships)
        # Then get all parts from those definitions
        required_parts_query = """
        MATCH (target:Wiki {n: $target})-[:IS_A]->(definition:Wiki)
        MATCH (part)-[:PART_OF]->(definition)
        RETURN COLLECT(DISTINCT part.n) as required_parts, COLLECT(DISTINCT definition.n) as definitions
        """

        result = graph.execute_query(required_parts_query, {'target': target})

        if not result or not result[0].get('required_parts'):
            graph.close()
            # Target has no IS_A definitions or those definitions have no parts
            return {"error": f"Cannot instantiate {target}: target has no IS_A definitions with parts"}

        required_parts = result[0]['required_parts']
        definitions = result[0]['definitions']

        # Get source parts: either from parameter or query Neo4j
        if source_parts is None:
            source_parts_query = """
            MATCH (source:Wiki {n: $source})-[:PART_OF]->(part:Wiki)
            RETURN COLLECT(part.n) as source_parts
            """

            source_result = graph.execute_query(source_parts_query, {'source': source})
            graph.close()

            if not source_result:
                return {"error": f"Source concept '{source}' not found in Neo4j"}

            source_parts = source_result[0].get('source_parts', [])
        else:
            graph.close()

        # Check if source has PART_OF to all required parts
        missing_parts = [part for part in required_parts if part not in source_parts]

        if missing_parts:
            return {
                "error": f"Cannot instantiate {target}: source '{source}' missing required parts: {', '.join(missing_parts)}. "
                        f"Target IS_A {definitions} which require parts {required_parts}. Source only has {source_parts}."
            }

        return {"valid": True, "required_parts": required_parts, "source_parts": source_parts, "definitions": definitions}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Completeness check failed: {str(e)}"}


def get_next_version_number(config: ConceptConfig, base_name: str) -> str:
    """Find next available version number for a concept."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Find all versions of this concept
        version_query = """
        MATCH (c:Wiki)
        WHERE c.n = $base_name OR c.n =~ $version_pattern
        RETURN c.n as name
        ORDER BY c.n
        """

        params = {
            'base_name': base_name,
            'version_pattern': f"{base_name}_v[0-9]+"
        }

        result = graph.execute_query(version_query, params)
        graph.close()

        if not result:
            return f"{base_name}_v2"

        # Extract version numbers
        import re
        max_version = 1
        for record in result:
            name = record['name']
            match = re.match(rf"{re.escape(base_name)}_v(\d+)", name)
            if match:
                version_num = int(match.group(1))
                max_version = max(max_version, version_num)

        return f"{base_name}_v{max_version + 1}"

    except Exception as e:
        traceback.print_exc()
        return f"{base_name}_v2"


def create_concept_in_neo4j(config: ConceptConfig, concept_name: str, description: str, relationships: Dict[str, List[str]], shared_connection=None) -> str:
    """Create concept in Neo4j with :Wiki namespace using minimal tokens."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        if shared_connection:
            graph = shared_connection
            should_close = False
        else:
            # Try module-level connection first (fast path)
            graph = _get_module_connection()
            if graph:
                should_close = False
            else:
                # Fallback: create temporary connection (slow path)
                graph = KnowledgeGraphBuilder(
                    uri=config.neo4j_url,
                    user=config.neo4j_username,
                    password=config.neo4j_password
                )
                should_close = True

        # Create indexes for Wiki namespace
        index_queries = [
            "CREATE INDEX wiki_concept_name IF NOT EXISTS FOR (c:Wiki) ON (c.n)",
            "CREATE INDEX wiki_concept_canonical IF NOT EXISTS FOR (c:Wiki) ON (c.c)",
        ]
        
        for query in index_queries:
            graph.execute_query(query)
        
        # Create concept node
        # Only set c.t on creation (when null), always update c.last_modified
        concept_query = """
        MERGE (c:Wiki {n: $name, c: $canonical_form})
        SET c.d = $description
        SET c.t = CASE WHEN c.t IS NULL THEN datetime($timestamp) ELSE c.t END
        SET c.last_modified = datetime($timestamp)
        RETURN c.n as node_id
        """
        
        from datetime import datetime
        params = {
            'name': concept_name,
            'canonical_form': concept_name.lower().replace(' ', '_'),
            'description': description or f"No description available for {concept_name}.",
            'timestamp': datetime.now().isoformat()
        }
        
        result = graph.execute_query(concept_query, params)
        
        # Define inverse relationships
        relationship_inverses = {
            'is_a': 'has_instances',
            'part_of': 'has_parts',
            'depends_on': 'supports',
            'instantiates': 'has_instances',
            'relates_to': 'relates_to',  # bidirectional
            'has_tag': 'has_concepts',  # tag metadata
            'has_personal_domain': 'contains_concepts',  # personal domain categorization (enum)
            'has_actual_domain': 'contains_concepts',  # actual domain categorization (flexible)
            'has_subdomain': 'contains_concepts',  # subdomain categorization
            'has_subsubdomain': 'contains_concepts'  # subsubdomain categorization
        }

        # Create relationships
        for rel_type, related_concepts in relationships.items():
            for related_concept in related_concepts:
                # Normalize target concept name to match filesystem convention
                normalized_target = normalize_concept_name(related_concept)

                # Create forward relationship
                rel_query = f"""
                MATCH (c1:Wiki {{n: $from_concept}})
                MERGE (c2:Wiki {{n: $to_concept, c: $to_canonical}})
                MERGE (c1)-[r:{rel_type.upper()}]->(c2)
                SET r.ts = datetime($timestamp)
                """

                rel_params = {
                    'from_concept': concept_name,
                    'to_concept': normalized_target,
                    'to_canonical': normalized_target.lower(),
                    'timestamp': datetime.now().isoformat()
                }

                graph.execute_query(rel_query, rel_params)

                # Create inverse relationship if defined
                if rel_type in relationship_inverses:
                    inverse_rel_type = relationship_inverses[rel_type]

                    inverse_query = f"""
                    MATCH (c1:Wiki {{n: $from_concept}})
                    MATCH (c2:Wiki {{n: $to_concept}})
                    MERGE (c2)-[r:{inverse_rel_type.upper()}]->(c1)
                    SET r.ts = datetime($timestamp)
                    """

                    inverse_params = {
                        'from_concept': concept_name,
                        'to_concept': normalized_target,
                        'timestamp': datetime.now().isoformat()
                    }

                    graph.execute_query(inverse_query, inverse_params)

        if should_close:
            graph.close()

        return f"Neo4j: Created concept '{concept_name}' with {sum(len(items) for items in relationships.values())} relationships"
        
    except ImportError:
        traceback.print_exc()
        return "Neo4j: Driver not available, skipping graph storage"
    except Exception as e:
        traceback.print_exc()
        return f"Neo4j: Failed to create concept - {str(e)}"


def get_update_history_symbol(concept_name: str) -> str:
    """Get the symbol (0-9, A-Z) for organizing update history."""
    normalized_name = normalize_concept_name(concept_name)
    first_char = normalized_name[0].upper()

    if first_char.isdigit():
        return first_char
    elif first_char.isalpha():
        return first_char
    else:
        return "0"  # Default for special characters


def update_concept_history(
    concept_name: str,
    observation_name: str,
    confidence: float,
    timestamp: str
) -> None:
    """Update the {Symbol}_Update_History concept with this mention."""
    symbol = get_update_history_symbol(concept_name)
    history_concept_name = f"{symbol}_Update_History"

    # Format the update entry
    update_entry = f"- **{concept_name}** mentioned in [{observation_name}](../{observation_name}/{observation_name}_itself.md) with confidence {confidence} at {timestamp}"

    print(f"Updating {history_concept_name} for {concept_name}", file=sys.stderr)

    # Try to read existing history
    import os
    from pathlib import Path
    base_path = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    concepts_dir = Path(base_path) / "wiki" / "concepts"
    history_dir = concepts_dir / history_concept_name
    history_file = history_dir / f"{history_concept_name}_itself.md"

    existing_content = ""
    if history_file.exists():
        existing_content = history_file.read_text(encoding="utf-8")

    # Append new entry
    if existing_content:
        new_content = existing_content + "\n" + update_entry
    else:
        new_content = f"# {history_concept_name}\n\nTracking all concept mentions with confidence scores.\n\n{update_entry}"

    # Update or create the history concept (no is_a relationship needed for tracking concepts)
    try:
        add_concept_tool_func(
            concept_name=history_concept_name,
            description=new_content,
            relationships=[{"relationship": "relates_to", "related": ["Observation_System"]}]
        )
    except Exception as e:
        # If it fails, just log it
        print(f"Warning: Could not update history concept: {e}", file=sys.stderr)
        traceback.print_exc()


def link_observation_to_timeline(observation_name: str, timestamp: str, concept_cache: Optional[List[str]] = None) -> None:
    """
    Parse timestamp and link observation to Timeline hierarchy.

    Creates temporal concepts: Year -> Month -> Day
    Links observation via part_of to Day concept.

    Args:
        observation_name: Name of the observation concept
        timestamp: Timestamp string in format YYYY_MM_DD_HH_MM_SS
        concept_cache: Pre-loaded list of all concept names (avoids Neo4j queries)
    """
    from datetime import datetime

    # Parse timestamp components
    try:
        dt = datetime.strptime(timestamp, "%Y_%m_%d_%H_%M_%S")
        year = dt.year
        month = dt.month
        day = dt.day
        month_name = dt.strftime("%B")  # Full month name (e.g., "October")
    except Exception as e:
        print(f"Warning: Could not parse timestamp {timestamp}: {e}", file=sys.stderr)
        return

    # Create temporal concept names
    year_concept = f"{year}_Year"
    month_concept = f"{month_name}_{year}_Month"
    day_concept = f"Day_{year}_{month:02d}_{day:02d}"

    print(f"Linking {observation_name} to timeline: {year_concept} -> {month_concept} -> {day_concept}", file=sys.stderr)

    # Create Year concept if needed
    try:
        add_concept_tool_func(
            concept_name=year_concept,
            description=f"Year {year} in the Timeline hierarchy. Contains all months and days of {year}.",
            relationships=[{"relationship": "part_of", "related": ["Timeline"]}],
            concept_cache=concept_cache
        )
    except Exception as e:
        print(f"Note: {year_concept} might already exist: {e}", file=sys.stderr)

    # Create Month concept if needed
    try:
        add_concept_tool_func(
            concept_name=month_concept,
            description=f"{month_name} {year} in the Timeline hierarchy. Contains all days of this month.",
            relationships=[{"relationship": "part_of", "related": [year_concept]}],
            concept_cache=concept_cache
        )
    except Exception as e:
        print(f"Note: {month_concept} might already exist: {e}", file=sys.stderr)

    # Create Day concept if needed
    try:
        add_concept_tool_func(
            concept_name=day_concept,
            description=f"Day {year}-{month:02d}-{day:02d} in the Timeline hierarchy. Contains all observations and events from this day.",
            relationships=[{"relationship": "part_of", "related": [month_concept]}],
            concept_cache=concept_cache
        )
    except Exception as e:
        print(f"Note: {day_concept} might already exist: {e}", file=sys.stderr)

    # Link observation to Day
    # This is handled by adding the relationship when we create the observation
    # We'll update add_observation() to include this relationship


def sink_concept_globally(concept_name: str, config: ConceptConfig, reason: str) -> Dict[str, Any]:
    """
    Sink concept globally (Phase 1B): rename concept → concept_v1 in Neo4j and filesystem.

    Args:
        concept_name: Concept to sink
        config: ConceptConfig with Neo4j credentials
        reason: Why concept is being sunk (e.g., "cyclic_dependency")

    Returns:
        Result dict with success/error
    """
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        import os
        import shutil

        print(f"[Sinking] Sinking {concept_name} (reason: {reason})", file=sys.stderr)

        # 1. Rename in Neo4j: concept → concept_v1
        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        sink_query = """
        MATCH (c:Wiki {n: $concept_name})
        SET c.n = $sunk_name
        RETURN c.n as new_name
        """

        sunk_name = f"{concept_name}_v1"
        result = graph.execute_query(sink_query, {"concept_name": concept_name, "sunk_name": sunk_name})

        if not result:
            graph.close()
            return {"error": f"Concept {concept_name} not found in Neo4j"}

        # 2. Create requires_evolution relationship
        evolution_query = """
        MATCH (c:Wiki {n: $sunk_name})
        MERGE (re:Wiki {n: "Requires_Evolution", c: "requires_evolution"})
        SET re.d = "Index of all concepts that require evolution due to validation failures"
        MERGE (c)-[r:REQUIRES_EVOLUTION]->(re)
        SET r.reason = $reason, r.ts = datetime($timestamp)
        RETURN c.n as sunk_concept
        """

        from datetime import datetime
        graph.execute_query(evolution_query, {
            "sunk_name": sunk_name,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })
        graph.close()

        # 3. Rename in filesystem: concepts/concept → concepts/concept_v1
        base_dir = config.base_path
        concept_dir = Path(base_dir) / "concepts" / concept_name
        sunk_dir = Path(base_dir) / "concepts" / sunk_name

        if concept_dir.exists():
            shutil.move(str(concept_dir), str(sunk_dir))
            print(f"[Sinking] Renamed filesystem: {concept_name} → {sunk_name}", file=sys.stderr)

        print(f"[Sinking] Successfully sunk {concept_name} → {sunk_name}", file=sys.stderr)
        return {"success": True, "sunk_name": sunk_name, "reason": reason}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Sinking failed: {str(e)}"}


def validate_observation_background(observation_name: str, all_concept_names: List[str]):
    """
    Background validation job (Phase 1B: actual validation and sinking).

    This runs AFTER observation returns to user. Validates concepts created
    in the observation and sinks any that fail validation.
    """
    import os
    print(f"[BG Validation] Starting validation for {observation_name}...", file=sys.stderr)

    try:
        # Get config
        config = ConceptConfig(
            github_pat=os.getenv('GITHUB_PAT', 'dummy'),
            repo_url=os.getenv('REPO_URL', 'dummy'),
            neo4j_url=os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687'),
            neo4j_username=os.getenv('NEO4J_USER', 'neo4j'),
            neo4j_password=os.getenv('NEO4J_PASSWORD', 'password'),
            base_path=os.getenv('BASE_PATH')
        )

        # Get observation and its parts from Neo4j
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Find all concepts that are part_of this observation
        parts_query = """
        MATCH (part:Wiki)-[:PART_OF]->(obs:Wiki {n: $observation_name})
        RETURN part.n as concept_name
        """

        parts_result = graph.execute_query(parts_query, {"observation_name": observation_name})
        observation_parts = [record["concept_name"] for record in parts_result] if parts_result else []

        print(f"[BG Validation] Found {len(observation_parts)} parts: {observation_parts}", file=sys.stderr)

        # Step 1: Intra-observation auto-linking
        # Build local cache of just this observation's parts for cross-linking
        local_cache = [normalize_concept_name(part) for part in observation_parts]
        print(f"[BG Validation] Running intra-observation auto-linking with local cache: {local_cache}", file=sys.stderr)

        base_path = config.base_path if config.base_path else os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        concepts_dir = Path(base_path) / "wiki" / "concepts"

        for concept_name in observation_parts:
            normalized_name = normalize_concept_name(concept_name)
            concept_dir = concepts_dir / normalized_name
            itself_file = concept_dir / f"{normalized_name}_itself.md"

            if itself_file.exists():
                # Read current content
                current_content = itself_file.read_text(encoding='utf-8')

                # Extract the description section (between "## Overview" and "## Relationships")
                import re
                overview_match = re.search(r'## Overview\n(.+?)(?=\n## )', current_content, re.DOTALL)
                if overview_match:
                    raw_description = overview_match.group(1).strip()

                    # Run auto-linking with local cache (links to other parts in same observation)
                    linked_description = auto_link_description(
                        raw_description,
                        base_path,
                        concept_name,
                        concept_cache=local_cache
                    )

                    # Only update if auto-linking found new links
                    if linked_description != raw_description:
                        updated_content = current_content.replace(raw_description, linked_description)
                        itself_file.write_text(updated_content, encoding='utf-8')
                        print(f"[BG Validation] Updated intra-observation links for {concept_name}", file=sys.stderr)

        print(f"[BG Validation] Intra-observation auto-linking complete", file=sys.stderr)

        # Step 2: Validate each part for IS_A cycles
        for concept_name in observation_parts:
            # Get all is_a relationships for this concept
            is_a_query = """
            MATCH (c:Wiki {n: $concept_name})-[:IS_A]->(target:Wiki)
            RETURN target.n as target_name
            """

            is_a_result = graph.execute_query(is_a_query, {"concept_name": concept_name})

            if is_a_result:
                for record in is_a_result:
                    target = record["target_name"]
                    # Check for cycle
                    cycle_result = check_is_a_cycle(config, concept_name, target)

                    if "error" in cycle_result:
                        print(f"[BG Validation] IS_A CYCLE DETECTED: {concept_name} → {target}", file=sys.stderr)
                        # Sink the concept
                        sink_result = sink_concept_globally(concept_name, config, "cyclic_is_a_dependency")
                        if "error" in sink_result:
                            print(f"[BG Validation] Sinking failed: {sink_result['error']}", file=sys.stderr)
                        break  # Don't check more relationships for this concept

        # Step 3: Validate each part for PART_OF cycles
        for concept_name in observation_parts:
            # Get all part_of relationships for this concept
            rels_query = """
            MATCH (c:Wiki {n: $concept_name})-[:PART_OF]->(target:Wiki)
            RETURN target.n as target_name
            """

            rels_result = graph.execute_query(rels_query, {"concept_name": concept_name})

            if rels_result:
                for record in rels_result:
                    target = record["target_name"]
                    # Check for cycle
                    cycle_result = check_part_of_cycle(config, concept_name, target)

                    if "error" in cycle_result:
                        print(f"[BG Validation] PART_OF CYCLE DETECTED: {concept_name} → {target}", file=sys.stderr)
                        # Sink the concept
                        sink_result = sink_concept_globally(concept_name, config, "cyclic_part_of_dependency")
                        if "error" in sink_result:
                            print(f"[BG Validation] Sinking failed: {sink_result['error']}", file=sys.stderr)
                        break  # Don't check more relationships for this concept

        # Step 4: Validate each part for INSTANTIATES completeness
        for concept_name in observation_parts:
            # Get all instantiates relationships for this concept
            instantiates_query = """
            MATCH (c:Wiki {n: $concept_name})-[:INSTANTIATES]->(target:Wiki)
            RETURN target.n as target_name
            """

            instantiates_result = graph.execute_query(instantiates_query, {"concept_name": concept_name})

            if instantiates_result:
                for record in instantiates_result:
                    target = record["target_name"]
                    # Check for completeness (surjectivity)
                    completeness_result = check_instantiates_completeness(config, concept_name, target)

                    if "error" in completeness_result:
                        print(f"[BG Validation] INSTANTIATES INCOMPLETE: {concept_name} → {target}: {completeness_result['error']}", file=sys.stderr)
                        # Sink the concept
                        sink_result = sink_concept_globally(concept_name, config, "incomplete_instantiation")
                        if "error" in sink_result:
                            print(f"[BG Validation] Sinking failed: {sink_result['error']}", file=sys.stderr)
                        break  # Don't check more relationships for this concept

        graph.close()
        print(f"[BG Validation] Validation complete for {observation_name}", file=sys.stderr)

    except Exception as e:
        traceback.print_exc()
        print(f"[BG Validation] Validation failed: {str(e)}", file=sys.stderr)


def _add_observation_worker(
    observation_data: Dict[str, Any],
    shared_connection=None,
) -> str:
    """
    INTERNAL: Worker function that actually processes observations.
    Called by background daemon, not by MCP tool directly.

    Create an observation with multiple part concepts in batch.

    Observation envelope structure:
    {
        "insight_moment": [{"name": str, "description": str}, ...],
        "struggle_point": [{"name": str, "description": str}, ...],
        "daily_action": [{"name": str, "description": str}, ...],
        "implementation": [{"name": str, "description": str}, ...],
        "emotional_state": [{"name": str, "description": str}, ...],
        "confidence": float
    }

    Creates N+1 concepts:
    - 1 observation wrapper: {datetime}_Observation
    - N part concepts, one per item in all tag lists

    Returns:
        Success message with created concepts summary

    Raises:
        Exception: if any concept creation fails
    """
    from datetime import datetime

    # Query Neo4j ONCE for all concept names (Phase 1A: query-once caching)
    from .carton_utils import CartOnUtils
    utils = CartOnUtils(shared_connection=shared_connection)
    concept_cache = utils.get_all_concept_names()
    print(f"Loaded {len(concept_cache)} concepts into cache", file=sys.stderr)

    # Generate observation timestamp name
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    observation_name = f"{timestamp}_Observation"

    # Extract confidence and hide_youknow (optional)
    confidence = observation_data.get("confidence", 1.0)
    hide_youknow = observation_data.get("hide_youknow", False)

    # Collect all active tags (tags that have concepts)
    active_tags = []
    all_part_concepts = []

    for tag in OBSERVATION_TAGS:
        concepts_list = observation_data.get(tag, [])
        if concepts_list:
            active_tags.append(tag)
            all_part_concepts.extend([(tag, concept) for concept in concepts_list])

    if not all_part_concepts:
        raise Exception("Observation must have at least one concept under an observation tag")

    # Link observation to Timeline before creating wrapper
    # This creates the Year/Month/Day concepts
    link_observation_to_timeline(observation_name, timestamp, concept_cache)

    # Get the day concept name for linking
    dt = datetime.strptime(timestamp, "%Y_%m_%d_%H_%M_%S")
    day_concept = f"Day_{dt.year}_{dt.month:02d}_{dt.day:02d}"

    # UNWIND all observation content into description
    observation_desc_parts = [
        f"# Observation at {timestamp}",
        f"Confidence: {confidence}",
        ""
    ]

    # Group by tag and build sections
    tags_content = {}
    for tag, concept_data in all_part_concepts:
        if tag not in tags_content:
            tags_content[tag] = []
        tags_content[tag].append(concept_data)

    # Build local cache of just this observation's part names for intra-observation linking
    local_part_cache = [normalize_concept_name(concept_data["name"]) for tag, concept_data in all_part_concepts]
    print(f"Built local cache of {len(local_part_cache)} observation parts for intra-linking", file=sys.stderr)

    # Build full description with all content unwound and auto-linked
    base_path = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    for tag, concepts_list in tags_content.items():
        observation_desc_parts.append(f"## {tag}")
        observation_desc_parts.append("")
        for concept_data in concepts_list:
            concept_name = concept_data["name"]
            concept_description = concept_data["description"]

            # Auto-link description against local parts (intra-observation linking)
            linked_description = auto_link_description(
                concept_description,
                base_path,
                concept_name,
                concept_cache=local_part_cache
            )

            # Create markdown link for concept name
            normalized_name = normalize_concept_name(concept_name)
            concept_link = f"[{concept_name}](../{normalized_name}/{normalized_name}_itself.md)"
            observation_desc_parts.append(f"### {concept_link}")
            observation_desc_parts.append(linked_description)
            observation_desc_parts.append("")

    observation_description = "\n".join(observation_desc_parts)

    observation_relationships = [
        {"relationship": "is_a", "related": ["Concept"]},
        {"relationship": "part_of", "related": [day_concept]},
    ]

    print(f"Creating observation wrapper: {observation_name}", file=sys.stderr)
    add_concept_tool_func(
        concept_name=observation_name,
        description=observation_description,
        relationships=observation_relationships,
        concept_cache=concept_cache,
        hide_youknow=hide_youknow,
        shared_connection=shared_connection,
    )

    # Create each part concept
    created_parts = []
    for tag, concept_data in all_part_concepts:
        concept_name = concept_data["name"]
        concept_description = concept_data["description"]
        user_relationships = concept_data.get("relationships", [])
        desc_update_mode = concept_data.get("desc_update_mode", "append")

        # Validate user relationships have is_a, part_of, has_personal_domain, has_actual_domain
        if user_relationships:
            has_is_a = any(rel.get("relationship") == "is_a" for rel in user_relationships)
            has_part_of = any(rel.get("relationship") == "part_of" for rel in user_relationships)
            has_personal_domain = any(rel.get("relationship") == "has_personal_domain" for rel in user_relationships)
            has_actual_domain = any(rel.get("relationship") == "has_actual_domain" for rel in user_relationships)

            if not (has_is_a and has_part_of and has_personal_domain and has_actual_domain):
                raise Exception(f"Concept '{concept_name}' must have is_a, part_of, has_personal_domain, and has_actual_domain in relationships field. Got: {user_relationships}")

            # Validate personal_domain is in enum
            personal_domain_rel = next((rel for rel in user_relationships if rel.get("relationship") == "has_personal_domain"), None)
            if personal_domain_rel:
                personal_domain_values = personal_domain_rel.get("related", [])
                for pd_value in personal_domain_values:
                    if pd_value not in PERSONAL_DOMAINS:
                        raise Exception(f"Invalid personal_domain '{pd_value}'. Must be one of: {', '.join(PERSONAL_DOMAINS)}")

        # Auto-add tag metadata and observation link
        auto_relationships = [
            {"relationship": "has_tag", "related": [tag]},
            {"relationship": "part_of", "related": [observation_name]}
        ]

        # Merge: user relationships + auto relationships
        part_relationships = user_relationships + auto_relationships

        print(f"Creating part concept: {concept_name} (has_tag: {tag})", file=sys.stderr)
        result = add_concept_tool_func(
            concept_name=concept_name,
            description=concept_description,
            relationships=part_relationships,
            concept_cache=concept_cache,
            desc_update_mode=desc_update_mode,
            hide_youknow=hide_youknow,
            shared_connection=shared_connection,
        )
        created_parts.append(f"{concept_name} ({tag})")

        # Update the concept's history with this observation mention
        update_concept_history(
            concept_name=concept_name,
            observation_name=observation_name,
            confidence=confidence,
            timestamp=timestamp
        )

    summary = f"Observation '{observation_name}' created with {len(created_parts)} parts: {', '.join(created_parts)}"

    # Synchronous validation (no threading in MCP - Neo4j writes already complete)
    print(f"[Validation] Running validation for {observation_name}", file=sys.stderr)
    validate_observation_background(observation_name, concept_cache)

    return summary


def add_observation(
    observation_data: Dict[str, Any],
) -> str:
    """
    Queue an observation for background processing.

    Writes observation_data to file queue and returns immediately.
    Background daemon processes the queue asynchronously.

    Args:
        observation_data: Observation envelope with insight_moment, struggle_point, etc.

    Returns:
        Immediate confirmation that observation was queued
    """
    from datetime import datetime
    import uuid

    try:
        name = submit_queue_entry(observation_data)
        print(f"[Observation Queue] Wrote {name}", file=sys.stderr)
        return f"✅ Observation queued: {name}"

    except Exception as e:
        traceback.print_exc()
        return f"❌ Error queuing observation: {str(e)}"


# DEAD CODE — Commented out 2026-03-29. Python validation that bypasses the reasoner. The reasoner (Pellet + SHACL) runs inside youknow() compiler at _compile_packet() line 498-553. CartON calls youknow(), youknow() runs the reasoner. This function should not exist.
# def validate_giint_hierarchy(concept_name: str, relationship_dict: Dict[str, List[str]]) -> Optional[str]:
    # """
    # Validate GIINT hierarchy constraints (Mar 03 unification).

    # Returns error string if validation fails, None if passes.
    # """
    # # Reject standalone Architecture_ concepts (now GIINT_Project descriptions)
    # if concept_name.startswith("Architecture_"):
        # return (
            # "ERROR: Architecture_ concepts replaced by GIINT_Project (Mar 03 unification). "
            # "Architecture_ is now the DESCRIPTION of a GIINT_Project, not a separate concept type. "
            # "Create a GIINT_Project with 'description' field containing architecture info."
        # )

    # # Check if this IS a GIINT_Project - require valid relationships
    # is_a_list = relationship_dict.get("is_a", [])
    # if "GIINT_Project" in is_a_list or concept_name.startswith("GIINT_Project"):
        # # GIINT_Project must have part_of pointing to system/domain
        # part_of_list = relationship_dict.get("part_of", [])
        # if not part_of_list:
            # return (
                # "ERROR: GIINT_Project must have PART_OF relationship pointing to parent system/domain. "
                # "Example: part_of=['Compound_Intelligence_System']"
            # )

        # # NOTE: has_path validation REMOVED (Mar 13 2026).
        # # GIINT_Projects are auto-created by ensure_ontology_completeness
        # # when a Starsystem_Collection is created. No path dependency.

    # # Check Bug_ prefix - Bug lives UNDER a GIINT_Deliverable or GIINT_Component
    # # Hierarchy: Project → Feature → Component → Deliverable → Bug → Task
    # if concept_name.startswith("Bug_"):
        # if "Bug" not in is_a_list:
            # return (
                # "ERROR: Bug_ concepts must have IS_A Bug. "
                # "Bugs are problems found in Deliverables/Components. "
                # "Hierarchy: Project → Feature → Component → Deliverable → Bug → Task. "
                # "Add: is_a=['Bug']"
            # )
        # part_of_list = relationship_dict.get("part_of", [])
        # has_valid_parent = any(
            # "GIINT_Deliverable" in parent or "GIINT_Component" in parent or
            # "Deliverable" in parent or "Component" in parent
            # for parent in part_of_list
        # )
        # if not has_valid_parent:
            # return (
                # "ERROR: Bug_ must have PART_OF relationship to a GIINT_Deliverable or GIINT_Component. "
                # "Bugs are found IN deliverables/components, not at project/feature level. "
                # "Hierarchy: Project → Feature → Component → Deliverable → Bug → Task. "
                # "Add: part_of=['GIINT_Deliverable_Name' or 'GIINT_Component_Name']"
            # )

    # # Check Potential_Solution_ prefix - lives UNDER a Bug as a proposed fix
    # # Hierarchy: Bug → Potential_Solution → Task (to implement the solution)
    # if concept_name.startswith("Potential_Solution_"):
        # if "Potential_Solution" not in is_a_list:
            # return (
                # "ERROR: Potential_Solution_ concepts must have IS_A Potential_Solution. "
                # "Solutions are proposed fixes for Bugs. "
                # "Hierarchy: Project → Feature → Component → Deliverable → Bug → Potential_Solution → Task. "
                # "Add: is_a=['Potential_Solution']"
            # )
        # part_of_list = relationship_dict.get("part_of", [])
        # has_bug_parent = any("Bug_" in parent or "Bug" in parent for parent in part_of_list)
        # if not has_bug_parent:
            # return (
                # "ERROR: Potential_Solution_ must have PART_OF relationship to a Bug_. "
                # "Solutions address specific bugs. "
                # "Add: part_of=['Bug_Name']"
            # )

    # # Check GIINT_Deliverable - must have proper hierarchy
    # if "GIINT_Deliverable" in is_a_list or concept_name.startswith("GIINT_Deliverable"):
        # part_of_list = relationship_dict.get("part_of", [])
        # has_component_parent = any("GIINT_Component" in parent or "Potential_Solution_" in parent or "Component" in parent for parent in part_of_list)
        # if not has_component_parent:
            # return (
                # "ERROR: GIINT_Deliverable must have PART_OF relationship to GIINT_Component. "
                # "Deliverables are outputs of components. "
                # "Add: part_of=['Potential_Solution_Name' or 'GIINT_Component_Name']"
            # )

    # # Check GIINT_Task - must have proper hierarchy
    # if "GIINT_Task" in is_a_list or concept_name.startswith("GIINT_Task"):
        # part_of_list = relationship_dict.get("part_of", [])
        # has_deliverable_parent = any("GIINT_Deliverable" in parent or "Deliverable" in parent for parent in part_of_list)
        # if not has_deliverable_parent:
            # return (
                # "ERROR: GIINT_Task must have PART_OF relationship to GIINT_Deliverable. "
                # "Tasks are work items that produce deliverables. "
                # "Add: part_of=['GIINT_Deliverable_Name']"
            # )

    # # All checks passed
    # return None


# D2 rollup — WHY this exists (archaeology, carton_mcp_LEGACY_BACKUP commit b14cef5,
# CONCEPT_VISION.md, 2026-07-03): on the original markdown substrate, "description" and "the
# graph" were the SAME substance — auto_link_description scanned free-form prose for concept
# mentions and turned them into the graph edges. On the neo4j substrate, relationships are
# supplied FIRST as structured params, so the reverse direction (render the supplied graph BACK
# into a natural description) was never built. `_compute_description_rollup` + its three clause
# helpers below are that missing reverse-rendering piece, rendering Isaac's exact template
# (verbatim, 2026-07-03): "{X} {is_a}, {part_of} in the {subdomain} subdomain of {domain} domain.
# X has {has-part list}, which instantiates {instantiates}. {X} instantiating that graph produces
# {produces}." — never a generic per-relationship-type sentence dump.

ADMIN_ROLLUP_KEYS = {
    "is_a", "part_of", "instantiates", "produces",
    "has_domain", "has_subdomain", "has_personal_domain",
}


def _rollup_sentence_isa_partof(concept_name: str, is_a: List[str], part_of: List[str],
                                 domain: List[str], subdomain: List[str]) -> str:
    """Renders clause 1: "{X} is_a {is_a}, part_of {part_of} in the {subdomain} subdomain of
    {domain} domain." is_a/part_of are each independently optional; the domain/subdomain tail is
    appended only when at least one of them has a value. Returns "" if is_a and part_of are both
    empty (no sentence to render)."""
    clause = []
    if is_a:
        clause.append(f"is_a {', '.join(is_a)}")
    if part_of:
        clause.append(f"part_of {', '.join(part_of)}")
    if not clause:
        return ""
    sentence = f"{concept_name} " + ", ".join(clause)
    if subdomain and domain:
        sentence += f" in the {subdomain[0]} subdomain of {domain[0]} domain"
    elif subdomain:
        sentence += f" in the {subdomain[0]} subdomain"
    elif domain:
        sentence += f" in the {domain[0]} domain"
    return sentence + "."


def _rollup_sentence_has_instantiates(concept_name: str, has_parts: List[str],
                                       instantiates: List[str]) -> str:
    """Renders clause 2: "{X} has {has-part list}, which instantiates {instantiates}." has-parts
    and instantiates are each independently optional. Returns "" if both are empty."""
    if has_parts and instantiates:
        return f"{concept_name} has {', '.join(has_parts)}, which instantiates {', '.join(instantiates)}."
    if has_parts:
        return f"{concept_name} has {', '.join(has_parts)}."
    if instantiates:
        return f"{concept_name} instantiates {', '.join(instantiates)}."
    return ""


def _rollup_sentence_produces(concept_name: str, produces: List[str]) -> str:
    """Renders clause 3: "{X} instantiating that graph produces {produces}." Returns "" if
    produces is empty."""
    if not produces:
        return ""
    return f"{concept_name} instantiating that graph produces {', '.join(produces)}."


def _compute_description_rollup(concept_name: str, relationship_dict: Dict[str, List[str]]) -> str:
    """D2: render the concept's supplied relationships into Isaac's exact natural-paragraph
    template (see the module comment above `_compute_description_rollup` for the template + why),
    via the three `_rollup_sentence_*` clause helpers, joined with a space. Each clause is omitted
    if its data is empty — no relationship_dict key is required to exist. Empty relationship_dict
    produces an empty string. Multiple targets within one clause are comma-joined in their
    supplied order (no re-sorting — order is caller-meaningful).
    """
    if not relationship_dict:
        return ""

    is_a = relationship_dict.get("is_a", [])
    part_of = relationship_dict.get("part_of", [])
    instantiates = relationship_dict.get("instantiates", [])
    produces = relationship_dict.get("produces", [])
    domain = relationship_dict.get("has_domain", [])
    subdomain = relationship_dict.get("has_subdomain", [])

    # "has {has-part list}" = every OTHER has_* relationship (e.g. has_desc_content, has_step_1) —
    # the concept's real constituent parts, never the administrative domain/subdomain/personal_domain.
    has_parts: List[str] = []
    for rel_type, targets in relationship_dict.items():
        if rel_type in ADMIN_ROLLUP_KEYS or not rel_type.startswith("has_"):
            continue
        has_parts.extend(targets)

    sentences = [
        _rollup_sentence_isa_partof(concept_name, is_a, part_of, domain, subdomain),
        _rollup_sentence_has_instantiates(concept_name, has_parts, instantiates),
        _rollup_sentence_produces(concept_name, produces),
    ]
    return " ".join(s for s in sentences if s)


def _compute_d2_coverage(description: str, relationship_dict: Dict[str, List[str]]):
    """D2: a READ-ONLY coverage check, never a gate (Isaac 2026-07-03).

    D2 must NEVER modify, truncate, or reject the caller's description — the
    description is stored verbatim regardless of what this returns. This
    function only measures whether the relationships the caller DECLARED are
    actually TRACED somewhere in the prose they wrote, so a decoherence
    between "what I said in the graph" and "what I said in English" becomes a
    visible, informational [D2: ...] tag on the response — never a rejection.

    This is a heuristic, not a claim of full semantic coverage: it checks each
    relationship TARGET name (underscored -> spaced, case-folded) for a literal
    substring hit in the description. It does not catch paraphrase. It DOES
    catch the case D2 exists for: a concept graphed with relationships that the
    prose never mentions at all.

    Returns (coverage_pct: Optional[int], unmatched_targets: List[str]).
    coverage_pct is None when there are no relationship targets to check.
    """
    if not relationship_dict:
        return (None, [])
    targets = [t for tgts in relationship_dict.values() for t in (tgts or [])]
    if not targets:
        return (None, [])
    desc_lower = (description or "").lower()
    unmatched = []
    matched = 0
    for t in targets:
        t_str = str(t).lower()
        t_plain = t_str.replace("_", " ")
        if (t_str and t_str in desc_lower) or (t_plain and t_plain in desc_lower):
            matched += 1
        else:
            unmatched.append(str(t))
    coverage = round(100 * matched / len(targets))
    return (coverage, unmatched)


def validate_personal_domain_value(value: Any, source: str) -> None:
    """Enum-check ONE personal_domain value, CASE-INSENSITIVELY. Pure; raises on invalid.

    CASE-INSENSITIVE IS LOAD-BEARING, NOT A CONVENIENCE. PERSONAL_DOMAINS is written in
    lowercase ('cave'), but CartON NORMALIZES every relationship target to
    Title_Case_With_Underscores, so the graph actually holds `Cave`/`Paiab`/`Sanctum`/`Misc`/
    `Personal`. A caller that reads a personal_domain back out of the graph and passes it
    straight back in is therefore handing us the Title_Case form — which a literal
    `not in PERSONAL_DOMAINS` REJECTS even though it is the correct, already-stored value.
    Measured 2026-08-26: 604 LEGAL values are stored Title_Case, so a case-sensitive gate here
    would refuse every one of them (and a migration job that "corrected" them would flatten all
    604 to misc — that exact trap was caught by an agent before it wrote, and is why this is a
    named helper with the reasoning attached rather than an inline `in` check).

    `sm_gate.py:853` already lowercases before comparing; this matches that existing pattern
    rather than inventing a second convention for the same enum.
    """
    if str(value).lower() not in PERSONAL_DOMAINS:
        raise Exception(
            f"Invalid personal_domain '{value}' (supplied via {source}). Must be one of: "
            f"{', '.join(PERSONAL_DOMAINS)} (case-insensitive — Title_Case is accepted, "
            f"since that is how CartON stores it)"
        )


def merge_optional_domain_fields(
    relationships: List[Dict[str, Any]],
    domain: Optional[str],
    subdomain: Optional[str],
    personal_domain: Optional[str],
    produces: Optional[List[str]],
) -> List[Dict[str, Any]]:
    """Pure helper for add_concept_tool_func's OPTIONAL domain/subdomain/personal_domain/
    produces params (Isaac 2026-07-04). Mirrors the add_concept MCP tool's has_domain/
    has_subdomain/has_personal_domain/produces convenience-building (server_fastmcp.py's
    add_concept), except every field here is OPTIONAL — this internal function is the one
    chokepoint every existing caller already passes through (Dragonbones, sm_gate.py,
    split_content_concept, the migration scripts — see Concept_Provenance_Enforcement_Gap);
    requiring these fields here would break every one of those callers until each is
    individually audited and updated, which has not been done. This function only gives
    callers the ABILITY to pass them correctly; it enforces nothing.

    personal_domain IS enum-validated regardless of the others being optional — the
    enum-check is not optional, only the field's presence is (raises Exception if invalid,
    matching this file's existing validation-failure convention). BOTH DOORS ARE CHECKED:
    the `personal_domain` param AND any `has_personal_domain` entry supplied through the raw
    `relationships` list, because those are two ways of stating the same fact and only the
    first was ever gated (see the comment at the check itself for the 640 illegal edges that
    came through the second). Validation is CASE-INSENSITIVE — `Cave` is as valid as `cave`,
    since Title_Case is the form CartON actually stores; see validate_personal_domain_value.

    Operates on the RELATIONSHIPS LIST (the [{"relationship":..., "related":...}, ...]
    shape), NOT relationship_dict — relationship_dict is a derived, SOMA/D2-validation-
    only view built FROM this list; add_concept_tool_func's queue write persists the LIST
    verbatim (queue_data["relationships"] = relationships), so merging only into
    relationship_dict would make these fields validate correctly but never actually reach
    the graph. Returns a NEW list (does not mutate the input list or its dict entries) with
    each provided field's relationship type merged in — appended as a new entry if that
    relationship type is not already present, or deduped into the existing entry's
    "related" list if it is (so a caller passing has_domain both ways does not end up with
    a duplicate target).
    """
    if personal_domain is not None:
        validate_personal_domain_value(personal_domain, "the personal_domain param")
    # THE HOLE THIS CLOSES (measured 2026-08-26): the check above only ever saw the
    # personal_domain PARAM. A caller supplying the same fact through the raw `relationships`
    # list — {"relationship": "has_personal_domain", "related": ["Frameworks"]} — walked
    # straight past it into the merge below and onto the graph. That is how 640 illegal
    # has_personal_domain edges across 7 non-enum values (Frameworks 606, _Unnamed 19,
    # Discord 5, Potential_Offers 3, Starsystem 3, Gnosys 3, Testing 1) got in while the enum
    # was "documented and enforced". A gate on one of two doors is not a gate.
    for rel in (relationships or []):
        if rel.get("relationship") == "has_personal_domain":
            for pd_value in (rel.get("related") or []):
                validate_personal_domain_value(pd_value, "the relationships list")
    merged = [{"relationship": rel["relationship"], "related": list(rel["related"])} for rel in (relationships or [])]
    by_type = {rel["relationship"]: rel for rel in merged}
    for rel_type, values in (
        ("has_domain", [domain] if domain else None),
        ("has_subdomain", [subdomain] if subdomain else None),
        ("has_personal_domain", [personal_domain] if personal_domain else None),
        ("produces", produces),
    ):
        if not values:
            continue
        if rel_type in by_type:
            existing = by_type[rel_type]["related"]
            for item in values:
                if item not in existing:
                    existing.append(item)
        else:
            entry = {"relationship": rel_type, "related": list(values)}
            merged.append(entry)
            by_type[rel_type] = entry
    return merged


def add_concept_tool_func(
    concept_name: str,
    description: Optional[str] = None,
    relationships: Optional[List[Dict[str, Any]]] = None,
    concept_cache: Optional[List[str]] = None,
    desc_update_mode: str = "append",
    hide_youknow: bool = False,
    shared_connection=None,
    _skip_ontology_healing: bool = False,
    source: str = "agent",
    target_descs: Optional[Dict[str, str]] = None,
    typed_values: Optional[List] = None,
    old_str_for_edit_case: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
    cb_guidance: bool = False,
    domain: Optional[str] = None,
    subdomain: Optional[str] = None,
    personal_domain: Optional[str] = None,
    produces: Optional[List[str]] = None,
    domain_about: Optional[str] = None,
    domain_part_of: Optional[str] = None,
    subdomain_about: Optional[str] = None,
) -> str:
    """
    Create a new concept with its component files.

    Args:
        concept_name: Name of the concept
        description: Description text
        relationships: List of relationship objects
        concept_cache: Pre-loaded concept names cache
        domain: OPTIONAL (Isaac 2026-07-04). Mirrors the add_concept MCP tool's REQUIRED
            domain param — becomes a has_domain relationship. OPTIONAL HERE, not required,
            because this internal function is the one chokepoint every existing caller
            already passes through (Dragonbones, sm_gate.py, split_content_concept, the
            migration scripts — see Concept_Provenance_Enforcement_Gap); making it required
            here would break every one of those callers until each is individually audited
            and updated, which has not been done. This just gives callers the ABILITY to
            pass it correctly (merged into relationship_dict below, deduped against
            anything already supplied via `relationships`) — it enforces nothing.
        subdomain: OPTIONAL, same status as domain — becomes a has_subdomain relationship.
        personal_domain: OPTIONAL, same status as domain — becomes a has_personal_domain
            relationship. If provided, IS validated against PERSONAL_DOMAINS (paiab/sanctum/
            cave/misc/personal) and raises if invalid — the enum-check is not optional, only
            the field's presence is.
        produces: OPTIONAL, same status as domain — merged into the produces relationship
            (deduped against any produces already supplied via `relationships`).
        domain_about: OPTIONAL. What the write's one domain that is not yet a domain node is about; that
            domain is written first, is_a Domain with has_about, part_of domain_part_of (card 726).
        domain_part_of: OPTIONAL. The domain node that new domain is part of.
        subdomain_about: OPTIONAL. What the write's one subdomain that is not yet a domain node is about;
            it is written first, is_a Domain with has_about, part_of the write's domains. A name written
            without its about lands as said and SOMA grades it; nothing is refused.
        desc_update_mode: How to update description if concept exists
            - "append": Add new description after existing (default)
            - "prepend": Add new description before existing
            - "replace": Sink old version, use only new description
            - "edit": Surgical str-replace WITHIN the existing n.d. old_str_for_edit_case
              is the string to find (must match EXACTLY ONCE); the description arg is
              the replacement (new_str). The daemon applies it via EditHelper.str_replace,
              writes a per-node undo log, and the rest of n.d (incl. any CartonObj fence
              elsewhere) is left byte-identical. A 0-or->1 match fails gracefully (n.d
              unchanged).
        old_str_for_edit_case: ONLY used when desc_update_mode == "edit": the exact
            substring of the existing n.d to replace with the description arg.
        hide_youknow: If False (default), SOMA validates and warns if invalid.
            If True, skip validation - silent add to soup.
        typed_values: Optional list of (value, type) pairs declaring programming
            types for relationship targets. Each entry is either a [value, type]
            list/tuple or {"value": ..., "type": ...} dict. Used by SOMA to
            assert typed observations. Unknown values default to string_value.
        properties: Optional dict of {key: value} NODE PROPERTIES to set on the
            concept via the carton property surface (set_concept_properties =
            scratch lane, per the-property-layer-doctrine). This is the SECOND
            meaning-channel beside relationships: relationships become graph edges;
            properties become neo4j node properties (status/order/gates/sm config/
            …). Values are scalars (str/int/float/bool) or flat lists of those —
            NEVER nested objects or concept-refs (those are relationships). Carried
            in the queue JSON; the daemon applies set_concept_properties AFTER the
            node is written (the node already exists in the same drain → no race,
            which is why the SM gates/steps no longer need <sm_spec> JSON in n.d).
            Reserved/managed keys (n/d/t/c/region/source/…) are refused by the
            property surface. This makes add_concept the universal carton write
            (relationships AND properties), so dragonbones can set both via a single
            add_concept call — the 🏷 property notation flows here.

    Raises:
        Exception: if relationships are empty or missing required fields.
    """
    from datetime import datetime
    import uuid

    # Validate relationships exist (checked BEFORE the optional-fields merge below —
    # domain/subdomain/personal_domain/produces alone must not satisfy "declare something
    # real"; the caller still must supply at least one core relationship such as is_a/
    # part_of/instantiates).
    if not relationships or len(relationships) == 0:
        raise Exception("ERROR: There is no reason you cannot put a WIP is_a, part_of, or has_type. Relationships cannot be empty or none.")

    # CIRCUIT BREAKER (sancrev issue 62 — Isaac's ruling, verbatim: "The circuit
    # breaker just has to be on add_concept it has to like actually tell them when
    # it errors to stop calling and report this to the user. then heaven agents
    # will use block reports."). One guarded call at this chokepoint (the
    # carton_kv precedent; the whole capability lives in carton_breaker.py).
    # When neo4j is unreachable this RETURNS the STOP-AND-REPORT actuator message
    # INSTEAD of silently queueing a write that would dead-letter (the issue-61
    # backlog mechanism); after N consecutive failures the breaker OPENs (shared
    # state FILE across every calling process) and calls fail fast without
    # touching the database for an exponentially growing cooldown. Healthy path:
    # one cheap RETURN-1 probe per CARTON_BREAKER_PROBE_TTL_S window. Sits BEFORE
    # the quota gate — quota's count query needs the same database.
    from carton_mcp.carton_breaker import check_breaker
    _breaker_msg = check_breaker(shared_connection=shared_connection)
    if _breaker_msg:
        return _breaker_msg

    # THE WEBBING AGENT'S WRITE GUARD: no write onto or declaring a system type, no merged label named; the
    # refusal returns before SOMA or the queue sees the write. The whole rule lives in webbing_write_guard.py.
    from carton_mcp.webbing_write_guard import WEBBING_SOURCE
    if source == WEBBING_SOURCE:
        from carton_mcp.webbing_write_guard import is_declared_system_type, merged_labels_named, webbing_write_refusal
        _webbing_refusal = webbing_write_refusal(source, concept_name, relationships,
                                                 is_declared_system_type(concept_name, shared_connection),
                                                 merged_labels_named(concept_name, relationships, shared_connection))
        if _webbing_refusal:
            return _webbing_refusal

    # No metering here — it runs at the box's query endpoint, not in the library a
    # tenant installs.

    # OPTIONAL domain/subdomain/personal_domain/produces passthrough (Isaac 2026-07-04).
    # Mirrors the add_concept MCP tool's has_domain/has_subdomain/has_personal_domain/
    # produces convenience-building (server_fastmcp.py's add_concept), but every field
    # here is OPTIONAL, not required — see the domain/subdomain/personal_domain/produces
    # docstring entries above for why. Reassigns `relationships` (not just a derived
    # dict) BEFORE relationship_dict is built below, so the merge is visible both to
    # SOMA/D2 validation (which reads relationship_dict) AND to the queue write further
    # down (queue_data["relationships"] = relationships, the actual graph persistence —
    # merging only into relationship_dict would validate correctly but never land).
    relationships = merge_optional_domain_fields(relationships, domain, subdomain, personal_domain, produces)

    # Only Health, Wealth, Social and Spiritual are is_a Hwss_Domain; any other domain is_a Domain.
    from carton_mcp.carton_merged_labels import confine_hwss_domain
    relationships, _hwss_confined = confine_hwss_domain(concept_name, relationships, normalize_concept_name)
    if _hwss_confined:
        logger.info(f"{concept_name}: is_a Hwss_Domain written as is_a Domain (only the four roots are Hwss_Domain)")
    # A domain or subdomain the write names that is not yet a domain node is written first, from the params supplied.
    from carton_mcp.carton_domain_axis import domain_node_reader, land_domain_axis
    _axis_lines = land_domain_axis(
        relationships,
        lambda name, about, rels: add_concept_tool_func(
            name, about, rels, shared_connection=shared_connection, source=source, hide_youknow=hide_youknow,
            properties={"has_about": about}),
        domain_node_reader(shared_connection), domain_about, domain_part_of, subdomain_about, normalize_concept_name)

    # Convert relationships list to dict for YOUKNOW
    relationship_dict = {}
    for rel in relationships:
        rel_type = rel["relationship"]
        rel_items = rel["related"]
        relationship_dict[rel_type] = rel_items

    # ACCUMULATE: merge existing CartON relationships with new ones so YOUKNOW
    # validates the FULL set. This enables SOUP→CODE evolution — each add_concept
    # call fills more fields, and YOUKNOW sees the accumulated state.
    try:
        from carton_mcp.carton_utils import CartOnUtils
        _utils = CartOnUtils(shared_connection=shared_connection)
        _existing = _utils.query_wiki_graph(
            "MATCH (c:Wiki {n: $name})-[r]->(t:Wiki) "
            "WHERE type(r) <> 'REQUIRES_EVOLUTION' "
            "RETURN toLower(type(r)) as rel, t.n as target",
            {"name": concept_name}
        )
        if _existing.get("success") and _existing.get("data"):
            for row in _existing["data"]:
                rel_type = row["rel"].lower()
                target = row["target"]
                if rel_type not in relationship_dict:
                    relationship_dict[rel_type] = [target]
                elif target not in relationship_dict[rel_type]:
                    relationship_dict[rel_type].append(target)
    except Exception:
        pass  # Can't query — validate with what we have

    # SOMA validation BEFORE queuing (warns, doesn't block).
    # YOUKNOW call abandoned (kept in file as dead code) — SOMA is the validator now.
    # SOMA does mereological regression on each typed value; every relationship value
    # gets a programming type. typed_values overrides default string_value for refs
    # that the caller knows are concept_ref / domain / etc.
    #
    # SOMA result string (from core.ingest_event) looks like:
    #   "triples=N deduction_chains_fired=M unmet=K\n
    #    <all_core_requirements_met | failure_error(...) block>\n
    #    [soup_gaps=N\n  - <gap sentence>\n  - ...]"
    #
    soup_items = []
    _yk_healed_concepts = []  # SOMA does not heal — keep empty so healing loop no-ops
    yk_data = {}  # SOMA returns no inferred fills — keep empty so legacy block no-ops
    soma_result = ""
    _soma_death = ""
    _soma_concept_status = None
    _soma_consulted = False
    _soma_error = ""
    # PRE-GATE INIT (pre-existing bug fix, surfaced by the CB-store step-2 acceptance):
    # queue_data references _fillable_requests, but it was ONLY assigned inside the
    # `if SOMA_AVAILABLE and not hide_youknow:` block below — so hide_youknow=True (or
    # SOMA down) left it UNBOUND → UnboundLocalError before the queue write. Default it
    # here alongside the other pre-gate vars, exactly like soup_items/soma_result.
    _fillable_requests = []

    # Build lookup of explicit typed values: target_value → programming_type.
    tv_lookup = {}
    if typed_values:
        for pair in typed_values:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                tv_lookup[str(pair[0])] = str(pair[1])
            elif isinstance(pair, dict) and "value" in pair and "type" in pair:
                tv_lookup[str(pair["value"])] = str(pair["type"])

    if _soma_up() and not hide_youknow:
        _soma_consulted = True
        try:
            # SOMA preferred observation shape per soma-http-event-shape rule:
            #   {source, name, description, relationships: [{relationship,
            #    related: [{value, type}]}]}
            # Unknown types default to string_value.
            soma_relationships = []
            for rel_type, targets in relationship_dict.items():
                related = []
                for target in targets:
                    t_str = str(target)
                    t_type = tv_lookup.get(t_str, "string_value")
                    related.append({"value": t_str, "type": t_type})
                soma_relationships.append({
                    "relationship": str(rel_type),
                    "related": related,
                })

            # PROPERTY->TRIPLE BRIDGE (Content Skyladder step-2, 2026-08-01). A vaulted
            # type's REQUIRED `str` field (e.g. Framework.obstacle ->
            # required_restriction(framework, has_obstacle, string_value, code)) is stored
            # on the carton node as a scratch-lane PROPERTY (`has_obstacle: "..."`), NOT as
            # a relationship — because the daemon MERGEs a :Wiki NODE for every relationship
            # target regardless of type (observation_worker_daemon.py ~:498), so a `str`
            # field cannot be a relationship without polluting the graph with a value-named
            # node. But SOMA reads TRIPLES, not carton node properties, so such a concept
            # grades SOUP forever and its projection/content d-chains never fire. Bridge it:
            # feed the concept's `has_`-prefixed STRING properties to the SOMA validation
            # payload ONLY as string_value triples (the neo4j write below is UNTOUCHED —
            # properties stay properties, zero node pollution). This lets a GAS-certified
            # framework climb SOUP->CODE so the content skyladder rung fires. NARROW by
            # design: only `has_`-prefixed string properties bridge (scratch-lane keys like
            # status/order/blessed/approved do not start with `has_`), and only when that
            # key is not already a relationship (so a real edge is never shadowed).
            _bridge_props = {}
            for _bk, _bv in (properties or {}).items():
                if (isinstance(_bk, str) and _bk.startswith("has_")
                        and isinstance(_bv, str) and _bv and _bk not in relationship_dict):
                    _bridge_props[_bk] = _bv
            try:
                from carton_mcp.carton_utils import CartOnUtils as _BridgeUtils
                _brow = _BridgeUtils(shared_connection=shared_connection).query_wiki_graph(
                    "MATCH (c:Wiki {n: $n}) RETURN properties(c) AS p", {"n": concept_name})
                _bdata = (_brow.get("data") or []) if isinstance(_brow, dict) else []
                for _bk, _bv in ((_bdata[0].get("p") if _bdata else {}) or {}).items():
                    if (isinstance(_bk, str) and _bk.startswith("has_")
                            and isinstance(_bv, str) and _bv
                            and _bk not in relationship_dict and _bk not in _bridge_props):
                        _bridge_props[_bk] = _bv
            except Exception:
                pass  # a properties read failure must never break the SOMA validation
            for _bk, _bv in _bridge_props.items():
                soma_relationships.append({
                    "relationship": str(_bk),
                    "related": [{"value": str(_bv), "type": "string_value"}],
                })

            soma_obs = [{
                "source": source,
                "name": concept_name,
                "description": description or "",
                "relationships": soma_relationships,
            }]

            soma_data = soma_validate(source=source, observations=soma_obs)
            soma_result = soma_data.get("result", "") if isinstance(soma_data, dict) else ""
            # The DEATH block rides apart from the verdict every parser below reads, and is put
            # back on the result this function returns; the presenters lift it to the top.
            _soma_death, soma_result = split_soma_death_block(soma_result)

            # AUTHORIZATION-TYPED REQUESTS (Isaac 2026-06-28). SOMA surfaces every gap whose fill
            # authority is NOT observing_agent — those (human_domain_expert / human_architect /
            # human_end_user / system_deduction / a manufactured LLM expert) are the cases the
            # caller-relay does NOT already cover. The SOMA SDK parses the verdict's soma_requests=
            # block into typed FillableRequest objects; we carry them in the queue so the daemon can
            # dispatch each to its filler (queue a human, manufacture an LLM expert, …). The
            # observing_agent case stays exactly as-is — SOMA's gap is relayed straight back to the
            # caller below; we do NOT duplicate it.
            _fillable_requests = []
            try:
                from soma_sdk import SomaResponse as _SomaResponse
                _soma_resp = _SomaResponse.from_verdict(soma_result)
                _fillable_requests = [
                    {**r.model_dump(), "authorization": r.authorization}
                    for r in _soma_resp.fillable_requests
                ]
            except Exception:
                _fillable_requests = []

            # Parse SOMA result for SOUP/CODE indicators.
            #
            # Doc 27 fix: SOMA now emits explicit per-concept status lines
            # (status=<concept>:<level>) and separates structural SOUP gaps
            # from informational INFO gaps (optional code args on a CODE
            # concept used to be lumped under soup_gaps=, causing CODE concepts
            # to surface here as is_soup=True). We honour the status= line for
            # THIS concept_name when present; we still collect soup_gaps text
            # so the agent sees the structural problems (which may include
            # other concepts in the graph), but is_soup for OUR concept is
            # determined by its explicit status, not by the global soup count.
            #
            # soup_gaps block lists unfilled slots ("  - <gap sentence>").
            if "soup_gaps=" in soma_result:
                in_soup = False
                for line in soma_result.split("\n"):
                    if line.startswith("soup_gaps="):
                        in_soup = True
                        continue
                    if in_soup:
                        stripped = line.strip()
                        if stripped.startswith("- "):
                            soup_items.append(stripped[2:].strip())
                        elif stripped.startswith("info=") or stripped.startswith("status="):
                            # Hit the next section — soup block ended.
                            break
                        elif not stripped:
                            continue

            # failure_error block = unmet deduction-chain requirements.
            if "failure_error" in soma_result:
                # Surface the failure_error preview as SOUP for the agent.
                for line in soma_result.split("\n"):
                    if "failure_error" in line and line.strip() not in soup_items:
                        soup_items.append(line.strip())
                        break

            # Per-concept SOMA status for THIS concept (doc 27): one of
            # "soup" / "code" / "unvalidated". Authoritative — overrides the
            # is_soup-from-soup_gaps inference below when present.
            # Compare the status= concept name UNDERSCORE-INSENSITIVELY. SOMA and
            # CartON canonicalize names DIFFERENTLY: SOMA's build_obs_list_string does
            # camelCase->snake ("TreeShell_Node" -> "tree_shell_node"), while CartON's
            # normalize_concept_name title-cases whole words ("TreeShell_Node" ->
            # "Treeshell_Node"). So a plain `nm.lower() == concept_name.lower()` FAILS
            # for any camel-humped name (`tree_shell_...` != `treeshell_...`) -> the
            # per-concept verdict is silently LOST -> the concept mis-records as soup
            # even when SOMA graded it code. Stripping `_` from both sides makes the
            # match invariant to WHERE each system places underscores, so the verdict
            # propagates; every previously-matching name still matches (strip is a
            # superset). (The deeper carton<->soma canonicalization unification is a
            # separate, larger item — see Understand_Soma_Observation_To_Carton_Canonicalization_Case.)
            _cn_key = concept_name.lower().replace("_", "")
            for line in soma_result.split("\n"):
                if line.startswith("status="):
                    body = line[len("status="):]
                    if ":" in body:
                        nm, lvl = body.split(":", 1)
                        if nm.strip().lower().replace("_", "") == _cn_key:
                            _soma_concept_status = lvl.strip().lower()
                            break
        except Exception as e:
            logger.warning(f"SOMA validation error: {e}\n{traceback.format_exc()}")
            _soma_error = str(e)

    # TYPE-2 CONTRADICTION = REJECTED COMPLETELY, EVEN BY CARTON (Isaac 2026-06-22). This
    # is the ONE case where saying is NOT free. Unlike a Type-1 undefined-is_a (saved as
    # soup + fill, below), a geometric CONTRADICTION — SOMA status `contradiction`, the
    # concept's is_a reaching two disjoint DOLCE top branches ("you cannot be both") —
    # would DECOHERE THE GEOMETRY even in the soup region subgraph. So CartON does NOT save
    # it: return early, BEFORE the queue write, relaying SOMA's reason. (FactualInconsistency
    # / contradicts_existing_chain in uarl.owl. Type-1, which is FactualFabrication /
    # produces_unknown_target, is fillable soup and falls through to the save below.)
    if locals().get("_soma_concept_status") == "contradiction":
        _contra_reason = ""
        _cn_key2 = concept_name.lower().replace("_", "")
        if "contradictions=" in soma_result:
            for line in soma_result.split("\n"):
                stripped = line.strip()
                if stripped.startswith("- ") and _cn_key2 in stripped.lower().replace("_", ""):
                    _contra_reason = stripped[2:].strip()
                    break
        logger.warning(f"CONTRADICTION (REJECTED, not saved): {concept_name}: {_contra_reason}")
        # P0 Rejection_Ledger: the Type-2 reject is an oracle-labeled hard negative —
        # capture it before it evaporates (this return is the ONLY record otherwise).
        record_soma_rejection(concept_name, relationships, "contradiction", _contra_reason)
        _critical = soma_critical_lines(soma_result)
        return "\n".join(
            [f"❌ {concept_name} REJECTED: geometric contradiction; CartON did not store it. {SOMA_INSTRUCTIONS_POINTER}"]
            + ([_soma_death] if _soma_death else [])
            + [f"CONTRADICTION: {_contra_reason or 'its is_a claims reach two disjoint branches'}. The claim would "
               f"decohere the geometry even as soup."]
            + ([_critical] if _critical else [])
            + [SOMA_HELP_POINTER,
               f"DO CONTRADICTION: remove the contradicting is_a claim, the one that reaches one of the two disjoint "
               f"branches, then add {concept_name} again."])

    # MEREO_ERROR: the concept is not validly the type it claims, its execution failed; CartON
    # stores the write so it can be seen, and SOMA does not admit it (Isaac 2026-09-29).
    if locals().get("_soma_concept_status") == "mereo_error":
        _mereo_reason = ""
        if "mereo_errors=" in soma_result:
            _in_m = False
            for line in soma_result.split("\n"):
                if line.startswith("mereo_errors="):
                    _in_m = True
                    continue
                if _in_m:
                    stripped = line.strip()
                    if stripped.startswith("- ") and concept_name.lower() in stripped.lower():
                        _mereo_reason = stripped[2:].strip()
                        break
                    elif stripped.startswith(("soup_gaps=", "info=", "status=", SOMA_ISA_FILLS_HEADER,
                                              "release_effects=", "deduction_chains_fired=")):
                        break
        logger.info(f"MEREO: {concept_name} is {_SOMA_FAILED}; CartON keeps the write so it can be seen; "
                    f"{_SOMA_IF_MEANT} it is inside the meaning the writer meant: {_mereo_reason}")
        record_soma_rejection(concept_name, relationships, "mereo_error", _mereo_reason)

    # HAS_VALIDATOR: check parent template requirements before queuing
    # If any part_of parent has REQUIRES_RELATIONSHIP entries, child must have those rel types
    part_of_targets = relationship_dict.get("part_of", [])
    if part_of_targets:
        from carton_mcp.carton_utils import CartOnUtils
        utils = CartOnUtils(shared_connection=shared_connection)
        for parent_name in part_of_targets:
            req_query = """
            MATCH (p:Wiki {n: $name})-[:REQUIRES_RELATIONSHIP]->(r:Wiki)
            RETURN r.n as required_rel
            """
            req_result = utils.query_wiki_graph(req_query, {"name": parent_name})
            if req_result.get("success") and req_result.get("data"):
                required_rels = [r["required_rel"] for r in req_result["data"]]
                provided_types = {k.lower() for k in relationship_dict.keys()}
                missing = [r for r in required_rels if r.lower() not in provided_types]
                if missing:
                    missing_str = ", ".join(missing)
                    raise Exception(
                        f"TEMPLATE VALIDATION: '{parent_name}' requires relationships: [{missing_str}]. "
                        f"Compose on scratchpad, add missing rels, submit when complete."
                    )

    # GIINT validation happens inside youknow() compiler via system_type_validator
    # + recursive restriction walk. Do NOT duplicate that here — CartON calls
    # youknow(), youknow() validates against OWL restrictions and returns CODE/SOUP.

    # D2 (Isaac 2026-07-03): D2 NEVER touches, truncates, or rejects the caller's
    # description — it is stored VERBATIM, always, no matter what D2 finds. D2's
    # only job is to run a read-only coverage check AFTER the fact and surface an
    # INFORMATIONAL D2 line in the result (built with the other result lines near
    # the return) — a warning, never a gate. This replaces a prior version of this
    # comment that claimed the rollup REPLACED the stored description (it never
    # did; _caller_raw_description below has always been the verbatim string that
    # gets queued).
    _caller_raw_description = description or ""
    _d2_coverage, _d2_unmatched = _compute_d2_coverage(_caller_raw_description, relationship_dict)

    # The queue write happens below, via submit_queue_entry — which posts to the box
    # when this process is a client rather than the owner.

    # Parse THREE-LEVEL status from SOMA result.
    #
    # SOMA's report carries enough information to distinguish three admissibility
    # levels (see SOMA's deduce_validation_status + the soup_gaps / unmet split):
    #
    #   SOUP        — any missing_slot present (code-stage restriction unmet,
    #                  i.e. a structural arg is missing). soup_items is non-empty.
    #                  Cannot project; cannot run d-chains meaningfully.
    #   CODE        — no soup_items AND all_core_requirements_met BUT unmet > 0.
    #                  Code args are present (structure is valid) but at least
    #                  one deduction chain is still unmet (additional admissibility
    #                  logic still to satisfy). Projection NOT yet allowed.
    #   SYSTEM_TYPE — no soup_items AND all_core_requirements_met AND unmet == 0.
    #                  Fully admissible: structure valid, every d-chain proved,
    #                  every restriction satisfied. Projection d-chains are free
    #                  to fire.
    #
    # Parse `unmet=N` from the "deduction_chains_fired=X unmet=Y" line in the
    # SOMA report. core.py emits this twice (once in the prolog_report header
    # and once in the trailing summary); both carry the same N, so we take the
    # first match. The pattern is anchored on "unmet=" to avoid matching the
    # word "unmet" in failure_error text.
    import re as _re_status
    _unmet_count = 0
    _m = _re_status.search(r'\bunmet=(\d+)', soma_result)
    if _m:
        try:
            _unmet_count = int(_m.group(1))
        except (ValueError, TypeError):
            _unmet_count = 0

    # Parse the fired_chains= verdict section (P0 Verdict_Chain_Granularity, 2026-07-06).
    # SOMA now names WHICH deduction chains fired (one `  - chain: <name>` per chain), not
    # just the count — the training substrate Chain_Prioritizer needs. Carried into the
    # queue AND appended to the fired-chains exhaust ledger below (the verdict string alone
    # is displayed then dropped; without persisting, every real event's chain-firing record
    # evaporates — the compounding-cost item).
    _fired_chains = []
    if "fired_chains=" in soma_result:
        _in_fc = False
        for line in soma_result.split("\n"):
            if line.startswith("fired_chains="):
                _in_fc = True
                continue
            if _in_fc:
                stripped = line.strip()
                if stripped.startswith("- chain:"):
                    _fired_chains.append(stripped[len("- chain:"):].strip())
                elif stripped.startswith(("soup_gaps=", "info=", "status=", "mereo_errors=",
                                          "contradictions=", "release_effects=",
                                          "soma_requests=", "composed=",
                                          "compose_suggestions=", "failure_error")):
                    break
                elif not stripped:
                    continue
    if _fired_chains:
        # Fired-chains exhaust ledger: {concept, fired_chains, unmet, status, timestamp} per
        # event — same append-only JSONL idiom as the rejection ledger above. Best-effort.
        try:
            from datetime import datetime as _dt_fc
            with open(os.path.join(os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data'),
                                   'soma_fired_chains.jsonl'), 'a') as _fc_f:
                _fc_f.write(json.dumps({
                    "concept": concept_name,
                    "fired_chains": _fired_chains,
                    "status": locals().get("_soma_concept_status"),
                    "timestamp": _dt_fc.now().isoformat(),
                }) + "\n")
        except Exception as _fc_e:
            logger.error(f"fired-chains ledger append failed (non-fatal): {_fc_e}", exc_info=True)

    # Parse release_effects from the SOMA verdict (FIX-5 step 3 — RELEASE-LAW).
    # SOMA's projection d-chains (dchain_skill_project / dchain_rule_project) surface
    # release_effect(handler, arg) facts; core.py serializes them into a
    # `release_effects=N` verdict section, one `  - effect: <module>:<func> | <arg>`
    # per effect. SOMA does NOT run them (it is the inner reflection — it releases
    # them up); the daemon (the outer layer that called /event) imports + dispatches
    # each handler AFTER the neo4j write. We carry them into the queue so it can.
    _release_effects = []
    if "release_effects=" in soma_result:
        _in_eff = False
        for line in soma_result.split("\n"):
            if line.startswith("release_effects="):
                _in_eff = True
                continue
            if _in_eff:
                stripped = line.strip()
                if stripped.startswith("- effect:"):
                    payload = stripped[len("- effect:"):].strip()
                    if " | " in payload:
                        _eh, _ea = payload.split(" | ", 1)
                        _release_effects.append({"handler": _eh.strip(), "arg": _ea.strip()})
                elif stripped.startswith(("soup_gaps=", "info=", "status=", "deduction_chains_fired=")):
                    break
                elif not stripped:
                    continue

    # Parse the composed= verdict section (CARTON-BUNDLE-BACK, Isaac 2026-06-28). L3a's
    # curried backward-chain compose accepted matches from the store and SURFACED a
    # composed_triple(concept, prop, value) for each; core.py serialized them into a
    # `composed=N` section, one `  - composed: <concept> | <prop> | <value>` per triple.
    # These are SOMA's DEDUCED graph additions — facts the user never stated (e.g. SOMA
    # found spaghetti's cuisine is italian from its ingredients). SOMA is the INNER
    # reflection: it deduces them and releases them UP; it does NOT touch carton's KG.
    # WE — the outer layer — must realize them into neo4j or carton stays dumb (that is
    # literally SOMA's job). We carry them into the queue; the daemon (Phase 2.5e) MERGEs
    # each as a graph edge AFTER the node write. Mirrors release_effects exactly — without
    # this parse they are surfaced by SOMA but never land in the KG.
    _composed_triples = []
    if "composed=" in soma_result:
        _in_comp = False
        for line in soma_result.split("\n"):
            if line.startswith("composed="):
                _in_comp = True
                continue
            if _in_comp:
                stripped = line.strip()
                if stripped.startswith("- composed:"):
                    payload = stripped[len("- composed:"):].strip()
                    parts = [p.strip() for p in payload.split(" | ")]
                    if len(parts) == 3:
                        _c, _p, _v = parts
                        _composed_triples.append({"concept": _c, "prop": _p, "value": _v})
                elif stripped.startswith(("soup_gaps=", "info=", "status=",
                                          "release_effects=", "soma_requests=",
                                          "deduction_chains_fired=")):
                    break
                elif not stripped:
                    continue

    # Parse the compose_suggestions= verdict section (L3b — pure-mereo suggestion, Isaac 2026-06-28).
    # SOMA found a unique admissible candidate for a still-empty required slot with NO authorizing
    # d-chain, so it SUGGESTS the candidate for review (it did NOT auto-compose — that is L3a). One
    # `  - suggestion: <concept> | <prop> | <expected_type> | <candidate> | <reviewer_role>` per
    # suggestion. We carry them into the queue; the daemon (Phase 2.5f) PARKS each durably for review
    # (mints a run-id for the L3c review/resume). Mirrors the composed= / release_effects= parses.
    _compose_suggestions = []
    if "compose_suggestions=" in soma_result:
        _in_sg = False
        for line in soma_result.split("\n"):
            if line.startswith("compose_suggestions="):
                _in_sg = True
                continue
            if _in_sg:
                stripped = line.strip()
                if stripped.startswith("- suggestion:"):
                    payload = stripped[len("- suggestion:"):].strip()
                    parts = [p.strip() for p in payload.split(" | ")]
                    if len(parts) == 5:
                        _sc, _sp, _st, _sv, _srole = parts
                        _compose_suggestions.append({
                            "concept": _sc, "prop": _sp, "expected_type": _st,
                            "candidate": _sv, "reviewer_role": _srole,
                        })
                elif stripped.startswith(("soup_gaps=", "info=", "status=",
                                          "release_effects=", "soma_requests=",
                                          "composed=", "deduction_chains_fired=")):
                    break
                elif not stripped:
                    continue

    _has_soup = bool(soup_items)
    _all_core_met = ("all_core_requirements_met" in soma_result) and ("failure_error" not in soma_result)

    # Doc 27: PREFER the explicit per-concept status= line for THIS concept
    # when SOMA emitted one. Fall back to the legacy soup_gaps inference only
    # when the new line is missing (older SOMA daemon / hide_youknow path /
    # SOMA call failed). The old inference labels CODE concepts as SOUP when
    # they have optional_code_arg missing_slots, because compose_all_gap_sentences
    # dumped those under soup_gaps=. With status= the answer is authoritative.
    _is_soup, _is_code, _is_system_type = soma_grade_flags(_soma_concept_status, _unmet_count, _has_soup, _all_core_met)

    # The SOMA line, SOMA's numbered information lines, and the DO line for each.
    _grade = (soma_grade_line(_soma_concept_status, _unmet_count, (_is_soup, _is_code, _is_system_type), _soma_error)
              if _soma_consulted else "")
    _soma_info, _do_lines = (soma_result_lines(soma_result, concept_name, _soma_concept_status)
                             if _soma_consulted else ([], []))

    # SOMA does not currently emit a projection target (gen_target) — projection
    # is a d-chain, not a SOMA response field. Leave gen_target=None for now;
    # projection d-chains will compute their own targets when wired.
    _gen_target = None

    # ── CARTON → CB FAN-OUT + JOIN (canon/CORE-SENTENCE-SPECTRAL-SEQUENCE.md §5).
    # carton SAYS the sentence, SOMA ENFORCED it (above), CB ADDRESSES it. Derive
    # soma_region from carton's OWN SOMA verdict (no second SOMA call — the same
    # three-level status just computed), place the said sentence on CB best-effort,
    # and JOIN {soma_region, cb_coordinate, cb_encoded} onto the node as PROPERTIES
    # (the daemon's set_concept_properties lane below; `region` is reserved so the
    # key is `soma_region`). A CB miss never blocks the write. Type-2 contradiction
    # already returned early (the plane holds it, the graph refuses it) — it never
    # reaches here, so member/born-0 are the only shifts stamped.
    if _is_system_type:
        soma_region = "system_type"
    elif _is_code:
        soma_region = "code"
    elif _is_soup:
        soma_region = "mereo_error" if locals().get("_soma_concept_status") == "mereo_error" else "soup"
    else:
        soma_region = "unvalidated"

    _cb_props = {"soma_region": soma_region}
    _cb_guidance_block = None
    if CARTON_CB_STORE:
        _cb_x, _cb_y, _cb_enc, _cb_guidance_block = _cb_place(
            concept_name, relationship_dict, soma_region, want_guidance=cb_guidance)
        if _cb_enc:
            # THE CB coordinate is the 2-D PLANE POINT (planePlacement), not the bare
            # local fragment: cb_x = the kernel's column/global id, cb_y = the plane
            # position (decodes back to (kernelId, localCoord)). cb_encoded is the full
            # address string — lossless (cb_y, a float, can lose precision for deep coords).
            _cb_props["cb_x"] = _cb_x
            _cb_props["cb_y"] = _cb_y
            _cb_props["cb_encoded"] = _cb_enc
    _merged_properties = {**(properties or {}), **_cb_props}

    queue_data = {
        "raw_concept": True,
        "concept_name": concept_name,
        "description": _caller_raw_description,
        "raw_staging": _caller_raw_description,
        "relationships": relationships,
        "desc_update_mode": desc_update_mode,
        # CartON KV 'edit' mode: surgical str-replace within the existing n.d. The
        # description above is the new_str; this is the old_str to find (exactly once).
        # Applied by the daemon's batch_create_concepts_neo4j edit pre-step.
        "old_str_for_edit_case": old_str_for_edit_case,
        "hide_youknow": hide_youknow,
        # Three-level SOMA status. Mutually exclusive: exactly one is True
        # (or all False when SOMA was unavailable / hide_youknow=True).
        # SOUP        = missing_slots present (structure missing)
        # CODE        = structure valid, d-chains still unmet (admissibility incomplete)
        # SYSTEM_TYPE = structure valid AND all d-chains proved (fully admissible;
        #               projection d-chains are free to fire)
        "is_soup": _is_soup,
        "soup_reason": "; ".join(soup_items) if soup_items else None,
        "is_code": _is_code,
        "is_system_type": _is_system_type,
        # SOMA's unmet-d-chain count (kept verbatim so the daemon can show progress
        # toward SYSTEM_TYPE as more d-chains land).
        "unmet_dchains": _unmet_count,
        # P0 Verdict_Chain_Granularity: WHICH deduction chains fired for this event
        # (from the fired_chains= verdict block), not just the count. Empty when SOMA
        # fired none / was unavailable / predates the block. Also appended to the
        # fired-chains exhaust ledger above (Chain_Prioritizer's training substrate).
        "fired_chains": _fired_chains,
        "gen_target": _gen_target,
        # RELEASE-LAW projection effects (FIX-5 step 3): the release_effect facts
        # SOMA surfaced in the verdict, [{handler, arg}]. The daemon's Phase 2.5a
        # imports + dispatches each AFTER writing the concept to neo4j (gated on
        # is_system_type). Empty when SOMA emitted none / was unavailable.
        "release_effects": _release_effects,
        # AUTHORIZATION-TYPED fillable requests (Isaac 2026-06-28): SOMA gaps whose fill
        # authority is NOT observing_agent, parsed by the SOMA SDK into typed objects
        # [{authorization, concept, gap, reason, reply_contract, request_id}]. The daemon
        # dispatches each to its filler (human queue / LLM expert / …). Empty when SOMA
        # surfaced only observing-agent gaps (already relayed to the caller) or was unavailable.
        "fillable_requests": _fillable_requests,
        # CARTON-BUNDLE-BACK composed triples (Isaac 2026-06-28): SOMA's backward-chain
        # compose DEDUCED these graph additions and surfaced them in the composed= verdict
        # section; [{concept, prop, value}]. The daemon's Phase 2.5e MERGEs each as a neo4j
        # edge AFTER the node write so carton's KG realizes what SOMA deduced (facts the
        # user never stated). Empty when SOMA composed nothing / was unavailable. Mirrors
        # release_effects — without carrying it here SOMA's deductions never reach the KG.
        "composed_triples": _composed_triples,
        # L3b PURE-MEREO SUGGESTIONS (Isaac 2026-06-28): unique admissible candidates SOMA found
        # for still-empty required slots with no authorizing d-chain; [{concept, prop, expected_type,
        # candidate, reviewer_role}]. The daemon's Phase 2.5f PARKS each durably for review (mints a
        # run-id for the L3c review/resume). NOT auto-composed (that is composed_triples / L3a). Empty
        # when SOMA suggested nothing / was unavailable.
        "compose_suggestions": _compose_suggestions,
        # Ontology healing flag — daemon Phase 2.5 skips concepts with this set
        "skip_ontology_healing": _skip_ontology_healing,
        # Timeline source — who/what created this concept (agent, dragonbones_hook, precompact, etc.)
        "source": source,
        # Target descriptions — cached KV from EC desc= on +{} claims.
        # Daemon writes these to target nodes when auto-creating relationship targets.
        "target_descs": target_descs or {},
        # NODE PROPERTIES (the 🏷 property channel — scratch lane per the-property-layer-
        # doctrine). The daemon applies these via set_concept_properties AFTER it writes
        # the node (node already exists in the same drain → no race; reserved/managed keys
        # refused). Scalars or flat lists only — NEVER concept-refs/nested (those are
        # relationships). Empty dict when none. This is what lets add_concept carry
        # properties (status/order/sm gates/…) so dragonbones never has to smuggle config
        # through n.d as JSON. cb_coordinate/cb_encoded/soma_region ride here too
        # (the carton↔CB join — merged into _merged_properties above).
        "properties": _merged_properties,
    }

    queue_filename = submit_queue_entry(queue_data, "_concept")

    # Prolog fact injection happens INSIDE PrologRuntime.validate() — not here.
    # CartON does not manipulate Prolog directly. Prolog is the outer runtime.

    # REFACTOR-PLAN [SOMA-UNIFICATION 2026-06-16] — DEAD NO-OP. journal ...Soma_Unification_Removal (14:10).
    #   _yk_healed_concepts is hardcoded EMPTY (see top of this fn), so this whole block never runs.
    #   YOUKNOW is dead (SOMA is the validator). ENACT: DELETE this block (L~2288-2317) AND the now-vestigial
    #   skip_ontology_healing plumbing: the _skip_ontology_healing param (def), the "skip_ontology_healing"
    #   queue field, and the _yk_healed_concepts/yk_data dead vars. Update the 2 external callers that pass
    #   the kwarg (weld_world_graph.py:434, soma-prolog/tests/test_d2_integration.py:55) to drop it.
    #   (No SOMA replacement needed — there is nothing real here to replace.)
    # ONTOLOGY SELF-HEALING: Now driven by YOUKNOW's OWL restriction index.
    # The UARLValidator._validate_chain() auto-heals system types by creating
    # SOUP placeholders for missing required graph elements. Healed concepts
    # are stored on the validator singleton after youknow() runs.
# DISABLED 2026-06-16 (SOMA-unification): dead youknow OWL self-heal no-op. _yk_healed_concepts is hardcoded empty (SOMA is the validator), so this block never ran. journal Soma_Unification_Removal. delete-for-niceness pending. The _skip_ontology_healing param/queue-field/dead-vars stay for now (cross-file param removal is the later niceness step).
    # if not _skip_ontology_healing:
        # try:
            # if _yk_healed_concepts:
                # healed = _yk_healed_concepts
                # for h in healed:
                    # try:
                        # h_rels = [
                            # {"relationship": "is_a", "related": [h["type"]]},
                            # {"relationship": "part_of", "related": [h["parent_name"]]},
                        # ]
                        # add_concept_tool_func(
                            # concept_name=h["name"],
                            # description=f"SOUP placeholder for {h['parent_type']} {h['relationship_from_parent']} requirement",
                            # relationships=h_rels,
                            # hide_youknow=True,
                            # shared_connection=shared_connection,
                            # _skip_ontology_healing=True,
                        # )
                        # import sys
                        # print(f"[ONTOLOGY] Auto-healed: {h['name']} (required by {h['parent_name']})", file=sys.stderr)
                    # except Exception as he:
                        # logger.warning(f"[ONTOLOGY] Failed to heal {h['name']}: {he}")
                # if healed:
                    # youknow_msg += f" [+{len(healed)} healed from OWL]"
        # except Exception as e:
            # logger.warning(f"[ONTOLOGY] OWL self-healing failed for {concept_name}: {e}")

    # The first line says what was written and that the DO lines at the end are the instructions; the DEATH block
    # follows it; the information is in the middle; the SOMA help line and the DO lines close the result.
    _lines = [f"✅ {concept_name}: CartON Files queued, Neo4j queued. {SOMA_INSTRUCTIONS_POINTER}"]
    if _soma_death:
        _lines.append(_soma_death)
    if _grade:
        _lines.append(_grade)
    _lines += _soma_info + _axis_lines
    # D2 never gates the write: it says how many declared relationships the description names.
    if _d2_coverage is not None:
        _lines.append(f"D2: {_d2_coverage}% of the declared relationships are traced in the description; not "
                      f"mentioned: {', '.join(dict.fromkeys(_d2_unmatched))}." if _d2_unmatched else
                      f"D2: {_d2_coverage}%, every declared relationship is traced in the description.")

    # CARTON_CB_STORE places every concept on the Crystal Ball plane: the region and coordinate are always shown,
    # the larger PROMPTER block only when cb_guidance asks for it.
    _cb_coord = _cb_props.get("cb_encoded")
    if _cb_coord:
        _lines.append(f"CB: region={soma_region} coord={_cb_coord}.")
    if _cb_guidance_block:
        _lines.append(f"\n{_cb_guidance_block}")
    _critical = soma_critical_lines(soma_result)
    if _critical:
        _lines.append(_critical)
    if _soma_consulted:
        _lines.append(SOMA_HELP_POINTER)
    return "\n".join(_lines + _do_lines)


# # Dead code removed - daemon handles: auto-linking, file writes, Neo4j writes
# # See observation_worker_daemon.py batch_create_concepts_neo4j()


# class _DeadCodeDeleted:
#     """Placeholder - large block of dead code was here, deleted during async refactor."""
#     pass
#     concept_path = Path(base_dir) / "concepts" / concept_name
#     components_path = concept_path / "components"

#     # Auto-link the description to create proper Zettelkasten connections
#     if description:
#         linked_description = auto_link_description(description, base_dir, concept_name, concept_cache=concept_cache)
#     else:
#         linked_description = f"No description available for {concept_name}."

#     # Handle desc_update_mode: check if concept exists and apply update logic
#     # IMPORTANT: This must happen BEFORE directory creation
#     from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

#     # Use shared connection if provided, otherwise use module-level connection
#     if shared_connection:
#         graph = shared_connection
#         should_close = False
#     else:
#         # Try module-level connection first (fast path)
#         graph = _get_module_connection()
#         if graph:
#             should_close = False
#         else:
#             # Fallback: create temporary connection (slow path)
#             graph = KnowledgeGraphBuilder(
#                 uri=config.neo4j_url,
#                 user=config.neo4j_username,
#                 password=config.neo4j_password
#             )
#             should_close = True

#     check_query = "MATCH (c:Wiki {n: $name}) RETURN c.d as description"
#     existing_result = graph.execute_query(check_query, {'name': concept_name})
#     if should_close:
#         graph.close()

#     if existing_result and existing_result[0].get('description'):
#         existing_description = existing_result[0]['description']

#         if desc_update_mode == "append":
#             # Add new description after existing
#             linked_description = existing_description + "\n\n" + linked_description
#             print(f"[DESC UPDATE] Appending to {concept_name}", file=sys.stderr)
#         elif desc_update_mode == "prepend":
#             # Add new description before existing
#             linked_description = linked_description + "\n\n" + existing_description
#             print(f"[DESC UPDATE] Prepending to {concept_name}", file=sys.stderr)
#         elif desc_update_mode == "replace":
#             # Sink old version, use only new description
#             print(f"[DESC UPDATE] Replacing {concept_name} (sinking old version)", file=sys.stderr)
#             sink_result = sink_concept_globally(concept_name, config, "explicit_description_replacement")
#             if "error" in sink_result:
#                 raise Exception(sink_result["error"])
#             # linked_description stays as new description only
#         else:
#             raise Exception(f"Invalid desc_update_mode: {desc_update_mode}. Must be 'append', 'prepend', or 'replace'.")

#     # NOW create directories (after sinking has renamed old directory if needed)
#     concept_path.mkdir(parents=True, exist_ok=True)
#     components_path.mkdir(exist_ok=True)

#     # Build full concept content first to scan for auto-relationships
#     full_content = f"{concept_name}\n{linked_description}"

#     # Find auto-relationships by scanning content for existing concept names
#     auto_mentioned = find_auto_relationships(full_content, base_dir, concept_name, concept_cache=concept_cache)
    
#     relationship_dict = {}
#     if relationships:
#         for rel in relationships:
#             rel_type = rel["relationship"]
#             rel_items = rel["related"]
#             relationship_dict[rel_type] = rel_items
    
#     # Add auto-discovered relationships as "auto_related_to"
#     if auto_mentioned:
#         if "auto_related_to" not in relationship_dict:
#             relationship_dict["auto_related_to"] = []
#         relationship_dict["auto_related_to"].extend(auto_mentioned)

#     # ========================================================================
#     # VALIDATION: Relationship constraints
#     # ========================================================================

#     # 0. Check is_a for cycles
#     if "is_a" in relationship_dict:
#         for target in relationship_dict["is_a"]:
#             cycle_result = check_is_a_cycle(config, concept_name, target)
#             if "error" in cycle_result:
#                 raise Exception(cycle_result["error"])

#     # 1. Validate part_of targets are NOT tags (must be concepts)
#     if "part_of" in relationship_dict:
#         for target in relationship_dict["part_of"]:
#             if target in OBSERVATION_TAGS:
#                 raise Exception(
#                     f"part_of relationship cannot point to observation tags. "
#                     f"'{target}' is a tag, not a concept. part_of must point to concepts."
#                 )

#     # 2. Check part_of for cycles and instantiation conflicts
#     if "part_of" in relationship_dict:
#         for target in relationship_dict["part_of"]:
#             # Check if this would create a cycle
#             cycle_result = check_part_of_cycle(config, concept_name, target)
#             if "error" in cycle_result:
#                 raise Exception(cycle_result["error"])

#             # Check if target is instantiated (immutable)
#             if is_concept_instantiated(config, target):
#                 # Auto-version: create new version of target
#                 new_version = get_next_version_number(config, target)
#                 raise Exception(
#                     f"Cannot add part_of to instantiated concept '{target}'. "
#                     f"Target is immutable. Please create '{new_version}' instead or modify your relationships."
#                 )

#     # 3. Check instantiates for completeness (surjectivity)
#     if "instantiates" in relationship_dict:
#         source_parts = relationship_dict.get("part_of", [])
#         for target in relationship_dict["instantiates"]:
#             completeness_result = check_instantiates_completeness(config, concept_name, target, source_parts)
#             if "error" in completeness_result:
#                 raise Exception(completeness_result["error"])

#     # Define inverse relationships for filesystem sync
#     relationship_inverses = {
#         'is_a': 'has_instances',
#         'part_of': 'has_parts',
#         'depends_on': 'supports',
#         'instantiates': 'has_instances',
#         'relates_to': 'relates_to',  # bidirectional
#         'has_tag': 'has_concepts',  # tag metadata
#         'has_personal_domain': 'contains_concepts',  # personal domain categorization (enum)
#         'has_actual_domain': 'contains_concepts',  # actual domain categorization (flexible)
#         'has_subdomain': 'contains_concepts',  # subdomain categorization
#         'has_subsubdomain': 'contains_concepts'  # subsubdomain categorization
#     }

#     for rel_type, rel_items in relationship_dict.items():
#         # Create forward relationship file
#         rel_dir = components_path / rel_type
#         rel_dir.mkdir(exist_ok=True)

#         rel_file = rel_dir / f"{concept_name}_{rel_type}.md"
#         content = [
#             f"# {rel_type.title()} Relationships for {concept_name}",
#             "",
#         ]
#         for item in rel_items:
#             # Normalize the target concept name to match directory structure
#             normalized_item = normalize_concept_name(item)
#             item_url = f"../{normalized_item}/{normalized_item}_itself.md"
#             content.append(f"- {concept_name} {rel_type} [{item}]({item_url})")
#         rel_file.write_text("\n".join(content))

#         # Create inverse relationship files on target concepts
#         if rel_type in relationship_inverses:
#             inverse_rel = relationship_inverses[rel_type]

#             for item in rel_items:
#                 normalized_item = normalize_concept_name(item)
#                 target_concept_dir = Path(base_dir) / "concepts" / normalized_item
#                 target_components = target_concept_dir / "components"

#                 # Create target directories if needed (target concept might not exist yet)
#                 target_concept_dir.mkdir(parents=True, exist_ok=True)
#                 target_components.mkdir(exist_ok=True)

#                 # Create/update inverse relationship directory and file
#                 inverse_dir = target_components / inverse_rel
#                 inverse_dir.mkdir(exist_ok=True)
#                 inverse_file = inverse_dir / f"{normalized_item}_{inverse_rel}.md"

#                 # Build inverse relationship entry
#                 source_url = f"../{concept_name}/{concept_name}_itself.md"
#                 inverse_entry = f"- {normalized_item} {inverse_rel} [{concept_name}]({source_url})"

#                 # Append to existing file or create new
#                 if inverse_file.exists():
#                     existing_content = inverse_file.read_text()
#                     # Only append if this entry doesn't already exist (avoid duplicates)
#                     if inverse_entry not in existing_content:
#                         inverse_file.write_text(existing_content.rstrip() + "\n" + inverse_entry + "\n")
#                 else:
#                     # Create new inverse relationship file
#                     inverse_content = [
#                         f"# {inverse_rel.title()} Relationships for {normalized_item}",
#                         "",
#                         inverse_entry
#                     ]
#                     inverse_file.write_text("\n".join(inverse_content))

#     description_file = components_path / "description.md"
#     description_file.write_text(linked_description)

#     main_file = concept_path / f"{concept_name}.md"
#     main_content = [
#         f"# {concept_name}",
#         "",
#         "## Overview",
#         linked_description,
#         "",
#         "## Relationships",
#     ]

#     for rel_type, items in relationship_dict.items():
#         main_content.append(f"### {rel_type.title()} Relationships")
#         for item in items:
#             main_content.append(f"- {item}")
#     main_file.write_text("\n".join(main_content))

#     # Generate the _itself.md file by combining description and relationships
#     itself_file = concept_path / f"{concept_name}_itself.md"
#     itself_content = [
#         f"# {concept_name}",
#         "",
#         "## Overview",
#         linked_description,
#         "",
#         "## Relationships"
#     ]
    
#     # Add relationships from component files (extract just the - lines)
#     # Sort relationship types for consistent display order
#     for rel_type in sorted(relationship_dict.keys()):
#         items = relationship_dict[rel_type]
#         itself_content.extend(["", f"### {rel_type.title()} Relationships", ""])
#         for item in items:
#             # Normalize the target concept name to match directory structure
#             normalized_item = normalize_concept_name(item)
#             item_url = f"../{normalized_item}/{normalized_item}_itself.md"
#             itself_content.append(f"- {concept_name} {rel_type} [{item}]({item_url})")
    
#     itself_file.write_text("\n".join(itself_content))

#     # DISABLED: Missing concepts file scan takes 30s - run in background daemon later
#     # try:
#     #     file_updates = check_missing_concepts_and_manage_file(base_dir, concept_name, concept_cache=concept_cache)
#     #     file_summary = "; ".join(file_updates) if file_updates else "No file updates needed"
#     # except Exception as e:
#     #     traceback.print_exc()
#     #     file_summary = f"Missing concept file update failed: {e}"
#     file_summary = "Missing concepts check disabled (run in bg daemon)"

#     # NO GIT OPERATIONS - handled by background daemon after batch

#     # Synchronous Neo4j write (no threading in MCP)
#     neo4j_result = create_concept_in_neo4j(config, concept_name, linked_description, relationship_dict, shared_connection=shared_connection)
#     if "Failed to create concept" in neo4j_result:
#         raise Exception(f"Neo4j storage failed: {neo4j_result}")

#     # YOUKNOW validation (warns, doesn't block)
#     youknow_msg = ""
#     if not hide_youknow and YOUKNOW_AVAILABLE:
#         try:
#             youknow = YOUKNOW()
#             # Convert CartON concept to PIOEntity
#             entity = PIOEntity(
#                 name=concept_name,
#                 description=linked_description,
#                 is_a=relationship_dict.get("is_a", []),
#                 part_of=relationship_dict.get("part_of", []),
#                 instantiates=relationship_dict.get("instantiates", []),
#             )
#             youknow.add_entity(entity)
            
#             # Use UARL validation directly (not check_and_respond)
#             result = youknow.validate_entity(concept_name)
#             if not result.valid:
#                 youknow_msg = f" [YOUKNOW: {result.message}]"
#                 print(f"[YOUKNOW] {result.message}", file=sys.stderr)
#             # UARL validation now handles existence checking via domain.owl
#             # No need for redundant in-memory check
#         except Exception as e:
#             logger.warning(f"YOUKNOW validation error: {e}\n{traceback.format_exc()}")
def rename_concept_func(
    old_concept_name: str,
    new_concept_name: str,
    reason: str = "Conceptual refinement"
) -> str:
    """
    Rename a concept by creating new concept and updating all references.

    This is proactive evolution (vs defensive sinking with _v1 suffix).
    Operations:
    1. Create new concept with better terminology (copies description from old)
    2. Query Neo4j for ALL edges pointing to old concept
    3. Update all edges to point to new concept
    4. Create bidirectional evolution links (evolved_from/evolved_to)
    5. Keep old concept as historical record

    Distinction from sinking:
    - Sinking (_v1): automatic on validation failures, marks broken concepts
    - Renaming: user-initiated refinement, improves terminology while preserving graph

    Args:
        old_concept_name: Current concept name to be evolved
        new_concept_name: New improved concept name
        reason: Explanation for the rename (stored in evolution relationship)

    Returns:
        Status message describing the rename operation

    Raises:
        Exception if old concept doesn't exist or new concept already exists
    """
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        from datetime import datetime
        import os
        from pathlib import Path

        # Normalize both concept names
        old_normalized = normalize_concept_name(old_concept_name)
        new_normalized = normalize_concept_name(new_concept_name)

        # Get config
        config = ConceptConfig(
            github_pat=os.getenv('GITHUB_PAT', 'dummy'),
            repo_url=os.getenv('REPO_URL', 'dummy'),
            neo4j_url=os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687'),
            neo4j_username=os.getenv('NEO4J_USER', 'neo4j'),
            neo4j_password=os.getenv('NEO4J_PASSWORD', 'password'),
            base_path=os.getenv('BASE_PATH')
        )

        # Initialize graph connection
        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Step 1: Verify old concept exists and new concept doesn't
        check_old_query = "MATCH (c:Wiki {n: $name}) RETURN c.d as description"
        old_result = graph.execute_query(check_old_query, {'name': old_normalized})

        if not old_result:
            graph.close()
            raise Exception(f"Old concept '{old_normalized}' does not exist in Neo4j")

        old_description = old_result[0]['description'] if old_result else f"Description from {old_normalized}"

        check_new_query = "MATCH (c:Wiki {n: $name}) RETURN c"
        new_result = graph.execute_query(check_new_query, {'name': new_normalized})

        if new_result:
            graph.close()
            raise Exception(f"New concept '{new_normalized}' already exists - cannot rename")

        # Step 2: Create new concept with old concept's description
        print(f"[Rename] Creating new concept '{new_normalized}'...", file=sys.stderr)

        # Note: We don't call add_concept_tool_func here because we want the NEW concept
        # to inherit the old concept's description, not get a fresh description
        create_new_query = """
        CREATE (c:Wiki {n: $name, c: $canonical_form})
        SET c.d = $description
        SET c.t = datetime($timestamp)
        RETURN c.n as node_id
        """

        create_params = {
            'name': new_normalized,
            'canonical_form': new_normalized.lower().replace(' ', '_'),
            'description': old_description,
            'timestamp': datetime.now().isoformat()
        }

        graph.execute_query(create_new_query, create_params)

        # Step 3: Query for ALL relationships pointing TO old concept
        print(f"[Rename] Querying relationships pointing to '{old_normalized}'...", file=sys.stderr)

        incoming_query = """
        MATCH (source:Wiki)-[r]->(target:Wiki {n: $old_name})
        RETURN source.n as source_name, type(r) as rel_type, properties(r) as rel_props
        """

        incoming_rels = graph.execute_query(incoming_query, {'old_name': old_normalized})

        # Step 4: Update all incoming relationships to point to new concept
        print(f"[Rename] Updating {len(incoming_rels)} incoming relationships...", file=sys.stderr)

        for rel_data in incoming_rels:
            source_name = rel_data['source_name']
            rel_type = rel_data['rel_type']

            # Delete old relationship
            delete_query = f"""
            MATCH (source:Wiki {{n: $source}})-[r:{rel_type}]->(target:Wiki {{n: $old_name}})
            DELETE r
            """

            graph.execute_query(delete_query, {
                'source': source_name,
                'old_name': old_normalized
            })

            # Create new relationship to new concept
            create_rel_query = f"""
            MATCH (source:Wiki {{n: $source}})
            MATCH (target:Wiki {{n: $new_name}})
            CREATE (source)-[r:{rel_type}]->(target)
            SET r.ts = datetime($timestamp)
            SET r.renamed_from = $old_name
            """

            graph.execute_query(create_rel_query, {
                'source': source_name,
                'new_name': new_normalized,
                'old_name': old_normalized,
                'timestamp': datetime.now().isoformat()
            })

        # Step 5: Query for ALL relationships pointing FROM old concept
        print(f"[Rename] Querying relationships pointing from '{old_normalized}'...", file=sys.stderr)

        outgoing_query = """
        MATCH (source:Wiki {n: $old_name})-[r]->(target:Wiki)
        RETURN target.n as target_name, type(r) as rel_type, properties(r) as rel_props
        """

        outgoing_rels = graph.execute_query(outgoing_query, {'old_name': old_normalized})

        # Step 6: Copy all outgoing relationships from old to new concept
        print(f"[Rename] Copying {len(outgoing_rels)} outgoing relationships...", file=sys.stderr)

        for rel_data in outgoing_rels:
            target_name = rel_data['target_name']
            rel_type = rel_data['rel_type']

            # Create relationship from new concept to same targets
            copy_rel_query = f"""
            MATCH (source:Wiki {{n: $new_name}})
            MATCH (target:Wiki {{n: $target}})
            MERGE (source)-[r:{rel_type}]->(target)
            SET r.ts = datetime($timestamp)
            SET r.copied_from = $old_name
            """

            graph.execute_query(copy_rel_query, {
                'new_name': new_normalized,
                'target': target_name,
                'old_name': old_normalized,
                'timestamp': datetime.now().isoformat()
            })

        # Step 7: Create bidirectional evolution links
        print(f"[Rename] Creating evolution links...", file=sys.stderr)

        evolution_forward_query = """
        MATCH (old:Wiki {n: $old_name})
        MATCH (new:Wiki {n: $new_name})
        CREATE (old)-[r:EVOLVED_TO]->(new)
        SET r.ts = datetime($timestamp)
        SET r.reason = $reason
        """

        evolution_backward_query = """
        MATCH (old:Wiki {n: $old_name})
        MATCH (new:Wiki {n: $new_name})
        CREATE (new)-[r:EVOLVED_FROM]->(old)
        SET r.ts = datetime($timestamp)
        SET r.reason = $reason
        """

        evolution_params = {
            'old_name': old_normalized,
            'new_name': new_normalized,
            'timestamp': datetime.now().isoformat(),
            'reason': reason
        }

        graph.execute_query(evolution_forward_query, evolution_params)
        graph.execute_query(evolution_backward_query, evolution_params)

        # Step 8: Create filesystem concept for new name (if needed)
        base_path = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        concepts_dir = Path(base_path) / "wiki" / "concepts"
        new_concept_dir = concepts_dir / new_normalized

        if not new_concept_dir.exists():
            print(f"[Rename] Creating filesystem directory for '{new_normalized}'...", file=sys.stderr)
            new_concept_dir.mkdir(parents=True, exist_ok=True)

            # Copy the description file
            old_concept_dir = concepts_dir / old_normalized
            old_itself_file = old_concept_dir / f"{old_normalized}_itself.md"

            if old_itself_file.exists():
                new_itself_file = new_concept_dir / f"{new_normalized}_itself.md"

                # Read old content and update concept name references
                old_content = old_itself_file.read_text(encoding='utf-8')
                new_content = old_content.replace(old_normalized, new_normalized)

                # Add evolution note at the top
                evolution_note = f"*This concept evolved from [{old_normalized}](../{old_normalized}/{old_normalized}_itself.md) on {datetime.now().strftime('%Y-%m-%d')}. Reason: {reason}*\n\n"
                new_content = f"# {new_normalized}\n\n{evolution_note}{new_content.split('## Overview')[1] if '## Overview' in new_content else new_content}"

                new_itself_file.write_text(new_content, encoding='utf-8')

        # Commit filesystem changes
        result = run_git_command(["git", "add", "."], base_path)
        if "error" not in result:
            result = run_git_command(["git", "commit", "-m", f"Rename: {old_normalized} -> {new_normalized}"], base_path)

        graph.close()

        summary = f"Renamed '{old_normalized}' to '{new_normalized}'. Updated {len(incoming_rels)} incoming and {len(outgoing_rels)} outgoing relationships. Evolution links created. Old concept preserved as historical record."
        print(f"[Rename] {summary}", file=sys.stderr)

        return summary

    except ImportError as e:
        traceback.print_exc()
        return f"Rename failed: Neo4j driver not available - {str(e)}"
    except Exception as e:
        traceback.print_exc()
        return f"Rename failed: {str(e)}"


# (removed 2026-06-25) The AddConceptTool / RenameConceptTool BaseHeavenTool wrappers + their
# ArgsSchema classes lived here. They were heaven-tool wrappers around add_concept_tool_func /
# rename_concept_func — NOTHING in the monorepo imported them (verified). carton exposes these as MCP
# tools via server_fastmcp (FastMCP), calling the funcs directly; it never used the heaven-tool wrappers.
# Their only effect was forcing `from heaven_base import BaseHeavenTool, ToolArgsSchema, ToolResult` at
# module top, which pulled langchain_core (~53 MB) into every carton process. Removed for that reason.
# If a heaven AGENT ever genuinely needs add-concept as a heaven tool, define that wrapper IN
# heaven-framework's tool system (where BaseHeavenTool lives), not here in the MCP.

