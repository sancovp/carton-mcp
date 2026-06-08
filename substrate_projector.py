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
        return

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
        return

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

    Path(rules_dir / "giint-hierarchy.md").write_text("\n".join(lines) + "\n")
    logger.info("Projected GIINT hierarchy rule to %s", rules_dir / "giint-hierarchy.md")


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
            import chromadb
            chroma_path = os.path.join(
                os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data"), "skill_chroma"
            )
            client = chromadb.PersistentClient(path=chroma_path)
            collection = client.get_or_create_collection(
                name="skillgraphs",
                metadata={"hnsw:space": "cosine"}
            )

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

            collection.upsert(
                ids=[f"skillgraph:{skill_name}"],
                documents=[doc_text],
                metadatas=[meta]
            )
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

            # Project GIINT hierarchy rule if not already present
            hierarchy_rule_path = rules_dir / "giint-hierarchy.md"
            if not hierarchy_rule_path.exists():
                try:
                    _project_giint_hierarchy_rule(utils, ss_path, rules_dir)
                except Exception:
                    logger.exception("Failed to project GIINT hierarchy rule to %s", ss_path)

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
    "rule": lambda substrate, concept_name: project_to_rule(substrate, concept_name),
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

    # Never project stub descriptions as rule files
    if has_content.strip().startswith("AUTO CREATED:"):
        return f"skipped: {concept_name} has stub description, not projecting"

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
    target_path = os.path.join(target_dir, filename)

    # Render new content
    new_body = _render_rule_file_content(has_content, has_paths)

    # Diff against existing
    if os.path.exists(target_path):
        try:
            existing = Path(target_path).read_text()
        except Exception as e:
            return f"skipped: cannot read existing {target_path}: {e}"
        if existing == new_body:
            return f"unchanged: {target_path}"
        action = "updated"
    else:
        action = "created"

    # Write
    try:
        os.makedirs(target_dir, exist_ok=True)
        Path(target_path).write_text(new_body)
    except Exception as e:
        return f"failed: cannot write {target_path}: {e}"

    logger.info("Rule projected: %s -> %s (%s)", concept_name, target_path, action)
    return f"{action}: {target_path}"


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

    # Get full concept data
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

    # Build template content from concept data
    # Parse description for taxonomy/source if present
    description = concept_data.get("description", "")

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
            "- **ALL task/concept work MUST go through Dragonbones entity chains** — emit ECs, let the hook compile to CartON, then run `python3 ~/.claude/scripts/project_memory.py` to update this file",
            "- **NEVER manually write MEMORY.md** — this file is compiler output. Source of truth is CartON.",
            "- **Task list → Dragonbones EC → CartON → compiler → MEMORY.md** — this is the only valid pipeline",
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
            "Collection name pointers for active starsystem HCs.",
            "Use `activate_collection()` when you need one.",
            "",
            "## Active Starsystem HC Collections",
        ])

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

    # Write the compiled file
    output_path = tier_paths[tier_num]
    if output_path is None:
        return f"Tier {tier_num} has dynamic path — not yet supported"

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
