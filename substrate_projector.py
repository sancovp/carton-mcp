# substrate_projector.py
"""
Substrate Projector - Project Carton concepts to various substrates.

Carton as source of truth, project content anywhere on demand.
"""

from pydantic import BaseModel, Field
from typing import Literal, Union, List
from pathlib import Path
import os
import re
import json
import shutil
import yaml
import logging

# metastack RenderablePiece — the typed self-rendering piece base. Used by the
# PublishManifest template (carton -> publish-manifest.json render). pydantic_stack_core
# is the metastack package (starsystem/metastack/pydantic_stack_core).
from pydantic_stack_core import RenderablePiece

logger = logging.getLogger(__name__)


# ============================================================================
# Substrate Models - each with self-documenting Field descriptions
# ============================================================================

class FileSubstrate(BaseModel):
    """Project to file at line or marker"""
    type: Literal["file"] = "file"
    path: str = Field(..., description="Path to target file")
    inject_at_line: int | None = Field(None, description="Line number to inject content at (1-indexed)")
    inject_at_marker: str | None = Field(None, description="Marker string like <!-- INJECT:name --> to find and replace after")
    replace_marker: bool = Field(False, description="If True, replace the marker line itself; if False, inject after marker")


class DiscordSubstrate(BaseModel):
    """Project to Discord channel"""
    type: Literal["discord"] = "discord"
    channel_id: str = Field(..., description="Discord channel ID")
    message_id: str | None = Field(None, description="Message ID to edit, or None for new message")


class RegistrySubstrate(BaseModel):
    """Project to HEAVEN registry key-value"""
    type: Literal["registry"] = "registry"
    key: str = Field(..., description="Registry key to write to")


class EnvSubstrate(BaseModel):
    """Project to environment variable (current process only)"""
    type: Literal["env"] = "env"
    var_name: str = Field(..., description="Environment variable name")


class SkillSubstrate(BaseModel):
    """Project CartON concept to skill package directory + ChromaDB skillgraph entry"""
    type: Literal["skill"] = "skill"
    output_dir: str | None = Field(None, description="Override output dir. Defaults to HEAVEN_DATA_DIR/skills/{name}")
    write_to_chromadb: bool = Field(True, description="Write skillgraph entry to ChromaDB for Crystal Ball discovery")


class RuleSubstrate(BaseModel):
    """Project CartON Rule_ concept to a Claude Code .md rule file.

    Resolves target dir from has_scope:
      - has_scope=global  -> ~/.claude/rules/<slug>.md
      - has_scope=project -> <starsystem_path>/.claude/rules/<slug>.md
                             (starsystem path resolved from has_starsystem)

    Renders has_content as the file body. If has_paths is set, renders YAML
    frontmatter with paths: list. Diffs against current file content; only
    writes if different. Never deletes.
    """
    type: Literal["rule"] = "rule"
    output_dir_override: str | None = Field(None, description="Override output dir, ignoring has_scope/has_starsystem")


# Union of all substrate types
Substrate = Union[FileSubstrate, DiscordSubstrate, RegistrySubstrate, EnvSubstrate, SkillSubstrate, RuleSubstrate]

# Registry of all substrate classes for dynamic instruction building
SUBSTRATE_CLASSES: List[type] = [
    FileSubstrate,
    DiscordSubstrate,
    RegistrySubstrate,
    EnvSubstrate,
    SkillSubstrate,
    RuleSubstrate,
]


# ============================================================================
# Projection Request Model
# ============================================================================

class SubstrateProjection(BaseModel):
    """Full projection request"""
    substrate: Substrate
    target: str = Field(..., description="Carton concept name to project from")
    description_only: bool = Field(True, description="If True, project only description; if False, include relationships")


# ============================================================================
# Instruction Builder
# ============================================================================

def build_instructions() -> str:
    """Dynamically build instructions from substrate Field descriptions"""
    lines = [
        "# Substrate Projector Instructions",
        "",
        "Project Carton concepts to various substrates (destinations).",
        "",
        "## Parameters",
        "- substrate: dict with 'type' and type-specific fields (see below)",
        "- target: Carton concept name to project from",
        "- description_only: True for just description, False to include relationships",
        "",
        "## Available Substrates",
        "",
    ]

    for substrate_cls in SUBSTRATE_CLASSES:
        lines.append(f"### {substrate_cls.__name__.replace('Substrate', '')}")
        lines.append(f"type: \"{substrate_cls.model_fields['type'].default}\"")
        if substrate_cls.__doc__:
            lines.append(f"  {substrate_cls.__doc__}")
        lines.append("")

        for name, field in substrate_cls.model_fields.items():
            if name == "type":
                continue
            required = "required" if field.is_required() else "optional"
            desc = field.description or "No description"
            lines.append(f"  - {name} ({required}): {desc}")

        lines.append("")

    lines.extend([
        "## Examples",
        "",
        "Project to file at line:",
        '  substrate={"type": "file", "path": "/path/to/file.md", "inject_at_line": 10}',
        '  target="My_Concept"',
        "",
        "Project to file at marker:",
        '  substrate={"type": "file", "path": "/path/to/file.md", "inject_at_marker": "<!-- INJECT:section -->"}',
        '  target="My_Concept"',
        "",
        "Project to Discord:",
        '  substrate={"type": "discord", "channel_id": "123456789"}',
        '  target="My_Concept"',
    ])

    return "\n".join(lines)


# ============================================================================
# Projection Logic
# ============================================================================

def get_concept_content(concept_name: str, description_only: bool) -> str:
    """Fetch concept content from Carton/Neo4j"""
    from carton_mcp.carton_utils import CartOnUtils

    utils = CartOnUtils()

    # Query concept directly from Neo4j
    cypher_query = """
    MATCH (c:Wiki) WHERE c.n = $concept_name AND c.d IS NOT NULL
    OPTIONAL MATCH (c)-[r]->(related:Wiki)
    RETURN c.n as name, c.d as description,
           collect({type: type(r), target: related.n}) as relationships
    """
    result = utils.query_wiki_graph(cypher_query, {"concept_name": concept_name})

    if not result.get("success") or not result.get("data"):
        raise ValueError(f"Concept '{concept_name}' not found")

    concept_data = result["data"][0]
    description = concept_data.get("description", "")
    # Strip wiki-links iteratively (nested links need multiple passes)
    for _ in range(5):
        prev = description
        # [word](../Path/Path_itself.md) → word
        description = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', description)
        # Orphan link targets: (../Path/Path_itself.md) or (/Path_itself.md)
        description = re.sub(r'\([^)]*_itself\.md\)', '', description)
        description = re.sub(r'\(\.\./[^)]*\)', '', description)
        # Bare brackets: [word] → word
        description = re.sub(r'\[([^\]]+)\]', r'\1', description)
        if description == prev:
            break
    # Strip truncated fragments
    description = re.sub(r'\(\.\./[^)]*$', '', description)
    description = re.sub(r'/\w+_itself\.md\)', '', description)
    # Clean up double spaces and leading/trailing whitespace per line
    description = re.sub(r'  +', ' ', description)

    if description_only:
        return description
    else:
        # Format with relationships
        lines = [description]

        relationships = [rel for rel in concept_data.get("relationships", []) if rel.get("type")]
        if relationships:
            lines.append("")
            lines.append("## Relationships")
            for rel in relationships:
                lines.append(f"- {rel['type']}: {rel['target']}")

        return "\n".join(lines)


def project_to_file(substrate: FileSubstrate, content: str) -> str:
    """Project content to file"""
    path = Path(substrate.path)

    if not path.exists():
        # Create new file with content
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return f"Created {path} with content"

    # Read existing file
    lines = path.read_text().splitlines()

    if substrate.inject_at_line is not None:
        # Inject at specific line (1-indexed)
        line_idx = substrate.inject_at_line - 1
        content_lines = content.splitlines()
        new_lines = lines[:line_idx] + content_lines + lines[line_idx:]
        path.write_text("\n".join(new_lines))
        return f"Injected at line {substrate.inject_at_line} in {path}"

    elif substrate.inject_at_marker is not None:
        # Find marker and inject after (or replace)
        marker = substrate.inject_at_marker
        marker_idx = None

        for i, line in enumerate(lines):
            if marker in line:
                marker_idx = i
                break

        if marker_idx is None:
            raise ValueError(f"Marker '{marker}' not found in {path}")

        content_lines = content.splitlines()

        if substrate.replace_marker:
            new_lines = lines[:marker_idx] + content_lines + lines[marker_idx + 1:]
        else:
            new_lines = lines[:marker_idx + 1] + content_lines + lines[marker_idx + 1:]

        path.write_text("\n".join(new_lines))
        action = "Replaced marker" if substrate.replace_marker else "Injected after marker"
        return f"{action} in {path}"

    else:
        # Append to end
        existing = path.read_text()
        path.write_text(existing + "\n" + content)
        return f"Appended to {path}"


def project_to_discord(substrate: DiscordSubstrate, content: str) -> str:
    """Project content to Discord channel"""
    # Import discord MCP tools
    try:
        from carton_mcp.server_fastmcp import mcp__our_discord__send_message, mcp__our_discord__edit_message
    except ImportError:
        pass

    # Use the discord MCP directly
    if substrate.message_id:
        # Edit existing message
        # This would need the discord MCP integration
        return f"Would edit message {substrate.message_id} in channel {substrate.channel_id}"
    else:
        # Send new message
        return f"Would send to channel {substrate.channel_id}"


def project_to_registry(substrate: RegistrySubstrate, content: str) -> str:
    """Project content to HEAVEN registry"""
    # TODO: Integrate with HEAVEN registry
    return f"Would write to registry key '{substrate.key}'"


def project_to_env(substrate: EnvSubstrate, content: str) -> str:
    """Project content to environment variable"""
    os.environ[substrate.var_name] = content
    return f"Set env var {substrate.var_name}"


def _project_giint_hierarchy_rule(utils, ss_path: str, rules_dir) -> None:
    """Project the GIINT hierarchy as a rule file into a starsystem's .claude/rules/.

    Queries CartON for the GIINT_Project under this starsystem and renders
    the full Project → Feature → Component tree as a markdown rule.
    """
    from pathlib import Path

    # Find GIINT_Project for this starsystem by walking from Starsystem concept
    path_slug = ss_path.strip("/").replace("/", "_").replace("-", "_").title()
    ss_concept = f"Starsystem_{path_slug}"

    # Query: Starsystem → has_project → Starlog_Project, then find GIINT_Project_ under it
    hierarchy_query = """
    MATCH (ss:Wiki {n: $ss_name})
    OPTIONAL MATCH (proj:Wiki)-[:PART_OF]->(ss)
    WHERE proj.n STARTS WITH 'Giint_Project_'
    WITH proj
    WHERE proj IS NOT NULL
    OPTIONAL MATCH (feat:Wiki)-[:PART_OF]->(proj)
    WHERE feat.n STARTS WITH 'Giint_Feature_'
    OPTIONAL MATCH (comp:Wiki)-[:PART_OF]->(feat)
    WHERE comp.n STARTS WITH 'Giint_Component_'
    RETURN proj.n as project, feat.n as feature, comp.n as component
    ORDER BY feat.n, comp.n
    """
    result = utils.query_wiki_graph(hierarchy_query, {"ss_name": ss_concept})

    if not result.get("success") or not result.get("data"):
        logger.info("No GIINT hierarchy found for %s", ss_concept)
        return "no-hierarchy"

    # Build tree from flat rows
    projects = {}
    for row in result["data"]:
        proj = row.get("project")
        feat = row.get("feature")
        comp = row.get("component")
        if not proj:
            continue
        if proj not in projects:
            projects[proj] = {}
        if feat:
            if feat not in projects[proj]:
                projects[proj][feat] = []
            if comp and comp not in projects[proj][feat]:
                projects[proj][feat].append(comp)

    if not projects:
        return "no-hierarchy"

    # Render as markdown
    lines = ["# GIINT Hierarchy", "", "This starsystem's project structure:", ""]
    for proj, features in projects.items():
        proj_short = proj.replace("Giint_Project_", "")
        lines.append(f"## {proj_short}")
        lines.append("")
        if not features:
            lines.append("*(No features defined yet)*")
            lines.append("")
            continue
        for feat, components in features.items():
            feat_short = feat.replace("Giint_Feature_", "")
            lines.append(f"### {feat_short}")
            if components:
                for comp in components:
                    comp_short = comp.replace("Giint_Component_", "")
                    lines.append(f"- {comp_short}")
            else:
                lines.append("- *(No components yet)*")
            lines.append("")

    content = "\n".join(lines) + "\n"
    target = Path(rules_dir) / "giint-hierarchy.md"
    # Diff-and-write (B1, 2026-06-15): re-render on every fire, write only if the
    # content changed. The projection d-chain fires on create AND update (sibling
    # projects under the same starsystem each re-render the whole tree), so the
    # write must be idempotent — converge on identical content, no churn.
    if target.exists() and target.read_text() == content:
        logger.info("GIINT hierarchy rule unchanged: %s", target)
        return "unchanged"
    target.write_text(content)
    logger.info("Projected GIINT hierarchy rule to %s", target)
    return "projected"


