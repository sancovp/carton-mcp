---
name: edit-content-skyladder
description: "WHAT: the dev flow for the content skyladder's release handlers and their d-chains. WHEN: editing content_projector.py or register_content_rungs.py."
---

# edit-content-skyladder — dev-flow for the Content Skyladder's release-effect content wiring

**In full:** WHAT: the dev-flow for the CONTENT SKYLADDER's release-effect wiring — the content release handlers SOMA never had (write_journeycore, write_blog) PLUS the DISTRIBUTE rungs (fire_park_feed → the 8-doc LAMAI/NEXUS park bundle, fire_park_upload → the gated NEXUS upload), their firing SOMA d-chains, and the vaulted journey_core type they scope to; the RELEASE-LAW path that turns a proven GAS-certified framework into a JourneyCore, a deterministic blog, a park bundle, and a NEXUS upload, dispatched by the carton observation worker daemon. WHEN: when editing content_projector.py (write_journeycore/write_blog/fire_park_feed/fire_park_upload/_framework_from_journeycore/_manualcore_dir/_manualcore/_certify/_content_outdir) in knowledge/carton-mcp, or register_content_rungs.py (the JourneyCore vault + the four add_dchain calls: write_journeycore/write_blog/park_feed/nexus_upload) in scalable-publishing/manualcore, or their premise/conclusion atoms, or the release-effect dispatch gate they depend on (any of).

Goal (Skyladder_Egregore_Compiler_Collection, Isaac /goal 2026-08-01): the Content_Skyladder's
CONTENT half — `write_journeycore → write_blog → site-publish` — reified as VAULTED MATCH-PATTERNS
that self-fire off the RELEASE-LAW, so a proven GAS-certified framework auto-produces its blog with
no cron and no hand-run. Before this, SOMA had ZERO content release handlers (its only handlers were
`carton_mcp.substrate_projector:project_framework/project_rule/project_skill`); content ran on two
DETOURS (the cron blog_organ + hand-run manualcore CLIs). This capability is the **3-wire content
gap** that closes it, mirroring the proven `dchain_skill_project`/`project_skill` exemplar exactly.

The three wires (READ the design in CartON `Content_Skyladder` + `Soma_Release_Effect_Chaining` first
— `activate_collection('Skyladder_Egregore_Compiler_Collection')`):
- **WIRE-1** = the two release handlers (`knowledge/carton-mcp/content_projector.py`).
- **WIRE-2** = the two SOMA d-chains that surface the release_effects (`register_content_rungs.py`).
- **WIRE-3** = vaulting `journey_core` (the content structure) so WIRE-2b has a type to scope to
  (`register_content_rungs.py`). `framework` is the ALREADY-vaulted foundation type WIRE-2a scopes to
  (`base/soma-prolog/soma_prolog/foundation/framework.py`, `register_foundation.py:36`).

## Part 1 — How you edit (read the whole RELEASE-LAW path first — the ONION)

The RELEASE-LAW (Isaac 2026-05-18 + FIX-5 2026-06-15): a SOMA d-chain, when its premise FAILS, asserts
a plain fact `release_effect('<module>:<func>', C)`; SOMA never runs business logic (it is the inner
reflection — it surfaces the fact and RELEASES the runtime up). The carton observation worker daemon
(`observation_worker_daemon.py:1855-1883`) dispatches it AFTER the neo4j write: `if not
c.get("is_system_type"): continue` gates it, then for each release_effect it does
`mod,fn = handler.split(":",1); fn = getattr(import_module(mod), fn); fn(c.name, shared_connection=neo4j)`.

