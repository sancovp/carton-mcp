---
name: carton-projection-flows
description: "WHAT: when and where CartON concepts project out to files, skills and rules. WHEN: deciding how a concept becomes an artifact, or one did not appear."
---

# carton-projection-flows

**In full:** WHAT: when and where CartON concepts project OUT to the world — the automatic release-effect lane (projection as a d-chain conclusion the daemon dispatches) vs the manual substrate_projector tool, the full handler inventory, which write channel feeds which projector, and where each artifact lands on disk. WHEN: deciding how a concept becomes a file, skill, rule, framework doc, GIINT registry entry, state machine, or diary entry; a projection did not happen and you need to know why; choosing between calling substrate_projector and modelling the concept so the system projects it; asking where a projected artifact went.

**Written 2026-08-09 from full reads of `substrate_projector.py` (2424 lines), `sm_gate.py`
(1174 lines), and the `server_fastmcp.py` wiring block. Everything below is [read from code]
unless marked otherwise; the dispatch path itself was E2E-verified previously per the repo's own
dev-flow rules (content-skyladder, carton-write-execution-boundary), not re-fired this session.**

## THE LAW — projection is a d-chain conclusion, not a habit

The default flow is NOT "call a projector." It is: **model the concept correctly → its vaulted
type's projection d-chain fires when the concept is COMPLETE → the daemon dispatches the
handler.** The d-chain premise gates on completeness (`code_gap(C)` — never bare `missing_slot`,
which permanently skips vaulted instances per mechanism-C), so an incomplete concept never
reaches a projector: it sits in soup with a fill signal instead. You author concepts; the system
projects them. Reaching for the manual tool when a typed lane exists bypasses the gate.

## LANE 1 — AUTOMATIC (release effects, dispatched by the observation worker daemon)

The SOMA verdict surfaces `release_effect('module:function', C)`; the daemon resolves the handler
by `import_module` + `split(":",1)` and calls `fn(concept_name, shared_connection)`. Contract
[read from every handler]: **best-effort, never raises; idempotent** (diff-before-write or
MERGE-on-names, so create+update re-fires converge); a skip returns an INSTRUCTIVE string naming
exactly what was missing — read it like a fill signal.

The handler inventory (what exists, what it reads, where it lands):

| handler | reads | lands |
|---|---|---|
| `project_skill` | the concept's OWN description = SKILL.md body; typed rels (HAS_WHAT/HAS_WHEN/HAS_CATEGORY/HAS_CONTEXT_MODE/SPAWNS_AGENT/HAS_HOOK/HAS_FLAG/HAS_ARGUMENT_HINT) = frontmatter; HAS_PART children routed by IS_A into scripts/resources/templates | `$HEAVEN_DATA_DIR/skills/<slug>/` + chroma skillgraph + the resolved starsystem's `.claude/skills/` |
| `project_rule` | the HAS_CONTENT **target's** description = body (fallback: own description); HAS_SCOPE global/project; HAS_PATHS → frontmatter | `~/.claude/rules/` or `<starsystem>/.claude/rules/`, via the ONE writer `paia_builder.rule_cli.write_rule` |
| `project_framework` | node PROPERTIES: definition/obstacle/overcome/dream (fallback chains `has_*`/`story_*`); skips naming the missing field | `$HEAVEN_DATA_DIR/frameworks/<slug>/FRAMEWORK.md` |
| `project_giint_hierarchy` | the Project→Feature→Component tree by PART_OF | `<starsystem>/.claude/rules/giint-hierarchy.md` |
| `project_giint_registry` | the PART_OF chain up to Giint_Project_ | the GIINT JSON registry via `llm_intelligence.projects` |
| `project_state_machine` | `sm_gates` property + Traversal_Step children's properties + has_domain/subdomain/personal_domain | the Sm_Chain graph structure via `create_sm_chain_live` (see `model-anything-in-carton` rung 5) |
| `flush_starlog_diary` | is_a → entry_type map; starsystem detected from file paths in the description | a starlog DebugDiaryEntry (graceful no-op while starlog is disconnected) |
| `write_journeycore` / `write_blog` | the content skyladder (its own dev-flow rule governs edits) | the manualcore content pipeline |

## LANE 2 — MANUAL (the `substrate_projector` MCP tool)

For one-offs and things without a typed lane. Substrates that actually work: **file** (create /
inject at line / inject at marker / append), **env**, **skill**, **rule**. **discord and registry
are STUBS** — they return "Would…" strings and write nothing. **framework is NOT reachable from
the manual tool** (absent from its dispatch table) — release-effect or direct call only. Optional
`template` param renders the concept through a registered metastack template first
(`render_through_template`); `hydrate_template_content` + `PublishManifest` is the one-level
child-hydration variant (registry -HAS_UNIT-> units → publish-manifest.json).

## WHICH CHANNEL FEEDS WHICH PROJECTOR (the load-bearing composition with `carton-write-channels`)

**Where you put a fact decides which projector can see it.** Skills read the concept's own PROSE
as the body. Rules read a NEIGHBOUR's prose (the HAS_CONTENT target). Frameworks and state
machines read PROPERTIES. The publish manifest reads properties across HAS_UNIT children. So
"model it, then project it" only works when the modelling rung (say/fill/declare/state) put the
content in the channel the target projector reads — check this table BEFORE writing, not after a
skip.

**DECIDED DIRECTION (Isaac 2026-08-09, issue 141 — not built yet):** this hardcoding becomes
content-source RESOLUTION — a projector checks for a content graph object first (`has_desc_content`
node, then `HAS_CONTENT` target, then description), and any projection that would overwrite
differing existing file content versions the prior state first via the sinking machinery
(`sink_concept` → `<name>_v1`; the read layer hides `_v`-numbered versions but preserves them).
Live state: `Projector_Content_Source_Awareness` concept (status property).

## THE LOCATION GOTCHA [read from code, twice independently]

Filesystem paths survive ONLY in the description (`"...Location: <dir>."` — carton_sync writes
it; both GIINT handlers regex it back out), because a relationship target gets Title_Cased and is
LOSSY for a path. Path-bearing facts go in prose or properties, never as relationship targets.
Starsystem→path resolution otherwise falls back to scanning known parent dirs against the
Title_Cased slug — heuristic, can miss.

## MEMORY TIERS ARE PROJECTIONS TOO

`compile_memory_tier(0..3)` compiles MEMORY.md / MTM / LTM / L2 from the Hypercluster graph.
MEMORY.md is OBJECT CODE — never hand-edited; the graph is the source.

## WHEN NOT TO PROJECT

Derived, re-derivable data stays in its source store. CA code facts are never copied into Wiki
nodes (one-database-two-doors: the join is a query, not an ingest); a projection that duplicates
a live store creates two drifting representations — the duplicate-store anti-pattern the
giint-registry port itself had to manage. Project when the destination is a CONSUMPTION surface
(a file an agent/tool reads, a registry a system executes), not a second store of truth.

## VERIFY

After any projection: read the artifact on disk (never the return string alone), and on a skip,
treat the skip string as the fill signal it is — fix the named gap on the CONCEPT, re-save, let
the d-chain re-fire.

## Cross-refs

`model-anything-in-carton` (the ladder that makes a concept projectable; rung 5 = state
machines) · `carton-write-channels` (which surface sees which channel) · `edit-content-skyladder`
+ `carton-write-execution-boundary` (the repo dev-flows governing handler edits) ·
`vault-a-library-into-soma` (authoring the projection d-chains themselves).
