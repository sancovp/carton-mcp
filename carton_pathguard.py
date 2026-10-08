"""Canonical-path guard for carton file writes — issue #206.

WHY THIS EXISTS (the 2026-08-28 corruption, issue #206): add_document_concept
was called with garbage canonical_paths (the recursive-normalizer signature:
double slashes + Title_Cased copies of real path segments, e.g.
/home/GOD//Home/God/Home/x/Server_Fastmcp.py). The daemon drained the queue and
the file-projection lane APPENDED wiki metadata blocks into a TRACKED SOURCE
FILE (server_fastmcp.py, left unparseable) and minted a stray file. Two lanes
were open: (1) project_to_file (substrate_projector.py) appends to ANY existing
path — FileSubstrate.path is an unconstrained str and there was no root check
anywhere; (2) the wiki lane (observation_worker_daemon.create_wiki_files_for_
concepts) builds paths from normalized names with nothing asserting containment.
The #200 sanitizer (add_concept_tool.py) closed the NAME-level escape (slashes
in concept names now collapse); this module closes the PATH level.

One capability, one module (this repo's convention — the carton_breaker /
carton_kv / split_content precedent): the containment logic lives here; each of
the three write chokepoints carries ONE guarded call:

  1. substrate_projector.project_to_file — checks 'create' (new file) or
     'append' (any rewrite of an existing file, including inject_at_line /
     inject_at_marker) BEFORE touching the path. A refusal propagates as the
     ValueError contract the callers already handle.
  2. server_fastmcp.add_document_concept — checks canonical_path SYNCHRONOUSLY
     at the front door, BEFORE anything is queued, because the queue is
     fire-and-forget and its async failures are silent (the KNOWN-BUG comment
     in that function): the caller must see the refusal.
  3. observation_worker_daemon.create_wiki_files_for_concepts — asserts each
     _itself.md stays under the wiki root; a refusal is recorded per-concept
     and the drain continues (the loop's existing per-concept discipline).

THE RULES (check_write, mode in {'create','append','wiki'}):
  (i)   garbage-path ARTIFACTS refuse outright, naming them: 'double_slash',
        'titlecased_self_segment' (a segment case-colliding with another —
        the recursive-normalizer signature), 'repeated_root' (the same
        absolute prefix appearing twice).
  (ii)  the resolved path must sit under a SANCTIONED ROOT: $HEAVEN_DATA_DIR
        (default /tmp/heaven_data) plus each entry of $CARTON_DOC_ROOTS
        (colon-separated, may be absent). Outside every root -> refuse,
        naming the root set.
  (iii) 'append' is WIKI-ONLY: rewriting an existing file is allowed only
        under $HEAVEN_DATA_DIR/wiki. Registered doc roots are CREATE-only —
        projection may mint a NEW file there, never rewrite a tracked one.
        (Appending to tracked source is exactly the #206 corruption.)
  (iv)  'wiki' additionally asserts containment under $HEAVEN_DATA_DIR/wiki.

Every refusal is a CartonPathRefused (a ValueError) whose message names the
path, the violated rule, and the sanctioned roots — loud, never silent.
Pure logic: no neo4j, no MCP, no I/O beyond Path.resolve(); env is injectable
for tests (the breaker/quota discipline).
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

WIKI_SUBDIR = "wiki"


class CartonPathRefused(ValueError):
    """A carton file write was refused: the message names the offending path,
    the rule violated, and the sanctioned roots. Subclasses ValueError so
    existing callers of project_to_file keep their error contract."""


def sanctioned_roots(env=None) -> list:
    """The roots carton file writes may land under: $HEAVEN_DATA_DIR (default
    /tmp/heaven_data) + every entry of $CARTON_DOC_ROOTS (colon-separated).
    Resolved absolute. PURE apart from reading the injected env."""
    env = os.environ if env is None else env
    roots = [Path(env.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")).resolve()]
    extra = (env.get("CARTON_DOC_ROOTS") or "").strip()
    if extra:
        for part in extra.split(":"):
            part = part.strip()
            if part:
                roots.append(Path(part).resolve())
    return roots


def wiki_root(env=None) -> Path:
    """The one root where appends/rewrites are permitted: $HEAVEN_DATA_DIR/wiki."""
    env = os.environ if env is None else env
    return Path(env.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")).resolve() / WIKI_SUBDIR


def detect_path_artifacts(path_str: str) -> list:
    """PURE. Name the garbage-path artifacts present in path_str:

    'double_slash'            — '//' anywhere in the string.
    'titlecased_self_segment' — two segments equal case-insensitively but
                                differing in case (e.g. .../GOD//Home/God/...),
                                the recursive-normalizer garbage signature.
    'repeated_root'           — the same absolute two-segment prefix appearing
                                twice (e.g. /home/god ... /home/god ...).

    Returns the (possibly empty) list of artifact names found.
    """
    artifacts = []
    if "//" in path_str:
        artifacts.append("double_slash")

    segments = [s for s in path_str.split("/") if s]
    by_lower = {}
    for seg in segments:
        by_lower.setdefault(seg.lower(), set()).add(seg)
    if any(len(cased) > 1 for cased in by_lower.values()):
        artifacts.append("titlecased_self_segment")

    if path_str.startswith("/") and len(segments) >= 2:
        lowered = path_str.lower()
        prefix = "/" + segments[0].lower() + "/" + segments[1].lower()
        if lowered.find(prefix, 1) > 0:
            artifacts.append("repeated_root")

    return artifacts


def check_write(path, mode, env=None) -> None:
    """The gate. Returns None when the write is sanctioned; raises
    CartonPathRefused (loudly naming path + rule + roots) when it is not.

    mode: 'create' — minting a new file; allowed under any sanctioned root.
          'append' — rewriting an existing file (append / inject_at_line /
                     inject_at_marker); allowed ONLY under the wiki root.
          'wiki'   — the daemon's _itself.md lane; must sit under the wiki root.

    An unknown mode raises RuntimeError — a broken caller must never silently
    disable the guard (the breaker/quota loud-on-garbage discipline).
    """
    if mode not in ("create", "append", "wiki"):
        raise RuntimeError(
            f"carton_pathguard.check_write: unknown mode {mode!r} — refusing to "
            "guess (a broken call site must not silently disable the path guard)"
        )
    env = os.environ if env is None else env
    raw = str(path)

    artifacts = detect_path_artifacts(raw)
    if artifacts:
        raise CartonPathRefused(
            f"garbage-path artifacts {artifacts} in {raw!r} — this is the "
            "recursive-normalizer corruption signature (issue #206); nothing "
            "was written"
        )

    resolved = Path(raw).resolve()
    roots = sanctioned_roots(env)
    if not any(resolved == r or resolved.is_relative_to(r) for r in roots):
        raise CartonPathRefused(
            f"{resolved} is outside every sanctioned root "
            f"{[str(r) for r in roots]} — carton writes only under "
            "$HEAVEN_DATA_DIR or a $CARTON_DOC_ROOTS entry (issue #206); "
            "nothing was written"
        )

    wroot = wiki_root(env)
    if mode == "append" and not (resolved == wroot or resolved.is_relative_to(wroot)):
        raise CartonPathRefused(
            f"append/rewrite refused for {resolved}: append is wiki-only "
            f"(under {wroot}); registered doc roots are CREATE-only — "
            "rewriting an existing file outside the wiki lane is the #206 "
            "corruption shape; nothing was written"
        )
    if mode == "wiki" and not (resolved == wroot or resolved.is_relative_to(wroot)):
        raise CartonPathRefused(
            f"wiki write refused for {resolved}: the wiki lane must stay under "
            f"{wroot}; nothing was written"
        )
    return None