1. **WIRE-1 handlers (`content_projector.py`) each have the EXACT dispatch signature**
   `fn(concept_name: str, shared_connection=None) -> str` — mirroring
   `substrate_projector.project_skill`. They MUST NOT raise past the daemon's `except Exception` guard:
   manualcore's loaders raise `SystemExit` (a BaseException) on a missing/uncomposed framework, so
   `_certify` catches `SystemExit` as `_NotBuildable` and both handlers convert EVERY failure into a
   returned string. They WRAP the deterministic, tested manualcore pipeline
   (`scalable-publishing/manualcore/`: `spec_from_carton.load_framework/build_spec` → THE JourneyCore
   spec; `spec_to_gas.render_gas_facts`; `manual_gas_check.gas_verdict`; `render_blog.render_story_blog/
   render_usage_blog` gated on `status=='compiled'` + no `[FILL:]`; `render_blog.stamp_site_publish`) —
   they do NOT reinvent content. `write_journeycore` certifies a framework and, if `status=='compiled'`,
   writes a `Journey_Core_<framework>` concept (spec/verdict as JSON-string scratch-lane properties) via
   `add_concept_tool_func`. `write_blog` reads those properties off the JourneyCore node and renders.
2. **`_manualcore_dir()` MUST stay robust to BOTH the monorepo checkout AND the installed
   site-packages copy** (env-first, then first-EXISTING of `$DOCMIRROR_MONOREPO/…`, the source-relative
   `parents[2]/…`, and the canonical `/home/GOD/gnosys-plugin-v2/scalable-publishing/manualcore`). The
   carton daemon imports the INSTALLED `content_projector`; the old bare `parents[2]` default resolves to
   the python lib dir from site-packages and does NOT exist → the handler silently fails to import
   manualcore → the daemon dispatches nothing. Proven 2026-08-01: from cwd `/tmp` with `MANUALCORE_DIR`
   UNSET, the installed copy resolves to the canonical path (exists) and imports all 4 manualcore modules.
3. **WIRE-2 conclusion atoms MUST byte-match the handler dispatch path.** `register_content_rungs.py`'s
   `_DCHAIN_WRITE_JOURNEYCORE`/`_DCHAIN_WRITE_BLOG` conclusions assert
   `release_effect('carton_mcp.content_projector:write_journeycore', C)` /
   `:write_blog` — the module path + `:` + func name is what the daemon's `handler.split(":",1)` +
   `import_module` resolves. The single quotes are pre-escaped `\\'` (a backslash-quote in Python source)
   because the conclusion string crosses TWO Prolog parse layers (`mi_add_event` string + the obs_concept
   atom re-parse) — same escaping `foundation/skill.py`/`framework.py` use. Change a handler's
   module/name → change the conclusion atom in lockstep, or the dispatch `getattr` fails.
4. **THE PREMISE GATE IS `code_gap(C)`, NEVER a bare `missing_slot(C,_,_)`** (the traced bug, fixed
   2026-08-01): `( triple(C, <marker>, _) ; code_gap(C) )` succeeds (⇒ SKIP) when already-marked OR the
   concept carries a BLOCKING code-stage gap; FAILS (⇒ fire) only when code-proven and not-yet-marked.
   The skill.py-style `missing_slot(C,_,_)` form SKIPS FOREVER for a vaulted-type instance, because
   mechanism-C (2026-07-05) auto-composes `instantiates <type>` on every instance, which lands a
   PERMANENT NON-BLOCKING `wrong_instantiates_lineage` missing_slot. `code_gap(C)` is exactly the
   CODE-status blocker and ignores non-blocking geometry/lineage nits — this is IDENTICAL to
   `foundation/framework.py:328`'s own `dchain_framework_project` gate (proven necessary there for the
   same reason). The GAS/manualcore certification is NOT a Prolog premise — it CANNOT be (it is a
   swipl/manualcore check); the CERTIFICATION lives in the HANDLER (`write_journeycore` refuses to write
   a JourneyCore unless `gas_verdict.status=='compiled'`), and the handler is idempotent (re-firing
   diffs onto the same node), so — like skill.py (FIX-5) — the marker is never set and the rung fires on
   create AND update.