def project_to_skill(substrate: SkillSubstrate, concept_name: str, shared_connection=None) -> str:
    """Project CartON concept to skill package + optional ChromaDB skillgraph entry.

    Fetches structured concept data (description + relationships) from Neo4j,
    maps relationships to GnosysSkillMetadata fields, writes skill package dir.

    Args:
        substrate: SkillSubstrate with output config
        concept_name: CartON concept name (NOT content string — skill fetches its own data)
    """
    from carton_mcp.carton_utils import CartOnUtils

    utils = CartOnUtils(shared_connection=shared_connection)

    # Fetch structured concept data
    cypher = """
    MATCH (c:Wiki) WHERE c.n = $name AND c.d IS NOT NULL
    OPTIONAL MATCH (c)-[r]->(related:Wiki)
    RETURN c.n as name, c.d as description,
           collect({type: type(r), target: related.n}) as relationships
    """
    result = utils.query_wiki_graph(cypher, {"name": concept_name})

    if not result.get("success") or not result.get("data"):
        raise ValueError(f"Concept '{concept_name}' not found")

    data = result["data"][0]
    # Strip CartON wiki-links: [word](../Path/Path_itself.md) → word
    description = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', data.get("description", ""))
    rels = data.get("relationships", [])

    # Helpers for relationship extraction
    def rel_targets(rel_type):
        return [r["target"] for r in rels if r.get("type") == rel_type]

    def first_rel(rel_type):
        targets = rel_targets(rel_type)
        return targets[0] if targets else None

    # SKILL CONTENT SOURCE: The source concept's description (c.d in Neo4j) IS the
    # SKILL.md body. Set by the FIRST desc= in the Dragonbones EC.
    # has_content is NOT used here — OWL does not require it on Skill (only on
    # Claude_Code_Rule). giint_types.py does not require it either (removed Apr 29 2026).
    # If you are looking for where has_content matters: see project_to_rule() below.

    # Map relationships to GnosysSkillMetadata fields
    domain = (first_rel("HAS_DOMAIN") or first_rel("HAS_PERSONAL_DOMAIN")
              or first_rel("HAS_ACTUAL_DOMAIN") or "PAIAB")
    subdomain = first_rel("HAS_SUBDOMAIN")
    raw_category = first_rel("HAS_CATEGORY") or "understand"
    # Strip Skill_Category_ prefix: "Skill_Category_Preflight" → "preflight"
    category = re.sub(r'^Skill_Category_', '', raw_category).lower()

    # ARG fields: the concept NAME is the value. Convert to readable text.
    def _resolve_arg_text(rel_type):
        """Convert ARG relationship target name to readable text."""
        name = first_rel(rel_type)
        if not name or name == "_Unnamed" or name == "none":
            return None
        return name.replace("_", " ")

    what_text = _resolve_arg_text("HAS_WHAT")
    when_text = _resolve_arg_text("HAS_WHEN")
    produces = first_rel("HAS_PRODUCES") or first_rel("PRODUCES")
    requires = rel_targets("REQUIRES") or None

    # Bidirectional sync: if Neo4j has no REQUIRES but _metadata.json does, backfill
    if not requires:
        heaven_dir = os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")
        _meta_path = Path(heaven_dir) / "skills" / concept_name.lower().replace("_", "-") / "_metadata.json"
        if _meta_path.exists():
            try:
                _existing_meta = json.loads(_meta_path.read_text())
                _fs_requires = _existing_meta.get("requires", [])
                if _fs_requires:
                    # Create REQUIRES edges in Neo4j
                    for req_skill in _fs_requires:
                        req_concept = "Skill_" + req_skill.replace("-", "_").title().replace(" ", "_")
                        backfill_cypher = (
                            "MATCH (s:Wiki {n: $src}), (t:Wiki {n: $tgt}) "
                            "MERGE (s)-[:REQUIRES]->(t)"
                        )
                        utils.query_wiki_graph(backfill_cypher, {"src": concept_name, "tgt": req_concept})
                    requires = [
                        "Skill_" + r.replace("-", "_").title().replace(" ", "_")
                        for r in _fs_requires
                    ]
                    logger.info(f"Backfilled REQUIRES edges from _metadata.json: {requires}")
            except Exception:
                pass  # Non-critical — projection continues without backfill

    describes = first_rel("HAS_DESCRIBES_COMPONENT") or first_rel("DESCRIBES_COMPONENT")
    starsystem = first_rel("HAS_STARSYSTEM")

    # Extract native Claude Code skill fields from typed relationships
    # These were stored by skillmanager._sync_skill_to_carton()
    context_mode = first_rel("HAS_CONTEXT_MODE")
    if context_mode and context_mode.startswith("Skill_Context_"):
        context_mode = context_mode.replace("Skill_Context_", "").lower()
    else:
        context_mode = None

    agent_type = first_rel("SPAWNS_AGENT")
    if agent_type and agent_type.startswith("Agent_Type_"):
        agent_type = agent_type.replace("Agent_Type_", "").replace("_", " ").strip()
    else:
        agent_type = None

    # Known Claude Code hook types — CartON title-cases them (PreToolUse → Pretooluse)
    _HOOK_CASING = {
        "pretooluse": "PreToolUse", "posttooluse": "PostToolUse",
        "notification": "Notification", "stop": "Stop",
        "userpromptsubmit": "UserPromptSubmit",
    }
    hook_targets = rel_targets("HAS_HOOK")
    hooks_list = []
    for ht in hook_targets:
        hook_name = ht.replace("Hook_Type_", "") if ht.startswith("Hook_Type_") else ht
        hook_name = _HOOK_CASING.get(hook_name.lower(), hook_name)
        hooks_list.append(hook_name)

    flag_targets = rel_targets("HAS_FLAG")
    not_user_invocable = "Skill_Flag_Not_User_Invocable" in flag_targets
    model_invocation_disabled = "Skill_Flag_Disable_Model_Invocation" in flag_targets

    argument_hint = first_rel("HAS_ARGUMENT_HINT")
    if argument_hint and argument_hint.startswith("Argument_Hint_"):
        argument_hint = f"[{argument_hint.replace('Argument_Hint_', '')}]"
    else:
        argument_hint = None

    # Derive skill name from concept name
    skill_name = concept_name.lower().replace("_", "-")
    for suffix in ["-feb8", "-feb7", "-feb6", "-feb5", "-feb4", "-feb2026"]:
        if skill_name.endswith(suffix):
            skill_name = skill_name[:len(skill_name) - len(suffix)]
            break

    # Determine output directory
    if substrate.output_dir:
        skill_dir = Path(substrate.output_dir)
    else:
        heaven_dir = os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")
        skill_dir = Path(heaven_dir) / "skills" / skill_name

    skill_dir.mkdir(parents=True, exist_ok=True)

    # Build SKILL.md with YAML frontmatter (yaml.dump for correctness + all fields)
    what_line = what_text or description[:100].replace("\n", " ")
    when_line = when_text or "Context matches domain"

    frontmatter = {
        "name": skill_name,
        "description": f"WHAT: {what_line}\nWHEN: {when_line}",
    }

    # Native Claude Code fields (only include when present)
    if context_mode:
        frontmatter["context"] = context_mode
    if agent_type:
        frontmatter["agent"] = agent_type
    if hooks_list:
        frontmatter["hooks"] = {h: {} for h in hooks_list}
    if not_user_invocable:
        frontmatter["user-invocable"] = False
    if model_invocation_disabled:
        frontmatter["disable-model-invocation"] = True
    if argument_hint:
        frontmatter["argument-hint"] = argument_hint

    skill_md = "---\n" + yaml.dump(frontmatter, default_flow_style=False, sort_keys=False) + "---\n\n" + description + "\n"
    # Final wiki-link strip — catches ALL links regardless of source (linker, DualSubstrate, etc.)
    skill_md = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', skill_md)
    (skill_dir / "SKILL.md").write_text(skill_md)

    # Build _metadata.json
    metadata = {
        "domain": domain,
        "subdomain": subdomain,
        "category": category,
        "what": what_text,
        "when": when_text,
        "produces": produces,
        "requires": requires,
        "describes_component": describes,
        "starsystem": starsystem,
    }
    metadata = {k: v for k, v in metadata.items() if v is not None}
    (skill_dir / "_metadata.json").write_text(json.dumps(metadata, indent=2))

    # Build reference.md and create child files routed by IS_A type
    children = rel_targets("HAS_PART")

    # Query each child's description and IS_A types in one shot
    child_entries = []  # list of (name, desc, dir_name, filename)
    for child_name in children:
        child_result = utils.query_wiki_graph(
            "MATCH (c:Wiki {n: $name}) "
            "OPTIONAL MATCH (c)-[:IS_A]->(t:Wiki) "
            "RETURN c.d as description, collect(t.n) as types",
            {"name": child_name}
        )
        if not (child_result.get("success") and child_result.get("data")):
            continue
        row = child_result["data"][0]
        raw_desc = row.get("description", "")
        # Strip wiki-links from child content
        child_desc = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', raw_desc)
        types = [t.lower() for t in row.get("types", [])]

        # Route by IS_A type → directory + extension
        if any("script" in t for t in types):
            dir_name = "scripts"
            base = child_name.lower().replace("_", "-")
            # Detect language from shebang or default to .py
            ext = ".py" if child_desc.lstrip().startswith("#!") or "import " in child_desc else ".sh"
            filename = base + ext
        elif any("template" in t for t in types):
            dir_name = "templates"
            filename = child_name.lower().replace("_", "-") + ".md"
        else:
            dir_name = "resources"
            filename = child_name.lower().replace("_", "-") + ".md"

        child_entries.append((child_name, child_desc, dir_name, filename))

    # Write reference.md
    ref_lines = [f"# {skill_name} Reference", ""]
    if child_entries:
        # Group by directory
        for section in ["scripts", "resources", "templates"]:
            items = [(n, fn) for n, _, d, fn in child_entries if d == section]
            if items:
                ref_lines.append(f"## {section.title()}")
                ref_lines.append("")
                for name, fn in items:
                    ref_lines.append(f"- **{name}**: See `{section}/{fn}`")
                ref_lines.append("")
    else:
        ref_lines.append("No additional resources.")
    (skill_dir / "reference.md").write_text("\n".join(ref_lines))

    # Create directories and write child files
    for child_name, child_desc, dir_name, filename in child_entries:
        target_dir = skill_dir / dir_name
        target_dir.mkdir(exist_ok=True)
        if dir_name == "scripts":
            # Scripts: write content verbatim (it's code)
            (target_dir / filename).write_text(child_desc)
        else:
            # Resources/templates: add header
            (target_dir / filename).write_text(f"# {child_name}\n\n{child_desc}")

    # Write to ChromaDB skillgraphs collection
    chromadb_msg = ""
    if substrate.write_to_chromadb:
        try:
            # Write skillgraphs via the chroma daemon (ZERO chroma import here). NOTE: this UNIFIES the
            # store — this used to write to a SEPARATE PersistentClient 'skill_chroma' dir while
            # carton_utils read the ':8101 chroma_db' skillgraphs collection (a split-brain). Both now use
            # the daemon's single ':8101' skillgraphs collection, so writes here are read by enforce_ontology.
            from carton_mcp.chroma_client import chroma_coll_upsert

            # Skillgraph naming convention: Skillgraph_{Title_Case}
            sg_name = "Skillgraph_" + concept_name.replace("-", "_")
            # Ontological sentence — typed fields, NOT bag-of-words
            parts = [f"[SKILLGRAPH:{skill_name}]"]
            parts.append(f"is_a:Skill")
            parts.append(f"has_domain:{domain}")
            if subdomain:
                parts.append(f"has_subdomain:{subdomain}")
            if category:
                parts.append(f"has_category:{category}")
            if what_text:
                parts.append(f"what:{what_text}")
            if when_text:
                parts.append(f"when:{when_text}")
            if produces:
                parts.append(f"produces:{produces}")
            if requires:
                parts.append(f"requires:[{','.join(requires)}]")
            if context_mode:
                parts.append(f"context:{context_mode}")
            if agent_type:
                parts.append(f"agent:{agent_type}")
            if hooks_list:
                parts.append(f"hooks:[{','.join(hooks_list)}]")
            if not_user_invocable:
                parts.append("user_invocable:false")
            if model_invocation_disabled:
                parts.append("disable_model_invocation:true")
            parts.append("[/SKILLGRAPH]")
            doc_text = " ".join(parts)

            meta = {
                "name": sg_name,
                "skill": skill_name,
                "domain": domain,
                "category": category,
                "concept_name": concept_name,
                "type": "skillgraph",
            }
            if produces:
                meta["produces"] = produces
            if subdomain:
                meta["subdomain"] = subdomain
            if context_mode:
                meta["context"] = context_mode
            if agent_type:
                meta["agent"] = agent_type

            chroma_coll_upsert("skillgraphs", ids=[f"skillgraph:{skill_name}"],
                               documents=[doc_text], metadatas=[meta])
            chromadb_msg = " + ChromaDB skillgraph written"
        except Exception as e:
            chromadb_msg = f" (ChromaDB failed: {e})"

    # Phase 3: Project skill to starsystem .claude/skills/ directory
    # Walk: Skill → HAS_DESCRIBES_COMPONENT → GIINT_Component → part_of chain → Starsystem_
    starsystem_msg = ""
    starsystem_paths = set()

    def _resolve_starsystem_path(starsystem_name: str) -> str | None:
        """Resolve starsystem concept name to filesystem path.

        Starsystem names are created by starlog init_project:
            path.strip('/').replace('/', '_').replace('-', '_').title()
        So /home/GOD/carton_mcp → Starsystem_Home_God_Carton_Mcp

        We reverse this by scanning known parent dirs for matching subdirectories.
        """
        slug = starsystem_name
        if slug.startswith("Starsystem_"):
            slug = slug[len("Starsystem_"):]

        # Known parent directories where starsystems live
        parent_dirs = ["/home/GOD", "/tmp", "/home/GOD/gnosys-plugin-v2"]

        for parent in parent_dirs:
            parent_slug = parent.strip("/").replace("/", "_").replace("-", "_").title()
            if not slug.startswith(parent_slug):
                continue
            remainder = slug[len(parent_slug):]
            if remainder.startswith("_"):
                remainder = remainder[1:]
            if not remainder:
                continue

            # Try to find matching subdir — check with underscores, hyphens, lowercase
            # Original transform: .replace("-", "_").title()
            # So "carton_mcp" → "Carton_Mcp", "sdna-repo" → "Sdna_Repo"
            lower_remainder = remainder.lower()
            candidates = [
                lower_remainder,                              # carton_mcp
                lower_remainder.replace("_", "-"),            # carton-mcp
                lower_remainder.replace("_", "-", 1),        # try partial
            ]
            for candidate in candidates:
                full_path = os.path.join(parent, candidate)
                if os.path.isdir(full_path):
                    return full_path

            # Also try subdirectories of parent for partial matches
            if os.path.isdir(parent):
                for entry in os.listdir(parent):
                    entry_path = os.path.join(parent, entry)
                    if not os.path.isdir(entry_path):
                        continue
                    entry_slug = entry.replace("-", "_").title()
                    if entry_slug == remainder or entry_slug == remainder.replace("_", ""):
                        return entry_path

        return None

    # Strategy 1: Walk from HAS_DESCRIBES_COMPONENT up GIINT hierarchy
    if describes:
        try:
            walk_query = """
            MATCH (start:Wiki {n: $start_name})
            MATCH path = (start)-[:PART_OF*1..6]->(ancestor:Wiki)
            WHERE ancestor.n STARTS WITH 'Starsystem_'
            RETURN ancestor.n as starsystem_name, ancestor.d as starsystem_desc
            LIMIT 1
            """
            walk_result = utils.query_wiki_graph(walk_query, {"start_name": describes})
            if walk_result.get("success") and walk_result.get("data"):
                ss_name = walk_result["data"][0].get("starsystem_name", "")
                ss_path = _resolve_starsystem_path(ss_name)
                if ss_path:
                    starsystem_paths.add(ss_path)
        except Exception:
            logger.exception("Failed to walk GIINT hierarchy for starsystem projection")

    # Strategy 2: Direct HAS_STARSYSTEM relationship
    if starsystem:
        try:
            ss_query = "MATCH (s:Wiki {n: $name}) RETURN s.d as desc"
            ss_path = _resolve_starsystem_path(starsystem)
            if ss_path:
                starsystem_paths.add(ss_path)
        except Exception:
            logger.exception("Failed to resolve HAS_STARSYSTEM for projection")

    # Project to each found starsystem
    projected_to = []
    for ss_path in starsystem_paths:
        try:
            target_skills_dir = Path(ss_path) / ".claude" / "skills" / skill_name
            if target_skills_dir.exists():
                # Already projected — update in place
                shutil.copytree(str(skill_dir), str(target_skills_dir), dirs_exist_ok=True)
            else:
                target_skills_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(str(skill_dir), str(target_skills_dir))

            # Create accompanying rule
            rules_dir = Path(ss_path) / ".claude" / "rules"
            rules_dir.mkdir(parents=True, exist_ok=True)
            rule_content = f"# Use {skill_name}\n\nUse the `{skill_name}` skill when: {when_text or 'working in this domain'}.\n"
            (rules_dir / f"use-{skill_name}.md").write_text(rule_content)

            # NOTE: the GIINT hierarchy rule is NO LONGER projected here. SOMA owns
            # the rule (the gnosys_vault giint_project presence d-chains) and the
            # dchain_giint_project_render_hierarchy projection d-chain releases the
            # effect carton_mcp.substrate_projector:project_giint_hierarchy, which
            # the carton observation worker daemon dispatches. Skill projection no
            # longer side-branches into GIINT rendering. (2026-06-15 logic→d-chain.)

            projected_to.append(ss_path)
            logger.info("Projected skill '%s' to starsystem %s", skill_name, ss_path)
        except Exception:
            logger.exception("Failed to project skill '%s' to %s", skill_name, ss_path)

    if projected_to:
        starsystem_msg = f" + projected to {len(projected_to)} starsystem(s): {', '.join(projected_to)}"

    return f"Skill '{skill_name}' projected to {skill_dir}{chromadb_msg}{starsystem_msg}"


