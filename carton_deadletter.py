"""Dead-letter annotation and transient-retry backoff for the observation queue.

TWO INVARIANTS, and this module exists to hold them:

1. EVERY dead letter carries the reason it was dead-lettered. A payload moved to
   `failed/` with no recorded reason cannot be triaged, replayed or trusted: a
   transient rejection and a permanently-malformed one look identical once they are in
   the directory, and nothing afterwards can tell them apart.

2. A batch write that FAILS is retried with backoff before anything is dead-lettered.
   A queue drain writes many payloads in ONE transaction, so one failure of that
   transaction condemns every payload in it. Retrying the write is what separates "the
   store was briefly unreachable" from "this payload can never be applied".

One capability, one module (this repo's convention — the carton_breaker /
carton_pathguard / carton_quota precedent). Layering (onion): the pure functions take
no I/O and are unit-testable standalone; `dead_letter` is the one thin wrapper that
touches the filesystem, and it never raises — a failure to record a reason must never
itself break a drain.

`error_message` is the annotation key because that is the key the recovery verbs
(`check_failed_observations` / `retry_failed_observations`) already read, so an
annotated dead letter is immediately triageable by tools that already exist.

Logging is at WARNING and above throughout: every event here is either a lost payload
or a malformed knob, and both must reach the daemon's stderr log without any handler
having to be configured for them.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# The annotation keys written onto a dead-lettered payload.
REASON_KEY = "error_message"          # read by check_failed_observations / retry_failed_observations
WHEN_KEY = "dead_lettered_at"
ATTEMPTS_KEY = "dead_letter_write_attempts"

DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BASE_S = 2.0
DEFAULT_RETRY_CAP_S = 30.0

# Substrings that mark a store failure as a CONNECTIVITY failure rather than a payload
# defect. Used ONLY to word the recorded reason, never as a gate on whether to retry:
# gating retries on a list of recognised signatures would silently strand every
# transient failure whose wording is not on the list.
_TRANSIENT_MARKERS = (
    "serviceunavailable",
    "sessionexpired",
    "failed to connect",
    "connection closed",
    "incomplete handshake",
    "network is unreachable",
    "network unreachable",
    "connection refused",
    "connection reset",
    "defunct connection",
    "timed out",
    "timeout",
    "broken pipe",
)


# ---------------------------------------------------------------- pure


def _env_number(name, default, cast, minimum=None, env=None):
    """Read a numeric env knob, falling back LOUDLY to the default on garbage.

    A malformed knob must never silently disable a retry or a backoff — it is reported
    with its traceback and the documented default is used.
    """
    source = os.environ if env is None else env
    raw = source.get(name)
    if raw is None:
        return default
    try:
        value = cast(raw)
        if minimum is not None and value < minimum:
            raise ValueError(f"below the minimum of {minimum}")
        return value
    except (TypeError, ValueError):
        logger.warning("%s=%r is not usable — using the default %s", name, raw, default,
                       exc_info=True)
        return default


def retry_attempts(env=None):
    """How many times a failing batch write is attempted in total (at least 1)."""
    return _env_number("CARTON_BATCH_RETRY_ATTEMPTS", DEFAULT_RETRY_ATTEMPTS, int,
                       minimum=1, env=env)


def backoff_delays(attempts, base=None, cap=None, env=None):
    """The waits BETWEEN attempts: exponential from `base`, doubling, capped at `cap`.

    `attempts` total tries yield `attempts - 1` waits, so a single attempt never waits.
    Returns [] for fewer than two attempts.
    """
    if attempts is None or attempts < 2:
        return []
    if base is None:
        base = _env_number("CARTON_BATCH_RETRY_BASE_S", DEFAULT_RETRY_BASE_S, float,
                           minimum=0, env=env)
    if cap is None:
        cap = _env_number("CARTON_BATCH_RETRY_CAP_S", DEFAULT_RETRY_CAP_S, float,
                          minimum=0, env=env)
    return [min(base * (2 ** i), cap) for i in range(attempts - 1)]


def run_with_retry(attempt, succeeded, delays, sleep_fn=None, before_retry=None):
    """Call `attempt()` until `succeeded(result)` is true or the delays run out.

    `delays` is the schedule from `backoff_delays`, so `len(delays) + 1` attempts are
    made at most. `before_retry(attempt_no, delay, result)` runs AFTER each wait and
    BEFORE the next attempt — that is where a caller re-establishes a connection, which
    is usually the thing that makes the next attempt succeed. Returning False from it
    aborts the remaining attempts.

    Returns `(result, attempts_made)`. The last result is returned whether or not it
    succeeded, so the caller can report the failure it actually got.

    This lives here rather than inline in the drain loop so that "fails, then lands on a
    later attempt" is provable without staging an outage against a live store.
    """
    import time
    sleep_fn = sleep_fn or time.sleep
    result = None
    attempts_made = 0
    for i in range(len(delays) + 1):
        attempts_made = i + 1
        result = attempt()
        if succeeded(result):
            return result, attempts_made
        if i >= len(delays):
            break
        sleep_fn(delays[i])
        if before_retry is not None and before_retry(attempts_made, delays[i], result) is False:
            break
    return result, attempts_made


def classify_failure(errors):
    """Word a batch failure as 'transient' or 'unknown' from its error text.

    This decides only how the recorded reason READS. It is deliberately not a gate on
    retrying — see the note on _TRANSIENT_MARKERS.
    """
    blob = " ".join(str(e) for e in (errors or [])).lower()
    return "transient" if any(m in blob for m in _TRANSIENT_MARKERS) else "unknown"


def batch_failure_reason(errors, attempts):
    """The reason recorded on every payload condemned by ONE failed batch write.

    Names the class, how many attempts were made, and the store's own error text, so a
    later reader can tell a retryable outage from a payload that can never be applied.
    It also says explicitly that the payload was condemned as part of a batch, because
    that is the difference between "this payload is broken" and "this payload was
    standing next to one that was".
    """
    kind = classify_failure(errors)
    detail = "; ".join(str(e) for e in (errors or [])) or "no error text was captured"
    return (f"batch write to the graph failed ({kind}) after {attempts} attempt(s); "
            f"every payload parsed in the same batch was dead-lettered with it: {detail}")


# The three things that can happen to the files a batch parsed. THREE, not two — a drain
# that only asks "did the write succeed?" has nowhere to put "nothing was tried".
PROCESSED = "processed"
REQUEUE = "requeue"
DEAD_LETTER = "dead_letter"


def batch_disposition(succeeded, attempts):
    """PURE: what happens to the files a batch parsed — THREE outcomes, never two.

    - PROCESSED    the write landed; the files are consumed.
    - REQUEUE      NOTHING WAS ATTEMPTED (there was no connection), so the files stay in
                   the queue and the next drain retries them once the connection is
                   re-established at the top of the batch.
    - DEAD_LETTER  the write was attempted and failed anyway; the files are condemned
                   carrying the store's own error text. Unchanged behaviour.

    Invariant 2 of this module says a failing write is retried before anything is
    dead-lettered. That is only half a guarantee: a write that was never ATTEMPTED has
    also never been retried, and condemning it is the same loss by a quieter route. A
    payload that was never attempted is not a defective payload, and filing it beside
    genuinely malformed ones is what makes a dead-letter pile unreadable — the pile this
    module exists to keep readable. Measured on the live queue (issue 280): payloads
    filed as `after 0 attempt(s)`, which is the fingerprint of a lane that never ran.

    `attempts == 0` IS the never-attempted signal, and it is exact rather than a proxy:
    `run_with_retry` sets its counter BEFORE each call, so any lane that ran reports at
    least 1 and only a lane skipped entirely can report 0.

    With no parsed files every answer is a no-op, so the caller guards on its own list
    rather than this function inventing a fourth state for an empty batch.
    """
    if succeeded:
        return PROCESSED
    if not attempts:
        return REQUEUE
    return DEAD_LETTER


def annotate_payload(data, reason, when, attempts=None):
    """Return the payload dict with its dead-letter reason recorded.

    Sets `fixed` to False only when the key is absent, so an operator's `"fixed": true`
    marker is never clobbered by a re-run.
    """
    out = dict(data) if isinstance(data, dict) else {"payload": data}
    out[REASON_KEY] = reason
    out[WHEN_KEY] = when
    if attempts is not None:
        out[ATTEMPTS_KEY] = attempts
    out.setdefault("fixed", False)
    return out


def summarize_dead_letters(records):
    """Triage summary of a dead-letter pile, from `(name, payload_or_None)` pairs.

    A pile with no reader rots silently — which is how three months of lost writes
    accumulated with nobody able to say what any of them were. This turns the pile into
    the three numbers a reader can act on: how many there are, how many can be
    explained, and what the explanations say.

    Reasons are grouped by their leading clause (up to the first colon) so that one
    outage's worth of identically-worded dead letters collapses into a single line with
    a count, instead of scrolling past as hundreds of rows.
    """
    from collections import Counter
    total = 0
    with_reason = 0
    unreadable = 0
    by_reason = Counter()
    by_source = Counter()
    for name, payload in records:
        total += 1
        if payload is None:
            unreadable += 1
            continue
        by_source[payload.get("source") or "(no source)"] += 1
        reason = payload.get(REASON_KEY)
        if reason:
            with_reason += 1
            by_reason[str(reason).split(":", 1)[0].strip()[:110]] += 1
    return {
        "total": total,
        "with_reason": with_reason,
        "without_reason": total - with_reason,
        "unreadable": unreadable,
        "by_reason": by_reason.most_common(),
        "by_source": by_source.most_common(8),
    }


def format_dead_letter_report(summary):
    """One human-readable block from `summarize_dead_letters`. Never raises.

    Says plainly when payloads cannot be explained, because an unexplained dead letter
    is the thing a reader most needs to know exists.
    """
    if not summary or not summary.get("total"):
        return "dead-letter queue: EMPTY"
    lines = [
        f"dead-letter queue: {summary['total']} payload(s) — "
        f"{summary['with_reason']} explained, {summary['without_reason']} with NO recorded reason"
    ]
    if summary.get("unreadable"):
        lines.append(f"  {summary['unreadable']} could not be parsed at all")
    for reason, count in summary.get("by_reason", [])[:8]:
        lines.append(f"  {count:6d}  {reason}")
    if summary.get("without_reason"):
        lines.append(f"  {summary['without_reason']:6d}  (no reason recorded — predates the "
                     f"reason-carrying dead-letter lane, and cannot be explained retroactively)")
    return "\n".join(lines)


# ---------------------------------------------------------------- thin wrapper


def dead_letter_report(failed_dir, max_read=5000):
    """Read a dead-letter directory and return its triage report. Never raises.

    `max_read` bounds the JSON parsing on a large pile. The total is always the true
    file count, so the headline number is never understated by the cap.
    """
    failed_dir = Path(failed_dir)
    try:
        files = sorted(failed_dir.glob("*.json"))
    except Exception:
        logger.warning("could not list %s", failed_dir, exc_info=True)
        return "dead-letter queue: unreadable"

    # sorted() on timestamped names puts the newest last, so the cap keeps the RECENT
    # ones — those are the explainable ones, and the ones a reader can still act on.
    split = max(0, len(files) - max_read) if max_read else 0
    records = []
    for f in files[:split]:
        records.append((f.name, {}))          # counted, past the cap, not explained
    for f in files[split:]:
        try:
            with open(f) as fh:
                records.append((f.name, json.load(fh)))
        except Exception:
            # Counted as unreadable in the summary, which is a stronger record than a log
            # line; the traceback goes to DEBUG so a pile of bad files cannot spam stderr.
            logger.debug("dead letter %s could not be parsed", f.name, exc_info=True)
            records.append((f.name, None))

    return format_dead_letter_report(summarize_dead_letters(records))


def dead_letter(queue_file, failed_dir, reason, attempts=None, now_fn=None):
    """Record `reason` on the payload and move it to `failed_dir`. Never raises.

    The move happens even when the payload cannot be annotated (unreadable or
    unparseable JSON) — losing the file would be worse than losing the reason — and the
    annotation failure is reported with its traceback rather than swallowed.

    Returns True when the file was moved.
    """
    from datetime import datetime
    queue_file = Path(queue_file)
    failed_dir = Path(failed_dir)
    when = (now_fn or datetime.now)().isoformat(timespec="seconds")

    try:
        with open(queue_file) as fh:
            data = json.load(fh)
        with open(queue_file, "w") as fh:
            json.dump(annotate_payload(data, reason, when, attempts), fh, indent=2)
    except Exception:
        logger.warning("could not record the reason on %s; moving it anyway. "
                       "The reason was: %s", queue_file.name, reason, exc_info=True)

    try:
        failed_dir.mkdir(exist_ok=True)
        queue_file.rename(failed_dir / queue_file.name)
        logger.warning("dead-lettered %s: %s", queue_file.name, reason)
        return True
    except Exception:
        logger.error("FAILED to move %s to %s — it stays in the queue and will be "
                     "retried on the next drain", queue_file.name, failed_dir,
                     exc_info=True)
        return False
