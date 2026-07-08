# doc(m): substrate_projector.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/substrate_projector.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10 (added `hydrate_template_content` + `PublishManifest`; module-level `RenderablePiece` import; `_build_template_content` None-description coercion)

## Purpose (one paragraph)

`substrate_projector.py` is the CartON-to-substrate projection engine: given a CartON concept name and a substrate descriptor, it fetches the concept's content from Neo4j and writes it to the target substrate (file, Discord, registry, environment variable, skill package, or Claude Code rule file). It also contains two standalone functions that operate outside the per-concept projection loop: `compile_memory_tier` (the MEMORY.md compiler — queries all Hyperclusters, UltraMaps, and Done collections from CartON and writes one of four tier files) and `memory_tier_stats` / `prune_memory_tier` (stats/deprecated stub). It additionally carries the **manifest-as-render** path: `hydrate_template_content` builds a metastack template content dict for a concept and (one level deep) for its children reached by a given edge, and the `PublishManifest` `RenderablePiece` renders that hydrated content into the scalable-publishing `publish-manifest.json` structure — i.e. the graph IS the manifest source. The module is the primary write path for CartON → filesystem materialisation.

## Surface (1:1 — every public thing, in file order)

### Substrate models — `substrate_projector.py:24`

Pydantic `BaseModel` subclasses describing projection targets. All are members of the `Substrate` union type (`substrate_projector.py:76`).

- `FileSubstrate`  — `substrate_projector.py:24`
  - `type="file"`, `path` (required), `inject_at_line` (optional int, 1-indexed), `inject_at_marker` (optional str), `replace_marker` (bool, default False).
  - `inject_at_line`: inserts content before that line. `inject_at_marker`: finds first line containing the marker string, inserts after (or replaces if `replace_marker=True`). Neither set: appends to end.

- `DiscordSubstrate`  — `substrate_projector.py:33`
  - `type="discord"`, `channel_id` (required), `message_id` (optional). Currently stub-only: `project_to_discord` returns placeholder strings without calling any Discord API.

- `RegistrySubstrate`  — `substrate_projector.py:39`
  - `type="registry"`, `key` (required). Currently stub-only: `project_to_registry` returns a TODO string.

- `EnvSubstrate`  — `substrate_projector.py:44`
  - `type="env"`, `var_name` (required). Sets `os.environ[var_name] = content`. Current-process only.

- `SkillSubstrate`  — `substrate_projector.py:52`
  - `type="skill"`, `output_dir` (optional override; default `$HEAVEN_DATA_DIR/skills/{skill_name}`), `write_to_chromadb` (bool, default True).

- `RuleSubstrate`  — `substrate_projector.py:59`
  - `type="rule"`, `output_dir_override` (optional). Resolves target dir from `has_scope` relationship: `global` → `~/.claude/rules/`, `project` → `{starsystem_path}/.claude/rules/`. Diffs against existing content; writes only if different.

- `SUBSTRATE_CLASSES: List[type]`  — `substrate_projector.py:79`
  - `[FileSubstrate, DiscordSubstrate, RegistrySubstrate, EnvSubstrate, SkillSubstrate, RuleSubstrate]`. Used by `build_instructions()` to dynamically generate the instructions string.
  - **NOTE:** `RuleSubstrate` IS in `SUBSTRATE_CLASSES` (line 85), but the `substrate_classes` dict inside `substrate_project()` at line 1546–1553 does NOT include `"rule"` as a key. This means `substrate_project()` will raise `KeyError` if called with `substrate_type="rule"`. The `PROJECTORS` dispatch table at line 820–827 does include `"rule"`, so direct calls to `PROJECTORS["rule"]` work; only the `substrate_project()` entrypoint is broken for rule projections. IS (code-verified at lines 1546–1553).

### Instruction builder — `substrate_projector.py:104`

- `build_instructions() -> str`  — `substrate_projector.py:104`
  - Dynamically generates a markdown instruction string from `SUBSTRATE_CLASSES` Field descriptions and hardcoded examples. Called by the MCP server to populate tool descriptions.

### `SubstrateProjection` model — `substrate_projector.py:93`

