#!/usr/bin/env python3
"""test_content_projector — WIRE-1 proof (the content release handlers).

Run as a SCRIPT (this repo's convention — the repo root IS the carton_mcp package;
pytest-from-dir breaks on package inference):  python3 test_content_projector.py

Proves, WITHOUT any live daemon / live carton / live files beyond a tmp dir:
  1. write_blog renders a REAL deterministic blog (story + usage) off a certified
     fixture spec — the manualcore render actually runs; the handler wraps it right.
  2. write_journeycore's control-flow contract: NOT-certified -> reported, never raises;
     certified -> writes a Journey_Core concept carrying spec_json (the next rung's input).
  3. A handler NEVER raises past the daemon guard (load_framework's SystemExit is caught).

Boundaries stubbed: the carton read (CartOnUtils), the carton write (add_concept_tool_func),
and — for write_journeycore — the manualcore certify chain (so the test needs no swipl/graph).
write_blog uses the REAL render_blog on a REAL fixture spec (that is the point of the proof).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types

# A minimal CERTIFIED spec matching render_blog's field expectations (root_claim /
# story beats / steps) with ZERO [FILL:] markers, so assert_renderable passes.
FIXTURE_SPEC = {
    "title": "Content Skyladder First Rung",
    "subject": "Content_Skyladder_First_Rung",
    "version": "v0-test",
    "root_claim": {
        "process": "wiring the content skyladder's release chain",
        "dream_outcome": "a blog that renders itself off a GAS-certified structure",
        "system": "SOMA release-effects + the manualcore renderer",
        "guarantees": "nothing renders unless the structure compiles",
        "receipt_modes": ["entailment"],
    },
    "story": {
        "status_quo": "Content ran on two detours. Neither went through GAS-SOMA-release.",
        "obstacle": "SOMA had zero content handlers, so proof could not drive content.",
        "overcome": "We added the three wires: handlers, d-chains, and the vault.",
        "accomplishment": "A proven structure now fires a release that writes a blog.",
        "the_boon": "Anyone can point the chain at a certified structure and get content.",
    },
    "concepts": [],
    "steps": [
        {"instruction": "Vault the content structure so a d-chain can fire on it.",
         "when": "when the structure is GAS-certified", "done_signal": "SOMA grades it code",
         "claim": "the structure is vaulted", "receipt": "proven in the recorded source"},
    ],
    "supports": [],
    "receipts_ledger": {"entailment": "the release chain compiles", "my_outcomes": "1 rung",
                        "customer_outcomes": "GAP: none recorded."},
    "gaps": [],
    "provenance": {"claims": [], "receipt_nodes": [], "ruling": "", "approved_at": ""},
}
FIXTURE_VERDICT = {"status": "compiled", "cert": {"grand_argument": 4}, "gaps": [], "elapsed_ms": 7}


def _install_fake_carton(spec_json: str | None, verdict_json: str | None, write_sink: list):
    """Inject fake carton_mcp.carton_utils + carton_mcp.add_concept_tool so the handlers'
    lazy `from carton_mcp... import ...` gets stubs (no live neo4j / no live writes)."""
    cu = types.ModuleType("carton_mcp.carton_utils")

    class _FakeUtils:
        def query_wiki_graph(self, cypher, parameters=None):
            return {"data": [{"spec_json": spec_json, "verdict_json": verdict_json}]}
    cu.CartOnUtils = _FakeUtils
    sys.modules["carton_mcp.carton_utils"] = cu

    act = types.ModuleType("carton_mcp.add_concept_tool")
    def _fake_add(**kwargs):
        write_sink.append(kwargs)
        return "OK (fake)"
    act.add_concept_tool_func = _fake_add
    sys.modules["carton_mcp.add_concept_tool"] = act


def test_write_blog_renders_real_content() -> None:
    import content_projector as cp
    with tempfile.TemporaryDirectory() as td:
        os.environ["CONTENT_OUTDIR"] = td
        _install_fake_carton(json.dumps(FIXTURE_SPEC), json.dumps(FIXTURE_VERDICT), [])
        out = cp.write_blog("Journey_Core_Content_Skyladder_First_Rung")
        # both drafts must land under CONTENT_OUTDIR/<slug>/
        slug = FIXTURE_SPEC["subject"].lower().replace("_", "-")
        story = os.path.join(td, slug, "story-blog.md")
        usage = os.path.join(td, slug, "usage-blog.md")
        assert os.path.exists(story), f"story blog not written: {out}"
        assert os.path.exists(usage), f"usage blog not written: {out}"
        story_txt = open(story).read()
        usage_txt = open(usage).read()
        # the render must carry the fixture's certified content verbatim (deterministic)
        assert FIXTURE_SPEC["story"]["the_boon"] in story_txt, "boon missing from story blog"
        assert "machine-checked" in story_txt, "cert line missing from story blog"
        assert FIXTURE_SPEC["steps"][0]["done_signal"] in usage_txt, "done-signal missing from usage blog"
    del os.environ["CONTENT_OUTDIR"]


def test_write_blog_no_spec_is_reported_not_raised() -> None:
    import content_projector as cp
    _install_fake_carton(None, None, [])
    out = cp.write_blog("Journey_Core_Nonexistent")
    assert "no spec_json" in out, out


def _stub_manualcore(cp, *, status: str):
    """Replace cp._manualcore with fakes for the certify chain (load_framework/build_spec/
    gas_verdict), reusing the REAL render_blog grabbed via content_projector's OWN importer
    — that call also puts the manualcore dir on the import path, so the test adds none."""
    _sfc, _stg, _mgc, rb = cp._manualcore()
    sfc = types.SimpleNamespace(
        load_framework=lambda name: ({"name": name}, [{"name": "c1"}]),
        build_spec=lambda fw, claims: FIXTURE_SPEC,
    )
    stg = types.SimpleNamespace(render_gas_facts=lambda spec, depth=4: "facts")
    mgc = types.SimpleNamespace(gas_verdict=lambda facts: {**FIXTURE_VERDICT, "status": status})
    cp._manualcore = lambda: (sfc, stg, mgc, rb)


def test_write_journeycore_certified_writes_concept() -> None:
    import content_projector as cp
    sink: list = []
    _install_fake_carton(None, None, sink)
    _stub_manualcore(cp, status="compiled")
    out = cp.write_journeycore("Content_Skyladder_First_Rung")
    assert "wrote Journey_Core_Content_Skyladder_First_Rung" in out, out
    assert sink and sink[0]["concept_name"] == "Journey_Core_Content_Skyladder_First_Rung", "no JourneyCore written"
    props = sink[0].get("properties") or {}
    assert "spec_json" in props and json.loads(props["spec_json"])["subject"] == FIXTURE_SPEC["subject"]
    assert props.get("journeycore_written") is True


def test_write_journeycore_uncertified_is_reported() -> None:
    import content_projector as cp
    sink: list = []
    _install_fake_carton(None, None, sink)
    _stub_manualcore(cp, status="incomplete")
    out = cp.write_journeycore("Content_Skyladder_First_Rung")
    assert "NOT certified" in out, out
    assert not sink, "wrote a JourneyCore for an uncertified structure (must not)"


def _install_fake_park_feed(*, rc=0, raise_systemexit=None):
    """Inject a fake `park_feed` module so fire_park_feed's control flow is testable with
    no live graph / no real render. main() records the argv it was called with (so we can
    assert the Framework name was derived from the JourneyCore) and returns `rc`, or raises
    SystemExit(raise_systemexit) to simulate load_framework's not-buildable signal."""
    pf = types.ModuleType("park_feed")
    calls = []

    def _main(argv=None):
        calls.append(list(argv or []))
        if raise_systemexit is not None:
            raise SystemExit(raise_systemexit)
        return rc
    pf.main = _main
    pf._calls = calls
    sys.modules["park_feed"] = pf
    return calls


