"""carton_vault_payload — the lane a vault registration takes INTO CartON.

Isaac, 2026-08-18, verbatim: *"it has to ADD whatever gets vaulted TO CARTON, and adding it
TO CARTON stores it on the SOMA store because it hits SOMA and SOMA adds it to the quadstore.
This is exactly how 'SOMA has a mirror of carton but carton doesnt necessarily mirror SOMA
unless we want it to' is achieved. It should FLAG when it already wrote those things to
carton, and then it should maybe every 7 days check to make sure it isnt lying (and this can
just be logic, last datetime of check and the function checks, not a cron)."*

⇒ THE DIRECTION OF TRUTH, made structural rather than maintained by hand. Before this module,
`vault()` POSTed straight to `/event` and separately mirrored a FLAT summary into CartON — so
a vaulted type reached the SOMA reflection by a path that never went through the record, and
the two stores could disagree from birth (measured on a fresh box: 165 SOMA subjects against
41 CartON nodes). Here the SOMA hit is made BY the CartON write, so the mirroring direction
falls out of the call stack.

⛔ WHY THIS IS A PAYLOAD FUNCTION AND NOT A LOOP OVER add_concept_tool_func — the constraint
that shapes the whole module, MEASURED on an isolated daemon (2026-08-18), never inferred:

  A vault registration's observations are ATOMIC. The type node carries
  `has_required_part -> <arg node>`; each arg node separately carries `has_arg_property` +
  `instantiates`; and SOMA's `register_one_system_type` joins those THREE triples to derive
  the `required_restriction/5` that validates every future instance. That convention is
  guarded by `\\+ system_type_registered(T)` — IT FIRES ONCE PER TYPE PER PROCESS.

  `add_concept_tool_func` writes ONE concept per call and POSTs ITS OWN event per call. So a
  per-observation loop would deliver the type node in one event and its arg nodes in later
  ones; the derivation would run against parts that do not exist yet, derive nothing, and
  LATCH. Measured directly: a type registered that way graded `code` with ZERO restrictions,
  and an instance missing every required field graded `code` instead of `soup` — silently.
  Sending the parts FIRST does not rescue it either: the derivation then fires but binds the
  target type to `artifact` (from `code_arg is_a artifact`) instead of the arg's real
  primitive. Only atomicity gets both right.

⇒ so THE ORDER IS TWO STEPS, and both are needed (Isaac, 2026-08-18): *"first it needs to call
Soma, like add into Soma directly into the quad store. Then it needs to call Carton so that it
adds it AS A SYSTEM TYPE, because that calls Soma and Soma validates it."*

  STEP 1 — the whole payload as ONE direct SOMA event. This is what derives the complete
  `required_restriction`s, and it LATCHES `system_type_registered(T)`.
  STEP 2 — the per-concept CartON writes, each of which CALLS SOMA ITSELF
  (`hide_youknow=False`). SOMA validates each write and grades it, so the concept lands in the
  record AS a system type — with its region, its `is_system_type` flag and its release-effects.

  ⭐ STEP 2 CANNOT UNDO STEP 1, and that is why the order works: `register_one_system_type` is
  guarded by `\+ system_type_registered(T)`, so once step 1 has registered the type the
  per-concept calls simply do not re-derive anything. PROVEN on an isolated daemon (2026-08-18):
  after both steps all six concepts came back `is_system_type=True` AND an instance missing both
  required fields still graded `soup` with `requires has_alpha (string_value)` /
  `requires has_beta (int_value)` — the restrictions intact and correctly typed.

  ⛔ AN EARLIER VERSION OF THIS MODULE PASSED `hide_youknow=True` in step 2, on the reasoning
  that SOMA had already seen the observations so a re-POST would be the split that loses the
  restrictions. That reasoning is WRONG ONCE STEP 1 HAS RUN — and it cost the thing the design is
  for: the queue entries carried `is_soup/is_code/is_system_type` all False and no
  release-effects, so nothing came back as a system type at all. Measured, then corrected.

See `soma_prolog/vault.py`'s `_BATCH` comment for the same invariant on the batch side.
"""

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# How long a written-flag is trusted before the function re-verifies it against CartON.
# Isaac's "maybe every 7 days check to make sure it isnt lying" — logic in the function,
# never a cron, so the check rides the next call that would have done the work anyway.
FLAG_TTL_DAYS = int(os.environ.get("CARTON_VAULT_FLAG_TTL_DAYS", "7"))