- `target: str` — CartON concept name to project from.
- `substrate: Substrate` — the destination descriptor.
- `description_only: bool` — if True, project only `c.d`; if False, include relationships section.

### Projection logic functions

- `get_concept_content(concept_name, description_only) -> str`  — `substrate_projector.py:159`
  - Fetches concept data from Neo4j via `CartOnUtils().query_wiki_graph`. Applies wiki-link stripping (5-pass loop, same patterns as `strip_wiki_links` but re-implemented locally). If `description_only=False`, appends a `## Relationships` section. Used by all non-skill, non-rule projectors.

- `project_to_file(substrate: FileSubstrate, content: str) -> str`  — `substrate_projector.py:213`
  - Creates new file if path doesn't exist; otherwise reads existing lines and injects at line, at marker, or appends. Returns status string.

- `project_to_discord(substrate: DiscordSubstrate, content: str) -> str`  — `substrate_projector.py:265`
  - STUB. Attempts import of `mcp__our_discord__*` from `server_fastmcp` (silently ignores `ImportError`). Returns placeholder strings only.

- `project_to_registry(substrate: RegistrySubstrate, content: str) -> str`  — `substrate_projector.py:283`
  - STUB. Returns `"Would write to registry key '{key}'"`. TODO comment present.

- `project_to_env(substrate: EnvSubstrate, content: str) -> str`  — `substrate_projector.py:289`
  - Sets `os.environ[substrate.var_name] = content`. Returns status string.

- `_project_giint_hierarchy_rule(utils, ss_path, rules_dir) -> None`  — `substrate_projector.py:295`
  - Queries CartON for the `Giint_Project_*`→`Giint_Feature_*`→`Giint_Component_*` tree under the starsystem concept. Renders as a markdown rule file at `{rules_dir}/giint-hierarchy.md`. Called from `project_to_skill` when projecting to a starsystem.

- `project_to_skill(substrate: SkillSubstrate, concept_name: str, shared_connection=None) -> str`  — `substrate_projector.py:371`
  - Fetches concept data from Neo4j. Maps relationships to skill fields:
    - `HAS_DOMAIN`/`HAS_PERSONAL_DOMAIN`/`HAS_ACTUAL_DOMAIN` → domain (default `"PAIAB"`)
    - `HAS_SUBDOMAIN` → subdomain
    - `HAS_CATEGORY` → category (strips `Skill_Category_` prefix, lowercases)
    - `HAS_WHAT` / `HAS_WHEN` → `what_text` / `when_text` (concept name → readable text via `_resolve_arg_text`)
    - `HAS_PRODUCES`/`PRODUCES` → produces
    - `REQUIRES` → requires (with backfill from `_metadata.json` if Neo4j has none)
    - `HAS_DESCRIBES_COMPONENT`/`DESCRIBES_COMPONENT` → describes
    - `HAS_STARSYSTEM` → starsystem
    - `HAS_CONTEXT_MODE` → context_mode (strips `Skill_Context_` prefix)
    - `SPAWNS_AGENT` → agent_type (strips `Agent_Type_` prefix)
    - `HAS_HOOK` → hooks_list (normalises casing via `_HOOK_CASING`)
    - `HAS_FLAG` → `not_user_invocable`, `model_invocation_disabled`
    - `HAS_ARGUMENT_HINT` → `argument_hint`
  - Writes `SKILL.md` (YAML frontmatter + description body), `_metadata.json`, `reference.md`, and child files routed by `IS_A` type (`Script_*` → `scripts/`, `Template_*` → `templates/`, default → `resources/`).
  - If `write_to_chromadb=True`: upserts an ontological sentence to a `PersistentClient` at `$HEAVEN_DATA_DIR/skill_chroma` (NOTE: this uses `PersistentClient`, not the shared `HttpClient` at port 8101 that `SmartChromaRAG` uses — inconsistency).
  - Phase 3: walks `HAS_DESCRIBES_COMPONENT` → `PART_OF*1..6` → `Starsystem_*` and direct `HAS_STARSYSTEM` to find starsystem filesystem paths (via nested `_resolve_starsystem_path`), copies skill dir to `{ss_path}/.claude/skills/{skill_name}`, writes a `use-{skill_name}.md` rule, and calls `_project_giint_hierarchy_rule`.
  - Returns status string with optional `+ ChromaDB skillgraph written` and `+ projected to N starsystem(s)` suffixes.