5. **`register_content_rungs.py` is the CONTENT-SIDE runtime registration, per
   `soma-foundation-vs-contamination` (NUCLEAR).** Content-domain atoms (`journey_core`,
   `write_journeycore`, `write_blog`) NEVER go into SOMA foundation code; they enter as runtime
   `vault()`/`add_dchain()` calls from the content side (exactly like `base/soma-prolog/gnosys-vault/scripts/
   register_gnosys_vault.py` registers the GIINT d-chains). `register()` raises `SystemExit` on any
   `SOMA_POST_ERROR`/`INGEST_ERROR` so a half-registered rung set halts loudly.

## Part 2 — What you must ALSO edit (the coherence edit-set — never edit one wire only)

1. **The three wires are ONE unit.** A handler rename in `content_projector.py` (WIRE-1) → the matching
   conclusion atom in `register_content_rungs.py` (WIRE-2). A change to the JourneyCore concept shape
   (its `is_a`, its `spec_json`/`verdict_json` properties) → BOTH `write_journeycore` (writes them) and
   `write_blog` (reads them) AND the `JourneyCore` pydantic model in `register_content_rungs.py`
   (WIRE-3, whose vault defines the `journey_core` type). The `JourneyCore` model fields are ALL
   `Optional` by design so a `journey_core` instance grades CODE (no `code_gap`) and WIRE-2b fires — do
   NOT make them required.
2. **The unit test moves in lockstep.** `knowledge/carton-mcp/test_content_projector.py` (run as a
   SCRIPT — the repo root IS the `carton_mcp` package; pytest-from-dir breaks on package inference)
   hard-asserts: `write_blog` renders REAL story+usage blogs off a certified fixture spec; `write_blog`
   no-spec is reported not raised; `write_journeycore` certified writes a Journey_Core carrying
   `spec_json` + `journeycore_written`; `write_journeycore` uncertified is reported and NEVER writes.
   Any change to a handler's control-flow contract updates these in the same edit.
3. **DEPLOY — the running daemon is the INSTALLED package, NOT the source** (installed-package law).
   After editing `content_projector.py`: `pip install --no-deps /home/GOD/gnosys-plugin-v2/knowledge/
   carton-mcp` (per `pip-install-our-packages-no-deps`; NEVER `--force-reinstall`). The standing
   `observation_worker_daemon` imports `content_projector` fresh at dispatch time (`import_module`), so
   a redeploy BEFORE the rungs are registered needs no daemon restart. `register_content_rungs.py`
   (manualcore) is imported directly, not installed — a source edit there is live for the next
   `register()` run.
4. **REGISTERING THE RUNGS is a SOMA write.** `register(soma_url, mirror_carton)` does `vault(JourneyCore)`
   + two `add_dchain`. Against an ISOLATED daemon for testing; against prod `:8091` this is the
   SANCTIONED real durable-infrastructure registration (the never-`:8091` gate is for THROWAWAY probes
   only — vaulting a real type + registering real d-chains is exactly the one exception in
   `never-test-against-the-production-soma-daemon`). `mirror_carton=False` keeps the `journey_core` type
   out of the live carton graph. Registered on prod `:8091` 2026-08-01 (`journey_core:code`,
   `dchain_framework_write_journeycore:code`, `dchain_journeycore_write_blog:code`).

## Part 3 — How you test it (the isolated-daemon + real-render gates; "it imported" is NOT the gate)

**Unit gate (WIRE-1, necessary NOT sufficient):** `pip install --no-deps knowledge/carton-mcp` then
`python3 knowledge/carton-mcp/test_content_projector.py` → `ALL PASS (6/6)` — `write_blog` actually
renders (files land, fixture content verbatim), `write_journeycore` writes/refuses correctly,
`fire_park_feed` derives the framework + reports rc/refuse/not-buildable, `fire_park_upload` gates when
`LAMAI_NEXUS_PUBLISH_URL` is unset / skips with no bundle / reads the bundle + POSTs (mocked) when live,
and no handler raises past the daemon guard. (The four distribute/content handlers share the
`_framework_from_journeycore` prefix-strip helper.)