def test_fire_park_feed_derives_framework_and_reports() -> None:
    import content_projector as cp
    # rc=0 -> success, and the Framework name is derived from the JourneyCore (prefix stripped)
    calls = _install_fake_park_feed(rc=0)
    out = cp.fire_park_feed("Journey_Core_Grand_Argument_Synthesis_Gas")
    assert calls and calls[0] == ["Grand_Argument_Synthesis_Gas"], f"framework not derived: {calls}"
    assert "park bundle produced for Grand_Argument_Synthesis_Gas" in out, out
    # rc=1 -> refused/usage reported (not raised)
    _install_fake_park_feed(rc=1)
    out = cp.fire_park_feed("Journey_Core_X")
    assert "returned 1" in out and "refused/usage" in out, out
    # SystemExit (load_framework not-buildable) -> reported, never raised past the daemon guard
    _install_fake_park_feed(raise_systemexit="X has no APPROVED composed_from claims")
    out = cp.fire_park_feed("Journey_Core_X")
    assert "NOT buildable" in out and "APPROVED" in out, out


def _install_fake_urlopen(sink):
    """Monkeypatch urllib.request.urlopen to RECORD the POSTed Request and return a fake HTTP-200
    response (a context manager exposing .status) — so fire_park_upload's POST path is testable with
    no live NEXUS. Returns the original urlopen for the caller to restore in a finally block."""
    import urllib.request

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def getcode(self):
            return 200

    orig = urllib.request.urlopen

    def _fake(req, timeout=None):
        sink.append(req)
        return _Resp()
    urllib.request.urlopen = _fake
    return orig