### Rule projection helpers — `substrate_projector.py:834`

- `_resolve_starsystem_dir(starsystem_name: str) -> str | None`  — `substrate_projector.py:834`
  - Module-level version of the nested `_resolve_starsystem_path` inside `project_to_skill`. Converts `Starsystem_X` concept name to filesystem path by reverse-engineering the slug transform (`path.replace("-","_").title()`). Scans `["/home/GOD", "/tmp", "/home/GOD/gnosys-plugin-v2"]` as known parent dirs. Returns path string or None if not found.

- `_rule_concept_to_filename(concept_name: str) -> str`  — `substrate_projector.py:878`
  - Converts `Claude_Code_Rule_Persona_Equip` → `persona-equip.md`. Strips `Claude_Code_Rule_` or `Rule_` prefix, lowercases, replaces underscores with hyphens. Fallback when `has_name` is absent on the concept.

- `_render_rule_file_content(has_content: str, has_paths: list | None) -> str`  — `substrate_projector.py:894`
  - Renders the `.md` file body. If `has_paths` is set, prepends YAML frontmatter `paths:` list before the body text.

- `project_to_rule(substrate: RuleSubstrate, concept_name: str, shared_connection=None) -> str`  — `substrate_projector.py:907`
  - Fetches concept + relationships from Neo4j. Rule content source: `HAS_CONTENT` relationship → loads that concept's `c.d` as the rule body; falls back to the concept's own description if `has_content` is missing or target has no description. Skips stub descriptions starting with `"AUTO CREATED:"`.
  - Resolves scope from `HAS_SCOPE` (default `"global"`); resolves starsystem path via `_resolve_starsystem_dir` for `scope=project`.
  - Resolves `HAS_PATHS`/`HAS_PATH` → strips `Path_` prefix and replaces underscores with `/`.
  - Computes filename from `_rule_concept_to_filename`. Diffs against existing file; writes only if different. Returns `"created: {path}"`, `"updated: {path}"`, `"unchanged: {path}"`, or `"skipped: <reason>"`.

### Dispatch table — `substrate_projector.py:820`

```python
PROJECTORS = {
    "file": project_to_file,
    "discord": project_to_discord,
    "registry": project_to_registry,
    "env": project_to_env,
    "skill": project_to_skill,
    "rule": lambda substrate, concept_name: project_to_rule(substrate, concept_name),
}
```

### Template rendering — `substrate_projector.py:1043`

- `_build_template_content(concept_data: dict, concept_name: str) -> dict`  — `substrate_projector.py:1048`
  - Pure helper (unit-tested in `test_carton_properties.py`) that builds the `template_content` dict from a fetched concept row: coerces a missing/`None` `description` to `""` (a property-only node created via MERGE has `c.d == None`), extracts optional `**Taxonomy:**` / `**Source:**` blocks from the description, splits essence into paragraph/sentence, maps relationships to `{type, related}`, then MERGES the node's neo4j properties (`concept_data["props"]`) into the dict — excluding `RESERVED_PROPERTY_KEYS` (imported from `carton_utils`, never redefined) and only filling keys not already present (explicit concept-data keys — name, essence_*, relationships, taxonomy, source — always win).

- `render_through_template(concept_name: str, template_name: str) -> str`  — `substrate_projector.py:1116`
  - Fetches concept data (the Cypher now also returns `properties(c) as props`), builds the template content via `_build_template_content` (which merges non-reserved node properties), looks up the template via `heaven_base.registry.RegistryService` under `"metastacks"`, imports and instantiates the template class dynamically, calls `.render()`. Used by `substrate_project` when `template` param is provided.

### Manifest-as-render path — `substrate_projector.py:1182`