# Dispatch table
PROJECTORS = {
    "file": project_to_file,
    "discord": project_to_discord,
    "registry": project_to_registry,
    "env": project_to_env,
    "skill": project_to_skill,
    "rule": lambda substrate, concept_name, shared_connection=None: project_to_rule(substrate, concept_name, shared_connection),
}


# ============================================================================
# Rule Projection
# ============================================================================

def _resolve_starsystem_dir(starsystem_name: str) -> str | None:
    """Resolve a Starsystem_X concept name to its filesystem path.

    Mirrors the helper nested inside project_to_skill, exposed at module
    level so project_to_rule can use it without re-implementing.
    """
    slug = starsystem_name
    if slug.startswith("Starsystem_"):
        slug = slug[len("Starsystem_"):]

    parent_dirs = ["/home/GOD", "/tmp", "/home/GOD/gnosys-plugin-v2"]
    for parent in parent_dirs:
        parent_slug = parent.strip("/").replace("/", "_").replace("-", "_").title()
        if not slug.startswith(parent_slug):
            continue
        remainder = slug[len(parent_slug):]
        if remainder.startswith("_"):
            remainder = remainder[1:]
        if not remainder:
            continue

        lower_remainder = remainder.lower()
        candidates = [
            lower_remainder,
            lower_remainder.replace("_", "-"),
            lower_remainder.replace("_", "-", 1),
        ]
        for candidate in candidates:
            full_path = os.path.join(parent, candidate)
            if os.path.isdir(full_path):
                return full_path

        if os.path.isdir(parent):
            for entry in os.listdir(parent):
                entry_path = os.path.join(parent, entry)
                if not os.path.isdir(entry_path):
                    continue
                entry_slug = entry.replace("-", "_").title()
                if entry_slug == remainder or entry_slug == remainder.replace("_", ""):
                    return entry_path

    return None


def _rule_concept_to_filename(concept_name: str) -> str:
    """Convert Claude_Code_Rule_Persona_Equip -> persona-equip.md.

    Note: this is a fallback. The concept SHOULD provide has_name explicitly
    (matching the rules CLI arg shape). Filename derivation is only used when
    has_name is absent.
    """
    slug = concept_name
    if slug.startswith("Claude_Code_Rule_"):
        slug = slug[len("Claude_Code_Rule_"):]
    elif slug.startswith("Rule_"):
        slug = slug[len("Rule_"):]
    slug = slug.lower().replace("_", "-")
    return f"{slug}.md"


def _render_rule_file_content(has_content: str, has_paths: list | None) -> str:
    """Render the .md file body. If has_paths is set, prepend YAML frontmatter."""
    body = (has_content or "").rstrip() + "\n"
    if not has_paths:
        return body
    fm_lines = ["---", "paths:"]
    for p in has_paths:
        fm_lines.append(f'  - "{p}"')
    fm_lines.append("---")
    fm_lines.append("")
    return "\n".join(fm_lines) + "\n" + body