def flag_path() -> str:
    """The written-flag store. A FILE, so every process that vaults shares one answer
    (the carton_breaker / carton_quota precedent) rather than each re-deciding."""
    base = os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "carton_vault_written.json")


def _load_flags() -> dict:
    """Read the flag store. A corrupt/absent file means UNFLAGGED — i.e. do the work.
    Failing toward doing the write is the safe direction: the writes are idempotent
    (add_concept is also the update path), while a false 'already written' silently
    leaves the record without the type, which is the exact defect this module exists
    to close."""
    try:
        with open(flag_path()) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        logger.warning("carton vault flag store unreadable — treating as unflagged", exc_info=True)
        return {}


def _save_flags(flags: dict) -> bool:
    """Persist the flag store atomically. Returns whether it actually landed.

    THE RETURN VALUE IS LOAD-BEARING: a caller that assumes a flag was stored when it was
    not will re-do the write next boot, which is merely slow. A caller that assumes the
    OPPOSITE would skip a write that never happened. So this reports honestly and the
    caller never treats a failed save as success."""
    try:
        tmp = flag_path() + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(flags, fh, indent=2)
        os.replace(tmp, flag_path())
        return True
    except Exception:
        logger.warning("could not persist the carton vault flag store", exc_info=True)
        return False


def payload_key(observations: list) -> str:
    """A stable identity for one registration: its observation names PLUS the SHAPE of
    each observation's type-bearing relationships.

    Names alone are NOT enough, and assuming they were silently broke a real deploy
    (measured 2026-08-21). The old docstring reasoned: "a signature change DOES add or
    remove an arg node, which changes the name set, which correctly re-does the write."
    That is FALSE for every change that alters an EXISTING arg instead of adding one:
      - optional -> required (the arg node already existed, the name set is identical)
      - adding has_target_type (the ontological type the value must BE)
      - adding accepts_unnamed
    In all three the name set is byte-identical, so the flag reported "already written",
    the write was skipped, and the boot register still printed rc=0 and
    "REGISTERED SUCCESSFULLY" over a record that never changed — the exact green-log-over-
    an-unchanged-record failure this module exists to close, committed by this function.

    So the key now also folds in each observation's relationship SHAPE (relationship name
    -> sorted target values) for the relationships that carry typing: is_a, instantiates,
    has_target_type, has_arg_property, accepts_unnamed, has_required_part,
    has_optional_part. A description edit still does not change the key (descriptions are
    not in the shape), which preserves the original intent; a SHAPE change now does.

    NOTE: this changes every existing key, so the first run after this lands rewrites all
    registrations. That is the safe direction (the writes are idempotent — add_concept is
    also the update path) and it is a one-time cost."""
    SHAPE_RELS = ("is_a", "instantiates", "has_target_type", "has_arg_property",
                  "accepts_unnamed", "has_required_part", "has_optional_part")

    def _targets(related):
        out = []
        for r in related or []:
            out.append(str(r.get("value", "")) if isinstance(r, dict) else str(r))
        return sorted(out)

    parts = []
    for o in sorted(observations, key=lambda x: str(x.get("name", ""))):
        name = str(o.get("name", ""))
        shape = []
        for rel in o.get("relationships", []) or []:
            rname = str(rel.get("relationship", ""))
            if rname in SHAPE_RELS:
                shape.append(f"{rname}={','.join(_targets(rel.get('related')))}")
        parts.append(name + "#" + ";".join(sorted(shape)))
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str):
    """Parse a stored timestamp. An unparseable one means UNKNOWN, which callers read as
    'stale' — so a corrupted flag triggers re-verification rather than silent trust."""
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        logger.debug("unparseable timestamp in the carton vault flag store: %r", ts, exc_info=True)
        return None