def test_fire_park_upload_gated_bundle_and_post() -> None:
    import content_projector as cp
    import urllib.request
    # (1) GATED: LAMAI_NEXUS_PUBLISH_URL unset -> gated no-op, never raises, names the framework.
    os.environ.pop("LAMAI_NEXUS_PUBLISH_URL", None)
    out = cp.fire_park_upload("Journey_Core_Grand_Argument_Synthesis_Gas")
    assert "GATED" in out and "Grand_Argument_Synthesis_Gas" in out, out
    with tempfile.TemporaryDirectory() as td:
        os.environ["MANUALCORE_DIR"] = td  # authoritative override -> park_dir resolves under td
        os.environ["LAMAI_NEXUS_PUBLISH_URL"] = "http://nexus.test/park-publish"
        # (2) URL set but NO bundle on disk (park_feed has not run) -> reported, never raised.
        out = cp.fire_park_upload("Journey_Core_Grand_Argument_Synthesis_Gas")
        assert "no park bundle" in out and "Skipped" in out, out
        # (3) URL set + a real 2-doc park bundle on disk + mocked POST -> uploaded; framework/slug
        #     derived from the JourneyCore name; the POST body carries framework/slug/bundle.
        park = os.path.join(td, "manuals", "grand-argument-synthesis-gas", "rendered", "park")
        os.makedirs(os.path.join(park, "docs"), exist_ok=True)
        with open(os.path.join(park, "docs", "museum.json"), "w") as f:
            f.write('{"museum": "GAS"}')
        with open(os.path.join(park, "ranger_sidecar.json"), "w") as f:
            f.write('{"ranger": "x"}')
        sink: list = []
        orig = _install_fake_urlopen(sink)
        try:
            out = cp.fire_park_upload("Journey_Core_Grand_Argument_Synthesis_Gas")
        finally:
            urllib.request.urlopen = orig
        assert "uploaded park bundle" in out and "HTTP 200" in out, out
        assert "(2 docs)" in out, f"expected 2 docs read: {out}"
        assert sink, "no POST fired"
        body = json.loads(sink[0].data.decode("utf-8"))
        assert body["framework"] == "Grand_Argument_Synthesis_Gas", body
        assert body["slug"] == "grand-argument-synthesis-gas", body
        assert "docs/museum.json" in body["bundle"] and "ranger_sidecar.json" in body["bundle"], body
    del os.environ["MANUALCORE_DIR"]
    del os.environ["LAMAI_NEXUS_PUBLISH_URL"]


def main() -> int:
    test_write_blog_renders_real_content()
    test_write_blog_no_spec_is_reported_not_raised()
    test_write_journeycore_certified_writes_concept()
    test_write_journeycore_uncertified_is_reported()
    test_fire_park_feed_derives_framework_and_reports()
    test_fire_park_upload_gated_bundle_and_post()
    print("\nALL PASS (6/6) — WIRE-1 content handlers (incl. fire_park_feed / fire_park_upload) verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