def project_to_rule(substrate: RuleSubstrate, concept_name: str, shared_connection=None) -> str:
    """Project a CartON Rule_ concept to a Claude Code .md rule file.

    Fetches the concept's description, has_content, has_scope, has_starsystem,
    and has_paths relationships from Neo4j. Resolves the target directory based
    on scope, computes the filename from the concept name, renders the file
    body (with optional frontmatter from has_paths), diffs against the existing
    file content, and writes only if different.

    Returns a status string describing the action taken: created, updated,
    unchanged, or skipped (with reason).
    """
    from carton_mcp.carton_utils import CartOnUtils

    utils = CartOnUtils(shared_connection=shared_connection)

    # Fetch concept + relationships
    cypher = """
    MATCH (c:Wiki) WHERE c.n = $name AND c.d IS NOT NULL
    OPTIONAL MATCH (c)-[r]->(related:Wiki)
    RETURN c.n as name, c.d as description,
           collect({type: type(r), target: related.n}) as relationships
    """
    result = utils.query_wiki_graph(cypher, {"name": concept_name})
    if not result.get("success") or not result.get("data"):
        return f"skipped: concept {concept_name} not found"

    data = result["data"][0]
    rels = data.get("relationships", [])

    def rel_targets(rel_type):
        return [r["target"] for r in rels if r.get("type") == rel_type]

    def first_rel(rel_type):
        targets = rel_targets(rel_type)
        return targets[0] if targets else None

    # RULE CONTENT SOURCE: has_content points to ANOTHER concept whose description
    # IS the rule body text. OWL requires minCard(hasContent, 1) on Claude_Code_Rule.
    # If has_content is missing or its target has no description, we fall back to
    # the rule concept's own description (c.d). This fallback handles the case where
    # the agent put the rule body directly in desc= instead of creating a separate
    # content concept.
    # If you are looking for skill content: see project_to_skill() above — skills
    # use the concept's own description directly, NOT has_content.
    has_content_concept = first_rel("HAS_CONTENT")
    if has_content_concept:
        # has_content points to another concept whose description IS the rule body
        content_q = utils.query_wiki_graph(
            "MATCH (c:Wiki {n: $name}) RETURN c.d as desc", {"name": has_content_concept}
        )
        if content_q.get("success") and content_q.get("data"):
            has_content = content_q["data"][0].get("desc", "") or ""
        else:
            has_content = ""
    else:
        has_content = ""

    # If no has_content, fall back to the concept's own description
    # (handles the case where the agent put the rule body directly in desc=)
    if not has_content:
        has_content = data.get("description", "") or ""

    if not has_content.strip():
        return f"skipped: {concept_name} has no body content"

    # (FIX, Isaac 2026-06-15) The "AUTO CREATED:" stub band-aid was REMOVED here.
    # A claude_code_rule whose has_content is a _Unnamed placeholder is now caught
    # AT THE SOURCE by SOMA: has_content -> _Unnamed no longer satisfies the code
    # arg (soma_partials missing_code_restriction), so the rule is soup + raises
    # failure_error (dchain_rule_no_unnamed_value), and dchain_rule_project is gated
    # on missing_slot so it never surfaces a release_effect — the daemon never
    # dispatches a _Unnamed rule to this projector. The downstream string-check was
    # treating the symptom; the gate is now in the logic program where it belongs.

    # Resolve scope
    scope_target = first_rel("HAS_SCOPE")
    if scope_target:
        scope = scope_target.lower().replace("scope_", "").replace("rule_scope_", "")
    else:
        scope = "global"  # default
    if scope not in ("global", "project"):
        scope = "global"

    # Resolve target directory
    if substrate.output_dir_override:
        target_dir = substrate.output_dir_override
    elif scope == "global":
        target_dir = os.path.expanduser("~/.claude/rules")
    else:
        ss_name = first_rel("HAS_STARSYSTEM")
        if not ss_name:
            return f"skipped: {concept_name} has scope=project but no has_starsystem"
        ss_path = _resolve_starsystem_dir(ss_name)
        if not ss_path:
            return f"skipped: could not resolve starsystem path for {ss_name}"
        target_dir = os.path.join(ss_path, ".claude", "rules")

    # Resolve has_paths if any
    has_paths = rel_targets("HAS_PATHS") or rel_targets("HAS_PATH")
    has_paths = [p for p in has_paths if p] or None
    # If has_paths targets are concept names like Path_Src_Foo_Py, strip prefix
    if has_paths:
        cleaned = []
        for p in has_paths:
            if p.startswith("Path_"):
                cleaned.append(p[len("Path_"):].replace("_", "/"))
            else:
                cleaned.append(p)
        has_paths = cleaned

    # Compute filename
    filename = _rule_concept_to_filename(concept_name)

    # FIX-5: write via the SINGLE rule writer (paia_builder.rule_cli.write_rule) so the
    # SOMA rule projection and the user-facing `rules` CLI produce byte-identical files
    # (one writer, Isaac 2026-06-15 "the rule projector calls the CLI inside").
    # write_rule renders content + frontmatter via render_rule_body, which is kept
    # byte-identical to the legacy _render_rule_file_content here, and diffs (unchanged
    # if no change). target_dir overrides the scope dir (this projector resolved a
    # possibly-starsystem dir already); name is the filename stem.
    from paia_builder.rule_cli import ClaudeCodeRule, write_rule
    rule = ClaudeCodeRule(
        name=filename[:-3] if filename.endswith(".md") else filename,
        scope=scope,
        content=has_content,
        paths=has_paths,
    )
    try:
        result = write_rule(rule, target_dir=target_dir)
    except Exception as e:
        return f"failed: cannot write rule {concept_name}: {e}"
    logger.info("Rule projected: %s -> %s/%s (%s)", concept_name, target_dir, filename, result.split(":", 1)[0])
    return result


# ── release_effect dispatch entrypoints (FIX-5: projection-as-d-chain) ──────────
# These are NOT new projectors — they are thin single-argument shims so the SOMA
# projection d-chains can dispatch the CANONICAL rich projectors above through the
# universal release_effect bridge (soma_prolog/util_deps/dchain.py calls a handler
# as ``fn(concept_name)`` — one positional). The d-chain surfaces a plain fact
# ``release_effect('carton_mcp.substrate_projector:project_skill', C)``; the bridge
# imports this module and calls the shim, which constructs the default substrate
# and calls the existing projector. shared_connection defaults to None so the
# projector opens its own Neo4j connection (the dispatch runs inside the SOMA
# daemon, not the carton worker, so there is no shared connection to pass). The
# projectors are idempotent (they diff against the existing file / Neo4j state), so
# re-firing on an update event is safe. Update DETECTION is the carton observation
# daemon's job (it re-submits changed concepts) — the d-chain just fires.
def project_skill(concept_name: str, shared_connection=None) -> str:
    """release_effect entrypoint for dchain_skill_project → rich project_to_skill.

    Dispatched by the carton observation worker daemon (the RELEASE-LAW outer
    layer) which passes its shared neo4j connection so the projector reads the
    concept off the same connection it just wrote it on (FIX-5 step 3)."""
    return project_to_skill(SkillSubstrate(), concept_name, shared_connection=shared_connection)


def project_rule(concept_name: str, shared_connection=None) -> str:
    """release_effect entrypoint for dchain_rule_project → rich project_to_rule.

    Dispatched by the carton observation worker daemon (the RELEASE-LAW outer
    layer) which passes its shared neo4j connection (FIX-5 step 3)."""
    return project_to_rule(RuleSubstrate(), concept_name, shared_connection=shared_connection)


def project_giint_hierarchy(concept_name: str, shared_connection=None) -> str:
    """release_effect entrypoint for dchain_giint_project_render_hierarchy.

    The GIINT-hierarchy RULE — what a project's structure IS — lives in SOMA as
    the giint_project presence d-chains (gnosys_vault.giint). This is only the
    projection EFFECT they release: when a giint_project is CODE-complete, render
    the starsystem's full Project→Feature→Component tree into its
    .claude/rules/giint-hierarchy.md. It REPLACES the old skill-projection
    side-branch (project_to_skill used to call _project_giint_hierarchy_rule
    inline); SOMA now owns the rule and the daemon dispatches this effect.

    concept_name = the firing giint_project node (c.name). It is the TRIGGER; the
    render covers ALL projects under the same starsystem (diff-write makes
    sibling-project fires converge on identical content — no clobbering). The real
    filesystem ss_path is recovered from the project node's description
    ("GIINT Project: <id>. Location: <dir>." — carton_sync.py sets it; HAS_PATH is
    title-normalized + lossy so it cannot give the real path). No-ops gracefully
    when ss_path is missing or not on disk (many graph projects are stale/test)."""
    from pathlib import Path
    from carton_mcp.carton_utils import CartOnUtils

    utils = CartOnUtils(shared_connection=shared_connection)
    desc_res = utils.query_wiki_graph(
        "MATCH (p:Wiki {n: $name}) RETURN p.d AS descr", {"name": concept_name}
    )
    if not desc_res.get("success") or not desc_res.get("data"):
        return f"giint-hierarchy skipped: project '{concept_name}' not found"
    descr = desc_res["data"][0].get("descr") or ""
    # Raw path survives ONLY in n.d ("...Location: <dir>."). First line, before any
    # ⟐ provenance separator; the trailing '.' is the carton_sync delimiter.
    m = re.search(r"Location:\s*(.+?)\.\s*$", descr, re.M)
    if not m:
        return f"giint-hierarchy skipped: no Location in '{concept_name}' description"
    ss_path = m.group(1).strip()
    if not ss_path or not Path(ss_path).is_dir():
        return f"giint-hierarchy skipped: ss_path '{ss_path}' not on disk"
    rules_dir = Path(ss_path) / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    status = _project_giint_hierarchy_rule(utils, ss_path, rules_dir) or "no-hierarchy"
    return f"giint-hierarchy {status} for {concept_name} → {rules_dir / 'giint-hierarchy.md'}"


# GIINT level prefixes (case-insensitive), title-cased as carton stores them.
# Mirrors automation/dragonbones/dragonbones/compiler.py GIINT_PREFIXES — the
# registry-write logic this handler ports out of dragonbones.
_GIINT_REGISTRY_PREFIXES = {
    "giint_project_": "project",
    "giint_feature_": "feature",
    "giint_component_": "component",
    "giint_deliverable_": "deliverable",
    "giint_task_": "task",
}


def _strip_giint_level(name: str):
    """Strip a GIINT level prefix (case-insensitive), return (level, stripped) or (None, name)."""
    name_lower = name.lower()
    for prefix, level in _GIINT_REGISTRY_PREFIXES.items():
        if name_lower.startswith(prefix):
            return level, name[len(prefix):]
    return None, name


def _walk_giint_part_of_chain(utils, concept_name: str) -> list:
    """Walk PART_OF from a GIINT concept up to its GIINT_Project_, reading neo4j.

    Returns the chain TOP-DOWN: [Giint_Project_X, Giint_Feature_Y, ..., concept].
    Mirrors automation/dragonbones/dragonbones/compiler.py:_walk_hierarchy, but reads
    every parent from the graph (the handler runs in the carton worker, not the
    in-memory dragonbones batch). At each hop it follows the FIRST PART_OF target
    that is itself a GIINT_ level concept, stopping at (and including) the project.
    """
    chain = [concept_name]
    current = concept_name
    seen = {concept_name}

    for _ in range(5):  # Task→Deliverable→Component→Feature→Project (max 5 levels)
        if current.lower().startswith("giint_project_"):
            break
        res = utils.query_wiki_graph(
            "MATCH (c:Wiki {n: $name})-[:PART_OF]->(p:Wiki) "
            "WHERE toLower(p.n) STARTS WITH 'giint_' "
            "RETURN p.n AS parent",
            {"name": current},
        )
        if not res.get("success") or not res.get("data"):
            break
        # Prefer the next-level-up GIINT parent; take the first GIINT_ parent found.
        parent = None
        for row in res["data"]:
            cand = row.get("parent")
            if cand and _strip_giint_level(cand)[0] is not None:
                parent = cand
                break
        if not parent or parent in seen:
            break
        seen.add(parent)
        chain.append(parent)
        current = parent
        if parent.lower().startswith("giint_project_"):
            break

    chain.reverse()  # top-down: Project > Feature > Component > Deliverable > Task
    return chain