def _concepts_present(names: list, shared_connection=None) -> bool:
    """Is every one of these concepts actually in CartON right now?

    This is the half that makes the flag honest — it is the check that catches the flag
    LYING (the store was rebuilt, a tenant box was reprovisioned, someone pruned). An
    UNANSWERABLE query returns False so the caller re-writes: a meter that cannot count
    must never report 'all present'."""
    try:
        from carton_mcp.add_concept_tool import normalize_concept_name
        from carton_mcp.carton_utils import CartOnUtils
        wanted = [normalize_concept_name(n) for n in names]
        res = CartOnUtils(shared_connection=shared_connection).query_wiki_graph(
            "MATCH (c:Wiki) WHERE c.n IN $names RETURN count(DISTINCT c.n) AS n",
            {"names": wanted})
        if not (isinstance(res, dict) and res.get("success")):
            return False
        rows = res.get("data") or []
        return bool(rows) and rows[0].get("n") == len(set(wanted))
    except Exception:
        logger.debug("carton presence check failed", exc_info=True)
        return False


ABSENT, NOT_CODE, CODE = "absent", "present_not_code", "present_code"


def _prolog_atom_text(value: str) -> str:
    """The text SOMA stores for a primitive value: the quoted Prolog atom it was sent as, read back."""
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), value)


def _value_triples(observations: list, normalize) -> set:
    """Every (subject, predicate, object) the payload says, keyed the way SOMA stores it:
    names and concept refs through ``normalize``, primitive values as the atom text."""
    triples = set()
    for o in observations:
        subject = normalize(str(o.get("name", "")))
        for rel in o.get("relationships") or []:
            pred = str(rel.get("relationship") or rel.get("predicate") or "")
            for item in rel.get("related") or []:
                value = item.get("value") if isinstance(item, dict) else item
                vtype = item.get("type") if isinstance(item, dict) else ""
                if vtype in _PRIMITIVE_TYPES:
                    triples.add((subject, pred, _prolog_atom_text(str(value))))
                else:
                    triples.add((subject, pred, normalize(str(value))))
    return triples


def _reflection_state(observations: list, store_path: str = None) -> tuple:
    """Where this payload stands in SOMA's quadstore: (ABSENT | NOT_CODE | CODE, not-code names).

    ABSENT when any name, relationship or value of the payload is missing, so an edit is sent.
    Otherwise NOT_CODE names every observation holding no ``is_a`` row at code or higher —
    vaulting makes a thing code, so such a registration is vaulted wrong — and CODE means all
    of it is there at code or higher. Names are read under ``soma_prolog.names.normalize_name``.
    An unanswerable check is ABSENT."""
    import sqlite3
    try:
        from soma_prolog.names import normalize_name
    except Exception:
        logger.debug("soma_prolog.names unavailable — reflection unanswerable", exc_info=True)
        return ABSENT, []
    path = store_path or os.environ.get(
        "SOMA_QUADSTORE_PATH", "/tmp/soma_data/soma_quadstore.sqlite3")
    names = sorted({normalize_name(str(o.get("name", ""))) for o in observations} - {""})
    if not names or not os.path.exists(path):
        return ABSENT, []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            for triple in _value_triples(observations, normalize_name):
                if con.execute("SELECT 1 FROM soma_triples WHERE subject=? AND predicate=? "
                               "AND object=? LIMIT 1", triple).fetchone() is None:
                    return ABSENT, []
            not_code = [n for n in names if con.execute(
                "SELECT 1 FROM soma_triples WHERE subject=? AND predicate='is_a' "
                "AND status <> 'soup' LIMIT 1", (n,)).fetchone() is None]
        finally:
            con.close()
        return (NOT_CODE, not_code) if not_code else (CODE, [])
    except Exception:
        logger.debug("soma quadstore presence check failed", exc_info=True)
        return ABSENT, []


def payload_digest(observations: list) -> str:
    """A hash of the whole payload — every name, relationship, type and value — so a
    re-send is recorded against the exact content that was sent."""
    body = sorted(
        (str(o.get("name", "")),
         sorted((str(r.get("relationship") or r.get("predicate") or ""),
                 sorted(json.dumps(i, sort_keys=True) for i in r.get("related") or []))
                for r in o.get("relationships") or []))
        for o in observations)
    return hashlib.sha1(json.dumps(body).encode("utf-8")).hexdigest()[:16]


_RESENT_KEY = "__not_code_resent__"


