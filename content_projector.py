"""content_projector — the CONTENT release handlers (the Content Skyladder's WIRE-1).

RELEASE-LAW (Isaac 2026-05-18, the exact discipline substrate_projector.project_skill
uses): a SOMA d-chain surfaces a plain fact release_effect('carton_mcp.content_projector:
<fn>', C); the carton observation worker daemon (observation_worker_daemon.py:~1875)
imports THIS module and calls <fn>(concept_name, shared_connection=neo4j). SOMA never runs
business logic — it only surfaces the fact; Python does the I/O on release. These two
functions are the CONTENT analogues of project_skill/project_rule/project_framework — the
handlers that were MISSING (SOMA had zero content handlers; content ran on the cron/hand-run
detours). They do NOT reinvent content: they WRAP the deterministic, tested manualcore
pipeline (scalable-publishing/manualcore/) that already turns a GAS-certified Framework into
a JourneyCore/spec and renders blogs off the certified structure.

THE TWO CONTENT RUNGS (Content_Skyladder design, Gas_Journeycore_Blog_Architecture):
  write_journeycore(Framework)  = matches a proven GAS structure -> load_framework ->
      build_spec (THE JourneyCore/spec) -> render_gas_facts -> gas_verdict; if the structure
      certifies (status == 'compiled'), write a Journey_Core concept back to carton carrying
      the spec + verdict as JSON-string scratch-lane properties. That write re-enters SOMA,
      which fires the next rung.
  write_blog(Journey_Core)      = matches a fresh JourneyCore -> read its spec+verdict ->
      render_story_blog + render_usage_blog (DETERMINISTIC, gated on status=='compiled' and
      no [FILL:] markers) -> write the drafts -> stamp the site-publish nodes (already wired
      to the live fire_site_publish absorber).

CONTRACT (matches the daemon dispatch + project_skill): each handler is
  fn(concept_name: str, shared_connection=None) -> str
and returns a human-readable trace string (the daemon logs it as the release result). A
handler MUST NOT raise past the daemon's `except Exception` guard — manualcore's loaders
raise SystemExit (a BaseException) on a missing/uncomposed framework, so both handlers
convert every failure into a returned string.

STATUS: IS (this module, the WIRE-1 handlers). The firing d-chains (WIRE-2) + the
content-structure vault (WIRE-3) are the other two wires; without them nothing dispatches
these yet. Proven end-to-end only via the isolated-daemon test (never against prod :8091).
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# The Journey_Core concept name is derived from its Framework so write_blog's d-chain can be
# scoped to journey_core and the pair is 1:1 and idempotent (re-firing diffs onto the same node).
_JOURNEY_CORE_PREFIX = "Journey_Core_"


def _framework_from_journeycore(concept_name: str) -> str:
    """Derive the source Framework name from a JourneyCore concept name by stripping the
    `Journey_Core_` prefix. A no-op when the name is already a bare framework — so the same
    handler resolves correctly whether a d-chain fires on the JourneyCore OR (via part_of
    cross-scope) on the Framework itself. Shared by fire_park_feed / fire_park_upload."""
    if concept_name.startswith(_JOURNEY_CORE_PREFIX):
        return concept_name[len(_JOURNEY_CORE_PREFIX):]
    return concept_name


def _manualcore_dir() -> str:
    """Resolve the manualcore dir — first EXISTING candidate wins, robust to BOTH the
    monorepo checkout AND the installed site-packages copy.

    The old default (`parents[2]/scalable-publishing/manualcore`) is correct only from
    `<monorepo>/knowledge/carton-mcp/`; from the INSTALLED copy (site-packages) it
    resolves to the python lib dir and does NOT exist — silently breaking daemon
    auto-dispatch. Order: (1) MANUALCORE_DIR env = authoritative override, returned
    verbatim; then first EXISTING of (2) $DOCMIRROR_MONOREPO/…, (3) source-relative
    parents[2]/…, (4) the canonical monorepo path (canonical-source-dirs), which is what
    lets the installed copy resolve without a MANUALCORE_DIR env or a daemon restart.
    None exist → return (3) so the import raises a clear ModuleNotFoundError (the
    handlers convert it to a returned string, never escaping the daemon except-guard).
    """
    env = os.environ.get("MANUALCORE_DIR")
    if env:
        return env
    src_rel = Path(__file__).resolve().parents[2] / "scalable-publishing" / "manualcore"
    candidates = []
    mono = os.environ.get("DOCMIRROR_MONOREPO")
    if mono:
        candidates.append(Path(mono) / "scalable-publishing" / "manualcore")
    candidates.append(src_rel)
    candidates.append(Path("/home/GOD/gnosys-plugin-v2/scalable-publishing/manualcore"))
    for c in candidates:
        if c.is_dir():
            return str(c)
    return str(src_rel)


def _manualcore():
    """Lazily import the manualcore modules (flat script package on its own dir).

    Lazy + path-inserted so (a) importing carton_mcp.content_projector never drags
    manualcore (avoiding a carton<->manualcore import cycle: manualcore imports
    carton_mcp), and (b) the daemon resolves them at call time. Returns
    (spec_from_carton, spec_to_gas, manual_gas_check, render_blog) modules.
    """
    mc = _manualcore_dir()
    if mc not in sys.path:
        sys.path.insert(0, mc)
    import spec_from_carton  # noqa: E402  (manualcore flat module)
    import spec_to_gas  # noqa: E402
    import manual_gas_check  # noqa: E402
    import render_blog  # noqa: E402
    return spec_from_carton, spec_to_gas, manual_gas_check, render_blog


def _certify(framework_name: str, target_depth: int = 4):
    """load_framework -> build_spec -> render_gas_facts -> gas_verdict.

    Returns (spec, verdict) or raises _NotBuildable (carrying a reason string) for any
    manualcore failure — INCLUDING SystemExit (load_framework raises SystemExit on a
    missing / un-approved-claims framework; SystemExit is a BaseException and would
    otherwise escape the daemon's `except Exception`). The caller turns it into a return
    string so nothing propagates out of a release handler.
    """
    sfc, stg, mgc, _rb = _manualcore()
    try:
        framework, claims = sfc.load_framework(framework_name)
        spec = sfc.build_spec(framework, claims)
        verdict = mgc.gas_verdict(stg.render_gas_facts(spec, target_depth))
    except SystemExit as e:  # load_framework's not-found / no-approved-claims signal
        raise _NotBuildable(str(e)) from e
    except Exception as e:  # noqa: BLE001 — a handler never raises; report as data
        raise _NotBuildable(f"{type(e).__name__}: {e}") from e
    return spec, verdict


class _NotBuildable(RuntimeError):
    """A content structure that cannot be turned into content (not found, not
    composed, or not GAS-certified). Carried as a returned string, never raised out."""


def write_journeycore(concept_name: str, shared_connection=None) -> str:
    """WIRE-1a — release handler for a proven GAS content structure (a Framework).

    Certifies the Framework through the manualcore pipeline and, if it compiles,
    writes a Journey_Core concept (the certified spec) back to carton so the next
    rung (write_blog) fires. Returns a trace string; never raises past the daemon.
    """
    try:
        spec, verdict = _certify(concept_name)
    except _NotBuildable as e:
        return f"write_journeycore({concept_name}): NOT buildable — {e}. JourneyCore not written."

    status = (verdict or {}).get("status")
    if status != "compiled":
        gaps = ", ".join(str(g) for g in (verdict or {}).get("gaps", [])[:3])
        return (f"write_journeycore({concept_name}): structure NOT certified "
                f"(status={status!r}{'; ' + gaps if gaps else ''}). JourneyCore not written.")

    jc_name = f"{_JOURNEY_CORE_PREFIX}{concept_name}"
    try:
        from carton_mcp.add_concept_tool import add_concept_tool_func
        add_concept_tool_func(
            concept_name=jc_name,
            description=(
                f"JourneyCore for {concept_name}: the GAS-certified spec (manualcore "
                f"build_spec output) that the blog renders from. Written by the content "
                f"skyladder's write_journeycore rung on relational proof of the structure."),
            relationships=[
                {"relationship": "is_a", "related": ["Journey_Core"]},
                {"relationship": "part_of", "related": [concept_name]},
            ],
            # Scratch-lane properties: the spec + verdict as JSON strings (str values,
            # property-doctrine legal) so write_blog is self-contained off this one node.
            properties={
                "spec_json": json.dumps(spec),
                "verdict_json": json.dumps(verdict),
                "journeycore_written": True,
                "content_status": "journeycore",
            },
            source="content_projector",
        )
    except Exception as e:  # noqa: BLE001 — report, never raise out of a handler
        log.warning("write_journeycore carton write failed for %s: %s", jc_name, e, exc_info=True)
        return f"write_journeycore({concept_name}): certified but carton write failed — {type(e).__name__}: {e}"

    return f"write_journeycore({concept_name}): certified {status} -> wrote {jc_name}"


def _content_outdir(subject: str) -> str:
    """Where the rendered drafts land. CONTENT_OUTDIR overrides; default mirrors
    manualcore's own machine-render lane (manuals/<slug>/rendered/) under manualcore."""
    env = os.environ.get("CONTENT_OUTDIR")
    if env:
        return os.path.join(env, subject.lower().replace("_", "-"))
    slug = subject.lower().replace("_", "-")
    return os.path.join(_manualcore_dir(), "manuals", slug, "rendered")


def write_blog(concept_name: str, shared_connection=None) -> str:
    """WIRE-1b — release handler for a fresh JourneyCore.

    Reads the JourneyCore's spec+verdict (JSON-string properties), renders the story
    and usage blogs DETERMINISTICALLY off the certified structure (render_blog refuses
    unless status=='compiled' and no [FILL:] markers), writes the drafts, and stamps
    the site-publish nodes (already wired to the live absorber). Returns a trace string.
    """
    _sfc, _stg, _mgc, rb = _manualcore()
    try:
        from carton_mcp.carton_utils import CartOnUtils
        utils = CartOnUtils()
        rows = utils.query_wiki_graph(
            "MATCH (c:Wiki {n: $n}) RETURN c.spec_json AS spec_json, "
            "c.verdict_json AS verdict_json",
            parameters={"n": concept_name})
    except Exception as e:  # noqa: BLE001
        return f"write_blog({concept_name}): carton read failed — {type(e).__name__}: {e}"

    data = (rows or {}).get("data") or []
    if not data or not data[0].get("spec_json"):
        return f"write_blog({concept_name}): no spec_json on the node (not a written JourneyCore). Skipped."

    try:
        spec = json.loads(data[0]["spec_json"])
        verdict = json.loads(data[0].get("verdict_json") or "{}")
    except Exception as e:  # noqa: BLE001
        return f"write_blog({concept_name}): spec/verdict JSON parse failed — {type(e).__name__}: {e}"

    subject = spec.get("subject") or concept_name.replace(_JOURNEY_CORE_PREFIX, "")
    try:
        story_md = rb.render_story_blog(spec, verdict)
        usage_md = rb.render_usage_blog(spec, verdict)
    except rb.NotCertified as e:
        return f"write_blog({concept_name}): render REFUSED — {e}"
    except Exception as e:  # noqa: BLE001
        return f"write_blog({concept_name}): render failed — {type(e).__name__}: {e}"

    outdir = _content_outdir(subject)
    try:
        written = rb._write_drafts(outdir, story_md, usage_md)
        stamped = rb.stamp_site_publish(subject, written)
    except Exception as e:  # noqa: BLE001
        return f"write_blog({concept_name}): wrote nothing — {type(e).__name__}: {e}"

    return (f"write_blog({concept_name}): rendered story+usage for {subject} -> "
            f"{list(written.values())}; stamped {stamped}")


def fire_park_feed(concept_name: str, shared_connection=None) -> str:
    """WIRE-1c — release handler for the DISTRIBUTE half's park_feed rung (sprint A).

    Fired (via a d-chain scoped to journey_core, dchain_journeycore_park_feed) after a
    JourneyCore's blog is produced. Derives the Framework from the JourneyCore name and
    runs the already-BUILT manualcore/park_feed.py pipeline (park_feed.main): a
    framework's certified backing subgraph -> the 8 schema-conformant park docs
    (museum/exhibits=chapters/trails=funnel/ranger_sidecar/...) written to
    manuals/<slug>/rendered/park. This is the C2 seam (hot CartON mindpalace ->
    publish-snapshot, never JIT -> cold park), the 6th renderer off the ONE certified
    subgraph, and the distribute terminal that feeds NEXUS/LAMAI.

    park_feed re-derives spec/verdict from the Framework itself (it does NOT read the
    JourneyCore's spec_json), so this handler passes the Framework name. It NEVER raises
    past the daemon's except-guard: park_feed.main's load_framework/load_feed_extras
    raise SystemExit (a BaseException) on a missing/uncomposed framework, and park_bundle
    raises NotCertified (caught inside main -> rc=1) — all converted to a returned string.
    """
    framework = _framework_from_journeycore(concept_name)
    mc = _manualcore_dir()
    if mc not in sys.path:
        sys.path.insert(0, mc)
    try:
        import park_feed  # noqa: E402 (manualcore flat module, resolved via _manualcore_dir)
    except Exception as e:  # noqa: BLE001
        return f"fire_park_feed({concept_name}): park_feed import failed — {type(e).__name__}: {e}"
    try:
        rc = park_feed.main([framework])
    except SystemExit as e:  # load_framework / load_feed_extras not-found / no-approved-claims
        return f"fire_park_feed({concept_name}): park_feed NOT buildable for {framework} — {e}. Park bundle not written."
    except Exception as e:  # noqa: BLE001 — report, never raise out of a handler
        log.warning("fire_park_feed failed for %s: %s", framework, e, exc_info=True)
        return f"fire_park_feed({concept_name}): park_feed failed for {framework} — {type(e).__name__}: {e}"
    if rc == 0:
        return f"fire_park_feed({concept_name}): park bundle produced for {framework} (manuals/<slug>/rendered/park)."
    return f"fire_park_feed({concept_name}): park_feed returned {rc} (refused/usage) for {framework}."


def fire_park_upload(concept_name: str, shared_connection=None) -> str:
    """WIRE-1d — release handler for the NEXUS upload rung (sprint C: the course-graph ->
    NEXUS upload half, the distribute TERMINAL into a live LAMAI park).

    Reads the park bundle that fire_park_feed produced (manuals/<slug>/rendered/park —
    the 8 schema-conformant docs) and POSTs it to the deployed LAMAI NEXUS park-publish
    API. GATED BY DESIGN: if LAMAI_NEXUS_PUBLISH_URL is unset (lamai-saas not yet Fly-
    deployed — the Isaac-hands step), this returns a gated no-op trace; the wiring is
    already live so the moment the site is deployed + the env is set, the same JourneyCore
    event uploads the bundle. Framework derived from the JourneyCore name; never raises
    past the daemon guard (every failure -> a returned string)."""
    framework = _framework_from_journeycore(concept_name)
    url = os.environ.get("LAMAI_NEXUS_PUBLISH_URL")
    if not url:
        return (f"fire_park_upload({concept_name}): GATED — LAMAI_NEXUS_PUBLISH_URL unset "
                f"(lamai-saas not deployed). Park bundle for {framework} is ready to upload once live.")
    slug = framework.lower().replace("_", "-")
    park_dir = os.path.join(_manualcore_dir(), "manuals", slug, "rendered", "park")
    if not os.path.isdir(park_dir):
        return f"fire_park_upload({concept_name}): no park bundle at {park_dir} (park_feed has not run). Skipped."
    try:
        bundle = {}
        for _root, _dirs, files in os.walk(park_dir):
            for fn in files:
                fp = os.path.join(_root, fn)
                with open(fp, "rb") as f:
                    bundle[os.path.relpath(fp, park_dir)] = f.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return f"fire_park_upload({concept_name}): reading the park bundle failed — {type(e).__name__}: {e}"
    try:
        import urllib.request
        body = json.dumps({"framework": framework, "slug": slug, "bundle": bundle}).encode("utf-8")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
    except Exception as e:  # noqa: BLE001 — report, never raise out of a handler
        log.warning("fire_park_upload POST failed for %s: %s", framework, e, exc_info=True)
        return f"fire_park_upload({concept_name}): upload POST failed for {framework} — {type(e).__name__}: {e}"
    return f"fire_park_upload({concept_name}): uploaded park bundle ({len(bundle)} docs) for {framework} to NEXUS ({url}) -> HTTP {status}."