def project_giint_registry(concept_name: str, shared_connection=None) -> str:
    """release_effect entrypoint for the giint_* registry-write d-chains.

    PORTS the GIINT registry-write that dragonbones compiler.py did inline
    (_walk_hierarchy + _sync_to_giint_registry) into a SOMA effect d-chain handler:
    when a GIINT-typed concept is added (its add_concept POSTs to SOMA, the per-level
    registry d-chain fires), this writes the matching node into the GIINT JSON
    registry via llm_intelligence.projects.{create_project, add_feature_to_project,
    add_component_to_feature, add_deliverable_to_component, add_task_to_deliverable}.

    concept_name = the firing GIINT concept node (c.name, Title_Case). The handler
    walks its PART_OF chain up to the GIINT_Project_, derives the
    project/feature/component/deliverable/task params (stripping GIINT prefixes the
    same case-insensitive way compiler.py does), resolves the project's filesystem
    dir from the project node's description ("...Location: <dir>." — carton_sync.py
    sets it), and calls the registry function matching THIS concept's own level.

    Best-effort / never-raises (logs + returns on any error), mirroring the other
    projectors. The registry functions are idempotent at the data level (a re-add of
    an existing project/feature/... returns an "already exists" error which is logged
    and ignored), so firing on create AND update is safe — the same idempotency
    pattern as project_giint_hierarchy."""
    from carton_mcp.carton_utils import CartOnUtils

    try:
        level, _ = _strip_giint_level(concept_name)
        if not level:
            return f"giint-registry skipped: {concept_name} is not a GIINT level concept"

        utils = CartOnUtils(shared_connection=shared_connection)

        # Walk PART_OF up to the project, build {level: stripped_name} params.
        chain = _walk_giint_part_of_chain(utils, concept_name)
        params = {}
        for name in chain:
            lvl, stripped = _strip_giint_level(name)
            if lvl:
                params[lvl] = stripped

        if "project" not in params:
            return f"giint-registry skipped: {concept_name} chain has no GIINT_Project_ ({chain})"

        # Lazy import — a missing llm_intelligence must not break the dispatch.
        try:
            from llm_intelligence.projects import (
                create_project, add_feature_to_project, add_component_to_feature,
                add_deliverable_to_component, add_task_to_deliverable,
            )
        except ImportError as e:
            return f"giint-registry skipped: llm_intelligence unavailable ({e})"

        project_id = params["project"]

        if level == "project":
            # Resolve the real filesystem dir from the project node's description
            # ("...Location: <dir>." — carton_sync.py sets it; HAS_PATH is lossy).
            project_dir = ""
            desc_res = utils.query_wiki_graph(
                "MATCH (p:Wiki {n: $name}) RETURN p.d AS descr", {"name": concept_name}
            )
            if desc_res.get("success") and desc_res.get("data"):
                descr = desc_res["data"][0].get("descr") or ""
                m = re.search(r"Location:\s*(.+?)\.\s*$", descr, re.M)
                if m:
                    project_dir = m.group(1).strip()
            result = create_project(project_id=project_id, project_dir=project_dir or "/tmp")
        elif level == "feature" and "feature" in params:
            result = add_feature_to_project(project_id, params["feature"])
        elif level == "component" and "feature" in params and "component" in params:
            result = add_component_to_feature(project_id, params["feature"], params["component"])
        elif level == "deliverable" and all(k in params for k in ("feature", "component", "deliverable")):
            result = add_deliverable_to_component(
                project_id, params["feature"], params["component"], params["deliverable"]
            )
        elif level == "task" and all(k in params for k in ("feature", "component", "deliverable", "task")):
            result = add_task_to_deliverable(
                project_id, params["feature"], params["component"], params["deliverable"],
                params["task"], assignee="AI-Only", agent_id="gnosys",
            )
        else:
            return f"giint-registry skipped: {concept_name} incomplete chain for level={level} ({params})"

        msg = result.get("message", result.get("error", "")) if isinstance(result, dict) else str(result)
        logger.info("GIINT registry write: %s (level=%s) → %s", concept_name, level, msg)
        return f"giint-registry {level} for {concept_name} → {msg}"
    except Exception as e:  # noqa: BLE001 — never raise out of a release_effect handler
        logger.warning("GIINT registry write failed for %s: %s", concept_name, e)
        return f"giint-registry error for {concept_name}: {type(e).__name__}: {e}"


def _step_spec_from_row(st: dict) -> dict:
    """Build ONE `create_sm_chain` step spec from a raw Traversal_Step property row (as read from
    neo4j by `project_state_machine`'s query): `{id, required_pattern, text, next, branch_to,
    branch_pattern, branch_weight}`.

    PURE (no I/O, no neo4j) — the onion-architecture core of the branching-vs-scalar-`next`
    decision `project_state_machine` needs (see its docstring's BRANCHING section for the full
    resolved-technical-question writeup; this function only implements the decision).

    If `branch_to` is a non-empty list, builds the NEW parallel-flat-list branches form: each
    `branches[i] = {"to": branch_to[i], "required_pattern": branch_pattern[i], "weight":
    branch_weight[i]}`, zipped by index. `branch_pattern`/`branch_weight` being absent entirely OR
    shorter than `branch_to` degrades each missing index to `None`/`1.0` respectively (never
    raises — logged via the module `logger`, matching this file's best-effort/never-raises
    projector contract).

    Otherwise (no `branch_to`) returns the step UNCHANGED in the OLD scalar-`next` shape — this
    is the regression-critical path: an SM authored only with `next`/`required_pattern` (every
    existing dragonbones-authored SM, since dragonbones cannot author `branch_to` yet) must
    produce the EXACT SAME step spec as before this function existed.
    """
    branch_to = st.get("branch_to")
    if isinstance(branch_to, list) and branch_to:
        branch_pattern = st.get("branch_pattern")
        branch_pattern = branch_pattern if isinstance(branch_pattern, list) else None
        branch_weight = st.get("branch_weight")
        branch_weight = branch_weight if isinstance(branch_weight, list) else None
        if branch_pattern is None or len(branch_pattern) < len(branch_to):
            logger.warning(
                "project_state_machine: step %s branch_pattern missing/shorter than branch_to "
                "(%d vs %d) — defaulting missing entries to None",
                st.get("id"), len(branch_pattern or []), len(branch_to))
        if branch_weight is None or len(branch_weight) < len(branch_to):
            logger.warning(
                "project_state_machine: step %s branch_weight missing/shorter than branch_to "
                "(%d vs %d) — defaulting missing entries to 1.0",
                st.get("id"), len(branch_weight or []), len(branch_to))
        branches = []
        for i, to in enumerate(branch_to):
            pat = branch_pattern[i] if branch_pattern is not None and i < len(branch_pattern) else None
            w = branch_weight[i] if branch_weight is not None and i < len(branch_weight) else 1.0
            branches.append({"to": to, "required_pattern": pat, "weight": w})
        return {"id": st.get("id"), "required_pattern": st.get("required_pattern"),
                "text": st.get("text"), "branches": branches}
    return {"id": st.get("id"), "required_pattern": st.get("required_pattern"),
            "text": st.get("text"), "next": st.get("next")}


def project_state_machine(concept_name: str, shared_connection=None) -> str:
    """release_effect entrypoint for the state_machine compile d-chain (STAGE A3).

    PORTS dragonbones compiler.py._create_state_machine (the State_Machine EC →
    create_sm_chain_live call, the 2-SM gating stack) into a SOMA effect d-chain
    handler: when a state_machine concept is added (its add_concept POSTs to SOMA, the
    state_machine d-chain fires), this builds the GATING Sm_Chain via the carton SM
    factory (create_sm_chain_live) — the standard 2-SM stack (auto show-SM order-0 +
    the declared gating-SM order-1) so it actually gates (the sm_chain_visit stack-size
    > 1 rule).

    The SM spec travels as GRAPH + PROPERTIES — NO JSON anywhere (Isaac 2026-06-22:
    "setting up a state machine must NOT require properties you cannot set with dragonbones;
    NEVER transport JSON thru n.d"). The property-notation keystone made this RACE-FREE: the
    🏷 properties ride the add_concept queue and the daemon applies set_concept_properties
    AFTER it MERGEs the node, in the SAME drain — so by the time this release handler runs,
    the SM node, its Traversal_Step children, and all their properties already landed.
      - PROPERTY `sm_gates` on the SM node = the concept whose retrieval this SM gates
        (default: this state_machine concept itself, mirroring _create_state_machine's default).
      - each gating STEP = a Traversal_Step concept PART_OF this SM, carrying its
        required_pattern / text / next (the OLD scalar form) OR branch_to / branch_pattern /
        branch_weight (the NEW branching form — see BRANCHING below) as its OWN properties.

    BRANCHING (step 3 of the SM-branching build, 2026-07-04): `carton_utils.set_concept_properties`
    (verified by reading `_validate_property_value` in carton_utils.py) REFUSES nested/dict
    property values — only flat scalars and flat lists of scalars are legal — so a step's
    `branches` (inherently a list of compound `{to, required_pattern, weight}` objects) cannot
    ride as ONE property. The resolved, in-constraint encoding is THREE PARALLEL FLAT LISTS on
    the same Traversal_Step node — `branch_to`/`branch_pattern`/`branch_weight`, zipped by index
    — read here (the query below) and turned back into the `branches` list `create_sm_chain`
    expects by `_step_spec_from_row`. A step with a single unconditional next-step still uses the
    OLD scalar `next` property (backward compat — dragonbones cannot author `branch_to` yet, so
    EVERY EXISTING dragonbones-authored SM lands here as scalar `next` and must produce the EXACT
    SAME graph as before this change — the regression-critical path `_step_spec_from_row` preserves).

    ALSO FIXED HERE — the step-list ORDERING: `create_sm_chain` (`knowledge/carton-mcp/sm_gate.py`,
    read in full before this change) MERGEs each step by name and wires branches from whatever
    `branches`/`next` each step declares, INDEPENDENT of the `steps` list's position — it never
    reads list order, only the step `id`s each branch/`next` references. So the PRIOR `next`-
    linked-list walk here (entry = the step nobody's `next` points at; walk `next` from there) was
    ONLY EVER cosmetic (ordering the return value for readability), and was structurally
    INCOMPATIBLE with branching (a step with 2+ branches has no single `next` to follow, so the
    walk could never reach it). Since order is genuinely inconsequential to `create_sm_chain`'s
    correctness, this handler now passes `raw_steps` straight through in whatever order the query
    returns them — simpler AND correct for a DAG.

    The handler reads them from neo4j and calls create_sm_chain_live EXACTLY as
    _create_state_machine did from the EC claims (only the input source moves: EC claims →
    concept properties + Traversal_Step graph; the call is unchanged). The Sm_Chain wrapper,
    the auto show-SM, and the SM_CHAIN_RUNS edge-order (the parts add_concept cannot set) are
    built by the factory.

    Best-effort / never-raises (logs + returns on any error), mirroring the other
    projectors. create_sm_chain is idempotent (MERGE-on-names), so firing on create AND
    update is safe — the same idempotency contract as project_giint_registry.
    """
    import json
    from carton_mcp.carton_utils import CartOnUtils

    try:
        utils = CartOnUtils(shared_connection=shared_connection)

        # Read the SM spec from the GRAPH + PROPERTIES (no JSON). RACE-FREE: the 🏷 properties
        # rode the add_concept queue and the daemon applied set_concept_properties AFTER the
        # node MERGE, in the same drain, so by now the SM node, its Traversal_Step children, and
        # all their properties have landed. `m.sm_gates` = the gated concept; each Traversal_Step
        # PART_OF the SM carries required_pattern / text / next (old scalar form) AND/OR
        # branch_to / branch_pattern / branch_weight (new parallel-flat-list branching form) as
        # its own properties — `_step_spec_from_row` decides which form wins per step.
        res = utils.query_wiki_graph(
            "MATCH (m:Wiki {n: $name}) "
            "OPTIONAL MATCH (s:Wiki)-[:PART_OF]->(m) WHERE (s)-[:IS_A]->(:Wiki {n: 'Traversal_Step'}) "
            "OPTIONAL MATCH (m)-[:HAS_DOMAIN]->(dom:Wiki) "
            "OPTIONAL MATCH (m)-[:HAS_SUBDOMAIN]->(sub:Wiki) "
            "OPTIONAL MATCH (m)-[:HAS_PERSONAL_DOMAIN]->(pd:Wiki) "
            "RETURN m.sm_gates AS gates, dom.n AS domain, sub.n AS subdomain, pd.n AS personal_domain, "
            "collect({id: s.n, required_pattern: s.required_pattern, text: s.text, next: s.next, "
            "branch_to: s.branch_to, branch_pattern: s.branch_pattern, branch_weight: s.branch_weight}"
            ") AS steps",
            {"name": concept_name},
        )
        gates, raw_steps, domain, subdomain, personal_domain = None, [], None, None, None
        if res.get("success") and res.get("data"):
            row = res["data"][0]
            gates = row.get("gates")
            domain = row.get("domain")
            subdomain = row.get("subdomain")
            personal_domain = row.get("personal_domain")
            raw_steps = [st for st in (row.get("steps") or []) if st and st.get("id")]

        if not (domain and subdomain and personal_domain):
            return (
                f"state-machine skipped: {concept_name} is missing has_domain/has_subdomain/"
                f"has_personal_domain (domain={domain!r} subdomain={subdomain!r} "
                f"personal_domain={personal_domain!r}) — create_sm_chain now REQUIRES these "
                f"(Isaac 2026-07-04). Add them as customs on the State_Machine concept's own "
                f"add_concept call, then re-save to re-fire this d-chain."
            )

        gated = gates or concept_name  # mirrors _create_state_machine's `gated` default

        # Build each step's spec — branches (new form) if `branch_to` is present, else the OLD
        # scalar `next` (regression-critical). No ordering pass: `create_sm_chain` does not need
        # step-list order (see the docstring above) — pass raw_steps through as returned.
        steps = [_step_spec_from_row(st) for st in raw_steps]

        if not steps:
            return (f"state-machine skipped: {concept_name} has no Traversal_Step children "
                    f"(nothing to gate yet)")

        # Build the standard 2-SM gating stack — IDENTICAL to compiler.py._create_state_machine:
        # order-0 auto show-SM (serves the content) + order-1 the declared gating-SM (the
        # concept_name), so the stack holds > 1 SM and sm_chain_visit GATES it.
        show_sm = {"name": f"{gated}_Show",
                   "steps": [{"id": f"{gated}_Show_Step", "required_pattern": None,
                              "text": "(serves the concept content)", "next": None}]}
        gating_sm = {"name": concept_name, "steps": steps}

        from carton_mcp.sm_gate import create_sm_chain_live
        result = create_sm_chain_live(gated, [show_sm, gating_sm],
                                       domain=domain, subdomain=subdomain,
                                       personal_domain=personal_domain)
        logger.info("State_Machine compiled: %s gates %s → chain=%s gated=%s",
                    concept_name, gated, result.get("sm_chain"), result.get("gated"))
        return (f"state-machine {concept_name}: gate on {gated} "
                f"chain={result.get('sm_chain')} sms={result.get('sms')} "
                f"gated={result.get('gated')}")
    except Exception as e:  # noqa: BLE001 — never raise out of a release_effect handler
        logger.warning("State_Machine compile failed for %s: %s", concept_name, e,
                       exc_info=True)
        return f"state-machine error for {concept_name}: {type(e).__name__}: {e}"