**Isolated-daemon gate (WIRE-2 + WIRE-3 + dispatch, proven 2026-08-01 on `:8095`, NEVER `:8091`):** boot
a throwaway SOMA daemon (separate port + wiped store) with the framework foundation registered (so
`framework` is vaulted), run `register_content_rungs.register(soma_url=<isolated>, mirror_carton=False)`,
POST a COMPLETE framework instance (all 5 required code-stage fields as SOMA relationships) → the verdict
carries `deduction_chains_fired=1`, chain `dchain_framework_write_journeycore`, `release_effects=1` naming
`carton_mcp.content_projector:write_journeycore`; POST a `journey_core` instance → chain
`dchain_journeycore_write_blog`, effect `:write_blog`. Confirm the daemon resolves BOTH handlers
DISPATCH-COMPATIBLE (`getattr(import_module('carton_mcp.content_projector'), fn)`) AFTER the pip install.

**The full UNATTENDED E2E (the release target — see the BLOCKER below):** a real GAS-certified framework
that ALSO grades SOMA-code → written to carton → the running daemon auto-dispatches `write_journeycore` →
the JourneyCore → `write_blog` → a blog, with NO manual handler call. Proven link-by-link + the genesis
blog produced through the path (handlers run directly, 2026-08-01); the single unattended loop is BLOCKED
below.

## THE UNATTENDED-SELF-RUN GATE — the framework must climb SOUP→CODE (RESOLVED 2026-08-01)

The content rung fires only when the framework grades SOMA-**code** — the daemon's OWN dispatch gate
(`observation_worker_daemon.py:1856`, `if not c.get("is_system_type"): continue`; `is_system_type` set
only when SOMA grades the concept code/ont with zero unmet, `add_concept_tool.py:2814-2822`) is upstream
of any d-chain premise. The vaulted `Framework` type has **5 REQUIRED code-stage `str` fields**
(`name/definition/obstacle/overcome/dream` → `required_restriction(framework, has_*, string_value,
code)`; plus `dchain_framework_journey_grounded` `framework.py:285` needs `has_obstacle`/`has_overcome`/
`has_dream` non-empty as **triples**). A manualcore/L6 framework stores those 5 as scratch-lane
**PROPERTIES** (correct for a `str` field) — NOT SOMA triples — and they cannot be relationships (the
daemon MERGEs a `:Wiki` node for every relationship target, `observation_worker_daemon.py:~498`, so a
`str` value would pollute the graph). So a GAS-*argument*-certified framework was SOMA-**SOUP** and both
`dchain_framework_write_journeycore` AND the foundation's own `dchain_framework_project` (same `code_gap`
gate) correctly SKIPPED it.

**RESOLVED — the property→triple bridge** (`add_concept_tool.py`, inside the SOMA-validation block;
unit-proven `test_property_triple_bridge.py` 3/3): the concept's `has_`-prefixed STRING properties (from
the `properties` param AND the existing neo4j node) are appended to the SOMA validation payload as
`string_value` triples — **the neo4j write is untouched** (properties stay properties, zero node
pollution; scratch-lane keys like `status`/`blessed` don't start with `has_`; a `has_` key already a
relationship is not double-bridged). SOMA then sees the 5 required fields → the framework climbs
SOUP→CODE → `is_system_type` true → the rung fires. Do NOT instead weaken the premise (the design
threshold IS `CODE`) or hand-mutate a blessed framework. **The bridge lives on the CENTRAL `add_concept`
write path** — its coherence edit-set + E2E gate belong to the `add_concept` dev-flow
(`edit-add-concept-optional-fields` is the sibling), and its **prod deploy** (`pip install --no-deps` →
the bridge runs on EVERY add_concept across the live 90k store, potentially reclassifying many
`has_`-propertied concepts SOUP→code + cascading their projection release-effects) is **Isaac-timed** per
the `edit-soma-validation` discipline. Not deployed.