- `hydrate_template_content(concept_name, edge_type=None, children_key="children", shared_connection=None) -> dict`  — `substrate_projector.py:1182`
  - Builds a metastack template content dict for `concept_name` by REUSING `_build_template_content` (NOT re-implementing it — so taxonomy/essence/relationships + non-reserved node properties merge identically). After building, if the node has a non-reserved `name` PROPERTY it overrides the concept-name default `content["name"]` (a property-node's data identity, e.g. unit "doc-mirror" vs concept "Publishing_Unit_Doc_Mirror"). If `edge_type` is given, every child reached by that edge is hydrated the SAME way (one level deep — `edge_type=None` on the recursive call, no grandchildren; YAGNI) and collected, ordered by `coalesce(child.order, 2147483647), child.n` (an authored `order` property wins; else name — deterministic), under `children_key` (the key is omitted when there are no children). Raises `ValueError` if the concept is not found. Unit-tested in `test_publish_manifest_render.py`.

- `class PublishManifest(RenderablePiece)`  — `substrate_projector.py:1258`
  - A metastack `RenderablePiece` that renders the scalable-publishing `publish-manifest.json` structure from hydrated content. Fields: `units: List[dict]` (hydrated unit dicts, as produced by `hydrate_template_content(registry, edge_type="HAS_UNIT", children_key="units")`), `manifest_comment: str | None` (optional top-level `_comment`). `_unit_to_manifest` (static) reconstructs one manifest unit (with nested `readme`) from a flat hydrated dict: scalar `name`/`subdir`/`public_repo`/`pypi` pass through; `readme_description`/`readme_links`/`readme_badges` become `readme.{description,links,badges}` (links/badges `json.loads`'d from their stored json strings; falls back to `{}` on parse failure). `render()` emits `json.dumps(manifest, indent=2, sort_keys=False)` — `_comment` only when set, then `units`. Other hydrated keys (e.g. `order`, essence_*) are ignored by the manifest output. Unit-tested in `test_publish_manifest_render.py`.

### Memory tier compiler — `substrate_projector.py:1182`

- `compile_memory_tier(tier_num=0, shared_connection=None, active_hypercluster=None) -> str`  — `substrate_projector.py:1182`
  - Queries CartON for all `IS_A Hypercluster` nodes (with status, giint_project, parts), all `IS_A Ultramap` nodes, all `Done_*` collections.
  - **Tier 0 (MEMORY.md)** at `~/.claude/projects/-home-GOD/memory/MEMORY.md`:
    - Section 1: UltraMap — queries HC-to-HC morphisms (excluding structural/meta relationship types), groups by source HC, renders as `- **name**: rel_type → target` bullets. HC count summary.
    - Section 2: Active Hypercluster — reads active hypercluster name from `active_hypercluster` param or `/tmp/active_hypercluster.txt`. Calls `ontology_graphs.get_expanded_metagraph` + `format_metagraph_for_memory` for full GIINT expansion (names only); falls back to minimal display on error.
  - **Tier 1 (MTM)** at `~/.claude/rules/mid_term_memory.md`: lists all non-Done, non-MCP, non-Starsystem_Cascade collections with short description.
  - **Tier 2 (LTM)** at `~/.claude/rules/long_term_memory.md`: lists all activatable collection names (`IS_A Carton_Collection / Local_Collection / Identity_Collection / Hypercluster_Collection`).
  - Writes compiled content to `tier_paths[tier_num]`. Returns `"Compiled Tier N: {stats} -> {path}"`.
  - Active hypercluster lookup: checks `active_hypercluster` param first, then `/tmp/active_hypercluster.txt`.

- `prune_memory_tier(tier_num=0, dry_run=False, compress_all=False, shared_connection=None) -> str`  — `substrate_projector.py:1482`
  - **DEPRECATED.** Returns a deprecation message immediately. No logic executes.

- `memory_tier_stats(shared_connection=None) -> str`  — `substrate_projector.py:1487`
  - Queries total `IS_A Hypercluster` count from CartON; reads line counts of the three tier files. Returns a formatted status block.

### Main entrypoint — `substrate_projector.py:1523`

- `substrate_project(substrate: dict, target: str, description_only=True, template=None) -> str`  — `substrate_projector.py:1523`
  - Validates `substrate["type"]` against `PROJECTORS`. Parses substrate into the appropriate model via `substrate_classes` dict (lines 1546–1553).
  - **DISPATCH GAP (IS, code-verified):** `substrate_classes` at line 1546 only contains `"file"`, `"discord"`, `"registry"`, `"env"`, `"skill"` — `"rule"` is absent. Calling `substrate_project({"type":"rule",...}, ...)` will raise `KeyError: 'rule'`. The `PROJECTORS` dispatch table does include `"rule"`, but it is never reached because the parse step fails first.
  - For `skill` type: calls projector directly (fetches its own data). For other types with `template`: calls `render_through_template` first. Otherwise: calls `get_concept_content` then the projector.

## Dependencies

**stdlib:** `os`, `re`, `json`, `shutil`, `yaml`, `logging`, `pathlib`, `typing`

**third-party:**
- `pydantic` — `BaseModel`, `Field`
- `pydantic_stack_core` — `RenderablePiece` (imported at MODULE level; base class for `PublishManifest`). This is the metastack package at `starsystem/metastack/pydantic_stack_core` — a new hard module-level dependency of carton-mcp's substrate_projector.
- `yaml` — for YAML frontmatter generation in skill packages
- `chromadb` — `PersistentClient` (used inside `project_to_skill` for skillgraph ChromaDB writes — NOTE: uses `PersistentClient`, not the shared `HttpClient:8101`)

**intra-repo:**
- `carton_mcp.carton_utils` — `CartOnUtils`, `RESERVED_PROPERTY_KEYS` (imported at function call sites, not module level)
- `carton_mcp.ontology_graphs` — `get_expanded_metagraph`, `format_metagraph_for_memory` (imported inside `compile_memory_tier`)
- `heaven_base.registry` — `RegistryService` (imported inside `render_through_template`)

**consumers (within carton-mcp):**
- `observation_worker_daemon.py` — calls `compile_memory_tier`, `substrate_project`, `project_to_skill`, `project_to_rule`
- `server_fastmcp.py` — exposes `substrate_project` as MCP tool

**consumers (outside carton-mcp):**
- `scalable-publishing/bin/sync_manifest_to_carton.py` — re-homes `publish-manifest.json` units as `Publishing_Unit_<name>` property-nodes + `HAS_UNIT` edges; the manifest is then re-rendered from the graph via `hydrate_template_content` + `PublishManifest`.

## Notes

- **Dispatch gap for `"rule"` type** (`substrate_projector.py:1546–1553`): `substrate_classes` dict inside `substrate_project()` is missing the `"rule"` key. Direct calls to `project_to_rule()` work; calls through the `substrate_project()` entrypoint with `type="rule"` raise `KeyError`. IS (code-verified).
- **Two incompatible ChromaDB clients coexist**: `project_to_skill` writes to a `PersistentClient` at `$HEAVEN_DATA_DIR/skill_chroma`, while `SmartChromaRAG` and `enforce_ontology_invariants` use `HttpClient` at `localhost:8101`. These are different stores. Skills written via `project_to_skill` may not be visible to `SmartChromaRAG`-based queries.
- **`_resolve_starsystem_path`** is defined as a nested function inside `project_to_skill` (line 701) AND as a module-level function `_resolve_starsystem_dir` (line 834). They are functionally identical. The nested one is used only within `project_to_skill`; `_resolve_starsystem_dir` is used by `project_to_rule`.
- **`project_to_discord` and `project_to_registry` are stubs** — they return placeholder strings and perform no real I/O.
- **`prune_memory_tier` is deprecated** — returns immediately with a deprecation message.
- **`compile_memory_tier` reads `/tmp/active_hypercluster.txt`** to determine which hypercluster to expand in MEMORY.md. If the file is absent and `active_hypercluster` param is None, the active section renders as "No active hypercluster set."
- **`render_through_template`** depends on `heaven_base.registry.RegistryService` and dynamically imports template classes from `$HEAVEN_DATA_DIR/metastack_templates/`. Both must exist at runtime for this to work. Node properties merged by `_build_template_content` become extra template kwargs — a template class that rejects unexpected kwargs will raise on a concept carrying non-reserved properties (UNVERIFIED against any registered template; the merge logic itself is unit-tested).