def flush_starlog_diary(concept_name: str, shared_connection=None) -> str:
    """release_effect entrypoint for the per-typed-EC starlog-diary d-chains (STAGE A4).

    PORTS dragonbones compiler.py._flush_to_starlog_diary (the per-concept Captain's-Log
    debug-diary write) into a SOMA effect d-chain handler, fired per typed EC. When a
    typed concept is added, this writes a DebugDiaryEntry to the concept's starlog
    project (detected from file paths in its description); maps is_a → entry_type the
    same way compiler.py did.

    Best-effort / never-raises. starlog_mcp is part of the intentionally-disconnected
    GNOSYS stack, so while it is unavailable this no-ops gracefully (ImportError caught)
    and becomes live on starlog reconnect — the same replace-now / effect-on-reconnect
    contract as project_giint_registry / project_state_machine. Cross-cutting by design:
    UNTYPED concepts have no vaulted type, hence no diary d-chain (goal-consistent —
    "d-chains for vaulted system types").
    """
    from carton_mcp.carton_utils import CartOnUtils

    try:
        utils = CartOnUtils(shared_connection=shared_connection)
        res = utils.query_wiki_graph(
            "MATCH (c:Wiki {n: $name}) OPTIONAL MATCH (c)-[:IS_A]->(t:Wiki) "
            "RETURN c.d AS descr, collect(t.n) AS isa",
            {"name": concept_name},
        )
        if not (res.get("success") and res.get("data")):
            return f"starlog-diary skipped: {concept_name} not found"
        row = res["data"][0]
        desc = (row.get("descr") or "")[:200]
        isa = row.get("isa") or []

        # Map is_a → entry_type (IDENTICAL to compiler.py._flush_to_starlog_diary).
        type_map = {
            "Bug": "bug", "Potential_Solution": "potential_solution",
            "Skill": "skill", "GIINT_Deliverable": "deliverable",
            "GIINT_Task": "task", "Design": "design",
            "Idea": "idea", "Inclusion_Map": "inclusion_map",
        }
        entry_type = "observation"
        for isa_type, etype in type_map.items():
            if isa_type in isa:
                entry_type = etype
                break

        # starlog_mcp is part of the disconnected GNOSYS stack — a missing import is a
        # graceful no-op (the diary becomes live on reconnect).
        try:
            from starlog_mcp.starlog import Starlog
            from starlog_mcp.models import DebugDiaryEntry
            from starlog_mcp.starlog_sessions import (
                detect_starsystems_for_entry, get_joint_starlog_name,
            )
        except ImportError as e:
            return f"starlog-diary skipped: starlog unavailable ({e})"

        # Route to the starlog project detected from file paths in the description
        # (compiler.py's multi-starsystem joint-starlog routing). No context → skip,
        # exactly as compiler.py `continue`d when no starsystem was detected.
        detected = detect_starsystems_for_entry(desc, None)
        if len(detected) > 1:
            project_name = get_joint_starlog_name(list(detected.keys()))
        elif detected:
            project_name = list(detected.keys())[0]
        else:
            return f"starlog-diary skipped: {concept_name} has no starsystem context"

        sl = Starlog()
        stardate = sl._generate_stardate()
        entry_content = (f"Captain's Log, stardate {stardate}: [{entry_type}] "
                         f"Dragonbones compiled {concept_name}. {desc}")
        entry = DebugDiaryEntry(
            content=entry_content, entry_type=entry_type, source="dragonbones",
            concept_ref=concept_name, bug_report=(entry_type == "bug"),
        )
        sl._save_debug_diary_entry(project_name, entry)
        logger.info("Starlog diary: %s [%s] → %s", concept_name, entry_type, project_name)
        return f"starlog-diary {entry_type} for {concept_name} → {project_name}"
    except Exception as e:  # noqa: BLE001 — never raise out of a release_effect handler
        logger.warning("Starlog diary failed for %s: %s", concept_name, e, exc_info=True)
        return f"starlog-diary error for {concept_name}: {type(e).__name__}: {e}"


def _build_template_content(concept_data: dict, concept_name: str) -> dict:
    """
    Build the metastack template content dict from concept data.

    Explicit concept-data keys (name, essence_paragraph, essence_sentence,
    relationships, taxonomy, source) always win. NON-RESERVED node properties
    (concept_data["props"], i.e. properties(c) from neo4j) fill only the keys
    not already present; reserved managed fields (RESERVED_PROPERTY_KEYS in
    carton_utils — n, d, t, c, linked, ...) are excluded entirely.
    """
    from carton_mcp.carton_utils import RESERVED_PROPERTY_KEYS

    # Parse description for taxonomy/source if present. A property-only node (created
    # via MERGE with no c.d) returns description=None — coerce to "" so the essence/
    # taxonomy parsing below never hits a NoneType.
    description = concept_data.get("description") or ""

    # Extract taxonomy and source from description if formatted
    taxonomy = None
    source = None
    essence = description

    if "**Taxonomy:**" in description:
        parts = description.split("**Taxonomy:**")
        essence = parts[0].strip()
        meta_part = parts[1]
        if "**Source:**" in meta_part:
            tax_source = meta_part.split("**Source:**")
            taxonomy = tax_source[0].strip()
            source = tax_source[1].strip()
        else:
            taxonomy = meta_part.strip()

    # Build relationships list for template
    relationships = []
    for rel in concept_data.get("relationships", []):
        if rel.get("type") and rel.get("target"):
            relationships.append({"type": rel["type"], "related": rel["target"]})

    # Split essence into paragraph and sentence
    essence_lines = essence.split("\n\n")
    essence_paragraph = essence_lines[0] if essence_lines else essence
    essence_sentence = essence_lines[1] if len(essence_lines) > 1 else essence_paragraph[:200]

    # Build template content
    template_content = {
        "name": concept_data.get("name", concept_name),
        "essence_paragraph": essence_paragraph,
        "essence_sentence": essence_sentence,
        "relationships": relationships if relationships else None,
    }

    if taxonomy:
        template_content["taxonomy"] = taxonomy
    if source:
        template_content["source"] = source

    # Merge non-reserved node properties: they fill keys not already present;
    # the explicit concept-data keys above always win.
    node_props = concept_data.get("props") or {}
    for prop_key, prop_value in node_props.items():
        if prop_key in RESERVED_PROPERTY_KEYS or prop_key in template_content:
            continue
        template_content[prop_key] = prop_value

    return template_content


def render_through_template(concept_name: str, template_name: str) -> str:
    """
    Render concept through a metastack template.

    Args:
        concept_name: Carton concept name
        template_name: Registered metastack template name (e.g., 'reference_document')

    Returns:
        Rendered content from template
    """
    from carton_mcp.carton_utils import CartOnUtils

    utils = CartOnUtils()

    # Get full concept data (incl. node properties for the template merge)
    cypher_query = """
    MATCH (c:Wiki) WHERE c.n = $concept_name AND c.d IS NOT NULL
    OPTIONAL MATCH (c)-[r]->(related:Wiki)
    RETURN c.n as name, c.d as description,
           properties(c) as props,
           collect({type: type(r), target: related.n}) as relationships
    """
    result = utils.query_wiki_graph(cypher_query, {"concept_name": concept_name})

    if not result.get("success") or not result.get("data"):
        raise ValueError(f"Concept '{concept_name}' not found")

    concept_data = result["data"][0]

    # Build template content from concept data + non-reserved node properties
    template_content = _build_template_content(concept_data, concept_name)

    # Call metastack to render
    try:
        # PARALLEL: uses heaven_base.registry — should migrate to CartON/YOUKNOW
        from heaven_base.registry import RegistryService

        registry_dir = os.getenv("HEAVEN_DATA_DIR")
        if not registry_dir:
            raise RuntimeError("HEAVEN_DATA_DIR not set")

        registry = RegistryService(registry_dir)
        meta_info = registry.get("metastacks", template_name)

        if not meta_info:
            raise ValueError(f"Template '{template_name}' not found in registry")

        class_path = meta_info.get("class_path")
        defaults = meta_info.get("defaults", {})

        # Import and instantiate template class
        import sys
        templates_dir = os.path.join(registry_dir, "metastack_templates")
        if templates_dir not in sys.path:
            sys.path.insert(0, templates_dir)

        from importlib import import_module
        module_name, class_name = class_path.rsplit(".", 1)
        module = import_module(module_name)
        template_class = getattr(module, class_name)

        # Merge defaults with content
        merged = {**defaults, **template_content}

        # Instantiate and render
        instance = template_class(**merged)
        return instance.render()

    except ImportError as e:
        raise RuntimeError(f"Failed to import template: {e}")


def hydrate_template_content(
    concept_name: str,
    edge_type: str | None = None,
    children_key: str = "children",
    shared_connection=None,
) -> dict:
    """Build a metastack template content dict for a concept, optionally hydrating
    its children one level deep.

    The parent's own scalar properties come from `_build_template_content` (reused —
    NOT re-implemented), so taxonomy/source/essence/relationships + non-reserved node
    properties all merge the same way. If `edge_type` is given, every child reached by
    that edge (e.g. HAS_UNIT) is hydrated the SAME way and collected, in graph order,
    as a list of content dicts under `children_key` (e.g. 'units').

    One level of children is sufficient for the publish-manifest render (registry ->
    HAS_UNIT -> units); there is intentionally no deeper recursion (YAGNI).

    Args:
        concept_name: the parent concept whose content dict to build.
        edge_type: relationship type to follow to children (None = no children).
        children_key: key under which to place the hydrated children list.
        shared_connection: optional KnowledgeGraphBuilder (the MCP passes its _neo4j_conn).

    Returns:
        the parent's template content dict, with `children_key` -> [child dicts] when
        `edge_type` is set (the key is omitted when there are no children).
    """
    from carton_mcp.carton_utils import CartOnUtils

    utils = CartOnUtils(shared_connection=shared_connection)

    cypher = """
    MATCH (c:Wiki) WHERE c.n = $name
    OPTIONAL MATCH (c)-[r]->(related:Wiki)
    RETURN c.n as name, c.d as description,
           properties(c) as props,
           collect({type: type(r), target: related.n}) as relationships
    """
    result = utils.query_wiki_graph(cypher, {"name": concept_name})
    if not result.get("success") or not result.get("data"):
        raise ValueError(f"Concept '{concept_name}' not found")

    row = result["data"][0]
    content = _build_template_content(row, concept_name)

    # _build_template_content sets content["name"] = the CONCEPT name, which shadows a
    # node `name` PROPERTY (a property-node carries its own data name, e.g. a unit's
    # "doc-mirror" vs concept "Publishing_Unit_Doc_Mirror"). When a non-reserved `name`
    # property exists, it IS the data identity — let it win so the template reads it.
    node_props = row.get("props") or {}
    if node_props.get("name") is not None:
        content["name"] = node_props["name"]

    if edge_type:
        # Collect children by the requested edge. Order by a child `order` property
        # when present (preserves an authored sequence, e.g. the manifest's units
        # array), falling back to concept name so the output is always deterministic.
        child_cypher = """
        MATCH (parent:Wiki {n: $name})-[r]->(child:Wiki)
        WHERE type(r) = $edge_type
        RETURN child.n as name
        ORDER BY coalesce(child.`order`, 2147483647), child.n
        """
        child_result = utils.query_wiki_graph(
            child_cypher, {"name": concept_name, "edge_type": edge_type}
        )
        children = []
        if child_result.get("success") and child_result.get("data"):
            for row in child_result["data"]:
                child_name = row.get("name")
                if not child_name:
                    continue
                # Recurse exactly ONE level: hydrate each child WITHOUT following
                # further edges (no grandchildren).
                children.append(
                    hydrate_template_content(
                        child_name, edge_type=None, shared_connection=shared_connection
                    )
                )
        if children:
            content[children_key] = children

    return content