def resent_unchanged(observations: list) -> bool:
    """True iff this exact payload was already re-sent once while not code."""
    marks = _load_flags().get(_RESENT_KEY)
    return isinstance(marks, dict) and payload_digest(observations) in marks


def mark_resent(observations: list, not_code: list) -> bool:
    """Record that this exact payload was re-sent while not code. Returns whether it persisted."""
    flags = _load_flags()
    marks = flags.get(_RESENT_KEY) if isinstance(flags.get(_RESENT_KEY), dict) else {}
    marks[payload_digest(observations)] = {"at": _now().isoformat(), "not_code": sorted(not_code)}
    flags[_RESENT_KEY] = marks
    return _save_flags(flags)


NOT_CODE_TAG = "present but not code: "


def _state_of(reflection_fn, observations: list) -> tuple:
    """The reflection state of a payload; a ``reflection_fn`` answering a bool means CODE or ABSENT."""
    got = (reflection_fn or _reflection_state)(observations)
    if isinstance(got, bool):
        return (CODE, []) if got else (ABSENT, [])
    return got


def already_written(observations: list, shared_connection=None, present_fn=None,
                    reflection_fn=None) -> bool:
    """True iff this registration is in the reflection at code or higher AND in the record.

    The reflection is checked first, on every call. A flag fresher than FLAG_TTL_DAYS stands in
    for the record check; otherwise the record is asked, and a registration found in both stores
    is flagged and skipped whether or not it carried a flag. Anything else drops the flag and
    returns False so the caller writes."""
    key = payload_key(observations)
    flags = _load_flags()
    entry = flags.get(key)
    entry = entry if isinstance(entry, dict) else None

    if _state_of(reflection_fn, observations)[0] != CODE:
        if entry is not None:
            flags.pop(key, None)
            _save_flags(flags)
        return False

    checked = _parse(str(entry.get("last_checked", ""))) if entry else None
    if checked is not None and _now() - checked < timedelta(days=FLAG_TTL_DAYS):
        return True

    names = [str(o.get("name", "")) for o in observations]
    if (present_fn or _concepts_present)(names, shared_connection=shared_connection):
        mark_written(observations)
        return True

    if entry is not None:
        flags.pop(key, None)
        _save_flags(flags)
    return False


def mark_written(observations: list) -> bool:
    """Flag this registration as written. Returns whether the flag persisted."""
    key = payload_key(observations)
    flags = _load_flags()
    now = _now().isoformat()
    flags[key] = {
        "written_at": now,
        "last_checked": now,
        "names": sorted(str(o.get("name", "")) for o in observations),
    }
    return _save_flags(flags)


# SOMA's primitive TypedValue types. A target of one of these is DATA, not a reference to
# another concept — and that distinction decides whether it may become a CartON relationship.
_PRIMITIVE_TYPES = {"string_value", "int_value", "float_value",
                    "bool_value", "list_value", "dict_value"}


def _to_carton_relationships(obs: dict):
    """Convert a SOMA observation into CartON's (relationships, typed_values, properties).

    SOMA shape: `[{"relationship": r, "related": [{"value": v, "type": t}, ...]}]`.

    ⛔ A PRIMITIVE-TYPED TARGET BECOMES A PROPERTY, NEVER A RELATIONSHIP — this is the whole
    reason the function returns three things. The CartON daemon MERGEs a `:Wiki` NODE for
    every relationship target regardless of its declared type, so routing a `string_value`
    through the relationship channel MINTS A NODE NAMED AFTER THE VALUE. `add_concept_tool`'s
    own property-to-triple bridge documents this exactly: *"a `str` field cannot be a
    relationship without polluting the graph with a value-named node."*

    MEASURED, by doing it wrong: wiring `add_dchain` through this lane sent
    `has_deduction_premise` / `has_deduction_conclusion` — whose values are PROLOG GOAL
    STRINGS — as relationship targets, and the daemon minted **44 nodes** with names like
    `Checking(C),_Triple(C,_Has_Personal_Domain,__)` and
    `Assertz(Unmet_Requirement(Dchain_Skill_Category_Valid))` in the real graph. Concept refs
    stay relationships (they ARE other concepts); primitives ride the scratch-lane property
    channel, which is where the-property-layer-doctrine puts data.

    SOMA is unaffected either way — it received the observation verbatim, with the real
    string values, in the ONE event this module already sent."""
    rels, typed, props = [], [], {}
    for rel in obs.get("relationships") or []:
        name = str(rel.get("relationship") or rel.get("predicate") or "")
        if not name:
            continue
        values = []
        for item in rel.get("related") or []:
            if isinstance(item, dict):
                value, vtype = str(item.get("value")), str(item.get("type") or "")
            else:
                value, vtype = str(item), ""
            if vtype in _PRIMITIVE_TYPES:
                # DATA. Keep the LAST value if a primitive slot somehow carries several —
                # a property holds one value, and silently concatenating would invent one.
                props[name] = value
                continue
            values.append(value)
            if vtype:
                typed.append((value, vtype))
        if values:
            rels.append({"relationship": name, "related": values})
    return rels, typed, props


