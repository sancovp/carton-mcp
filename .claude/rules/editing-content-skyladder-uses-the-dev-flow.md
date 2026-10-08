When you are about to edit the Content Skyladder's release-effect wiring — the two content release
handlers in `knowledge/carton-mcp/content_projector.py` (`write_journeycore`, `write_blog`,
`_manualcore_dir`, `_manualcore`, `_certify`, `_content_outdir`), or
`scalable-publishing/manualcore/register_content_rungs.py` (the `JourneyCore` vault, the two `add_dchain`
calls and their premise/conclusion atoms), or `knowledge/carton-mcp/test_content_projector.py` — you MUST
FIRST use the `edit-content-skyladder` skill and do its COMPLETE Part-2 coherence edit-set, then its
Part-3 isolated-daemon and real-render gate. NEVER edit one wire only.

The capability is DISTRIBUTED across TWO repos and the SOMA foundation, and each part couples tightly:
- WIRE-1, `content_projector.py` in `knowledge/carton-mcp`, is the two release handlers the daemon
  dispatches. They WRAP the pure manualcore pipeline and MUST keep the exact
  `fn(concept_name, shared_connection=None) -> str` dispatch signature and NEVER raise past the daemon's
  `except Exception` guard.
- WIRE-2 and WIRE-3, `register_content_rungs.py` in `scalable-publishing/manualcore`, register the two
  SOMA d-chains and vault `journey_core` at RUNTIME from the content side. Content atoms NEVER enter SOMA
  foundation code.
- The release-effect dispatch (`observation_worker_daemon.py:1855-1883`) gates on `is_system_type` and
  iterates `release_effects`, resolving each via `handler.split(":",1)` plus `import_module` — so a
  handler's module and name MUST byte-match its d-chain's conclusion atom.

Three mechanisms break SILENTLY if you touch adjacent code without reading them first:
1. THE PREMISE GATE IS `code_gap(C)`, NEVER a bare `missing_slot(C,_,_)`. The skill.py-style
   `missing_slot` form SKIPS FOREVER for a vaulted-type instance, because it auto-composes
   `instantiates <type>` into a PERMANENT non-blocking `wrong_instantiates_lineage` missing_slot. This is
   the same reason `foundation/framework.py:328`'s own `dchain_framework_project` gates on `code_gap`.
   Regress this and the rung silently never fires.
2. THE INSTALLED-PACKAGE LAW PLUS THE `_manualcore_dir` DAEMON RESOLUTION. The running daemon imports the
   INSTALLED `content_projector` from site-packages, where a bare `parents[2]` manualcore default
   resolves WRONG, so the handler silently fails to import manualcore and the daemon dispatches nothing.
   A source edit changes nothing running without `pip install --no-deps knowledge/carton-mcp`, and
   `_manualcore_dir` MUST stay robust — env, then the first existing candidate including the canonical
   monorepo path — so the daemon resolves manualcore without a `MANUALCORE_DIR` env or a restart.
3. THE UNATTENDED-SELF-RUN BLOCKER IS A REAL FOUNDATION-ADJACENT SEAM, NOT A WIRING BUG. A GAS-certified
   manualcore framework stores its 5 required `str` fields (name, definition, obstacle, overcome, dream)
   as scratch-lane PROPERTIES, while the vaulted `Framework` type requires them as SOMA code-stage string
   TRIPLES — so it grades SOMA-SOUP (`code_gap`), and both the content rung and the foundation's own
   `dchain_framework_project` correctly skip it. Do NOT "fix" this by hand-mutating a blessed framework
   (a relationship value becomes a text-named neo4j node, which is pollution) or by weakening the premise
   (the design threshold IS `CODE`). It is owned by the `edit-soma-validation` dev-flow.

See `edit-content-skyladder` for the full edit-set and the only valid test: the WIRE-1 unit gate
(`test_content_projector.py` 4/4, run as a SCRIPT) PLUS the isolated-daemon gate — NEVER a throwaway
probe on `:8091`, though registering the real rungs on `:8091` is the sanctioned exception —
`register_content_rungs.register(<isolated>, mirror_carton=False)`, then POST a complete framework
instance, then confirm the verdict carries `release_effects` naming
`carton_mcp.content_projector:write_journeycore` and that the daemon resolves both handlers
DISPATCH-COMPATIBLE after `pip install --no-deps`. "It imported" and "the unit test passed" are NOT the
gate.

Composes with `every-build-ends-in-a-development-flow-skill` (the global law this enforces
project-scoped), `always-use-soma-skills-before-touching-soma`, `soma-foundation-vs-contamination`,
`never-test-against-the-production-soma-daemon`, `pip-install-our-packages-no-deps`,
`check-code-not-markdown-in-our-repos`.