## Status

**IS (proven 2026-08-01):** WIRE-1 handlers (test 4/4 + real render); WIRE-2 both d-chains fire the
correct release_effects; WIRE-3 `journey_core` vaulted; the `_manualcore_dir` daemon-resolution gap
CLOSED; the rungs REGISTERED on prod `:8091`; the **property→triple bridge** BUILT + unit-proven (3/3) +
DEPLOYED to prod. **PROOF-LADDER STEP 2 = DONE on the real prod system, UNATTENDED:** re-writing
`Grand_Argument_Synthesis_Gas` once (bridged) → it climbed SOUP→SYSTEM_TYPE (`✅ [SYSTEM_TYPE: all
d-chains satisfied]`) → the prod carton daemon (pid 661) auto-dispatched `write_journeycore` (certified →
wrote the JourneyCore) → `write_blog` (re-rendered story+usage blogs + stamped Site_Publish), with zero
further action; queue drained to 0, no runaway (`/tmp/carton_worker.log`, 16:34).

**IS (proven 2026-08-01, sprint A/B/C — the DISTRIBUTE half):** **A** = `fire_park_feed` +
`dchain_journeycore_park_feed` (wraps `manualcore/park_feed.py`) — DONE + proven UNATTENDED on prod: the
same framework climb now auto-produces the 8-doc park bundle (`manuals/<slug>/rendered/park/`, C2 export
byte-identical to lamai-saas `real/master`). **B** = `substrate_projector.project_to_framework` now reads
the journey fields via a per-field `p(x) or p(story_x) or p(has_x)` fallback chain — DONE + prod-verified:
`project_framework` no longer self-skips; `FRAMEWORK.md` projects (this SUPERSEDES the old "project_framework
self-skips" known-noise item — it is FIXED). **C** = `fire_park_upload` + `dchain_journeycore_nexus_upload`
(POST the park bundle to `LAMAI_NEXUS_PUBLISH_URL`) — CODE BUILT + WIRED + unit-tested (gated/no-bundle/POST
paths); its LIVE E2E is deploy-gated (see VISION). **KNOWN NOISE (not blocking):** the content/distribute
d-chains cross-fire once on the JourneyCore-vs-Framework via part_of scope and no-op — a scope-tighten
(B-part-2), not a bug.

**VISION (not built):** **C's live E2E** — needs the lamai-saas Fly deploy → then `LAMAI_NEXUS_PUBLISH_URL`
set in the daemon env + the park-publish API contract confirmed (my payload `{framework, slug, bundle}`) +
`dchain_journeycore_nexus_upload` registered on prod `:8091` + daemon restart; steps 3–4 (egregore launch =
a LAMAI community + NEXUS park; farm a real sale).

## Cross-refs (canonical)

CartON `Content_Skyladder` / `Soma_Release_Effect_Chaining` / `Vault_From_Gas` / `Egregore_Compiler`
(the design network — `activate_collection('Skyladder_Egregore_Compiler_Collection')`, the approved
knowledge; read it, this skill restates only the wiring slice); `foundation/skill.py` +
`foundation/framework.py` (the RELEASE-LAW exemplars this mirrors); `understand-soma-programming` +
`understand-soma-vault-system` (load BEFORE touching any d-chain/vault); `edit-soma-validation` (the
dev-flow that owns the framework-completion seam); `never-test-against-the-production-soma-daemon` (the
`:8091` gate + its real-registration exception); `pip-install-our-packages-no-deps`;
`every-build-ends-in-a-development-flow-skill`; `verify-via-user-surface-before-done`.

(Knowledge/dev-flow skill — no subagent dispatch, so no RELIABILITY block.)