# The signatures CartON uses to REFUSE a write while still returning normally. The breaker's
# stop-message actuator is the main one (carton_breaker.stop_message), and the quota gate and
# the SOMA-verdict rejections read the same way. Matching on the refusal TEXT is deliberate:
# these paths return a string precisely so an agent gets told what to do instead of getting an
# exception, and any caller that wants to know whether the write LANDED has to read it.
_REFUSAL_MARKERS = (
    "was not written",
    "nothing was queued",
    "stop calling carton tools",
    "quotaexceeded",
    "rejected",
    "❌",
)


def _first_line(text) -> str:
    return str(text).strip().splitlines()[0][:120] if text else ""


def _is_refusal(result) -> bool:
    """Did CartON REFUSE this write while returning normally? See _REFUSAL_MARKERS."""
    low = str(result or "").lower()
    return any(m in low for m in _REFUSAL_MARKERS)


def _default_soma():
    """The real SOMA call, with a timeout SCALED TO THE PAYLOAD. soma_validate defaults
    to 120s, which fits a single-concept event — but the atomic step-1 event of a vault
    chunk carries up to ~40 observations, its pipeline cost scales with the event, and
    on the daemon (single-threaded, serializing) later chunks queue behind earlier ones.
    MEASURED 2026-08-18: at 120s the boot-register's later step-1 events reported
    SOMA_UNREACHABLE while the daemon was still legitimately working. Same reasoning as
    vault.py's _FLUSH_POST_TIMEOUT (280s), floored there and scaled per-observation here."""
    from carton_mcp.add_concept_tool import soma_validate

    def _soma(source, observations, domain="default"):
        timeout = max(300, 15 * len(observations))
        return soma_validate(source=source, observations=observations,
                             domain=domain, timeout=timeout)
    return _soma


def _default_write():
    from carton_mcp.add_concept_tool import add_concept_tool_func
    return add_concept_tool_func