class PublishManifest(RenderablePiece):
    """RenderablePiece that emits the scalable-publishing publish-manifest.json
    structure from hydrated CartON content.

    Input shape (produced by `hydrate_template_content(registry, edge_type='HAS_UNIT',
    children_key='units')`): a dict carrying a `units` list, where each unit dict has the
    flat publishing fields stored as node properties (name, subdir, public_repo, pypi,
    readme_description, readme_links [json string], readme_badges [json string]). The
    render() reconstructs the nested `readme` object and serialises stable-ordered JSON
    matching publish-manifest.json.
    """

    units: List[dict] = Field(default_factory=list, description="Hydrated unit content dicts")
    manifest_comment: str | None = Field(
        default=None, description="Optional _comment string preserved at the top of the manifest"
    )

    @staticmethod
    def _unit_to_manifest(unit: dict) -> dict:
        """Reconstruct one manifest unit (with nested readme) from a flat hydrated dict."""
        def _loads(value, default):
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except (ValueError, TypeError):
                    return default
            return value if value is not None else default

        out = {
            "name": unit.get("name"),
            "subdir": unit.get("subdir"),
            "public_repo": unit.get("public_repo"),
            "pypi": unit.get("pypi"),
            "readme": {
                "description": unit.get("readme_description"),
                "links": _loads(unit.get("readme_links"), {}),
                "badges": _loads(unit.get("readme_badges"), {}),
            },
        }
        return out

    def render(self) -> str:
        manifest = {}
        if self.manifest_comment:
            manifest["_comment"] = self.manifest_comment
        manifest["units"] = [self._unit_to_manifest(u) for u in self.units]
        return json.dumps(manifest, indent=2, sort_keys=False)


def compile_memory_tier(tier_num: int = 0, shared_connection=None, active_hypercluster: str = None) -> str:
    """
    Compile a memory tier file from CartON Hypercluster graph.

    MEMORY.md is never manually edited — it's a compilation target.
    CartON graph = source code, this function = compiler, MEMORY.md = object code.

    3-Tier Design (Idea_Three_Tier_Memory_Architecture_Mar11):
    - Tier 0 (MEMORY.md): UltraMap (HC names + why) + ONE expanded active hypercluster
    - Tier 1 (rules): Starsystem HC collection list with hierarchy
    - Tier 2+ (faint): Compressed indices

    Args:
        tier_num: Which memory tier to compile (0=MEMORY.md, 1=rules L0, 2=L1, 3=L2)
        shared_connection: Optional shared Neo4j connection
        active_hypercluster: Name of the active hypercluster to expand (optional).
                            If not provided, checks /tmp/active_hypercluster.txt

    Returns:
        Result message with file path and stats
    """
    from carton_mcp.carton_utils import CartOnUtils

    utils = CartOnUtils(shared_connection=shared_connection)

    # Tier file paths
    tier_paths = {
        0: os.path.expanduser("~/.claude/projects/-home-GOD/memory/MEMORY.md"),
        1: os.path.expanduser("~/.claude/rules/mid_term_memory.md"),
        2: os.path.expanduser("~/.claude/rules/long_term_memory.md"),
        3: os.path.expanduser("~/.claude/rules/faintest-memories-L2.md"),
    }

    if tier_num not in tier_paths:
        return f"Unknown tier: {tier_num}"

    # Query all Hyperclusters (no tier relationship needed)
    query = """
    MATCH (h:Wiki)-[:IS_A]->(ht:Wiki {n: "Hypercluster"})
    OPTIONAL MATCH (h)-[:HAS_STATUS]->(status:Wiki)
    OPTIONAL MATCH (h)-[:HAS_GIINT_PROJECT]->(giint:Wiki)
    OPTIONAL MATCH (h)-[:HAS_PART]->(part:Wiki)
    RETURN h.n as name, h.d as description,
           status.n as status,
           giint.n as giint_project,
           collect(DISTINCT part.n) as parts
    ORDER BY h.n
    """
    result = utils.query_wiki_graph(query, {})

    if not result.get("success"):
        return f"Query failed: {result}"

    hyperclusters = result.get("data", [])

    # Group by status
    active = []
    protected = []
    blocked = []
    for hc in hyperclusters:
        status = hc.get("status", "Active")
        if status == "Protected":
            protected.append(hc)
        elif status == "Blocked":
            blocked.append(hc)
        else:
            active.append(hc)

    # Query UltraMaps
    ultramap_query = """
    MATCH (u:Wiki)-[:IS_A]->(ut:Wiki {n: "Ultramap"})
    RETURN u.n as name, u.d as description
    ORDER BY u.n
    """
    ultramap_result = utils.query_wiki_graph(ultramap_query, {})
    ultramaps = ultramap_result.get("data", []) if ultramap_result.get("success") else []

    # Query Done collections for archived section
    done_query = """
    MATCH (c:Wiki)-[:IS_A]->(ct:Wiki {n: "Carton_Collection"})
    WHERE c.n STARTS WITH "Done_"
    OPTIONAL MATCH (c)-[:HAS_PART]->(member:Wiki)
    RETURN c.n as name, count(member) as member_count
    ORDER BY c.n
    """
    done_result = utils.query_wiki_graph(done_query, {})
    done_collections = done_result.get("data", []) if done_result.get("success") else []

    # === COMPILE THE FILE ===
    def _clean_why(text):
        """Strip wiki-links and migration prefix from description."""
        # Strip complete wiki-links: [word](../Path/Path_itself.md) → word
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        # Strip truncated/partial wiki-links: [word](../partial... → word
        text = re.sub(r'\[([^\]]+)\]\([^)]*$', r'\1', text)
        # Strip orphan link targets: (../Path/Path_itself.md) with no preceding []
        text = re.sub(r'\(\.\./[^)]*\)', '', text)
        # Strip truncated orphan targets: (../partial...
        text = re.sub(r'\(\.\./[^)]*$', '', text)
        # Strip truncated opening brackets: [word without closing ]
        text = re.sub(r'\[[^\]]*$', '', text)
        # Strip leftover '''[ or similar artifacts
        text = re.sub(r"'{2,}\[?", '', text)
        # Strip migration prefix: "HyperCluster tracking GIINT_Project_X. Why: "
        text = re.sub(r'^HyperCluster tracking \S+\.\s*Why:\s*', '', text)
        # Clean up double spaces and trailing punctuation artifacts
        text = re.sub(r'  +', ' ', text)
        return text.strip()

    # Resolve active hypercluster from parameter or state file
    if not active_hypercluster:
        # CONNECTS_TO: /tmp/active_hypercluster.txt (read) — also accessed by MEMORY.md compilation
        active_hc_file = Path("/tmp/active_hypercluster.txt")
        if active_hc_file.exists():
            active_hypercluster = active_hc_file.read_text().strip()

    lines = []

    if tier_num == 0:
        # === SECTION 1: UltraMap (HC-to-HC morphisms) ===
        # UltraMap = relationships BETWEEN sibling hyperclusters
        # (DEPENDS_ON, BLOCKED_BY, FAILED_BECAUSE, RETRY_AS, etc.)
        morphism_query = """
        MATCH (h1:Wiki)-[:IS_A]->(:Wiki {n: "Hypercluster"})
        MATCH (h2:Wiki)-[:IS_A]->(:Wiki {n: "Hypercluster"})
        WHERE h1 <> h2
        MATCH (h1)-[r]->(h2)
        WHERE NOT type(r) IN ['IS_A', 'INSTANTIATES', 'INSTANTIATED_BY', 'PART_OF', 'HAS_PART', 'AUTO_RELATED_TO', 'HAS_STATUS', 'HAS_GIINT_PROJECT', 'HAS_WHY', 'HAS_DISPLAY_NAME', 'HAS_DONE_COLLECTION', 'HAS_INCLUSION_MAP', 'RELATES_TO']
        RETURN h1.n as source, type(r) as rel_type, h2.n as target
        ORDER BY h1.n, type(r)
        """
        morphism_result = utils.query_wiki_graph(morphism_query, {})
        morphisms = morphism_result.get("data", []) if morphism_result.get("success") else []

        lines.extend([
            "# MEMORY - GNO.SYS",
            "",
            "## Instructions (compiled — do not edit)",
            "- **Write work state to CartON via the sanctioned SOUP lane** — `add_concept` / the doc-mirror `journal` CLI / `set_properties` (the Dragonbones EC pipeline is DISABLED; do not emit ECs)",
            "- **NEVER manually write MEMORY.md** — this file is compiler output. Source of truth is CartON.",
            "- **CartON graph → compiler → MEMORY.md** — the graph is the source; run `python3 ~/.claude/scripts/project_memory.py` to recompile",
            # CONNECTS_TO: /tmp/heaven_data/task_list_backup.json (reference) — ephemeral task list backup
            "- **Backup task list to `/tmp/heaven_data/task_list_backup.json`** before session end (Claude Code tasks are ephemeral)",
            "",
            "## UltraMap (HC-to-HC morphisms)",
            "",
        ])

        if morphisms:
            # Group morphisms by source HC
            from collections import defaultdict
            morph_by_source = defaultdict(list)
            for m in morphisms:
                src = m["source"].replace("Hypercluster_", "").replace("_", " ")
                tgt = m["target"].replace("Hypercluster_", "").replace("_", " ")
                morph_by_source[src].append(f"{m['rel_type'].lower()} → {tgt}")

            for src_name, rels in sorted(morph_by_source.items()):
                lines.append(f"- **{src_name}**: {'; '.join(rels)}")
        else:
            lines.append("*(No HC-to-HC morphisms yet — add DEPENDS_ON/BLOCKED_BY between Hyperclusters)*")

        # HC count summary (one line — full list is in CartON, not MEMORY.md)
        total_hcs = len(active) + len(blocked) + len(protected)
        lines.append(f"")
        lines.append(f"**{total_hcs} hyperclusters** ({len(active)} active, {len(blocked)} blocked, {len(protected)} protected) — query CartON for full list")

        # === SECTION 2: Active Hypercluster (FULLY EXPANDED) ===
        # Show EVERY concept PART_OF the active HC's GIINT project
        lines.extend(["", "---", ""])

        expanded_hc = None
        expanded_giint = None
        if active_hypercluster:
            all_hcs = active + blocked + protected
            for hc in all_hcs:
                if hc["name"] == active_hypercluster or hc["name"].replace("Hypercluster_", "") == active_hypercluster:
                    expanded_hc = hc
                    expanded_giint = hc.get("giint_project")
                    break

        if expanded_hc:
            # Use ontology_graphs to get the FULL expanded metagraph (names only)
            try:
                from carton_mcp.ontology_graphs import get_expanded_metagraph, format_metagraph_for_memory
                conn = shared_connection or utils._get_connection()[0]
                metagraph = get_expanded_metagraph(expanded_hc["name"], conn)
                metagraph_text = format_metagraph_for_memory(metagraph)
                lines.append(metagraph_text)
            except Exception as e:
                # Fallback: minimal display
                display_name = expanded_hc["name"].replace("Hypercluster_", "").replace("_", " ")
                why = _clean_why(expanded_hc.get("description", "No description"))
                lines.extend([
                    f"## Active Task: {display_name}",
                    f"Why: {why}",
                    f"*(Metagraph error: {e})*",
                ])
        else:
            lines.extend([
                "## Active Task: None",
                "No active hypercluster set. Write hypercluster name to /tmp/active_hypercluster.txt",
            ])

    elif tier_num == 1:
        # MTM: Expanded active starsystem (minus the task HC which is on MEMORY.md)
        # Shows all collections in the current starsystem so agent knows what context is available
        lines.extend([
            "# Mid-Term Memory (MTM)",
            "",
            "Starsystem HC collection list with hierarchy.",
            "Use `activate_collection()` when you need one.",
            "",
            "## Hyperclusters by Starsystem",
        ])

        # Hierarchy-aware HC grouping (CHANGE_SPEC #6): when an HC has the welded
        # PART_OF -> Task_Collections -> Starsystem_Collection chain, group it under
        # that starsystem heading; HCs without the chain fall under "(unwelded)".
        # Works BOTH before the world-graph weld (everything (unwelded), flat) and
        # after (grouped). The query tolerates absent edges via OPTIONAL MATCH.
        ss_by_hc = {}
        try:
            hier_query = """
            MATCH (h:Wiki)-[:IS_A]->(:Wiki {n: "Hypercluster"})
            OPTIONAL MATCH (h)-[:PART_OF*1..3]->(ss:Wiki)-[:IS_A]->(:Wiki {n: 'Starsystem_Collection'})
            OPTIONAL MATCH (h)-[:HAS_STATUS]->(st:Wiki)
            RETURN h.n as name, collect(DISTINCT ss.n)[0] as starsystem, st.n as status
            ORDER BY h.n
            """
            hier_result = utils.query_wiki_graph(hier_query, {})
            hier_data = hier_result.get("data", []) if hier_result.get("success") else []
        except Exception:
            logger.exception("[MemoryCompiler] Tier 1 hierarchy query failed; falling back to flat")
            hier_data = []

        from collections import defaultdict as _dd
        grouped = _dd(list)
        for entry in hier_data:
            hc_name = entry.get("name", "")
            if not hc_name:
                continue
            ss = entry.get("starsystem") or "(unwelded)"
            status = entry.get("status")
            ss_by_hc[hc_name] = ss
            label = hc_name.replace("Hypercluster_", "").replace("_", " ")
            line = f"- {label}" + (f" [{status}]" if status else "")
            grouped[ss].append(line)

        if grouped:
            # Real starsystems first (alpha), "(unwelded)" last so the welded
            # hierarchy reads cleanly when the weld lands.
            for ss_name in sorted(grouped.keys(), key=lambda s: (s == "(unwelded)", s)):
                heading = ss_name.replace("_Collection", "").replace("_", " ") if ss_name != "(unwelded)" else "(unwelded)"
                lines.append(f"### {heading}")
                lines.extend(sorted(grouped[ss_name]))
                lines.append("")
        else:
            lines.append("*(No hyperclusters found)*")
            lines.append("")

        lines.append("## Active Starsystem HC Collections")

        # Find the active HC's starsystem, then list all collections in it
        active_hc_name = None
        if not active_hypercluster:
            # CONNECTS_TO: /tmp/active_hypercluster.txt (read) — also accessed by MEMORY.md compilation
            active_hc_file = Path("/tmp/active_hypercluster.txt")
            if active_hc_file.exists():
                active_hc_name = active_hc_file.read_text().strip()
        else:
            active_hc_name = active_hypercluster

        if active_hc_name:
            # Get all collections that share the same starsystem as the active HC
            mtm_query = """
            MATCH (c:Wiki)-[:IS_A]->(:Wiki {n: "Carton_Collection"})
            WHERE NOT c.n STARTS WITH 'Done_'
            AND NOT c.n STARTS WITH 'Mcp__'
            AND NOT c.n STARTS WITH 'Starsystem_Cascade'
            AND c.d IS NOT NULL AND c.d <> ''
            RETURN c.n as name, c.d as description
            ORDER BY c.n
            LIMIT 50
            """
            mtm_result = utils.query_wiki_graph(mtm_query, {})
            mtm_data = mtm_result.get("data", []) if mtm_result.get("success") else []

            for entry in mtm_data:
                name = entry.get("name", "")
                desc = entry.get("description", "")
                # Clean wiki links and truncate
                short_desc = _clean_why(desc.split('\n')[0][:80]) if desc else ""
                lines.append(f"- {name} ({short_desc})")
        else:
            lines.append("*(No active hypercluster set)*")

        lines.append("")

    elif tier_num == 2:
        # LTM: All starsystem names — the bird's eye view
        lines.extend([
            "# Long-Term Memory (LTM)",
            "",
            "Use `activate_collection()` to load any of these.",
            "",
            "## 🚀 Starsystems",
        ])

        # Query all activatable collections — IS_A any collection type
        # This is the bird's eye view of everything the agent can load
        ltm_query = """
        MATCH (c:Wiki)-[:IS_A]->(t:Wiki)
        WHERE t.n IN ['Carton_Collection', 'Local_Collection', 'Identity_Collection', 'Hypercluster_Collection']
        AND NOT c.n STARTS WITH 'Done_'
        AND NOT c.n STARTS WITH 'Starsystem_Cascade'
        AND NOT c.n STARTS WITH 'Starsystem_Actualization'
        AND NOT c.n STARTS WITH 'Mcp__'
        AND NOT c.n = 'Carton_Collection'
        AND NOT c.n = 'Local_Collection'
        AND NOT c.n = 'Identity_Collection'
        AND NOT c.n = 'Hypercluster_Collection'
        RETURN DISTINCT c.n as name
        ORDER BY c.n
        """
        ltm_result = utils.query_wiki_graph(ltm_query, {})
        ltm_data = ltm_result.get("data", []) if ltm_result.get("success") else []

        for entry in ltm_data:
            name = entry.get("name", "")
            lines.append(f"- {name}")

        lines.append("")

    elif tier_num == 3:
        # L2 (faintest): the most-compressed index — names only, one line per HC
        # (name + status if present), grouped under starsystem when the welded
        # PART_OF -> Starsystem_Collection chain exists, flat "(unwelded)" otherwise.
        # Kept deliberately small: no descriptions, no GIINT expansion. Mirrors the
        # tier-1 grouping shape but strips it to bare names.
        lines.extend([
            "# Faintest Memories (L2)",
            "",
            "Most-compressed HC index — names only. Query CartON to expand any.",
            "",
        ])

        l2_by_ss = {}
        try:
            l2_query = """
            MATCH (h:Wiki)-[:IS_A]->(:Wiki {n: "Hypercluster"})
            OPTIONAL MATCH (h)-[:PART_OF*1..3]->(ss:Wiki)-[:IS_A]->(:Wiki {n: 'Starsystem_Collection'})
            OPTIONAL MATCH (h)-[:HAS_STATUS]->(st:Wiki)
            RETURN h.n as name, collect(DISTINCT ss.n)[0] as starsystem, st.n as status
            ORDER BY h.n
            """
            l2_result = utils.query_wiki_graph(l2_query, {})
            l2_data = l2_result.get("data", []) if l2_result.get("success") else []
        except Exception:
            logger.exception("[MemoryCompiler] Tier 3 query failed; falling back to flat HC list")
            l2_data = []

        from collections import defaultdict as _dd3
        l2_grouped = _dd3(list)
        for entry in l2_data:
            hc_name = entry.get("name", "")
            if not hc_name:
                continue
            ss = entry.get("starsystem") or "(unwelded)"
            status = entry.get("status")
            label = hc_name.replace("Hypercluster_", "").replace("_", " ")
            l2_grouped[ss].append(f"- {label}" + (f" [{status}]" if status else ""))

        if l2_grouped:
            for ss_name in sorted(l2_grouped.keys(), key=lambda s: (s == "(unwelded)", s)):
                heading = ss_name.replace("_Collection", "").replace("_", " ") if ss_name != "(unwelded)" else "(unwelded)"
                lines.append(f"### {heading}")
                lines.extend(sorted(l2_grouped[ss_name]))
                lines.append("")
        else:
            # Fall back to the already-fetched hypercluster list (names only) so the
            # file is never empty/garbage even if the grouping query yields nothing.
            for hc in (active + blocked + protected):
                label = hc["name"].replace("Hypercluster_", "").replace("_", " ")
                lines.append(f"- {label}")
            if not (active or blocked or protected):
                lines.append("*(No hyperclusters found)*")
            lines.append("")

    # Write the compiled file
    # NOTE: every tier_paths value is a literal expanduser() path (no dynamic/None
    # tiers exist), so output_path can never be None here — the former None-guard
    # was dead code and has been removed (CHANGE_SPEC #4).
    output_path = tier_paths[tier_num]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(lines) + "\n")

    stats = f"{len(active)} active, {len(blocked)} blocked, {len(protected)} protected, {len(ultramaps)} ultramaps, {len(done_collections)} archived"
    logger.info(f"[MemoryCompiler] Tier {tier_num} compiled: {stats} -> {output_path}")
    return f"Compiled Tier {tier_num}: {stats} -> {output_path}"


def prune_memory_tier(tier_num: int = 0, dry_run: bool = False, compress_all: bool = False, shared_connection=None) -> str:
    """DEPRECATED — Memory tiers are abstract file labels, not CartON relationships. No pruning needed."""
    return "prune_memory_tier is deprecated. Memory tiers are file labels, not graph relationships."


def memory_tier_stats(shared_connection=None) -> str:
    """Show memory system status. Tiers are file labels, not graph relationships."""
    from carton_mcp.carton_utils import CartOnUtils

    utils = CartOnUtils(shared_connection=shared_connection)

    tier_paths = {
        0: os.path.expanduser("~/.claude/projects/-home-GOD/memory/MEMORY.md"),
        1: os.path.expanduser("~/.claude/rules/mid_term_memory.md"),
        2: os.path.expanduser("~/.claude/rules/long_term_memory.md"),
    }
    tier_labels = {0: "MEMORY.md (Tier 0)", 1: "MTM (Tier 1)", 2: "LTM (Tier 2)"}

    lines = []
    lines.append("=" * 60)
    lines.append("MEMORY SYSTEM STATUS")
    lines.append("=" * 60)

    # Total HCs
    hc_query = "MATCH (h:Wiki)-[:IS_A]->(:Wiki {n: 'Hypercluster'}) RETURN count(h) as count"
    hc_result = utils.query_wiki_graph(hc_query, {})
    hc_count = hc_result["data"][0].get("count", 0) if hc_result.get("success") and hc_result.get("data") else 0
    lines.append(f"\nTotal Hyperclusters: {hc_count}")

    # File line counts
    for tier_num in range(3):
        path = tier_paths.get(tier_num)
        file_lines = 0
        if path and Path(path).exists():
            file_lines = len(Path(path).read_text().split("\n"))
        lines.append(f"{tier_labels[tier_num]}: {file_lines} lines")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


def substrate_project(substrate: dict, target: str, description_only: bool = True, template: str = None) -> str:
    """
    Main projection function.

    Args:
        substrate: Dict with 'type' and type-specific fields
        target: Carton concept name
        description_only: Whether to include just description or relationships too
        template: Optional metastack template name (e.g., 'reference_document')
                  If provided, renders through template before projecting

    Returns:
        Result message
    """
    # Validate substrate
    substrate_type = substrate.get("type")
    if not substrate_type:
        raise ValueError("substrate must have 'type' field")

    if substrate_type not in PROJECTORS:
        raise ValueError(f"Unknown substrate type: {substrate_type}. Available: {list(PROJECTORS.keys())}")

    # Parse into appropriate model for validation
    substrate_classes = {
        "file": FileSubstrate,
        "discord": DiscordSubstrate,
        "registry": RegistrySubstrate,
        "env": EnvSubstrate,
        "skill": SkillSubstrate,
        "rule": RuleSubstrate,
    }

    substrate_model = substrate_classes[substrate_type](**substrate)

    # Get content and project
    projector = PROJECTORS[substrate_type]
    if substrate_type == "skill":
        # Skill projector fetches its own structured data from Neo4j
        result = projector(substrate_model, target)
    elif template:
        content = render_through_template(target, template)
        result = projector(substrate_model, content)
    else:
        content = get_concept_content(target, description_only)
        result = projector(substrate_model, content)

    return result