def add_vault_payload(observations: list, source: str = "vault",
                      shared_connection=None, force: bool = False,
                      soma_fn=None, write_fn=None, present_fn=None,
                      reflection_fn=None) -> str:
    """Write ONE vault registration through CartON, and let that write hit SOMA.

    Order, and why it is this order:
      1. ONE `soma_validate` call carrying EVERY observation — the direct add into the
         quadstore. Atomic, so `register_one_system_type` sees the type node and all of its
         part-nodes in the same event and derives COMPLETE restrictions (module header).
      2. The CartON writes, one concept per observation, `hide_youknow=False` — so each write
         CALLS SOMA and SOMA validates it, and the concept lands in the record AS a system
         type (region, `is_system_type`, release-effects). Step 1 has already latched
         `system_type_registered`, so this cannot re-derive or lose anything.

    SOMA runs FIRST because its verdict is what gates the record: that is CartON's own
    existing discipline (validate, then queue), kept rather than inverted.

    Returns a one-line report. NEVER raises — a vault registration must not die because
    the record is briefly unreachable, and the caller renders this string."""
    if not observations:
        return "carton_vault: 0 observations (nothing to write)"

    names = [str(o.get("name", "")) for o in observations]

    state, not_code = _state_of(reflection_fn, observations)
    if not force and state == CODE and already_written(
            observations, shared_connection=shared_connection, present_fn=present_fn,
            reflection_fn=lambda _obs: (state, not_code)):
        return (f"carton_vault: skipped {len(names)} concept(s) — already present at code or "
                f"higher in the reflection and in the record (flag {payload_key(observations)})")
    if not force and state == NOT_CODE and resent_unchanged(observations):
        return (f"carton_vault: posted nothing — this exact content was re-sent once already and "
                f"is still {NOT_CODE_TAG}{', '.join(not_code)}")

    # ── 1. the SOMA hit, made BY this CartON write, atomically ──────────────────────
    try:
        soma = soma_fn or _default_soma()
        soma_data = soma(source=source, observations=observations)
        verdict = soma_data.get("result", "") if isinstance(soma_data, dict) else ""
    except Exception as e:  # noqa: BLE001 — reported, never raised out of vault
        logger.debug("carton_vault soma_validate failed", exc_info=True)
        return f"carton_vault: SOMA_UNREACHABLE ({type(e).__name__}: {e}) — nothing written"

    # A geometric CONTRADICTION is the one verdict CartON refuses to store (accepting it
    # decoheres the graph even as soup). Everything else — including a mereo/soup fill
    # signal — is saved; a fill signal names what is missing, it does not reject.
    if "contradictions=" in verdict:
        logger.warning("carton_vault: SOMA reported a contradiction; refusing to write %s", names)
        return f"carton_vault: REFUSED — SOMA reported a contradiction for {names}"

    after, not_code_after = _state_of(reflection_fn, observations)
    tail = ""
    if after == NOT_CODE:
        mark_resent(observations, not_code_after)
        tail = f"; {NOT_CODE_TAG}{', '.join(not_code_after)}"

    # ── 2. the RECORD ───────────────────────────────────────────────────────────────
    written, failed = [], []
    try:
        write = write_fn or _default_write()
    except Exception as e:  # noqa: BLE001
        logger.debug("carton write entry point unavailable", exc_info=True)
        return f"carton_vault: carton unavailable ({type(e).__name__}: {e}) — SOMA saw the payload, record NOT written"

    for obs in observations:
        name = str(obs.get("name", ""))
        rels, typed, props = _to_carton_relationships(obs)
        if not rels:
            # add_concept refuses an empty relationship set, and rightly — a concept with
            # only data and no edges says nothing about what it IS.
            continue
        try:
            result = write(
                concept_name=name,
                description=obs.get("description") or "",
                relationships=rels,
                typed_values=typed,
                properties=props or None,
                # FALSE on purpose: this write CALLS SOMA, which is what makes the concept
                # come back graded AS a system type. See the module header's two steps.
                hide_youknow=False,
                source=source,
                shared_connection=shared_connection,
            )
            # ⛔ A RETURNED REFUSAL IS NOT A SUCCESS. `add_concept_tool_func` does NOT raise
            # when the graph is unreachable — the circuit breaker RETURNS its stop-message
            # actuator instead ("This concept was NOT written (nothing was queued)"), by
            # design, so an agent gets told to stop rather than getting an exception. Taking
            # the absence of a raise as proof of a write is therefore wrong, and it is wrong
            # in the worst direction: we would then FLAG the payload as written and skip it
            # on every future boot, leaving the record permanently without the type. Caught
            # by the first real E2E run of this lane, where neo4j was unreachable, the
            # breaker opened, ZERO queue entries were written — and the flag was still set.
            if _is_refusal(result):
                failed.append(f"{name}: carton refused the write ({_first_line(result)})")
            else:
                written.append(name)
        except Exception as e:  # noqa: BLE001
            logger.debug("carton_vault write failed for %s", name, exc_info=True)
            failed.append(f"{name}: {type(e).__name__}: {e}")

    if failed:
        return (f"carton_vault: wrote {len(written)}/{len(observations)} concept(s); "
                f"FAILED {len(failed)} ({'; '.join(failed[:3])}) — NOT flagged, so the next "
                f"call retries{tail}")

    flagged = mark_written(observations)
    return (f"carton_vault: registered {len(written)} concept(s) — one atomic SOMA event, "
            f"then {len(written)} validated CartON write(s)"
            f"{'' if flagged else ' (flag NOT persisted — will rewrite next call)'}{tail}")
