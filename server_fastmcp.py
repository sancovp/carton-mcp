#!/usr/bin/env python3
"""
CartON MCP Server - FastMCP Implementation
Zettelkasten-style concept management for knowledge graphs with prompts
"""
import json
import logging
import traceback
import subprocess
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from functools import wraps

from pydantic import BaseModel
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

# Import CartOn utilities
from carton_mcp.carton_utils import (
    CartOnUtils, strip_wiki_links,
    edit_carton_obj as _edit_carton_obj_lib,
    validate_carton_obj as _validate_carton_obj_lib,
    set_concept_properties as _set_concept_properties_lib,
    query_concepts_by_properties as _query_concepts_by_properties_lib,
    remove_concept_relationship as _remove_concept_relationship_lib,
    RESERVED_PROPERTY_KEYS as _RESERVED_PROPERTY_KEYS,
)
from .add_concept_tool import add_concept_tool_func, add_observation, rename_concept_func, get_observation_queue_dir, PERSONAL_DOMAINS
from .carton_split_content import split_content_concept as _split_content_concept_lib
from .concept_config import ConceptConfig

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import re

# --------- ChromaDB via the chroma daemon (ZERO chroma import in this MCP) ---------
# carton does NOT import chromadb / langchain_chroma / onnxruntime. ALL chroma goes through the
# chroma_daemon (the SOLE chroma importer; port 8190), reached over HTTP via the thin urllib-only
# chroma_client. So this MCP stays light: it sends TEXT to the daemon, the daemon embeds + queries the
# :8101 store + returns results. The old lazy `_get_rag`/SmartChromaRAG construction (which pulled the
# ~600MB neural stack into every carton process that ran a RAG path) is GONE. See chroma_daemon.py.
from .chroma_client import (chroma_query as _daemon_query, chroma_route as _daemon_route,
                            chroma_add_texts as _daemon_add_texts, ChromaDaemonError)


def _strip_md(text: str) -> str:
    """Delegate to the CANONICAL library stripper (onion arch — ONE implementation in carton_utils,
    used by the library read primitive AND this MCP formatter). Belt-and-suspenders: the library already
    strips at _execute_neo4j_query, so MCP data arrives clean; this guards any text built outside that path."""
    if not isinstance(text, str):
        return text
    return strip_wiki_links(text).strip()


def _dedup_desc(text: str) -> str:
    """Deduplicate description paragraphs. Repeated appends create massive duplication.
    Does NOT truncate — the _fmt overflow mechanism handles long output (writes to file)."""
    if not text or not isinstance(text, str):
        return text or ""
    # Split by double-newline (paragraphs)
    paragraphs = re.split(r'\n\n+', text)
    seen = set()
    deduped = []
    for p in paragraphs:
        normalized = p.strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return "\n\n".join(deduped)

_OVERFLOW_THRESHOLD = 10000  # chars before file overflow kicks in
_OVERFLOW_DIR = Path(os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")) / "query_overflow"

def _fmt(data) -> str:
    """Format data as compact string. No JSON bloat. Overflows to file if > 10k chars."""
    result = _fmt_inner(data)
    if len(result) > _OVERFLOW_THRESHOLD:
        _OVERFLOW_DIR.mkdir(parents=True, exist_ok=True)
        overflow_file = _OVERFLOW_DIR / f"overflow_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        overflow_file.write_text(result)
        truncated = result[:_OVERFLOW_THRESHOLD]
        return f"{truncated}\n\n... Full results ({len(result)} chars) at: {overflow_file}"
    return result

def _fmt_inner(data) -> str:
    """Inner formatter — no truncation, no overflow. Deduplicates descriptions."""
    if isinstance(data, str):
        return _dedup_desc(_strip_md(data))
    if isinstance(data, dict):
        if "result" in data:
            return _fmt_inner(data["result"])
        parts = []
        for k, v in data.items():
            if v is not None and v != [] and v != {}:
                parts.append(f"{k}: {_fmt_inner(v)}")
        return "\n".join(parts) if parts else "(empty)"
    if isinstance(data, list):
        if not data:
            return "(none)"
        return ", ".join(_fmt_inner(x) for x in data)
    return str(data)

# Create FastMCP server (the SDK class — UNTOUCHED; this is the stdio local
# server exactly as before). Network auth wraps the ASGI app in main()'s
# network branch instead — see network_gateway.py: the no-SSE law +
# fail-closed CARTON_API_KEY + a pure-ASGI bearer gate. Nothing blocking at
# import (the transport rule's startup-timeout lesson).
from .network_gateway import (
    STDIO as _GW_STDIO,
    resolve_transport as _gw_resolve_transport,
    run_network as _gw_run_network,
)

mcp = FastMCP("carton")

# Initialize shared Neo4j connection (lives for MCP lifetime)
def _create_shared_neo4j():
    """Create persistent Neo4j connection for MCP server lifetime."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        config = ConceptConfig()
        conn = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )
        conn._ensure_connection()
        logger.info("Neo4j shared connection established")
        return conn
    except Exception as e:
        logger.warning(f"Failed to create shared Neo4j connection: {e}")
        return None

_neo4j_conn = _create_shared_neo4j()

# Initialize utilities with shared connection
utils = CartOnUtils(shared_connection=_neo4j_conn)

# Stash for failed add_concept payloads — retry merges without re-typing everything
_concept_stash: dict = {}

# --- SM-GATE wiring (the carton-native CyberneticiRcus state-machine gate on the LIVE tool surface) ---
# Isaac 2026-06-20: every tool that retrieves/queries is gated by the active state machine and checks
# legality. DEFAULT-OFF: the gate engages ONLY when the enable flag file exists AND no kill switch —
# so normal carton behavior is byte-identical until SM-gating is explicitly turned on. The gate is
# also default-ungated PER-ACTOR (no locked Execution_State => pass) and FAILS OPEN, so it can never
# brick carton. The mechanism + its E2E proof live in sm_gate.py. (this is increment 2: the wiring.)
from carton_mcp import sm_gate as _sm_gate
from carton_mcp.soma_fillers import mark_compose_suggestion as _mark_compose_suggestion_lib
from carton_mcp.soma_fillers import record_fill_provenance as _record_fill_provenance_lib

_SM_GATE_ENABLE_FLAG = os.getenv("CARTON_SM_GATE_ENABLED",
                                 "/tmp/heaven_data/carton_sm_gate_enabled")

def _sm_gate_on() -> bool:
    try:
        return os.path.exists(_SM_GATE_ENABLE_FLAG) and not _sm_gate.gate_disabled()
    except Exception:
        return False

def _sm_actor() -> str:
    # Carton's analogue of CCC's explicit cybernet_name: the acting identity. Single-session MCP =>
    # one actor at a time. Resolved: the cross-process active-identity FILE (set by equip_persona in
    # the skill-manager-mcp process — env can't cross processes at runtime, so the persona hands its
    # carton_identity over via a file, exactly like the gate's own flag-files) FIRST, then env,
    # default 'Gnosys'. Absent the file => unchanged ('Gnosys'), so this is default-safe.
    handle = (_sm_gate.get_active_identity()
              or os.getenv("CARTON_SM_ACTOR") or os.getenv("AGENT_IDENTITY") or "Gnosys")
    # "identities are actual things" (Isaac 2026-06-23): resolve the raw carton_identity handle to its
    # Agent_Identity ENTITY node (MERGE-ensured) so the gate's lifecycle/Execution_State attaches to a
    # REAL identity node, not a bare handle that matches nothing. Only reached when the gate is ON
    # (callers early-return when off), so default carton behaviour is unchanged. FAILS OPEN to the handle.
    try:
        return _sm_gate.resolve_identity_entity(handle, _sm_run)
    except Exception:
        return handle

def _sm_run(query, params=None):
    rows = _neo4j_conn.execute_query(query, params or {}) if _neo4j_conn else []
    return [dict(r) if not isinstance(r, dict) else r for r in (rows or [])]

def _sm_gate_check(tool_name: str, arg_repr: str):
    """Gate a live tool call. If SM-gating is ON and the actor is locked at a step, RAISE
    GateRefusal unless the call matches the step's required_pattern (auto-advancing on a legal
    call). No-op when gating is off / the actor is unlocked (the default). Returns the progress
    event string or None."""
    if not _sm_gate_on():
        return None
    try:
        return _sm_gate.gate_call(_sm_actor(), f"{tool_name}({arg_repr})", _sm_run).get("event")
    except _sm_gate.GateRefusal:
        raise  # the refusal IS the next-move instruction — surface it to the caller
    except Exception as e:
        logger.error(f"sm_gate check fault (FAIL-OPEN): {e}")
        return None

def _sm_trigger_scan(results) -> None:
    """If a retrieval result carries a node with trigger_traversal, lock the actor into that flow."""
    if not _sm_gate_on():
        return
    try:
        _sm_gate.scan_and_trigger(results, _sm_actor(), _sm_run)
    except Exception as e:
        logger.error(f"sm_gate trigger scan fault: {e}")

def _sm_chain_require_next(concept: str) -> str:
    """CORE require-next (Isaac 2026-06-20): a deliberate visit to a Core-bearing concept ARMS a
    require-next. The concept's content is served as normal (a Core does NOT withhold it) — but the
    actor's NEXT move is now REQUIRED to match the concept's Core SM step, enforced by the normal
    _sm_gate_check/gate_call on subsequent calls (routing-persistence). Returns a '⛓ REQUIRED NEXT: …'
    suffix to append to the served content, or '' (no Core / gating off / fault). Default-OFF + FAILS
    OPEN ('') — a Core bug can only fail to append the note, never block carton or withhold content."""
    if not _sm_gate_on():
        return ""
    try:
        cv = _sm_gate.sm_chain_visit(_sm_actor(), concept, _sm_run)
        rn = cv.get("require_next") if isinstance(cv, dict) else None
        return f"\n\n⛓ REQUIRED NEXT: {rn}" if rn else ""
    except Exception as e:
        logger.error(f"sm_core require-next fault (FAIL-OPEN): {e}", exc_info=True)
        return ""

# DISABLED 2026-06-16 (SOMA-unification sprint, STEP 1). The carton ontology/memory
# "bootstrap" funcs only WROTE A GRAPH (not real code), duplicating ontology that now
# lives in SOMA's OWL. Memory_Tier / Memory_Tier_0..3 / UltraMap + the Hypercluster
# memory restrictions were ADDED to base/soma-prolog/soma_prolog/starsystem.owl;
# Skill / SkillSpec / Skill_Category(+3) / Hypercluster + the Has_* properties were
# ALREADY in starsystem.owl. So these carton bootstraps are redundant. Commented out
# (NOT deleted yet — niceness pass later). Existing live graphs already have the nodes;
# a fresh install gets them via the deferred auto-seed-from-SOMA (the VERY LAST step of
# the whole refactor). The function definitions are likewise commented out in carton_utils.py.
# try:
#     utils.bootstrap_ontology_types()
# except Exception as e:
#     logger.warning(f"Ontology bootstrap failed (non-fatal): {e}")
#
# try:
#     utils.bootstrap_memory_ontology_types()
# except Exception as e:
#     logger.warning(f"Memory ontology bootstrap failed (non-fatal): {e}")

# Enforce ontology invariants in background thread (non-blocking so MCP connects fast)
import threading
def _deferred_enforcement():
    try:
        enforcement_stats = utils.enforce_ontology_invariants()
        if enforcement_stats.get("neo4j_fixed") or enforcement_stats.get("chroma_fixed"):
            logger.info(f"Ontology enforcement applied fixes: {enforcement_stats}")
    except Exception as e:
        logger.warning(f"Ontology enforcement failed (non-fatal): {e}")
# # DISABLED: was pegging CPU at 99% — enforce_ontology_invariants creates chromadb.PersistentClient which never finishes
# threading.Thread(target=_deferred_enforcement, daemon=True).start()

"""
UARL ONTOLOGY SYSTEM STATUS:

Foundation implemented:
- Soup layer: Concepts with arbitrary descriptions, weak/strong compression tracking
- Ontology promotion: REIFIES → PROGRAMS → IS_A Carton_Ontology_Entity validation
- Dynamic UARL predicates: Bootstrap (is_a, part_of, instantiates) + reified concepts
- Compression marking: Weak relationship types and concepts using them marked REQUIRES_EVOLUTION

Not yet implemented:
- Ontology axiom extraction: Converting origination stacks (triples) into formal axioms
- Semantic pattern matching: Validating origination stack semantic narrative against UARL template
- Description composition: Generating ontology-level descriptions from composed triples instead of arbitrary text
- Complete origination stack semantics: Metastack template pattern, embodies/manifests tracking

Current state: Can type concepts into soup layer and manually trigger REIFIES for validation,
but ontology layer doesn't extract real formal knowledge yet. Infrastructure is ready for future axiom extraction.
"""


def git_push_batch():
    """Push all accumulated local commits to remote. Non-blocking, returns warning on failure."""
    try:
        # Get config from environment
        github_pat = os.getenv('GITHUB_PAT')
        repo_url = os.getenv('REPO_URL')
        branch = os.getenv('BRANCH', 'main')
        base_path = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        wiki_path = os.path.join(base_path, 'wiki')

        if not github_pat or not repo_url:
            return "⚠️ Git push skipped: GITHUB_PAT or REPO_URL not set"

        # Set up credentials
        auth_url = f"https://{github_pat}@github.com"
        credentials_path = Path.home() / ".git-credentials"
        credentials_path.write_text(auth_url + "\n")

        # Push accumulated commits
        result = subprocess.run(
            ["git", "push", "origin", branch],
            cwd=wiki_path,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            return f"⚠️ Git push failed: {result.stderr}"

        return "✅ Git push successful"
    except Exception as e:
        traceback.print_exc()
        return f"⚠️ Git push error: {str(e)}"


def with_git_push(func):
    """Decorator that pushes git changes after tool execution."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Execute the tool
        result = func(*args, **kwargs)

        # Push changes (non-blocking, failures become warnings)
        push_result = git_push_batch()

        # Append push status to result
        if isinstance(result, str):
            result = f"{result}\n\n{push_result}"

        return result
    return wrapper


# Pydantic models for proper schema validation
class ConceptRelationship(BaseModel):
    relationship: str
    related: List[str]

def _format_concept_result(concept_name: str, raw_result: str) -> str:
    """Format concept creation result for LLM readability"""
    # import re  # moved to top
    # MEREO ERROR reject (add_concept_tool #9 carton-defers-to-SOMA gate): the concept's
    # own is_a points to an unknown/undefined type, so SOMA admits it to no region and
    # CartON declines to ingest it (no queue file, no Neo4j node). The reject string
    # already carries the reason — surface it VERBATIM. Without this branch the reject
    # falls through to the bare "❌ ❌" else-path below and the ⛔ reason is DROPPED
    # entirely (a silent reject the agent cannot act on — the exact opposite of the
    # gate's purpose, which is to reject so the agent learns WHY and re-says it correctly).
    _rr = raw_result.lstrip()
    if _rr.startswith("⛔") or "REJECTED (MEREO ERROR" in raw_result:
        return (
            "🗺️‍⟷‍📦 **CartON** (Cartographic Ontology Net)\n\n"
            f"**Concept**: `{concept_name}`\n"
            "📁 **Files**: ❌\n"
            "📊 **Neo4j**: ❌\n"
            f"⛔ {_rr.lstrip('⛔').strip()}"
        )
    # Async queue flow: "queued" means daemon will create files + neo4j
    if "queued" in raw_result.lower() or "created successfully" in raw_result or raw_result.startswith("✅"):
        files_created = "⏳ queued"
        neo4j_created = "⏳ queued"
    else:
        files_created = "❌"
        neo4j_created = "❌"

    # Override if we see explicit success/failure markers
    if "Neo4j: Created concept" in raw_result:
        neo4j_created = "✅"
    if "files created" in raw_result.lower():
        files_created = "✅"

    # Surface the SOMA VERDICT VERBATIM, UNCONDITIONALLY (Isaac 2026-07-03: "CartON should not
    # fucking care. CartON needs to display THE SOMA STRING. PERIOD."). The prior approach
    # regex-matched five hardcoded bracket-tag shapes ([SOUP:]/[CODE:]/[SYSTEM_TYPE:]/
    # [SOMA ERROR:]/[SOMA error:]) and silently DROPPED anything that didn't match — which is
    # exactly what happened to the mereo_error case: add_concept_tool.py emits a DIFFERENT tag
    # shape for it ("[MEREO — saved as soup...]", add_concept_tool.py ~2295-2300) that matched
    # NONE of the five patterns, so every mereo_error verdict — the single most common one,
    # since it fires whenever is_a points at a type SOMA hasn't seen before — was computed
    # correctly by SOMA and then silently swallowed here, never reaching the caller. CartON
    # must never parse/understand SOMA's output shape to decide whether to show it; it must
    # show ALL of it, always, so no future verdict shape can be silently dropped again.
    # add_concept_tool_func's raw_result is exactly f"✅ {concept_name}{youknow_msg}" (the ⛔
    # reject string is handled by the branch above, before this code runs) — so youknow_msg is
    # simply everything after that fixed prefix.
    _success_prefix = f"✅ {concept_name}"
    if raw_result.startswith(_success_prefix):
        _youknow_msg = raw_result[len(_success_prefix):]
    else:
        _youknow_msg = raw_result
    youknow_line = f"\n{_youknow_msg.strip()}" if _youknow_msg.strip() else ""

    return f"""🗺️‍⟷‍📦 **CartON** (Cartographic Ontology Net)

**Concept**: `{concept_name}`
📁 **Files**: {files_created}
📊 **Neo4j**: {neo4j_created}{youknow_line}"""


def _check_name_expectations(concept_name: str) -> str | None:
    """Dynamic partial-name shape gate — bounce a fumbled concept_name back so the agent self-corrects.

    INERT BY DEFAULT. Reads env `CARTON_NAME_EXPECTATIONS` (a path to a JSON file). When the env var is
    unset, or the file is missing/unreadable/unparseable, this returns None and changes NOTHING — every
    other carton consumer (main-session MCP, journal CLI, observation worker, blog organ) is untouched.

    File format: [{"prefix": str, "must_contain": str, "suffix": str, "reason": str}, ...].
    For each expectation whose `prefix` the incoming concept_name startswith, the name MUST also contain
    `must_contain` AND end with `suffix`. A name matching NO prefix passes freely (scenes/dialogs/etc.
    untouched). On violation, returns Isaac's rejection string (a NORMAL result the agent reads and acts
    on next call — never raised). Designed so a hiccup never blocks the write: any error → return None.
    """
    path = os.environ.get("CARTON_NAME_EXPECTATIONS")
    if not path:
        return None
    try:
        p = Path(path)
        if not p.is_file():
            logger.debug(f"_check_name_expectations: file not found, inert ({path})")
            return None
        expectations = json.loads(p.read_text())
        if not isinstance(expectations, list):
            logger.debug(f"_check_name_expectations: file is not a list, inert ({path})")
            return None
    except Exception as e:
        logger.debug(f"_check_name_expectations: unreadable/unparseable, inert ({path}): {e}")
        return None

    for exp in expectations:
        if not isinstance(exp, dict):
            continue
        prefix = exp.get("prefix", "")
        if not prefix or not concept_name.startswith(prefix):
            continue
        must_contain = exp.get("must_contain", "")
        suffix = exp.get("suffix", "")
        reason = exp.get("reason", "")
        if (must_contain not in concept_name) or (not concept_name.endswith(suffix)):
            return (
                f"Error: System MUST receive this type of shape partial "
                f"'{prefix}...{must_contain}...{suffix}' because {reason}. "
                f"You sent: '{concept_name}'. Re-send add_concept with a concept_name matching that "
                f"exact shape — copy the partials verbatim, do not normalize or re-derive them."
            )
    return None


def _check_observation_geometry(observation_data: dict) -> str | None:
    """Check geometry for all concepts in observation. Returns error string or None if valid."""
    OBSERVATION_TAGS = ["insight_moment", "struggle_point", "daily_action", "implementation", "emotional_state"]
    errors = []

    for tag in OBSERVATION_TAGS:
        concepts = observation_data.get(tag, [])
        for i, concept in enumerate(concepts):
            name = concept.get("name", f"unnamed_{tag}_{i}")
            rels = concept.get("relationships", [])
            rel_types = {r.get("relationship") for r in rels}

            missing = []
            if "is_a" not in rel_types:
                missing.append("is_a")
            if "part_of" not in rel_types:
                missing.append("part_of")
            if "instantiates" not in rel_types:
                missing.append("instantiates")
            if not any(k.startswith("has_") for k in rel_types):
                missing.append("has_*")

            if missing:
                errors.append(f"{name}: missing {', '.join(missing)}")

    if errors:
        return f"❌ GEOMETRY ERROR: Incomplete ontological position in observation.\n" + "\n".join(errors)
    return None


@mcp.tool()
def add_concept(
    concept_name: str,
    is_a: List[str],
    part_of: List[str],
    instantiates: List[str],
    produces: List[str],
    domain: str,
    subdomain: str,
    personal_domain: str,
    concept: str = None,
    relationships: Optional[List[ConceptRelationship]] = None,
    desc_update_mode: str = "append",
    hide_youknow: bool = False,
    clear_stash: bool = False,
    source: str = "agent",
    typed_values: Optional[List[List[str]]] = None,
    old_str_for_edit_case: Optional[str] = None,
    properties: Optional[dict] = None,
    soma_run_id: Optional[str] = None,
) -> str:
    """Add a new concept to the knowledge graph

    Args:
        concept_name: Name of the concept (will be normalized to Title_Case_With_Underscores)
        is_a: REQUIRED. What category/type is this? e.g. ["Bug_Report"], ["Implementation_Status"]
        part_of: REQUIRED. What contains this? e.g. ["GNOSYS_System"], ["Launch_Strategy"]
        instantiates: REQUIRED. What pattern does this realize? e.g. ["Bug_Fix_Pattern"], ["Working_System_Pattern"]
        produces: REQUIRED. What does this produce/output? e.g. ["Bug_Fix"], ["Compiled_Code"]. Empty list is a
            valid list ([]) but the param itself must always be passed — same discipline as is_a/part_of/instantiates.
        domain: REQUIRED (Isaac 2026-07-03: "we must know what it is in, period, every single thing" — enforced
            HERE on the MCP tool, NOT on add_concept_tool_func, which keeps it optional for internal callers).
            Free-form Title_Case string naming the broad real-world/system area this concept is about (e.g.
            "Soma", "Carton_Schema", "Crystal_Ball"). Becomes a has_domain relationship.
        subdomain: REQUIRED, same enforcement as domain. Narrower than domain (e.g. "Mereo_Validation" under
            domain "Soma"). Becomes a has_subdomain relationship.
        personal_domain: REQUIRED, same enforcement as domain. Which strata of Isaac's life/work this concept
            belongs to — ENUM, must be one of: paiab, sanctum, cave, misc, personal. Becomes a
            has_personal_domain relationship (same predicate name add_observation_batch already uses).
        concept: Full conceptual content explaining the entire concept, ideas, technical details, etc. Mentioning
            other concept names auto-creates relates_to links. NEVER truncated or modified by D2 — D2 only reads
            this to compute an informational [D2: ...] coverage tag on the response; it never gates the write.
        relationships: OPTIONAL. Additional custom relationships beyond the required three. Each object must have format: {"relationship": "relation_type", "related": ["concept_name1", "concept_name2", ...]}. Use for has_*, depends_on, validates, etc.
        desc_update_mode: How to update description if concept exists - "append" (default), "prepend", "replace", "path" (concept field is a file path — reads file content as description), or "edit" (surgical str-replace WITHIN the existing n.d: old_str_for_edit_case is found EXACTLY ONCE and replaced by the concept arg; the rest of n.d, including any CartonObj fence elsewhere, stays byte-identical; a per-node undo log is written; a 0-or->1 match fails gracefully leaving n.d unchanged)
        old_str_for_edit_case: ONLY used when desc_update_mode == "edit": the exact substring of the existing n.d to replace with the concept arg.
        hide_youknow: If False (default), SOMA validates and shows SOUP/ONT status. If True, skip validation - silent add.
        clear_stash: If True, discard any stashed payload for this concept before processing. Use when a previous stash has stale/wrong values.
        typed_values: OPTIONAL. List of [value, type] string pairs declaring programming types for relationship targets (e.g. [["Starsystem", "Domain"]] → SOMA receives tv('starsystem','domain')). Unknown values default to string_value.
        properties: OPTIONAL. Dict of {key: value} NODE PROPERTIES to set on the concept (the scratch lane — status/order/gates/sm config/…). This is the SECOND meaning-channel beside relationships: relationships become graph edges, properties become neo4j node properties. Values are scalars (str/int/float/bool) or flat lists of those — NEVER nested objects or concept-refs. Applied by the daemon via set_properties AFTER the node is written (same drain → no race; reserved/managed keys n/d/t/c/region/source/… are refused). Lets add_concept set BOTH edges and properties in one call (so you do not need a separate set_properties call).
        soma_run_id: OPTIONAL. The run-id of a parked SOMA compose-SUGGESTION you are ACCEPTING with this add. SOMA's L3b surfaces a pure-mereo suggestion (a unique admissible candidate for a still-empty required slot) in the `compose_suggestions=` verdict block with a stable run-id (concept.prop.candidate). You ACCEPT it not via a separate RPC but by simply SAYING the fill — calling add_concept with the relationship that fills the slot — and passing soma_run_id so the parked review item is marked resolved (observation is the only operation; the add IS the compose, re-derivation resumes past the gap). Omit to add normally. To REJECT a suggestion, just do not add it.

    Returns:
        Formatted result showing success/failure of file and Neo4j operations
    """
    # Shape gate (inert unless CARTON_NAME_EXPECTATIONS is set): if the agent fumbled a name whose
    # partials we already know for sure, bounce a self-correction message back as the NORMAL result.
    rej = _check_name_expectations(concept_name)
    if rej:
        return rej
    if personal_domain not in PERSONAL_DOMAINS:
        return (
            f"❌ Invalid personal_domain '{personal_domain}'. Must be one of: "
            f"{', '.join(PERSONAL_DOMAINS)}"
        )
    stash_key = concept_name.strip()
    if clear_stash:
        _concept_stash.pop(stash_key, None)
    try:
        description = concept
        # desc_update_mode="path": concept field is a file path, read contents as description
        if desc_update_mode == "path" and description:
            from pathlib import Path as _Path
            p = _Path(description)
            if p.exists() and p.is_file():
                description = p.read_text()
                desc_update_mode = "replace"  # file content replaces existing desc
            else:
                return f"ERROR: desc_update_mode='path' but file not found: {description}"
        # Build relationships from required params + optional custom rels
        relationships_dict = [
            {"relationship": "is_a", "related": list(is_a)},
            {"relationship": "part_of", "related": list(part_of)},
            {"relationship": "instantiates", "related": list(instantiates)},
            {"relationship": "produces", "related": list(produces)},
            {"relationship": "has_domain", "related": [domain]},
            {"relationship": "has_subdomain", "related": [subdomain]},
            {"relationship": "has_personal_domain", "related": [personal_domain]},
        ]
        if relationships:
            relationships_dict.extend([rel.model_dump() for rel in relationships])

        # Merge from stash if a previous call failed for this concept
        stashed = _concept_stash.pop(stash_key, None)
        if stashed:
            if not description and stashed.get("description"):
                description = stashed["description"]
            if desc_update_mode == "append" and stashed.get("desc_update_mode"):
                desc_update_mode = stashed["desc_update_mode"]
            # Merge relationships: extend each type with stashed values
            for srel in stashed.get("relationships_dict", []):
                match = [r for r in relationships_dict if r["relationship"] == srel["relationship"]]
                if match:
                    existing_set = set(match[0]["related"])
                    for item in srel["related"]:
                        if item not in existing_set:
                            match[0]["related"].append(item)
                else:
                    relationships_dict.append(srel)

        raw_result = add_concept_tool_func(concept_name, description, relationships_dict, desc_update_mode=desc_update_mode, hide_youknow=hide_youknow, shared_connection=_neo4j_conn, source=source, typed_values=typed_values, old_str_for_edit_case=old_str_for_edit_case, properties=properties)
        out = _format_concept_result(concept_name, raw_result)
        # soma_run_id: this add ACCEPTS a parked SOMA compose-suggestion. The add itself IS the fill
        # (the relationship written above composes the slot); we just mark the parked review item
        # resolved (mark-only, no re-compose). Reject = simply not adding, so there is no reject path here.
        if soma_run_id:
            rec = _mark_compose_suggestion_lib(soma_run_id, "accepted")
            if rec.get("status") == "not_found":
                out += f"\n⚠️ soma_run_id '{soma_run_id}' had no parked compose-suggestion to resolve"
            else:
                # P1 provenance substrate: the accept IS a fill, sourced from the reviewing agent.
                if _neo4j_conn is not None and rec.get("concept") and rec.get("prop"):
                    _record_fill_provenance_lib(rec["concept"], rec["prop"], source, "agent_review",
                                                _neo4j_conn.execute_query)
                out += f"\n✅ accepted compose-suggestion {soma_run_id} (this add IS the fill)"
        return out
    except Exception as e:
        # Stash full payload so next call only needs missing fields
        _concept_stash[stash_key] = {
            "description": description if 'description' in dir() else concept,
            "relationships_dict": relationships_dict if 'relationships_dict' in dir() else [],
            "desc_update_mode": desc_update_mode,
        }
        traceback.print_exc()
        return (
            f"❌ {str(e)}\n\n"
            f"📦 STASHED: Payload saved for '{concept_name}'. "
            f"Next add_concept for this name only needs the missing fields — "
            f"everything else merges from stash."
        )


@mcp.tool()
def edit_carton_obj(
    concept_name: str,
    kvobj_name: str,
    key_path: str,
    op: str,
    value: str = None,
) -> str:
    """Edit (or read) one leaf of a structured KV object embedded in a concept's description.

    A CartON KV object is a `<CartonObj name=...>{ JSON-with-bare-refs }</CartonObj>` fence
    stored inside a concept's description (n.d). A BARE Title_Underscore token in the JSON is
    a carton concept REF; a quoted string is literal data. This tool reads or edits ONE leaf
    of ONE named fence, leaving prose and sibling fences byte-identical; writes go through the
    sanctioned observation-worker replace path (applied asynchronously by the daemon).

    Args:
        concept_name: The concept whose description holds the fence.
        kvobj_name:   The <CartonObj name=...> to target.
        key_path:     Dotted/indexed path into the JSON, e.g. "units.cave.tier" or "order.1".
                      Empty string targets the whole object (set replaces the entire body).
                      Ignored for remove_fence.
        op:           "get" | "set" | "append" | "remove" | "remove_fence".
                      remove_fence deletes the ENTIRE named fence (the ONLY way to delete a whole
                      CartonObj — an ordinary prose write can never drop one, thanks to the
                      fence-preservation guard).
        value:        For set/append — a value STRING interpreted as: a bare Title_Underscore
                      token = a carton concept ref; valid JSON = that JSON value; otherwise a
                      literal string. Ignored for get/remove/remove_fence.

    Returns:
        For get: the value at key_path. For set/append/remove: a queued confirmation
        (the daemon applies the n.d replace asynchronously).
    """
    from carton_mcp import carton_kv as _ckv

    interpreted = None
    if op in ("set", "append"):
        if value is None:
            return f"❌ op '{op}' requires a value"
        v = value.strip()
        if _ckv.is_title_underscore(v):
            interpreted = {"$ref": v}                       # bare ref
        else:
            try:
                interpreted = json.loads(value)             # JSON literal/structure
            except (json.JSONDecodeError, ValueError):
                interpreted = value                         # plain literal string

    result = _edit_carton_obj_lib(
        concept_name, kvobj_name, key_path, op, interpreted, shared_connection=_neo4j_conn
    )
    if not result.get("success"):
        return f"❌ {result.get('error', 'edit_carton_obj failed')}"
    if op == "get":
        return f"✅ {concept_name}.{kvobj_name}[{key_path}] = {json.dumps(result['value'])}"
    return (f"✅ queued {op} on {concept_name}.{kvobj_name}[{key_path}] "
            f"(queue file {result['queued']}); the daemon will apply the n.d replace.")


@mcp.tool()
def validate_carton_obj(concept_name: str, kvobj_name: str) -> str:
    """Validate a CartON KV object fence against its schema and check its refs resolve.

    Two checks: (a) if the fence has a schema=<Concept> attr, the referenced schema concept's
    is_schema=true fence (a json-schema) is loaded and the fence body is validated against it —
    reporting WHICH key failed and why; (b) every bare Title_Underscore ref in the body is
    checked to resolve to an existing concept, with fuzzy did-you-mean suggestions for any that
    don't (the cure for silently-spawned stubs).

    Args:
        concept_name: The concept whose description holds the fence.
        kvobj_name:   The <CartonObj name=...> to validate.

    Returns:
        A VALID/INVALID report listing any bad keys (schema violations) and unresolved refs
        (with did-you-mean suggestions).
    """
    res = _validate_carton_obj_lib(concept_name, kvobj_name, _neo4j_conn)
    if not res.get("success"):
        return f"❌ {res.get('error', 'validate_carton_obj failed')}"
    head = "✅ VALID" if res["valid"] else "❌ INVALID"
    schema_note = f" (schema {res['schema']})" if res.get("schema") else " (no schema attr)"
    lines = [f"{head}: {concept_name}.{kvobj_name}{schema_note}"]
    for e in res.get("errors", []):
        lines.append(f"  • bad key [{e['path']}]: {e['message']}")
    for ref, sugg in res.get("unresolved_refs", {}).items():
        dym = f" — did you mean: {', '.join(sugg)}" if sugg else " — no close matches found"
        lines.append(f"  • unresolved ref '{ref}'{dym}")
    return "\n".join(lines)


@mcp.tool()
def split_content_concept(concept_name: str, raw_content: str) -> str:
    """Split a concept's raw CONTENT off of its description into its own node.

    Use when `concept_name`'s existing description (n.d) is judged to be raw CONTENT (a data
    dump, a pasted document, verbatim info) rather than an actual DESCRIPTION that names/traces
    the concept's relationships (per `carton-description-is-annotation-not-knowledge`). Creates
    `{concept_name}_Desc_Content` holding `raw_content` verbatim (never truncated/modified),
    `is_a Desc_Content`, `part_of {concept_name}`, and adds
    `{concept_name} -[has_desc_content]-> {concept_name}_Desc_Content`. Ensures the universal
    `Desc_Content` type concept exists (created once, checked first).

    This tool does NOT rewrite `{concept_name}`'s own description, and does NOT atomize the
    split-off content into further sub-concepts — both are separate, judgment-driven steps for
    the caller (a coherer agent) to do afterward.

    Args:
        concept_name: The concept whose description is raw content, not a real description.
        raw_content: The exact raw content to preserve verbatim in the new content node.

    Returns:
        A queued-confirmation string; the daemon applies the writes asynchronously (verify via
        query_wiki_graph in a LATER turn, not the same turn's return value).
    """
    return _split_content_concept_lib(concept_name, raw_content, shared_connection=_neo4j_conn)


@mcp.tool()
def create_branching_sm(concept_name: str, state_machines: list, domain: str, subdomain: str,
                        personal_domain: str, sm_chain_name: str = None,
                        produces: Optional[List[str]] = None) -> str:
    """Directly author a branching CartON retrieval state-machine (an `Sm_Chain` gate stack) — the
    programmatic third authoring path alongside the dragonbones EC and treeshell `🐉🦴` annotation
    surfaces (see the `dragonbones-carton-retrieval-state-machines` skill).

    This is a genuinely THIN pass-through to the already-existing, already-tested carton SM factory
    `carton_mcp.sm_gate.create_sm_chain_live` — it does no shaping, no validation, no defaulting of its
    own (beyond forwarding domain/subdomain/personal_domain/produces, which create_sm_chain_live itself
    requires/validates — see below); it forwards `concept_name`/`state_machines`/`sm_chain_name`
    straight through and returns whatever the factory returns. All the SM-building logic (the 2-SM
    gating stack, the per-step `NEXT_STEP` edges, the branches-vs-scalar-`next` step shape) already
    exists and is already tested in `sm_gate.py`; nothing here re-describes that design.

    Args:
        concept_name: The concept whose retrieval this SM stack gates (gets the `HAS_SM_CHAIN` edge).
        state_machines: Ordered list of state-machine specs, each
            `{"name": <sm node name>, "steps": [{"id": <step node name>,
            "required_pattern": <regex str or None>, "text": <instruction str>,
            "branches": [{"to": <step id>, "required_pattern": <regex str or None>,
            "weight": <float, default 1.0>}, ...]}, ...]}`. A step may also still use the OLD
            single-`"next": <step id or None>` form instead of `"branches"` (accepted unchanged).
            The list's order = each SM's order on `SM_CHAIN_RUNS` (index 0 = show-SM / OFF per the
            stack-size rule; index 1+ = gating, once the stack holds >1 SM).
        domain: REQUIRED (Isaac 2026-07-04: "sm_gate should require it for the abstraction about the
            sm"). Tags the Sm_Chain node with a has_domain relationship. Passed straight through to
            create_sm_chain_live, which raises if missing.
        subdomain: REQUIRED, same status as domain — has_subdomain.
        personal_domain: REQUIRED, same status as domain — has_personal_domain. Enum-validated by
            create_sm_chain_live against PERSONAL_DOMAINS (paiab/sanctum/cave/misc/personal); raises
            if invalid.
        sm_chain_name: Optional `Sm_Chain` node name; defaults to `f"{concept_name}_Sm_Chain"`.
        produces: OPTIONAL. Tags the Sm_Chain node with produces relationships if given.

    Returns:
        The factory's result dict `{concept, sm_chain, sms: [sm names], steps: [step names],
        gated: bool}` (`gated` is `True` iff `len(state_machines) > 1`), formatted to a string via
        this file's shared `_fmt()` (every MCP tool in this server returns `str`; `_fmt()` is the
        established convention for rendering a library function's dict result as one).
    """
    from carton_mcp.sm_gate import create_sm_chain_live
    result = create_sm_chain_live(concept_name, state_machines, sm_chain_name=sm_chain_name,
                                  domain=domain, subdomain=subdomain, personal_domain=personal_domain,
                                  produces=produces)
    return _fmt(result)


@mcp.tool()
def set_properties(concept_name: str, properties: dict, mode: str = "merge") -> str:
    """Set or remove neo4j node properties on an EXISTING concept — SYNCHRONOUSLY.

    Properties are arbitrary structured fields on a concept node, SEPARATE from its
    description (n.d) and its relationships. Unlike every other write tool, this writes
    DIRECTLY (read-after-write), not through the async observation queue — it is safe to
    do so because properties never touch n.d, so no linker/fence machinery is involved.
    Use this to give a concept a status, an order, a file reference, a tier, etc.

    Args:
        concept_name: The concept to update. It MUST already exist (this never creates nodes).
        properties:   A dict of {key: value}. For mode="merge" the values are SET; for
                      mode="remove" the keys are REMOVEd (the values are ignored).
        mode:         "merge" (default) = set the given keys; "remove" = remove them.

    Reserved keys (n, d, t, c, linked, score, source, timeline_linked, odyssey_linked,
    system_generated, last_modified) are REFUSED and reported — they are managed fields.
    Value types: str/int/float/bool and flat lists of those. A nested dict value is REFUSED
    (flatten it or json.dumps it yourself).

    Property doctrine (Option-4 hybrid): scratch classes (Blog_Request, Chain_Step, etc.)
    and untyped nodes get a DIRECT property write only; ontology-bearing classes ALSO emit a
    thin SOMA observation trail. The trail NEVER blocks or fails the direct write (SOMA down
    → the property is still set; the report shows trail: scratch-lane | emitted | soma-unreachable).

    Returns: a report of which keys were updated/removed and which were refused.
    """
    res = _set_concept_properties_lib(
        concept_name, properties, mode=mode, shared_connection=_neo4j_conn)
    if not res.get("success"):
        return f"❌ {res.get('error', 'set_properties failed')}"
    parts = []
    if res.get("updated_keys"):
        parts.append(f"set {', '.join(res['updated_keys'])}")
    if res.get("removed_keys"):
        parts.append(f"removed {', '.join(res['removed_keys'])}")
    if res.get("refused_keys"):
        parts.append(f"REFUSED (reserved) {', '.join(res['refused_keys'])}")
    if res.get("error"):
        parts.append(res["error"])
    body = "; ".join(parts) if parts else "no changes"
    out = f"✅ {concept_name}: {body}"
    # Append the property→SOMA trail status line (only present on merge-mode writes).
    if res.get("trail"):
        out += f"\ntrail: {res['trail']}"
    return out


@mcp.tool()
def query_by_properties(where: dict, limit: int = 25) -> str:
    """Find concepts whose properties EXACTLY match every key/value in `where` (AND).

    Exact-match lookup over neo4j node properties (the structured fields set via
    set_properties). Property VALUES are passed as parameters (never interpolated), so
    this is injection-safe.

    Args:
        where: A non-empty dict of {property_key: exact_value} to match (all must match).
        limit: Maximum number of concepts to return (default 25).

    Returns: each matching concept's name plus the value of every key in `where`.
    """
    # SM-GATE (increment 2b): gate this retrieval call. No-op by default.
    _sm_gate_check("query_by_properties", repr(where))
    res = _query_concepts_by_properties_lib(where, limit=limit, shared_connection=_neo4j_conn)
    if not res.get("success"):
        return f"❌ {res.get('error', 'query_by_properties failed')}"
    results = res.get("results", [])
    if not results:
        return "(no concepts match)"
    return _fmt(results)


@mcp.tool()
def remove_relationship(source: str, rel_type: str, target: str) -> str:
    """Delete exactly the relationship (source)-[:REL_TYPE]->(target) — SYNCHRONOUSLY.

    Relationship CREATION is done via add_concept; this is the deletion counterpart, which
    did not exist before. The rel_type is strictly sanitized (^[A-Za-z_]+$) because a
    relationship type cannot be a Cypher parameter; source/target are passed as parameters.

    Args:
        source:   The source concept name.
        rel_type: The relationship type to delete (e.g. "PART_OF", "RELATED_TO").
        target:   The target concept name.

    Returns: how many relationships were deleted (0 if that edge did not exist).
    """
    res = _remove_concept_relationship_lib(
        source, rel_type, target, shared_connection=_neo4j_conn)
    if not res.get("success"):
        return f"❌ {res.get('error', 'remove_relationship failed')}"
    n = res.get("deleted_count", 0)
    return f"✅ deleted {n} relationship(s): ({source})-[:{rel_type}]->({target})"


@mcp.tool()
def add_document_concept(
    concept_name: str,
    description: str,
    canonical_path: str,
    template: str = None,
    relationships: Optional[List[ConceptRelationship]] = None
) -> str:
    """Index a document in Carton with canonical path and optional template

    Use this when you want Carton to act as a database/index for documents.
    The description should be a SUMMARY, not the full content.
    The canonical_path points to where the actual document lives.
    The template specifies how to parse/render the document.

    Args:
        concept_name: Name of the document concept (will be normalized)
        description: Summary of the document (not full content)
        canonical_path: Absolute path to the actual document file
        template: Optional metastack template name for parsing/rendering
        relationships: Additional relationships for the concept

    Returns:
        Formatted result showing success/failure
    """
    # KNOWN BUG (found 2026-07-03, not yet fixed — Isaac: deprioritized for now): the `rels` list
    # built below carries only has_canonical_path / uses_template / is_a — no part_of,
    # has_personal_domain, or has_actual_domain. It is queued via add_observation() (fire-and-forget,
    # returns immediately), but the ACTUAL validation requiring is_a+part_of+has_personal_domain+
    # has_actual_domain runs LATER, ASYNCHRONOUSLY, inside _add_observation_worker
    # (add_concept_tool.py, the block iterating all_part_concepts) when the daemon drains the queue.
    # So this tool reports "✅ queued" immediately and then silently fails in the daemon — the caller
    # never sees the real failure unless they separately run carton_management(check_failed_observations=True).
    try:
        # Build relationships list
        rels = []

        # Add canonical path as relationship
        rels.append({
            "relationship": "has_canonical_path",
            "related": [canonical_path]
        })
        
        # Add template if provided
        if template:
            rels.append({
                "relationship": "uses_template",
                "related": [template]
            })
        
        # Add is_a Document_Concept
        rels.append({
            "relationship": "is_a",
            "related": ["Document_Concept"]
        })
        
        # Add any additional relationships
        if relationships:
            for rel in relationships:
                rels.append(rel.model_dump())
        
        # Use observation queue for speed (instant) instead of direct add_concept (30s+)
        observation_data = {
            "implementation": [{
                "name": concept_name,
                "description": description,
                "relationships": rels
            }],
            "confidence": 1.0,
            "hide_youknow": True  # Skip SOMA validation (POST :8091/event): documents are index nodes, not ontology-validated concepts
        }
        
        result = add_observation(observation_data)
        return f"✅ ✅ Document concept queued: {result}"
    except Exception as e:
        traceback.print_exc()
        return f"❌ Error creating document concept: {str(e)}"



@mcp.tool()
def add_observation_batch(observation_data: dict, hide_youknow: bool = False) -> str:
    """Create observation capturing complete cognitive state

    Format example: {"insight_moment": [{"name": "Discord_Platform_Choice", "description": "Realized Discord is ideal for egregore launch", "relationships": [{"relationship": "is_a", "related": ["Platform_Decision"]}, {"relationship": "part_of", "related": ["Launch_Strategy"]}, {"relationship": "has_personal_domain", "related": ["cave"]}, {"relationship": "has_actual_domain", "related": ["Business_Strategy"]}]}], "struggle_point": [{"name": "Channel_Structure_Confusion", "description": "Struggled with organizing public vs private channels", "relationships": [{"relationship": "is_a", "related": ["Design_Challenge"]}, {"relationship": "part_of", "related": ["Discord_Architecture"]}, {"relationship": "has_personal_domain", "related": ["cave"]}, {"relationship": "has_actual_domain", "related": ["System_Design"]}]}], "daily_action": [{"name": "Channel_Setup", "description": "Organized AI LAB Discord channels", "relationships": [{"relationship": "is_a", "related": ["Implementation_Task"]}, {"relationship": "part_of", "related": ["AI_LAB_Discord"]}, {"relationship": "has_personal_domain", "related": ["cave"]}, {"relationship": "has_actual_domain", "related": ["Infrastructure"]}]}], "implementation": [{"name": "AI_LAB_Discord", "description": "Discord server for frameworks and COGLOG", "relationships": [{"relationship": "is_a", "related": ["Discord_Server"]}, {"relationship": "part_of", "related": ["Isaac_Infrastructure"]}, {"relationship": "has_personal_domain", "related": ["cave"]}, {"relationship": "has_actual_domain", "related": ["Infrastructure"]}]}], "emotional_state": [{"name": "Clarity_About_Path", "description": "Feeling clear about release strategy", "relationships": [{"relationship": "is_a", "related": ["Emotional_State"]}, {"relationship": "part_of", "related": ["Development_Journey"]}, {"relationship": "has_personal_domain", "related": ["cave"]}, {"relationship": "has_actual_domain", "related": ["Personal_Development"]}]}], "confidence": 0.9}

    Args:
        observation_data: ALL FIVE TAGS REQUIRED (multiple concepts each with is_a, part_of, has_personal_domain, has_actual_domain relationships), confidence float. Personal domains (enum): paiab, sanctum, cave, misc, personal. Actual domains: flexible.

        OPTIONAL desc_update_mode per concept:
        - "append" (default): Add new description after existing
        - "prepend": Add new description before existing
        - "replace": Sink old version to _vN, use only new description

        hide_youknow: If False (default), the queued concepts are validated via SOMA (POST localhost:8091/event), which returns each concept's SOUP/CODE/SYSTEM_TYPE/ONT region status and warns on issues. If True, skip SOMA validation - silent add. (Param name is vestigial: YOUKNOW was removed 2026-06-15; SOMA is the validator.)

    Returns:
        Summary
    """
    try:
        # GEOMETRY CHECK (warn, don't block)
        geometry_warning = _check_observation_geometry(observation_data)

        # Merge from stash if previous observation failed
        stashed_obs = _concept_stash.pop("_observation_pending", None)
        if stashed_obs:
            # Merge: current tags take precedence, stashed fills gaps
            for tag in ("insight_moment", "struggle_point", "daily_action", "implementation", "emotional_state"):
                if tag not in observation_data and tag in stashed_obs:
                    observation_data[tag] = stashed_obs[tag]
            if "confidence" not in observation_data and "confidence" in stashed_obs:
                observation_data["confidence"] = stashed_obs["confidence"]

        observation_data["hide_youknow"] = hide_youknow
        result = add_observation(observation_data)
        if geometry_warning:
            warning_text = geometry_warning.replace("❌ GEOMETRY ERROR:", "").strip()
            return f"✅ {result}\n\n⚠️ WARN: GEOMETRY ERROR: {warning_text} -- You may want to keep observing accordingly"
        return f"✅ {result}"
    except Exception as e:
        _concept_stash["_observation_pending"] = observation_data
        traceback.print_exc()
        return (
            f"❌ {str(e)}\n\n"
            f"📦 STASHED: Observation saved. Next add_observation_batch only needs "
            f"missing tags — existing tags merge from stash."
        )


@mcp.tool()
def observe_from_identity_pov(observation_data: dict, agent_identity: str = None, hide_youknow: bool = False) -> str:
    """Create observation from agent identity perspective

    Resolves agent identity via: env var AGENT_IDENTITY (takes priority) > agent_identity param.
    Ensures {identity}_Collection exists, adds concepts as PART_OF that collection,
    and transforms has_actual_domain to has_domain.

    The agent identity collection follows the proper hierarchy:
    - {AGENT_IDENTITY}_Collection IS_A Identity_Collection
    - Identity_Collection IS_A Carton_Collection
    - Concept PART_OF {AGENT_IDENTITY}_Collection

    Same format as add_observation_batch.

    Args:
        agent_identity: Identity name (used if AGENT_IDENTITY env var not set).
        hide_youknow: If False (default), the queued concepts are validated via SOMA (POST localhost:8091/event), which returns each concept's SOUP/CODE/SYSTEM_TYPE/ONT region status and warns on issues. If True, skip SOMA validation. (Param name is vestigial: YOUKNOW was removed 2026-06-15; SOMA is the validator.)

    Returns:
        Summary
    """
    import os
    from .add_concept_tool import normalize_concept_name

    try:
        # GEOMETRY CHECK (warn, don't block)
        geometry_warning = _check_observation_geometry(observation_data)

        observation_data["hide_youknow"] = hide_youknow
        # Env var takes priority (hardcoded identity). If unset, accept input.
        resolved_identity = os.getenv('AGENT_IDENTITY') or agent_identity
        if not resolved_identity:
            return "❌ No agent identity: set AGENT_IDENTITY env var or pass agent_identity param"
        agent_identity = resolved_identity

        # Normalize the collection name
        collection_name = f"{normalize_concept_name(agent_identity)}_Collection"

        # Ensure the agent's identity collection exists
        _ensure_identity_collection_exists(collection_name, agent_identity)

        # Transform observation_data
        for tag, concepts in observation_data.items():
            if tag in ("confidence", "hide_youknow"):
                continue

            for concept in concepts:
                if 'relationships' not in concept:
                    concept['relationships'] = []

                new_rels = []
                for rel in concept['relationships']:
                    rel_type = rel.get('relationship')
                    
                    if rel_type == 'has_actual_domain':
                        # Transform to has_domain (proper ontological relationship)
                        new_rels.append({
                            'relationship': 'has_domain',
                            'related': rel['related']
                        })
                    elif rel_type == 'has_personal_domain':
                        # Keep personal domain as-is (enum: paiab, sanctum, cave, etc.)
                        new_rels.append(rel)
                    elif rel_type == 'has_subdomain':
                        # KEPT (Isaac 2026-07-03): a prior version of this code stripped
                        # has_subdomain/has_subsubdomain as "artifacts of a broken approach,"
                        # on the theory domain hierarchy should come from IS_A/PART_OF alone.
                        # That is now explicitly overridden — domain/subdomain/personal_domain
                        # are REQUIRED on every add_concept call (the plain add_concept MCP
                        # tool enforces this), so silently deleting has_subdomain here would
                        # undo that requirement for every identity-POV observation. Kept as-is.
                        new_rels.append(rel)
                    else:
                        new_rels.append(rel)

                # Add PART_OF relationship to the agent's identity collection
                new_rels.append({
                    'relationship': 'part_of',
                    'related': [collection_name]
                })

                concept['relationships'] = new_rels

        result = add_observation(observation_data)
        if geometry_warning:
            warning_text = geometry_warning.replace("❌ GEOMETRY ERROR:", "").strip()
            return f"✅ [{agent_identity}] {result}\n\n⚠️ WARN: GEOMETRY ERROR: {warning_text} -- You may want to keep observing accordingly"
        return f"✅ [{agent_identity}] {result}"

    except Exception as e:
        traceback.print_exc()
        return f"❌ Error: {str(e)}"


def _ensure_identity_collection_exists(collection_name: str, agent_identity: str):
    """Ensure the agent's identity collection exists with proper typing.
    
    Creates if needed:
    - {AGENT_IDENTITY}_Collection IS_A Identity_Collection
    - Identity_Collection IS_A Carton_Collection (should already exist from bootstrap)
    """
    try:
        # Check if collection already exists
        check_query = """
        MATCH (c:Wiki {n: $collection_name})
        RETURN c.n as name
        """
        result = utils.query_wiki_graph(check_query, {"collection_name": collection_name})

        if not (result.get("success") and result.get("data")):
            # Collection doesn't exist - create it
            # First ensure the collection type hierarchy is bootstrapped
            utils.bootstrap_collection_types()

            # Create the identity collection
            from .add_concept_tool import add_concept_tool_func

            description = f"Identity collection for {agent_identity} agent. Contains all concepts observed from this agent's perspective."
            relationships = [
                {
                    "relationship": "is_a",
                    "related": ["Identity_Collection"]
                }
            ]

            add_concept_tool_func(
                collection_name,
                description,
                relationships,
                desc_update_mode="append",
                hide_youknow=True,  # Don't validate collection concepts
                shared_connection=_neo4j_conn
            )

            logger.info(f"Created identity collection: {collection_name}")

        # S4 — the collection->entity transition (Isaac 2026-06-23, the 'identities are actual things'
        # model). For BOTH the just-created AND the already-existing collection, co-ensure the
        # Agent_Identity ENTITY ('<TitleCase(handle)>_Identity', is_a Agent_Identity) and link it
        # HAS_COLLECTION to this collection (the reflection store). Idempotent (MERGE), best-effort, and
        # NOT gated on _sm_gate_on (the entity is the identity MODEL, independent of SM-gating). Uses the
        # in-process _sm_run. No frame/rules/skillset here — observe has only the identity + its collection;
        # equip_persona (S3) fills the persona-config parts. Never blocks the observation.
        try:
            _sm_gate.resolve_identity_entity(agent_identity, _sm_run)
        except Exception as e:
            logger.warning(f"Could not co-create Agent_Identity entity for {agent_identity}: {e}")

    except Exception as e:
        logger.warning(f"Could not ensure identity collection exists: {e}")
        # Don't fail the observation - the collection might just not have the IS_A yet


@mcp.tool()
def carton_management(
    restart_bg_server: bool = False,
    get_git_repo_url: bool = False,
    get_carton_dir: bool = False,
    get_carton_guide: bool = False,
    get_requires_evolution_list: bool = False,
    sync_rag: bool = False,
    check_failed_observations: bool = False,
    retry_failed_observations: bool = False,
    enable_gps: bool = False,
    disable_gps: bool = False,
    get_gps_status: bool = False,
    page: Optional[int] = None
) -> str:
    """CartON management utility

    Args:
        restart_bg_server: Kill and restart observation worker daemon
        get_git_repo_url: Return GitHub repository URL
        get_carton_dir: Return carton queue directory path
        get_carton_guide: Return CartON usage guide
        get_requires_evolution_list: Return paginated list of concepts requiring evolution
        sync_rag: Sync all concepts to ChromaRAG for semantic search
        check_failed_observations: Check for failed observation files in queue
        retry_failed_observations: Retry failed observations marked with "fixed": true
        enable_gps: Enable GPS auto-injection hook
        disable_gps: Disable GPS auto-injection hook
        get_gps_status: Get current GPS hook status
        page: Page number for requires_evolution_list (100 items per page, default: 1)

    Returns:
        Formatted string with requested information (one per line)
    """
    import subprocess
    import signal

    result_parts = []

    if restart_bg_server:
        try:
            # Kill existing daemon
            result = subprocess.run(
                ['pkill', '-f', 'observation_worker_daemon.py'],
                capture_output=True,
                text=True
            )

            # Start new daemon
            github_pat = os.getenv('GITHUB_PAT')
            repo_url = os.getenv('REPO_URL')
            neo4j_uri = os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687')
            neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
            neo4j_password = os.getenv('NEO4J_PASSWORD', 'password')
            heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
            openai_api_key = os.getenv('OPENAI_API_KEY')

            env = os.environ.copy()
            env_update = {
                'GITHUB_PAT': github_pat,
                'REPO_URL': repo_url,
                'NEO4J_URI': neo4j_uri,
                'NEO4J_USER': neo4j_user,
                'NEO4J_PASSWORD': neo4j_password,
                'HEAVEN_DATA_DIR': heaven_data_dir,
                'OPENAI_API_KEY': openai_api_key
            }
            # Filter out None values to avoid subprocess error
            env.update({k: v for k, v in env_update.items() if v is not None})

            daemon_path = Path(__file__).parent / 'observation_worker_daemon.py'
            log_path = '/tmp/carton_worker.log'

            process = subprocess.Popen(
                ['python3', str(daemon_path)],
                env=env,
                stdout=open(log_path, 'w'),
                stderr=subprocess.STDOUT,
                start_new_session=True
            )

            result_parts.append(f"✅ Daemon restarted: PID {process.pid}")

        except Exception as e:
            traceback.print_exc()
            result_parts.append(f"❌ Daemon restart failed: {e}")

    if get_git_repo_url:
        repo_url = os.getenv('REPO_URL', 'https://github.com/sancovp/private_wiki')
        result_parts.append(f"Git repo: {repo_url}")

    if get_carton_dir:
        heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        queue_dir = Path(heaven_data_dir) / 'carton_queue'
        result_parts.append(f"Queue dir: {queue_dir}")

    if get_carton_guide:
        guide = """
CartON Usage Guide:

1. **Observations** (instant, async processing):
   - Use add_observation_batch() to capture insights
   - Returns immediately with queue confirmation
   - Background daemon processes and commits

2. **Concepts** (direct creation):
   - Use add_concept() for individual concepts
   - Creates files + queues Neo4j write

3. **Background Daemon**:
   - Processes queue files from $HEAVEN_DATA_DIR/carton_queue/
   - ONE git commit when queue empty
   - ONE git push after commit
   - Check logs: tail -f /tmp/carton_worker.log

4. **Management**:
   - Restart daemon: carton_management(restart_bg_server=True)
   - Check queue: ls $HEAVEN_DATA_DIR/carton_queue/
   - Processed files: ls $HEAVEN_DATA_DIR/carton_queue/processed/
"""
        result_parts.append(guide.strip())

    if get_requires_evolution_list:
        try:
            # Default to page 1 if not specified
            current_page = page if page is not None else 1
            items_per_page = 100
            skip = (current_page - 1) * items_per_page

            # Query for concepts requiring evolution
            query = """
            MATCH (c:Wiki)-[r:REQUIRES_EVOLUTION]->(re:Wiki {n: "Requires_Evolution"})
            RETURN c.n as name, c.d as description, r.reason as reason, r.ts as timestamp
            ORDER BY r.ts DESC
            SKIP $skip
            LIMIT $limit
            """

            result = utils.query_wiki_graph(query, {"skip": skip, "limit": items_per_page})

            if result.get("success") and result.get("data"):
                concepts = result["data"]

                # Get total count
                count_query = """
                MATCH (c:Wiki)-[:REQUIRES_EVOLUTION]->(re:Wiki {n: "Requires_Evolution"})
                RETURN count(c) as total
                """
                count_result = utils.query_wiki_graph(count_query, {})
                total = count_result["data"][0]["total"] if count_result.get("success") else 0

                total_pages = (total + items_per_page - 1) // items_per_page

                evolution_list = f"Requires Evolution (Page {current_page}/{total_pages}, {total} total):\n"
                for i, concept in enumerate(concepts, skip + 1):
                    reason = concept.get("reason", "No reason specified")
                    evolution_list += f"{i}. {concept['name']} - {reason}\n"

                result_parts.append(evolution_list.strip())
            else:
                result_parts.append("No concepts require evolution")

        except Exception as e:
            traceback.print_exc()
            result_parts.append(f"❌ Error getting evolution list: {e}")

    if sync_rag:
        try:
            from neo4j import GraphDatabase
            import re as _re


            neo4j_uri = os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687')
            neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
            neo4j_pass = os.getenv('NEO4J_PASSWORD', 'password')

            driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
            with driver.session() as session:
                records = session.run(
                    "MATCH (c:Wiki) RETURN c.n AS name, c.d AS desc LIMIT 200000"
                ).data()
            driver.close()

            # Filter: skip empty, single-char, numeric, observations, syncs, transcripts
            # NOTE: Use IGNORECASE — CartON has mixed casing (UserThought vs Userthought)
            _I = _re.IGNORECASE
            skip_patterns = [
                _re.compile(r'^[A-Za-z0-9]$'),
                _re.compile(r'^\d+$'),
                _re.compile(r'^\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_Observation$', _I),
                _re.compile(r'^Sync_\d+$', _I),
                _re.compile(r'^Day_\d{4}_\d{2}_\d{2}$'),
                _re.compile(r'^Raw_Conversation_Timeline_', _I),
                _re.compile(r'^Conversation_', _I),
                _re.compile(r'^User_?Thought_', _I),
                _re.compile(r'^Agent_?Message_', _I),
                _re.compile(r'^Tool_?Call_', _I),
                _re.compile(r'^Coglog_', _I),
                _re.compile(r'^Iteration_', _I),
                _re.compile(r'^User_Message_', _I),
                _re.compile(r'^Phase_Summary_', _I),
                _re.compile(r'^Executive_Summary_', _I),
                _re.compile(r'^Subphase_', _I),
                _re.compile(r'^Iteration_Summary_', _I),
                _re.compile(r'.*_v\d+$'),
            ]

            # Route concepts to partitioned collections (via the chroma daemon — zero chroma import here)
            by_collection: dict[str, list[dict]] = {}
            for r in records:
                name = r.get("name") or ""
                if not name or name == "Requires_Evolution":
                    continue
                if any(p.match(name) for p in skip_patterns):
                    continue
                desc = r.get("desc") or name
                coll = _daemon_route(name)
                by_collection.setdefault(coll, []).append({"id": name, "text": f"{name}: {desc}"})

            # Batch upsert per collection
            total_synced = 0
            BATCH = 500
            for coll_name, items in by_collection.items():
                for i in range(0, len(items), BATCH):
                    batch = items[i:i+BATCH]
                    ids = [b["id"] for b in batch]
                    docs = [b["text"] for b in batch]
                    metas = [{"concept_name": b["id"]} for b in batch]
                    _daemon_add_texts(coll_name, ids, docs, metas)
                total_synced += len(items)

            coll_summary = ", ".join(f"{k}:{len(v)}" for k, v in by_collection.items())
            result_parts.append(
                f"✅ RAG sync complete: {total_synced} concepts across {len(by_collection)} collections ({coll_summary})"
            )

        except Exception as e:
            traceback.print_exc()
            result_parts.append(f"❌ RAG sync error: {str(e)}")

    if check_failed_observations:
        try:
            heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
            failed_dir = Path(heaven_data_dir) / 'carton_queue' / 'failed'

            if not failed_dir.exists():
                result_parts.append("✅ No failed observations (failed directory doesn't exist)")
            else:
                failed_count = len(list(failed_dir.glob('*.json')))

                if not failed_count:
                    result_parts.append("✅ No failed observations")
                else:
                    result_parts.append(f"❌ {failed_count} failed observations in: {failed_dir}")

        except Exception as e:
            traceback.print_exc()
            result_parts.append(f"❌ Error checking failed observations: {str(e)}")

    if retry_failed_observations:
        try:
            heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
            failed_dir = Path(heaven_data_dir) / 'carton_queue' / 'failed'
            queue_dir = Path(heaven_data_dir) / 'carton_queue'

            if not failed_dir.exists():
                result_parts.append("✅ No failed observations to retry")
            else:
                failed_files = sorted(failed_dir.glob('*.json'))

                if not failed_files:
                    result_parts.append("✅ No failed observations to retry")
                else:
                    retried = []
                    skipped = []

                    for failed_file in failed_files:
                        try:
                            # Read and check for "fixed": true
                            with open(failed_file, 'r') as f:
                                data = json.load(f)

                            if data.get('fixed') == True:
                                # Clean the observation data
                                data.pop('fixed', None)
                                data.pop('error_message', None)
                                data.pop('error_traceback', None)

                                # Write cleaned data
                                with open(failed_file, 'w') as f:
                                    json.dump(data, f)

                                # Move back to queue
                                queue_file = queue_dir / failed_file.name
                                failed_file.rename(queue_file)
                                retried.append(failed_file.name)
                            else:
                                skipped.append(failed_file.name)

                        except Exception as file_error:
                            result_parts.append(f"⚠️  Error processing {failed_file.name}: {file_error}")

                    retry_report = f"✅ Retry complete:\n"
                    retry_report += f"   Retried: {len(retried)}\n"
                    retry_report += f"   Skipped (not marked fixed): {len(skipped)}\n"

                    if retried:
                        retry_report += f"\nRetried files:\n"
                        for name in retried:
                            retry_report += f"   - {name}\n"

                    result_parts.append(retry_report.strip())

        except Exception as e:
            traceback.print_exc()
            result_parts.append(f"❌ Error retrying failed observations: {str(e)}")

    if enable_gps:
        try:
            heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
            gps_flag_file = Path(heaven_data_dir) / 'carton_gps_enabled'
            gps_flag_file.write_text('1')
            result_parts.append("✅ GPS auto-injection enabled")
        except Exception as e:
            traceback.print_exc()
            result_parts.append(f"❌ Error enabling GPS: {str(e)}")

    if disable_gps:
        try:
            heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
            gps_flag_file = Path(heaven_data_dir) / 'carton_gps_enabled'
            if gps_flag_file.exists():
                gps_flag_file.unlink()
            result_parts.append("✅ GPS auto-injection disabled")
        except Exception as e:
            traceback.print_exc()
            result_parts.append(f"❌ Error disabling GPS: {str(e)}")

    if get_gps_status:
        try:
            heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
            gps_flag_file = Path(heaven_data_dir) / 'carton_gps_enabled'
            if gps_flag_file.exists():
                result_parts.append("GPS auto-injection: ✅ ENABLED")
            else:
                result_parts.append("GPS auto-injection: ❌ DISABLED")
        except Exception as e:
            traceback.print_exc()
            result_parts.append(f"❌ Error checking GPS status: {str(e)}")

    return "\n".join(result_parts) if result_parts else "No actions requested"


@mcp.tool()
def rename_concept(
    old_concept_name: str,
    new_concept_name: str,
    reason: str = "Conceptual refinement"
) -> str:
    """Rename a concept by creating new concept and updating all graph references

    This is proactive evolution (not defensive sinking with _v1 suffix).

    Operations:
    1. Creates new concept with improved terminology (inherits old description)
    2. Updates ALL incoming relationships to point to new concept
    3. Copies ALL outgoing relationships from old to new
    4. Creates bidirectional evolution links (evolved_from/evolved_to)
    5. Preserves old concept as historical record

    Distinction from sinking:
    - Sinking (_v1): automatic on validation failures, marks broken concepts
    - Renaming: user-initiated refinement, improves terminology while preserving graph integrity

    Args:
        old_concept_name: Current concept name to be evolved/renamed
        new_concept_name: New improved concept name
        reason: Explanation for the rename (stored in evolution relationship)

    Returns:
        Summary of rename operation including relationship counts
    """
    try:
        result = rename_concept_func(old_concept_name, new_concept_name, reason)
        return f"✅ {result}"
    except Exception as e:
        traceback.print_exc()
        return f"❌ Error renaming concept: {str(e)}"


# DEAD (carton audit 2026-06-19): stub that always raises NotImplementedError (meta-testing pattern never built) — commented out, not deleted, pending skill-candidate review.
# @mcp.tool()
def observe_auto_meta_test(test_subject: str, fix_description: str) -> str:
    """Auto-observe a bug fix using meta-testing pattern

    Creates an observation about fixing a system bug by using the fixed system itself.
    The observation's completeness proves the fix worked (meta-testing).

    Args:
        test_subject: What was being tested/fixed (e.g., "observation_wrapper_linking")
        fix_description: Description of the bug and how it was fixed

    Returns:
        Result of meta-test observation creation
    """
    # Will call add_observation_batch, potentially in a loop, plus have pattern validators TBD
    raise NotImplementedError("Meta-testing pattern not yet implemented. Will create self-validating observations about system fixes.")


# DEAD (carton audit 2026-06-19): stub that always raises NotImplementedError + wired to the disabled flight/waypoint GNOSYS stack — commented out, not deleted, pending skill-candidate review.
# @mcp.tool()
def run_experiment(experiment_hypothesis: str, flight_config_name: str = None) -> str:
    """Run an experiment using flight config with waypoint PD for meta-test validation

    Sends message to use a specific flight that has a specific waypoint PD for running
    an experiment that sets up a meta test hypothesis and executes the constructor to
    see if it validates and then figures out why not through carton observation.
    This lets it chain research to farm knowledge.

    Args:
        experiment_hypothesis: The hypothesis to test
        flight_config_name: Optional specific flight config to use for the experiment

    Returns:
        Experiment execution results and observations
    """
    # Will integrate: flight configs + waypoint PDs + meta-test hypothesis validation + Carton observations
    # Creates knowledge farming research chain
    raise NotImplementedError("Experiment runner not yet implemented. Will chain research through flight/waypoint/observation system.")

@mcp.tool()
def query_wiki_graph(cypher_query: str, parameters: dict = None) -> str:
    """Execute arbitrary Cypher query on :Wiki namespace (read-only)

    Neo4j Schema:
    - Node label: :Wiki
    - Properties: n (name), d (description), c (canonical), t (timestamp)
    - Relationships: Various types like is_a, part_of, depends_on, relates_to, etc.

    UARL Two-Phase System:
    - Soup layer: All concepts (informal, arbitrary descriptions)
    - Ontology layer: Concepts with REIFIES (formal, strongly typed, complete knowledge)

    Query Patterns:
    - All concepts: MATCH (c:Wiki) RETURN c.n, c.d
    - Ontology only: MATCH (c:Wiki)-[:IS_A]->(:Wiki {n: "Carton_Ontology_Entity"}) RETURN c.n, c.d
    - Soup only: MATCH (c:Wiki) WHERE NOT (c)-[:IS_A]->(:Wiki {n: "Carton_Ontology_Entity"}) RETURN c.n, c.d
    - Find concepts: MATCH (c:Wiki) WHERE c.n CONTAINS "MCP" RETURN c.n, c.d
    - Get relationships: MATCH (c:Wiki)-[r]->(related:Wiki) WHERE c.n = "HEAVEN_System" RETURN type(r), related.n
    - Count concepts: MATCH (c:Wiki) RETURN count(c)

    Args:
        cypher_query: Cypher query targeting :Wiki namespace (read-only, no CREATE/MERGE allowed)
        parameters: Optional parameters for the Cypher query (use $param_name in query)

    Returns:
        JSON string with query results containing success status and data
    """
    # SM-GATE (increment 2b): gate the raw cypher call (the call text IS the query, exactly as
    # CCC gates query_database). No-op by default (gating off / actor unlocked).
    _sm_gate_check("query_wiki_graph", cypher_query)
    try:
        result = utils.query_wiki_graph(cypher_query, parameters)
        if result.get("success"):
            data = result["data"]
            formatted = _fmt(data)
            # Warn if no results and query might have case mismatch
            if not data or (isinstance(data, list) and len(data) == 0):
                import re
                # Check for potential case mismatch in concept names
                potential_names = re.findall(r"['\"]([A-Za-z_]+)['\"]", cypher_query)
                has_lowercase = any(c.islower() for name in potential_names for c in name if c.isalpha())
                if has_lowercase and potential_names:
                    formatted += "\n\n⚠️ REMINDER: CartON uses Title_Case for all concept names. Your query contains lowercase - try Title_Case (e.g., 'my_concept' → 'My_Concept')"
            return formatted
        else:
            return f"❌ {result.get('error')}"
    except Exception as e:
        traceback.print_exc()
        return f"❌ Error: {e}"

@mcp.tool()
def query_cb_math(cb_command: str) -> str:
    """Pass a Crystal Ball (CB) math / read query straight through to the CB shell and
    return its rendered view. The CB shell ALREADY implements the math — this is a THIN
    PASSTHROUGH, not a reimplementation. Use it to run the CB math over the (now unified)
    coordinate space directly from CartON.

    Examples:
        query_cb_math("MySpace orbits")      — per-slot orbit decomposition (the "orbits of X")
        query_cb_math("MySpace gram")        — pairwise member similarity (the neighborhood)
        query_cb_math("algebra meta")        — Aut / Monster / fusion analysis of a space
        query_cb_math("orgweb MyOrg 1.1.1")  — decode an org address across a family crossing
        query_cb_math("mine view")           — observe the persisted mineSpace

    READ-ONLY: mutating verbs (adopt/store/orgcompose/create/delete/rename/goldenize/mark/
    lock-subspace/add/slots/attr) are REJECTED — use the dedicated tools/verbs for those.
    The command is sent verbatim as {"input": cb_command} to /api/cb/flow (Bearer-authed
    from the CB key file). Returns the shell's `view`, or a loud error string (never raises).

    Args:
        cb_command: a CB shell read/math command, e.g. "<Space> orbits" or "<Space> gram".
    Returns:
        The CB shell's rendered view string (or a loud error string on failure).
    """
    import urllib.request as _u  # urllib not imported at module scope; json/os are (use globals)
    cmd = (cb_command or "").strip()
    if not cmd:
        return "❌ query_cb_math: empty command"
    _MUTATING = {"adopt", "store", "orgcompose", "create", "delete", "rename",
                 "goldenize", "mark", "lock-subspace", "add", "slots", "attr", "mirror"}
    first = cmd.split(None, 1)[0].lower()
    if first in _MUTATING:
        return (f"❌ query_cb_math is READ-ONLY — '{first}' is a mutating verb. "
                f"Use the dedicated tool/verb for writes; this tool is for math/read queries "
                f"(orbits, gram, algebra meta, orgweb, mine view, select, ews, ...).")
    url = os.environ.get("CARTON_CB_FLOW_URL", "http://localhost:3000/api/cb/flow")
    keyfile = os.environ.get("CARTON_CB_KEY_FILE", "/tmp/heaven_data/cb_api_key.txt")
    try:
        key = ""
        try:
            with open(keyfile) as _f:
                key = _f.read().strip()
        except Exception:
            key = ""
        body = json.dumps({"input": cmd}).encode()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = _u.Request(url, data=body, headers=headers)
        with _u.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        view = data.get("view")
        if view:
            return str(view)
        return json.dumps(data.get("data") or data)[:4000]
    except Exception as e:
        return f"❌ query_cb_math failed for {cb_command!r}: {e}"

@mcp.tool()
def get_concept_network(
    concept_name: str,
    depth: int = 1,
    rel_types: List[str] = None
) -> str:
    """Get concept network with specified relationship depth (1-3 hops)

    Explores the knowledge graph starting from a concept and following relationships
    to discover connected concepts. Useful for understanding concept dependencies,
    related ideas, and knowledge clusters.

    Args:
        concept_name: Name of the concept to explore network for (exact match on n property)
        depth: Relationship depth to traverse (1-3, default: 1). Higher depth = more connections
        rel_types: Optional list of relationship types to filter (e.g., ["IS_A", "PART_OF"])
                   Common types: IS_A, PART_OF, DEPENDS_ON, HAS_COMPONENT, VALIDATES, AUTO_RELATED_TO
                   If None, includes all relationship types

    Returns:
        JSON string with concept network data including nodes, relationships, and metadata
    """
    # SM-GATE (increment 2b): gate this retrieval call. No-op by default.
    _sm_gate_check("get_concept_network", repr(concept_name))
    try:
        result = utils.get_concept_network(concept_name, depth, rel_types)
        if result.get("success"):
            return _fmt(result)
        else:
            return f"❌ {result.get('error')}"
    except Exception as e:
        traceback.print_exc()
        return f"❌ Error: {e}"

@mcp.tool()
def get_concept(concept_name: str, refresh_code: bool = False, expand_refs: bool = False, depth: int = 0) -> TextContent:
    """Get complete concept information including description and all relationships

    Retrieves the full concept data in one call - both the concept description
    and all its relationships. This is the standard way to research a concept
    for blog writing, analysis, or understanding its place in the knowledge graph.

    Args:
        concept_name: Name of the concept to retrieve (exact match on n property)
        refresh_code: STALE / NON-FUNCTIONAL residue. If True, calls the retired
                      youknow_kernel OWL reasoner (refresh_code_reality) — the YOUKNOW
                      OWL was removed as the authority 2026-06-15; SOMA (POST :8091/event)
                      is now the validator/region authority and code-reality lives in
                      context-alignment. Leave False; this branch queries a dead ontology
                      and does not reflect current code state.
        expand_refs: If True (with depth>0), expand bare refs inside the concept's CartonObj
                      fences — replace each ref token in the RETURNED text with the referenced
                      concept's description + relationships, recursive to `depth`, cycle-guarded.
                      Render-only: the stored description is never changed.
        depth: Ref-expansion depth. 0 (default) = raw tokens (unchanged). 1 = one hop,
                      2 = recurse two levels, etc.

    Returns:
        JSON string with complete concept data: name, description, and relationships
    """
    # SM-GATE (increment 2): if SM-gating is ON and this actor is locked at a step, this call must
    # be a legal move (match the step's required_pattern) or it raises GateRefusal (the regex IS the
    # instruction). No-op by default (gating off / actor unlocked) — get_concept is unchanged.
    _sm_gate_check("get_concept", repr(concept_name))
    if refresh_code:
        try:
            from youknow_kernel.owl_reasoner import OWLReasoner
            r = OWLReasoner()
            refresh_result = r.refresh_code_reality()
            dangling = refresh_result.get("dangling_references", [])
            dropped = refresh_result.get("entities_dropped", 0)
            ingested = sum(
                sum(v for v in counts.values() if isinstance(v, int))
                for counts in refresh_result.get("entities_ingested", {}).values()
            )
            # Prepend refresh info to the response
            refresh_msg = f"[CODE REFRESHED: dropped {dropped}, re-ingested {ingested}, {len(dangling)} dangling refs]\n"
            if dangling:
                for d in dangling[:5]:
                    refresh_msg += f"  DANGLING: {d['giint_concept']} -> {d['stale_code_ref']}\n"
        except Exception as e:
            refresh_msg = f"[CODE REFRESH FAILED: {e}]\n"
    try:
        # Query for concept with all its relationships
        # Prioritize nodes with descriptions to handle duplicates
        cypher_query = """
        MATCH (c:Wiki) WHERE c.n = $concept_name AND c.d IS NOT NULL
        OPTIONAL MATCH (c)-[r]->(related:Wiki)
        RETURN c.n as name, c.d as description, c.score as score,
               properties(c) as props,
               collect({type: type(r), target: related.n}) as relationships
        """
        result = utils.query_wiki_graph(cypher_query, {"concept_name": concept_name})

        if result.get("success") and result.get("data"):
            concept_data = result["data"][0]
            # Filter out empty relationships (from OPTIONAL MATCH)
            relationships = [rel for rel in concept_data.get("relationships", []) if rel.get("type")]

            # Build compact output
            name = concept_data.get("name", "")
            desc = _dedup_desc(_strip_md(concept_data.get("description", "")))
            # CartON KV ref-expansion (READ-TIME, render-only — never mutates n.d). depth=0 default
            # = raw tokens (unchanged behavior). expand_refs + depth>0 inlines referenced concepts.
            if expand_refs and depth > 0:
                try:
                    from carton_mcp.carton_utils import expand_carton_refs
                    desc = expand_carton_refs(desc, _neo4j_conn, depth)
                except Exception as _e:
                    desc = desc + f"\n[ref-expansion failed: {_e}]"
            
            # Group relationships
            requires_evolution = []
            auto_rels = []
            normal_rels = []
            
            for rel in relationships:
                rel_type = rel.get("type", "")
                target = rel.get("target", "")
                if rel_type == "REQUIRES_EVOLUTION":
                    requires_evolution.append(target)
                elif rel_type == "AUTO_RELATED_TO":
                    auto_rels.append(target)
                else:
                    normal_rels.append(f"{rel_type.lower()} {target}")
            
            # Build output string
            score = concept_data.get("score")
            score_str = f" [{score}% description coverage]" if score is not None else ""
            lines = [f"Name: {name}", f"Description{score_str}: {desc}"]

            # Props block: render the node's NON-reserved neo4j properties (the structured
            # property surface), only when non-empty. Reserved/managed fields (n, d, t, c,
            # score, source, linked, …) are excluded — they are not user data.
            props = concept_data.get("props") or {}
            user_props = {k: v for k, v in props.items() if k not in _RESERVED_PROPERTY_KEYS}
            if user_props:
                rendered = ", ".join(f"{k}: {json.dumps(user_props[k])}"
                                     for k in sorted(user_props))
                lines.append(f"Props:{{{rendered}}}")

            lines.extend(["", "Rels:["])
            
            if requires_evolution:
                lines.append("# ⚠️ REQUIRES_EVOLUTION")
            
            for rel in normal_rels:
                lines.append(f"  {rel}")
            
            if auto_rels:
                lines.append("")
                lines.append("  AutoRels:[")
                for ar in auto_rels:
                    lines.append(f"    auto_related_to {ar}")
                lines.append("  ]")
            
            lines.append("]")

            # SOMA live status check via daemon (port 8091).
            # Replaces the YOUKNOW status check. Builds a SOMA observation from
            # the concept's outgoing relationships (defaults to string_value type
            # because get_concept has no way to know declared programming types)
            # and POSTs to /event. SOMA's report string is surfaced as CODE
            # (no soup gaps, no failure_error) or SOUP/failure preview.
            try:
                from carton_mcp.add_concept_tool import soma_validate, SOMA_AVAILABLE
                if SOMA_AVAILABLE:
                    rel_by_type = {}
                    for rel in normal_rels:
                        parts = rel.split(" ", 1)
                        if len(parts) == 2:
                            rel_type, target = parts[0], parts[1]
                            rel_by_type.setdefault(rel_type, []).append(target)
                    soma_relationships = []
                    for rel_type, targets in rel_by_type.items():
                        soma_relationships.append({
                            "relationship": rel_type,
                            "related": [{"value": t, "type": "string_value"} for t in targets],
                        })
                    if soma_relationships:
                        soma_obs = [{
                            "source": "get_concept",
                            "name": name,
                            "description": "",
                            "relationships": soma_relationships,
                        }]
                        soma_data = soma_validate(source="get_concept", observations=soma_obs)
                        if soma_data and isinstance(soma_data, dict):
                            result_str = soma_data.get("result", "")
                            # THREE-LEVEL status (mirrors add_concept_tool.py parsing):
                            #   SOUP        — soup_gaps or failure_error present (structure incomplete)
                            #   CODE        — all_core_requirements_met but unmet > 0 (d-chains pending)
                            #   SYSTEM_TYPE — all_core_requirements_met AND unmet == 0 (fully admissible)
                            has_soup = "soup_gaps=" in result_str
                            has_failure = "failure_error" in result_str
                            all_core_met = ("all_core_requirements_met" in result_str) and not has_failure
                            _unmet_match = re.search(r'\bunmet=(\d+)', result_str)
                            try:
                                unmet_n = int(_unmet_match.group(1)) if _unmet_match else 0
                            except (ValueError, TypeError):
                                unmet_n = 0

                            if not has_soup and all_core_met and unmet_n == 0:
                                lines.append("")
                                lines.append("SOMA: SYSTEM_TYPE ✅✅ (structure valid, all d-chains proved)")
                            elif not has_soup and all_core_met and unmet_n > 0:
                                lines.append("")
                                lines.append(f"SOMA: CODE ✅ (structure valid, {unmet_n} d-chain(s) still unmet)")
                            elif has_soup or has_failure:
                                lines.append("")
                                lines.append(f"SOMA: SOUP\n{result_str[:400]}")
                            else:
                                lines.append("")
                                lines.append(f"SOMA: {result_str[:200]}")
            except ImportError:
                pass
            except Exception as soma_err:
                lines.append(f"\nSOMA: error — {soma_err}")

            output = "\n".join(lines)
            # CORE require-next (Isaac 2026-06-20): a Core does NOT withhold this content (served above)
            # — it ARMS a require-next so the actor's NEXT move is required to match the concept's Core
            # SM step (enforced by the _sm_gate_check above + on the query tools). Default-OFF, fail-open.
            output += _sm_chain_require_next(name)
            if refresh_code:
                output = refresh_msg + output
            return TextContent(type="text", text=output)
        else:
            # Suggest Title_Case_With_Underscores if user might have wrong casing
            suggestion = concept_name.replace(" ", "_").replace("-", "_")
            parts = suggestion.split("_")
            title_cased = "_".join(p.capitalize() for p in parts if p)
            hint = ""
            if concept_name != title_cased:
                hint = f"\n💡 Did you mean: {title_cased}?"
            msg = f"❌ Concept '{concept_name}' not found.{hint}\n⚠️ CartON uses Title_Case_With_Underscores naming convention."
            if refresh_code:
                msg = refresh_msg + msg
            return TextContent(type="text", text=msg)

    except Exception as e:
        traceback.print_exc()
        return TextContent(type="text", text=f"❌ Error: {str(e)}")

@mcp.tool()
def youknow_sparql(query: str) -> str:
    """Run a SPARQL query against the SOMA OWL ontology (the total-runtime OWL).

    Queries SOMA's OWL — the authority for typing/validation since YOUKNOW was retired
    2026-06-15. Loads SOMA's three OWL files into one owlready2 world (soma.owl =
    schema/class definitions, uarl.owl = foundation/core-sentence, starsystem.owl =
    GIINT/Navy/Sanctum/Skills) and runs the SPARQL against that combined world. This is
    the same OWL the SOMA validator (POST localhost:8091/event) reasons over.

    This queries the ONTOLOGY, not the CartON Neo4j graph. Use this for:
    - Checking OWL class restrictions ("what does GIINT_Deliverable require?")
    - Exploring the foundation ontology structure (uarl) and domain ontologies (starsystem)

    For CartON graph queries, use query_wiki_graph (Cypher) instead.

    Args:
        query: SPARQL query string (SELECT, ASK, etc.)

    Returns:
        JSON results from the SOMA OWL world
    """
    try:
        import owlready2
    except ImportError:
        return json.dumps({"success": False, "error": "owlready2 not available"})
    try:
        import os as _os
        # SOMA's OWN OWL files (the total-runtime OWL the SOMA validator loads).
        # soma.owl + uarl.owl + starsystem.owl live next to each other in the soma-prolog package.
        soma_owl_dir = _os.environ.get(
            "SOMA_OWL_DIR",
            "/home/GOD/gnosys-plugin-v2/base/soma-prolog/soma_prolog",
        )
        soma_owl_files = ["soma.owl", "uarl.owl", "starsystem.owl"]
        loaded = []
        world = owlready2.World()
        for fname in soma_owl_files:
            fpath = _os.path.join(soma_owl_dir, fname)
            if _os.path.exists(fpath):
                world.get_ontology("file://" + fpath).load()
                loaded.append(fname)
        if not loaded:
            return json.dumps({
                "success": False,
                "error": f"No SOMA OWL files found in {soma_owl_dir} (looked for {soma_owl_files}); set SOMA_OWL_DIR",
            })
        results = []
        for row in world.sparql(query):
            results.append({f"var{i}": str(v) for i, v in enumerate(row)})
        return json.dumps({"success": True, "loaded": loaded, "results": results}, indent=2, default=str)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
def get_history_info(
    info_type: str,
    id: str
) -> str:
    """Query conversation history and summarizer outputs from typed CartON concepts

    Traverses the typed conversation structure to reconstruct full content.
    Use this instead of raw Cypher queries for history traversal.
    Each summarizer level can use this to get what the previous level created.

    Args:
        info_type: Type of history to retrieve:
            RAW DATA:
            - "iteration": Single iteration with all messages and tool calls
            - "conversation": All iterations in a conversation
            - "session": All conversations in a starlog session
            - "context_bundle": What was in context when a file was edited

            SUMMARIZER OUTPUTS:
            - "iteration_summary": Single iteration summary (L1 output)
            - "all_iteration_summaries": All iteration summaries for a conversation (for L2)
            - "phase": Single phase with its iteration summaries (L2 output)
            - "all_phases": All phases for a conversation (for L5)
            - "subphase": Single subphase (L3 output)
            - "executive_summary": Executive summary for conversation (L5 output)

        id: The concept name or conversation ID depending on info_type

    Returns:
        Formatted string with full content in sequence
    """
    # SM-GATE (increment 2b): gate this retrieval call. No-op by default.
    _sm_gate_check("get_history_info", repr(id))
    try:
        if info_type == "iteration":
            # Get iteration with all its components in sequence
            # NOTE (container/content split — why iter.d is fetched but never rendered below):
            # an Iteration is a MINIMAL CONTAINER concept (see carton_precompact) — the real content lives
            # in its child User_Message / Agent_Message / Tool_Call concepts (full untruncated text in each
            # child's description). This getter renders those children; the iteration node's OWN description
            # (iter.d) is a container label, not content, so it is intentionally not surfaced.
            # CONSEQUENCE: a PROPERTY set on the Iteration node (e.g. a "compaction happened here" flag) will
            # NOT reach an agent through this getter. Compaction/live status is instead conveyed to the phase
            # detector out-of-band (flow._run_l2 injects it from the ingest source + live marker), not via a
            # node property here. If a node-property ever DOES need to reach agents, surface it explicitly in
            # the output builder below rather than assuming this getter exposes it.
            # First get the iteration and its relationships
            query = """
            MATCH (iter:Wiki {n: $id})
            OPTIONAL MATCH (iter)-[r]->(component:Wiki)
            WHERE type(r) STARTS WITH 'HAS_USER_MESSAGE_'
               OR type(r) STARTS WITH 'HAS_AGENT_MESSAGE_'
               OR type(r) STARTS WITH 'HAS_TOOL_CALL_'
            RETURN iter.n as iteration_name, iter.d as iteration_desc,
                   type(r) as rel_type, component.n as component_name, component.d as component_desc
            ORDER BY rel_type
            """
            result = utils.query_wiki_graph(query, {"id": id})

            if not result.get("success") or not result.get("data"):
                return f"❌ Iteration '{id}' not found"

            data = result["data"]

            # Parse results into ordered components
            user_messages = []
            agent_messages = []
            tool_calls = []

            for row in data:
                rel_type = row.get("rel_type")
                if not rel_type:
                    continue

                component = {
                    "name": row.get("component_name"),
                    "content": _strip_md(row.get("component_desc") or "")
                }

                if rel_type.startswith("HAS_USER_MESSAGE_"):
                    seq_num = int(rel_type.replace("HAS_USER_MESSAGE_", ""))
                    user_messages.append((seq_num, component))
                elif rel_type.startswith("HAS_AGENT_MESSAGE_"):
                    seq_num = int(rel_type.replace("HAS_AGENT_MESSAGE_", ""))
                    agent_messages.append((seq_num, component))
                elif rel_type.startswith("HAS_TOOL_CALL_"):
                    seq_num = int(rel_type.replace("HAS_TOOL_CALL_", ""))
                    tool_calls.append((seq_num, component))

            # Sort by sequence number
            user_messages.sort(key=lambda x: x[0])
            agent_messages.sort(key=lambda x: x[0])
            tool_calls.sort(key=lambda x: x[0])

            # Build output
            lines = [f"=== {id} ===\n"]

            for seq, msg in user_messages:
                lines.append(f"[USER MESSAGE {seq}]")
                lines.append(msg["content"] or "(empty)")
                lines.append("")

            for seq, msg in agent_messages:
                lines.append(f"[AGENT MESSAGE {seq}]")
                lines.append(msg["content"] or "(empty)")
                lines.append("")

            if tool_calls:
                lines.append("[TOOL CALLS]")
                for seq, tc in tool_calls:
                    lines.append(f"  {seq}. {tc['content']}")
                lines.append("")

            return "\n".join(lines)

        elif info_type == "conversation":
            # Get all iterations in conversation ordered by sequence
            query = """
            MATCH (conv:Wiki {n: $id})<-[:PART_OF]-(iter:Wiki)
            WHERE iter.n STARTS WITH 'Iteration_'
            RETURN iter.n as iteration_name
            ORDER BY iter.n
            """
            result = utils.query_wiki_graph(query, {"id": id})

            if not result.get("success") or not result.get("data"):
                return f"❌ Conversation '{id}' not found or has no iterations"

            iterations = [row["iteration_name"] for row in result["data"]]

            lines = [f"=== {id} ===", f"Total iterations: {len(iterations)}\n"]

            for iter_name in iterations:
                # Recursively get each iteration
                iter_content = get_history_info("iteration", iter_name)
                lines.append(iter_content)
                lines.append("---\n")

            return "\n".join(lines)

        elif info_type == "session":
            # Get all conversations in session
            query = """
            MATCH (session:Wiki {n: $id})<-[:PART_OF]-(conv:Wiki)
            WHERE conv.n STARTS WITH 'Conversation_'
            RETURN conv.n as conversation_name
            ORDER BY conv.n
            """
            result = utils.query_wiki_graph(query, {"id": id})

            if not result.get("success") or not result.get("data"):
                return f"❌ Session '{id}' not found or has no conversations"

            conversations = [row["conversation_name"] for row in result["data"]]

            lines = [f"=== {id} ===", f"Total conversations: {len(conversations)}\n"]

            for conv_name in conversations:
                lines.append(f"### {conv_name}")
                # Just list iterations, don't recurse fully to avoid massive output
                iter_query = """
                MATCH (conv:Wiki {n: $conv_name})<-[:PART_OF]-(iter:Wiki)
                WHERE iter.n STARTS WITH 'Iteration_'
                RETURN count(iter) as iteration_count
                """
                iter_result = utils.query_wiki_graph(iter_query, {"conv_name": conv_name})
                if iter_result.get("success") and iter_result.get("data"):
                    count = iter_result["data"][0].get("iteration_count", 0)
                    lines.append(f"  Iterations: {count}")
                lines.append("")

            return "\n".join(lines)

        elif info_type == "context_bundle":
            # Find what files were read before a file was edited
            # id should be a file path or File_* concept name

            # Normalize file path to concept name if needed
            file_concept = id if id.startswith("File_") else f"File_{id.replace('/', '_').replace('.', '_')}"

            query = """
            // Find edit tool calls that touched this file
            MATCH (tc:Wiki)-[:TOUCHES_FILE]->(file:Wiki {n: $file_concept})
            MATCH (tc)-[:USES_TOOL]->(tool:Wiki {n: 'Edit'})
            MATCH (iter:Wiki)-[edit_rel]->(tc)
            WHERE type(edit_rel) STARTS WITH 'HAS_TOOL_CALL_'

            // Find all read tool calls in the same iteration before the edit
            WITH iter, toInteger(replace(type(edit_rel), 'HAS_TOOL_CALL_', '')) as edit_seq
            MATCH (iter)-[read_rel]->(read_tc:Wiki)-[:USES_TOOL]->(read_tool:Wiki {n: 'Read'})
            WHERE toInteger(replace(type(read_rel), 'HAS_TOOL_CALL_', '')) < edit_seq
            MATCH (read_tc)-[:TOUCHES_FILE]->(read_file:Wiki)

            RETURN iter.n as iteration,
                   read_file.n as file_read,
                   type(read_rel) as read_seq
            ORDER BY iter.n, read_seq
            """
            result = utils.query_wiki_graph(query, {"file_concept": file_concept})

            if not result.get("success") or not result.get("data"):
                return f"❌ No context bundle found for '{id}' (no edits with prior reads)"

            # Group by iteration
            bundles = {}
            for row in result["data"]:
                iter_name = row["iteration"]
                if iter_name not in bundles:
                    bundles[iter_name] = []
                bundles[iter_name].append(row["file_read"])

            lines = [f"=== Context Bundle for {id} ===\n"]
            for iter_name, files in bundles.items():
                lines.append(f"In {iter_name}:")
                for f in files:
                    # Convert File_... back to path
                    path = f.replace("File_", "").replace("_", "/").replace("/_", ".")
                    lines.append(f"  - {path}")
                lines.append("")

            return "\n".join(lines)

        # === SUMMARIZER OUTPUT TYPES ===

        elif info_type == "iteration_summary":
            # Get a single iteration summary
            query = """
            MATCH (s:Wiki {n: $id})
            WHERE s.n STARTS WITH 'Iteration_Summary_'
            RETURN s.n as name, s.d as description
            """
            result = utils.query_wiki_graph(query, {"id": id})

            if not result.get("success") or not result.get("data"):
                return f"❌ Iteration summary '{id}' not found"

            data = result["data"][0]
            return f"=== {data['name']} ===\n\n{_strip_md(data['description'] or '')}"

        elif info_type == "all_iteration_summaries":
            # Get all iteration summaries for a conversation (id = conversation concept name)
            query = """
            MATCH (s:Wiki)-[:PART_OF]->(conv:Wiki {n: $id})
            WHERE s.n STARTS WITH 'Iteration_Summary_'
            RETURN s.n as name, s.d as description
            ORDER BY s.n
            """
            result = utils.query_wiki_graph(query, {"id": id})

            if not result.get("success") or not result.get("data"):
                return f"❌ No iteration summaries found for '{id}'"

            lines = [f"=== Iteration Summaries for {id} ===\n"]
            for row in result["data"]:
                lines.append(f"### {row['name']}")
                lines.append(_strip_md(row['description'] or "(empty)"))
                lines.append("")

            return "\n".join(lines)

        elif info_type == "phase":
            # Get a single phase with its iteration summaries
            query = """
            MATCH (p:Wiki {n: $id})
            WHERE p.n STARTS WITH 'Conversation_Phase_'
            OPTIONAL MATCH (p)-[r]->(s:Wiki)
            WHERE type(r) STARTS WITH 'HAS_ITERATION_SUMMARY_'
            RETURN p.n as phase_name, p.d as phase_desc,
                   type(r) as rel_type, s.n as summary_name, s.d as summary_desc
            ORDER BY rel_type
            """
            result = utils.query_wiki_graph(query, {"id": id})

            if not result.get("success") or not result.get("data"):
                return f"❌ Phase '{id}' not found"

            data = result["data"]
            phase_desc = data[0].get("phase_desc", "")

            # Collect summaries in order
            summaries = []
            for row in data:
                rel_type = row.get("rel_type")
                if rel_type and rel_type.startswith("HAS_ITERATION_SUMMARY_"):
                    seq = int(rel_type.replace("HAS_ITERATION_SUMMARY_", ""))
                    summaries.append((seq, row.get("summary_name"), row.get("summary_desc")))

            summaries.sort(key=lambda x: x[0])

            lines = [f"=== {id} ===\n", _strip_md(phase_desc or "(no description)"), "\n### Iteration Summaries:"]
            for seq, name, desc in summaries:
                lines.append(f"\n{seq}. {name}")
                lines.append(_strip_md(desc or "(empty)"))

            return "\n".join(lines)

        elif info_type == "all_phases":
            # Get all phases for a conversation (id = conversation concept name)
            query = """
            MATCH (p:Wiki)-[:PART_OF]->(conv:Wiki {n: $id})
            WHERE p.n STARTS WITH 'Conversation_Phase_'
            RETURN p.n as name, p.d as description
            ORDER BY p.n
            """
            result = utils.query_wiki_graph(query, {"id": id})

            if not result.get("success") or not result.get("data"):
                return f"❌ No phases found for '{id}'"

            lines = [f"=== All Phases for {id} ===\n"]
            for row in result["data"]:
                lines.append(f"### {row['name']}")
                lines.append(_strip_md(row['description'] or "(empty)"))
                lines.append("")

            return "\n".join(lines)

        elif info_type == "subphase":
            # Get a single subphase
            query = """
            MATCH (s:Wiki {n: $id})
            WHERE s.n STARTS WITH 'Conversation_Subphase_'
            RETURN s.n as name, s.d as description
            """
            result = utils.query_wiki_graph(query, {"id": id})

            if not result.get("success") or not result.get("data"):
                return f"❌ Subphase '{id}' not found"

            data = result["data"][0]
            return f"=== {data['name']} ===\n\n{_strip_md(data['description'] or '')}"

        elif info_type == "all_subphases":
            # Get all subphases for a phase (id = phase concept name)
            query = """
            MATCH (s:Wiki)-[:PART_OF]->(p:Wiki {n: $id})
            WHERE s.n STARTS WITH 'Conversation_Subphase_'
            RETURN s.n as name, s.d as description
            ORDER BY s.n
            """
            result = utils.query_wiki_graph(query, {"id": id})

            if not result.get("success") or not result.get("data"):
                return f"❌ No subphases found for '{id}'"

            lines = [f"=== Subphases for {id} ===\n"]
            for row in result["data"]:
                lines.append(f"### {row['name']}")
                lines.append(_strip_md(row['description'] or "(empty)"))
                lines.append("")

            return "\n".join(lines)

        elif info_type == "executive_summary":
            # Get executive summary for a conversation (id = conversation concept name OR executive summary name)
            # Try direct match first
            query = """
            MATCH (e:Wiki)
            WHERE e.n = $id OR e.n = 'Executive_Summary_' + $id
            RETURN e.n as name, e.d as description
            """
            result = utils.query_wiki_graph(query, {"id": id})

            if not result.get("success") or not result.get("data"):
                # Try finding by conversation
                query2 = """
                MATCH (e:Wiki)-[:PART_OF]->(conv:Wiki {n: $id})
                WHERE e.n STARTS WITH 'Executive_Summary_'
                RETURN e.n as name, e.d as description
                """
                result = utils.query_wiki_graph(query2, {"id": id})

            if not result.get("success") or not result.get("data"):
                return f"❌ Executive summary not found for '{id}'"

            data = result["data"][0]
            return f"=== {data['name']} ===\n\n{_strip_md(data['description'] or '')}"

        else:
            valid_types = "iteration, conversation, session, context_bundle, iteration_summary, all_iteration_summaries, phase, all_phases, subphase, all_subphases, executive_summary"
            return f"❌ Unknown info_type '{info_type}'. Must be one of: {valid_types}"

    except Exception as e:
        traceback.print_exc()
        return f"❌ Error: {str(e)}"


@mcp.tool()
def list_missing_concepts() -> str:
    """List all missing concepts that are referenced but don't exist yet
    
    Scans the knowledge graph for concept names mentioned in descriptions or relationships
    that don't have their own concept files. Useful for finding gaps in the knowledge base
    and planning which concepts need to be created next.
    
    Returns:
        JSON string with missing concepts and their inferred relationships from existing concepts
    """
    try:
        result = utils.list_missing_concepts()
        if result.get("success"):
            return _fmt(result["data"])
        else:
            return f"❌ {result.get('error')}"
    except Exception as e:
        traceback.print_exc()
        return f"❌ Error: {e}"

@mcp.tool()
def create_missing_concepts(concepts_data: list) -> str:
    """Create multiple missing concepts with AI-generated descriptions
    
    Batch creates concepts that were identified as missing from the knowledge graph.
    Uses AI to generate appropriate descriptions based on context from existing concepts
    that reference them.
    
    Args:
        concepts_data: List of concept objects to create, each containing name and context
        
    Returns:
        JSON string with creation results showing success/failure for each concept
    """
    try:
        result = utils.create_missing_concepts(concepts_data)
        if result.get("success"):
            return _fmt(result["data"])
        else:
            return f"❌ {result.get('error')}"
    except Exception as e:
        traceback.print_exc()
        return f"❌ Error: {e}"

@mcp.tool()
def get_recent_concepts(n: int = 20, timeline: str = None) -> str:
    """CartON timeline — most recent concept activity.

    Shows concepts sorted by most recent activity (created or modified).
    Each entry shows 'new' or 'mod' and the timestamp.

    Args:
        n: Number of entries (default: 20, max: 100)
        timeline: Filter by timeline. Options:
            - "chat": concepts created by agent/dragonbones during conversations
            - "system": background system events (daemon, linker, projector)
            - "odyssey": narrative/BML concepts (Episode, Journey, Epic, summaries)
            - "overall": all timeline-linked concepts across all timelines
            - None (default): no filter, shows all concepts

    Returns:
        Table of concept name | new/mod timestamp
    """
    # SM-GATE (increment 2b): gate this retrieval call. No-op by default.
    _sm_gate_check("get_recent_concepts", repr(timeline))
    try:
        n = min(n, 100)

        # Timeline filters based on source property and timeline flags
        timeline_clauses = {
            "chat": "(c.source IN ['agent', 'dragonbones_hook', 'session_start'] AND NOT c.source IN ['colonizer'] AND NOT c.n STARTS WITH 'Starsystem_' AND NOT c.n STARTS WITH 'Starship_' AND NOT c.n STARTS WITH 'Squadron_' AND NOT c.n STARTS WITH 'Fleet_' AND NOT c.n STARTS WITH 'Mcp_Skill_' AND NOT c.n STARTS WITH 'Skill_Create_' AND NOT c.n STARTS WITH 'File_')",
            "system": "(c.source IN ['observation_daemon', 'precompact', 'hierarchical_summarizer', 'linker', 'substrate_projector', 'colonizer'] OR c.n STARTS WITH 'System_Event_')",
            "odyssey": "c.odyssey_linked = true",
            "overall": "(c.source IS NOT NULL OR c.odyssey_linked = true OR c.timeline_linked = true)",
        }
        timeline_filter = ""
        if timeline and timeline.lower() in timeline_clauses:
            timeline_filter = f" AND ({timeline_clauses[timeline.lower()]})"

        # Exclude system-generated bulk entries (add prefixes as needed)
        exclude_prefixes = ["Skillgraph_"]
        exclude_clause = " AND ".join([f"NOT c.n STARTS WITH '{p}'" for p in exclude_prefixes])

        # Normalize mixed timestamp types (integer epoch ms, string ISO, Neo4j datetime)
        norm_t = """CASE
            WHEN c.t IS NULL THEN null
            WHEN valueType(c.t) STARTS WITH 'INTEGER' OR valueType(c.t) STARTS WITH 'FLOAT' THEN datetime({epochMillis: toInteger(c.t)})
            WHEN valueType(c.t) STARTS WITH 'STRING' THEN datetime(c.t)
            ELSE c.t END"""
        norm_lm = """CASE
            WHEN c.last_modified IS NULL THEN null
            WHEN valueType(c.last_modified) STARTS WITH 'INTEGER' OR valueType(c.last_modified) STARTS WITH 'FLOAT' THEN datetime({epochMillis: toInteger(c.last_modified)})
            WHEN valueType(c.last_modified) STARTS WITH 'STRING' THEN datetime(c.last_modified)
            ELSE c.last_modified END"""

        query = f"""
        MATCH (c:Wiki)
        WHERE (c.t IS NOT NULL OR c.last_modified IS NOT NULL) AND {exclude_clause}{timeline_filter}
        WITH c, {norm_t} AS norm_created, {norm_lm} AS norm_modified
        WITH c, norm_created, norm_modified, COALESCE(norm_modified, norm_created) AS effective_time
        RETURN c.n as name,
               CASE WHEN norm_modified IS NOT NULL THEN 'mod' ELSE 'new' END as action,
               toString(effective_time) as at
        ORDER BY effective_time DESC
        LIMIT $n
        """

        result = utils.query_wiki_graph(query, {"n": n})

        if result.get("success", False):
            concepts = result.get("data", [])
            if not concepts:
                return "No concepts with timestamps found."

            tl_label = f" [{timeline}]" if timeline else ""
            lines = [f"Recent concepts{tl_label} ({len(concepts)}):", "name | at", "-" * 60]
            for c in concepts:
                ts = str(c.get("at", "?")).replace("T", " ").split(".")[0].split("+")[0][:16]
                lines.append(f"{c['name']} | {c['action']} {ts}")

            return "\n".join(lines)
        else:
            return "❌ Failed to query recent concepts"

    except Exception as e:
        logger.error(f"Error getting recent concepts: {e}")
        traceback.print_exc()
        return f"❌ Error: {e}"

@mcp.tool()
def calculate_missing_concepts() -> str:
    """Scan all concepts, update missing_concepts.md, and commit to GitHub

    Scans all existing concepts in the knowledge graph to find references to concepts
    that don't exist yet. Updates the missing_concepts.md file with the findings
    and commits the changes to GitHub.

    Returns:
        JSON string with calculation results and list of missing concepts
    """
    try:
        result = utils.calculate_missing_concepts()
        if result.get("success"):
            return _fmt(result["data"])
        else:
            return f"❌ {result.get('error')}"
    except Exception as e:
        traceback.print_exc()
        return f"❌ Error: {e}"

# # DISABLED 2026-07-04 (Isaac): unscoped full-graph O(n^2) SequenceMatcher scan (carton_utils.py:1807-1873,
# untouched since the initial commit 317931f) hung 52min with zero output against the current graph size
# and had to be force-interrupted. No LIMIT/pagination/timeout in the underlying query or comparison loop.
# Do not re-enable without first scoping the query (e.g. a WHERE/LIMIT) or replacing SequenceMatcher with
# the existing Chroma embedding search this codebase already has for real similarity search.
# @mcp.tool()
# def deduplicate_concepts(similarity_threshold: float = 0.8) -> str:
    # """Find and analyze duplicate or similar concepts

    # Scans all concepts in the knowledge graph to find duplicates or similar concepts
    # based on name similarity. Useful for identifying concepts that may need to be
    # merged or renamed for consistency.

    # Args:
        # similarity_threshold: Similarity threshold (0.0-1.0, default: 0.8). Higher values require closer matches.

    # Returns:
        # JSON string with duplicate groups and similarity analysis
    # """
    # try:
        # result = utils.deduplicate_concepts(similarity_threshold)
        # if result.get("success"):
            # return _fmt(result["data"])
        # else:
            # return f"❌ {result.get('error')}"
    # except Exception as e:
        # traceback.print_exc()
        # return f"❌ Error: {e}"

@mcp.tool()
def equip_frame(frame: str) -> str:
    """Equip observation frame/lens determining observation structure

    Frames define how to structure observations for different contexts (skill development,
    task decomposition, meta-testing, health tracking, etc.). User-extensible via JSON file.

    Args:
        frame: Name of frame to equip (e.g., 'skill_development', 'meta_test', 'exercise')

    Returns:
        Frame-specific observation prompt/description
    """
    try:
        # Get frames path from env or use default
        # CONNECTS_TO: /tmp/heaven_data/carton_frames.json (read) — also accessed by summarizer_mcp.py
        frames_path = os.getenv('CARTON_FRAMES_PATH', '/tmp/heaven_data/carton_frames.json')
        frames_file = Path(frames_path)

        # Create default frames if file doesn't exist
        if not frames_file.exists():
            frames_file.parent.mkdir(parents=True, exist_ok=True)
            default_frames = {
                "skill_development": "Observe: skill being developed, current level, practice method, challenges, progress indicators",
                "task_decomposition": "Observe: task, subtasks, dependencies, blockers, completion criteria",
                "meta_test": "Observe: hypothesis, test execution, validation result, what the test proves",
                "transfer_learning": "Observe: source domain, target domain, analogies, what transfers, what doesn't",
                "exercise": "Observe: activity, duration, intensity, recovery state, progression",
                "nutrition": "Observe: food/meal, nutritional content, timing, energy/satiety effects",
                "supplements": "Observe: supplement, dosage, timing, effects, stacking interactions",
                "sleep": "Observe: duration, quality indicators, sleep phases, recovery assessment",
                "wake": "Observe: wake time, energy level, cognitive clarity, readiness state",
                "vision_synthesis": "Observe: components, relationships, emergent properties, big picture integration"
            }
            frames_file.write_text(json.dumps(default_frames))

        # Load frames
        frames = json.loads(frames_file.read_text())

        if frame not in frames:
            available = ", ".join(frames.keys())
            return f"❌ Frame '{frame}' not found. Available frames: {available}"

        return f"🔭 Frame equipped: {frame}\n\n{frames[frame]}"

    except Exception as e:
        traceback.print_exc()
        return f"❌ Error loading frame: {str(e)}"

# CartON Knowledge Management Prompts
@mcp.prompt()
def add_user_thought(user_quote: str, topic: str) -> str:
    """Capture user thoughts verbatim in the CartON knowledge graph with proper attribution and relationships
    
    Args:
        user_quote: Exact user quote to capture
        topic: Topic or context for the thought
        
    Returns:
        Prompt for adding user thought to knowledge graph
    """
    return f"""CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. You need to call mcp__carton__add_concept with concept_name="User_Thoughts_{topic}", concept containing the exact quote "{user_quote}", and relationships formatted as [{{"relationship": "relates_to", "related": ["Concept1", "Concept2"]}}] for any concepts mentioned in the quote, in order to capture this user thought verbatim in the knowledge graph."""

@mcp.prompt()
def update_known_concept(concept_name: str, current_description: str, new_info: str) -> str:
    """Update existing concepts with new information while maintaining consistency and relationships
    
    Args:
        concept_name: Name of concept to update
        current_description: Current concept description
        new_info: New information to integrate
        
    Returns:
        Prompt for updating existing concept
    """
    return f"""CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. You need to call mcp__carton__add_concept with concept_name="{concept_name}", concept that merges "{current_description}" with "{new_info}" seamlessly while preserving core meaning, and maintain all existing relationships formatted as [{{"relationship": "type", "related": ["ConceptList"]}}], in order to update this known concept with new information."""

@mcp.prompt()
def update_user_thought_train_emergently(
    original_concept_name: str, 
    original_description: str, 
    later_concept: str, 
    how_it_led_to: str
) -> str:
    """Track intellectual lineage by showing how user thoughts evolved and led to later insights
    
    Args:
        original_concept_name: Original user thought concept
        original_description: Original description
        later_concept: Later insight/concept
        how_it_led_to: How the thought evolved
        
    Returns:
        Prompt for tracking thought evolution
    """
    return f"""CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. You need to call mcp__carton__add_concept with concept_name="{original_concept_name}", concept that preserves "{original_description}" but adds how it evolved to "{later_concept}" via "{how_it_led_to}", and add relationships=[{{"relationship": "led_to", "related": ["{later_concept}"]}}], in order to track this user thought evolution emergently."""

@mcp.prompt()
def sync_after_update_known_concept(
    concept_list: str,
    change_summary: str,
    sync_number: str = "001"
) -> str:
    """Document concept changes and create sync concepts for version control integration

    Args:
        concept_list: List of updated concepts
        change_summary: Summary of changes made
        sync_number: Sync number (e.g., 001)

    Returns:
        Prompt for creating sync documentation
    """
    return f"""CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. You need to call mcp__carton__add_concept with concept_name="Sync{sync_number}", concept that documents "{concept_list}" were updated because "{change_summary}" and any key insights discovered, ready for GitHub sync, in order to create sync documentation for version control."""

@mcp.prompt()
def observe(description: str) -> str:
    """Quick observation capture - LLM analyzes description and creates appropriate observation

    Args:
        description: What you want to observe (insight, struggle, action, implementation, emotion, etc.)

    Returns:
        Prompt instructing LLM to analyze and create observation
    """
    return f"""[OBSERVATION MODE]
I need you to observe the following input: {description}"""

@mcp.prompt()
def add_frame(frame_name: str, description: str) -> str:
    """Add new observation frame to user's frame collection

    Args:
        frame_name: Name of the new frame (e.g., 'coding_session', 'debugging')
        description: Frame-specific observation prompt describing what to observe

    Returns:
        Prompt instructing LLM to add frame to frames file
    """
    # CONNECTS_TO: /tmp/heaven_data/carton_frames.json (read/write) — also accessed by summarizer_mcp.py
    frames_path = os.getenv('CARTON_FRAMES_PATH', '/tmp/heaven_data/carton_frames.json')

    return f"""[ADD FRAME MODE]
I need you to add a new observation frame to the frames file.

Frame name: {frame_name}
Frame description: {description}

File path: {frames_path}

Instructions:
1. Read the current frames file (JSON format)
2. Add new entry: "{frame_name}": "{description}"
3. Write the updated JSON back to the file
4. Confirm the frame was added successfully"""

@mcp.prompt()
def discover_patterns(n: int = 10) -> str:
    """Retrospective pattern discovery - analyze recent conversation turns

    Args:
        n: Number of recent chat turns to analyze (default: 10)

    Returns:
        Prompt for discovering interaction patterns
    """
    return f"""[PATTERN DISCOVERY MODE]
Map any patterns from the last {n} chat turns.

Analysis protocol:
1. What happened step by step?
2. What did I (user) do and what did you (assistant) do?
3. How were we interacting?
4. What patterns emerged in our collaboration?
5. What worked well? What didn't?
6. What metacognitive shifts occurred?

Then create an observation capturing:
- The interaction pattern discovered
- Step-by-step breakdown of the turns
- Collaboration dynamics
- Emergent insights from the pattern analysis"""

@mcp.prompt()
def scientific_method(hypothesis: str) -> str:
    """Apply scientific method to test hypothesis systematically

    Args:
        hypothesis: The hypothesis to test

    Returns:
        Prompt for systematic hypothesis testing
    """
    return f"""[SCIENTIFIC METHOD MODE]
Hypothesis: {hypothesis}

Testing protocol:
1. Query Carton for related concepts and past experiments
2. Design experiment to test hypothesis:
   - What variables to control?
   - What to measure?
   - What outcomes validate/invalidate hypothesis?
3. Execute experiment (code, analysis, observation)
4. Measure results objectively
5. Analyze: Does evidence support or refute hypothesis?
6. Draw conclusions with confidence score

Then create observation capturing:
- Hypothesis statement
- Experimental design
- Execution details
- Results and measurements
- Conclusion with confidence score (0-1)
- What this proves/disproves"""

@mcp.prompt()
def deep_dive(description: str) -> str:
    """Deep exploration of topic with systematic knowledge building

    Args:
        description: Topic or concept to explore deeply

    Returns:
        Prompt for deep dive exploration
    """
    return f"""[DEEP DIVE MODE]
Topic: {description}

Exploration protocol:
1. Query Carton for existing knowledge on this topic
2. Map what we know vs what we don't know
3. Identify knowledge gaps and questions
4. Systematically explore each gap:
   - Research/analyze
   - Build understanding
   - Connect to existing concepts
5. Synthesize findings into coherent understanding
6. Identify emergent insights from deep exploration

Then create observation capturing:
- Topic overview
- Knowledge map (what we knew before)
- Gaps explored
- New understanding built
- Connections to existing concepts
- Emergent insights from deep dive"""

@mcp.prompt()
def krr_engineer_domain(description: str) -> str:
    """Knowledge Representation & Reasoning - engineer domain ontology

    Args:
        description: Domain to engineer (e.g., 'exercise physiology', 'task management')

    Returns:
        Prompt for domain ontology engineering
    """
    return f"""[KRR DOMAIN ENGINEERING MODE]
Domain: {description}

Engineering protocol:
1. Query Carton for any existing domain concepts
2. Map domain landscape:
   - Core concepts (entities)
   - Relationships between concepts
   - Hierarchies (is_a, part_of)
   - Constraints and rules
3. Define ontology structure:
   - What are the fundamental building blocks?
   - How do they relate?
   - What patterns repeat?
4. Create concept network in Carton:
   - Add core domain concepts
   - Establish relationships
   - Document constraints
5. Validate ontology completeness

Then create observation capturing:
- Domain scope and boundaries
- Core concepts identified
- Relationship structure
- Ontology design decisions
- Knowledge representation choices
- What this domain model enables"""

@mcp.prompt()
def autobiography() -> str:
    """Interactive autobiography mapping - capture life memories in Timeline format

    Returns:
        Prompt for guided autobiographical memory capture
    """
    return """[AUTOBIOGRAPHY MODE]
Timeline memory capture protocol:

1. Check for Autobiography concept:
   - Query Carton for "Autobiography" concept
   - If not found, create it with description of life story structure

2. Ask user which period they want to map out:
   - "Which period of your life would you like to map out?"
   - If no preference, choose a significant period for them (childhood, college, first job, etc.)

3. Query Timeline structure:
   - Check existing Year/Month/Day concept formats in Carton
   - Timeline hierarchy: Year -contains-> Month -contains-> Day
   - Format: YYYY (Year), YYYY_MM (Month), YYYY_MM_DD (Day)

4. Capture the coherent story FIRST:
   - "Tell me the general story of this period - what was happening overall?"
   - Focus on narrative arc, major themes, life circumstances
   - Get the complete picture before drilling into details

5. Then capture specific memories:
   - "What specific moments or events do you remember from this period?"
   - For each memory shared:
     a) Identify the date (YYYY_MM_DD format)
     b) Create Day concept if it doesn't exist (e.g., "1995_03_15")
     c) Create observation with memory content
     d) Link observation as part_of the Day concept
     e) Link Day as part_of appropriate Month/Year in Timeline

6. Continue interaction:
   - Keep prompting for more memories in this period
   - Build out the Timeline structure as memories emerge
   - Only exit when user says they want to do something else

Remember:
- Coherent total story > great little pieces
- Conform to Timeline year/month/day formats
- Each memory gets part_of relationship to its Day
- Days get part_of relationship to Months, Months to Years"""

@mcp.prompt()
def stream() -> str:
    """Stream of consciousness capture with recursive grounding - map imagination to reality

    Returns:
        Prompt for active stream of consciousness with granular observation chains
    """
    return """[STREAM MODE]
Active stream of consciousness protocol:

Your role: Listen, suggest, ground, and capture through observation chains.

1. Stream Reception:
   - User will share stream of consciousness thoughts
   - Ideas may be abstract, imaginative, half-formed, or visionary
   - Do NOT interrupt the flow - let ideas emerge naturally

2. Active Suggestion Loop:
   - As ideas emerge, send targeted suggestions to develop them:
     * "What would make this idea concrete?"
     * "How does this connect to [existing concept from Carton]?"
     * "What's the next layer down in this abstraction?"
     * "If you had to implement this tomorrow, what would you need?"

3. Recursive Imagination → Reality Mapping:
   - For each abstract idea, recursively ground it:
     a) Abstract vision (imagination layer)
     b) Concrete manifestation (what this looks like in reality)
     c) Component breakdown (parts needed to build it)
     d) Implementation details (granular next steps)
   - Query Carton for related concepts at each layer
   - Suggest connections between new ideas and existing knowledge

4. Observation Chain Construction (EXTREMELY GRANULAR):
   - Each complete thought → observation
   - Each refinement → observation linked to parent thought
   - Each grounding step → observation showing abstraction→concrete mapping
   - Each connection discovered → observation with relates_to relationships
   - Build chains: Vision → Refinement → Grounding → Implementation → Next_Steps

5. Round Out Ideas:
   - Identify incomplete aspects: "What about [X]?"
   - Fill gaps: "You mentioned [Y], but how does it handle [Z]?"
   - Challenge assumptions: "What if [assumption] isn't true?"
   - Expand edges: "Where else does this apply?"

6. Capture Everything:
   - Create concepts for fully-formed ideas
   - Create observation chains for developmental thinking
   - Link observations: thought_evolution, refines, grounds_into, implements
   - Preserve the journey from abstract to concrete

Continue until user signals they're done streaming.

Remember:
- Granular observation chains > sparse high-level concepts
- Map imagination → reality recursively at every abstraction layer
- Active suggestions drive fuller, rounder ideas
- Preserve both the vision AND the grounding path"""

@mcp.prompt()
def hj(story: str) -> str:
    """Hero's Journey mapping - map story to Vogler's 12-stage model with archetypes

    Args:
        story: The story to map to hero's journey structure

    Returns:
        Prompt for guided hero's journey analysis and mapping
    """
    return f"""[HERO'S JOURNEY MODE]
Story to map: {story}

Vogler's 12-Stage Hero's Journey mapping protocol:

**The 12 Stages:**
1. Ordinary World
2. Call to Adventure
3. Refusal of the Call
4. Meeting the Mentor
5. Crossing the Threshold (Act 1 → Act 2a)
6. Tests, Allies, and Enemies (Fun and Games)
7. Approach to the Inmost Cave
8. Ordeal (Midpoint - Act 2a → Act 2b)
9. Reward (Seizing the Sword)
10. The Road Back (Act 2b → Act 3)
11. Resurrection (Climax)
12. Return with the Elixir

**Your Mission:**
Map the story to these 12 stages with proper archetypes and symbols. You CANNOT do this arbitrarily - the dynamics must be clear and follow archetype logic.

**Protocol:**

1. Assess Story Completeness:
   - Read the story carefully
   - Identify which stages are present vs missing
   - Check for required archetypal elements in each stage

2. If Story is Incomplete, Ask Specific Questions:
   - "I think I still need the act2a fun and games ordeal that breaks into the midpoint."
   - "I don't see the internal psychological obstacle/solution/solved mechanics."
   - "What's the mentor's gift or wisdom that enables threshold crossing?"
   - "Where's the death/rebirth moment at the ordeal?"
   - "What does the hero bring back to the ordinary world?"
   - "Is there a shadow figure or antagonist representing the internal obstacle?"

3. Map Archetypes:
   - Hero (protagonist)
   - Mentor (wisdom giver)
   - Threshold Guardian (tests readiness)
   - Herald (calls to adventure)
   - Shapeshifter (ambiguous loyalty)
   - Shadow (antagonist, internal obstacle)
   - Trickster (comic relief, disruption)

4. Map Symbols and Mechanics:
   - External obstacle (physical challenge)
   - Internal obstacle (psychological barrier)
   - Solution mechanism (how internal obstacle is overcome)
   - Transformation arc (who hero is at start → who they become)
   - Elixir (what knowledge/power hero brings back)

5. Visualize Architecture:
   - As you map, create visual structure showing:
     * Three-act breaks (Threshold, Ordeal, Road Back)
     * Character arcs (transformation journey)
     * Internal vs external conflict progression
     * Archetype relationships and dynamics
   - Use ASCII diagrams or clear structural breakdowns

6. Validate Dynamics:
   - Do the archetypes follow proper logic?
   - Does the internal obstacle resolution enable the external victory?
   - Is there a clear death/rebirth at the ordeal?
   - Does the hero return transformed with something valuable?

7. Iterate Until Complete:
   - Continue asking questions and refining mapping
   - Don't accept incomplete or arbitrary mappings
   - Ensure all 12 stages have clear archetypal content
   - Only conclude when dynamics are crystal clear

8. Capture in Carton:
   - Create concept for the story with hero's journey structure
   - Link archetypes, stages, and transformation mechanics
   - Preserve the complete mapping as knowledge

Remember:
- Archetypal logic > arbitrary stage filling
- Internal psychological mechanics must be clear
- Three-act structure must have proper breaks
- Transformation arc must be complete
- Elixir must be meaningful (not just "they won")"""

# CartON Event Detection Tools - LLM-triggered knowledge capture
# @mcp.tool()
def DetectEvent_user_thought(trigger: bool = True) -> str:
    """YOU MUST call this whenever user expresses a thought worth capturing in the knowledge graph
    
    YOU MUST USE THIS TOOL when you detect these patterns:
    - User shares insights, opinions, or ideas
    - User makes connections between concepts
    - User expresses preferences or mental models
    - User articulates problem-solving approaches
    
    This tool returns instructions for capturing the thought as a concept.
    """
    if trigger:
        return "CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. You need to call mcp__carton__add_concept with concept_name='User_Thoughts_{topic}', concept containing the exact user quote, and relationships formatted as [{\"relationship\": \"relates_to\", \"related\": [\"ConceptList\"]}] for any concepts mentioned, in order to capture this user thought verbatim in the knowledge graph."
    return ""

# @mcp.tool()
def DetectEvent_concept_update(trigger: bool = True) -> str:
    """YOU MUST call this whenever existing concepts need updating with new information
    
    YOU MUST USE THIS TOOL when you detect:
    - New information contradicts or expands existing concept descriptions
    - User provides corrections or clarifications about concepts
    - Context reveals concepts need more detail or different framing
    - Relationships between concepts change or need updating
    
    This tool returns instructions for updating the existing concept, then syncing.
    """
    if trigger:
        return "CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. Find the existing concept file at /tmp/heaven_data/wiki/concepts/{concept_name}/{concept_name}_itself.md (or HEAVEN_DATA_DIR/wiki/concepts/... if set differently). Read the current concept content, merge it with the new information while preserving core meaning and relationships, then write the updated content back to the file. After updating the concept file, call mcp__carton__DetectEvent_sync_needed to document this change."
    return ""

# @mcp.tool()
def DetectEvent_thought_evolution(trigger: bool = True) -> str:
    """YOU MUST call this whenever tracking how user thoughts evolve over time
    
    YOU MUST USE THIS TOOL when you detect:
    - User's current statement builds on or changes previous thoughts
    - User explicitly mentions how their thinking has changed
    - User connects current ideas to past conversations or concepts
    - User shows intellectual progression or refinement of ideas
    
    This triggers a concept update on the specific user thought.
    """
    if trigger:
        return "CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. User thought evolution detected. Call mcp__carton__DetectEvent_concept_update to update the specific user thought concept with how it has evolved."
    return ""

# All routed collection names used by sync_rag via route_concept_to_collection()
_ALL_RAG_COLLECTIONS = [
    "domain_knowledge",  # default fallthrough - most concepts land here
    "skillgraphs",
    "flightgraphs",
    "toolgraphs",
    "patterns",
    "conversations",
    "observations",
]

@mcp.tool()
def chroma_query(
    query: str,
    collection_name: str = "carton_concepts",
    k: int = 10,
    max_tokens: int = 20000
) -> str:
    """Query CartON concepts using semantic search via ChromaDB

    Returns ranked concept names based on semantic similarity to the query.
    Use this to discover which concepts are relevant to a topic, then use
    get_concept() or get_concept_network() to retrieve structured knowledge.

    Args:
        query: Natural language query to search for
        collection_name: ChromaDB collection name (default: carton_concepts)
        k: Number of results to retrieve (default: 10)
        max_tokens: Maximum tokens for results (default: 20000)

    Returns:
        Formatted string with ranked concept names and scores
    """
    # SM-GATE (increment 2b): gate this retrieval call. No-op by default.
    _sm_gate_check("chroma_query", repr(query))
    try:
        # When using the default "carton_concepts" (which doesn't exist as a real
        # collection), query ALL routed collections and merge results.
        # sync_rag routes concepts into partitioned collections via
        # route_concept_to_collection(), so we must query those same collections.
        if collection_name == "carton_concepts":
            collections_to_query = _ALL_RAG_COLLECTIONS
        else:
            collections_to_query = [collection_name]

        # Gather concept scores across all queried collections
        merged_concept_scores = {}
        total_docs_retrieved = 0

        for coll_name in collections_to_query:
            try:
                # Query the chroma daemon over HTTP (it embeds + queries + returns results, and returns
                # empty for an empty/missing collection — the old in-process count() check is folded in).
                result = _daemon_query(coll_name, query, k=k, max_tokens=max_tokens, search_type="mmr")

                if result.get("status") == "success":
                    total_docs_retrieved += result.get("documents_retrieved", 0)
                    # Extract per-concept scores from the result's packed documents
                    packed = result.get("results", [])
                    for idx, doc in enumerate(packed):
                        concept_name = doc.get("metadata", {}).get("concept_name")
                        if concept_name:
                            if concept_name not in merged_concept_scores:
                                merged_concept_scores[concept_name] = 0.0
                            # Score based on inverse rank (earlier = higher score)
                            merged_concept_scores[concept_name] += 1.0 / (idx + 1)
            except Exception as coll_err:
                logger.warning(f"Error querying collection {coll_name}: {coll_err}")
                continue

        if not merged_concept_scores:
            return f"🔍 **ChromaRAG Semantic Search**\n\nQuery: {query}\n\nNo concepts found. Collections may need syncing — run carton_management(sync_rag=True)."

        # Sort by score descending and format as numbered list
        sorted_concepts = sorted(
            merged_concept_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Limit to top k results
        sorted_concepts = sorted_concepts[:k]

        concepts = "\n".join([
            f"{i}. {name} ({score:.2f})"
            for i, (name, score) in enumerate(sorted_concepts, 1)
        ])

        # Cache results to file for query_graph_from_rag_result
        try:
            from datetime import datetime

            concept_list = [[name, score] for name, score in sorted_concepts]

            cache_data = {
                "timestamp": datetime.now().isoformat(),
                "query": query,
                "results": concept_list
            }

            heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
            cache_file = Path(heaven_data_dir) / 'carton_last_rag_query.json'
            cache_file.write_text(json.dumps(cache_data))

        except Exception as cache_error:
            logger.warning(f"Failed to cache RAG results: {cache_error}")

        queried_label = ", ".join(collections_to_query) if len(collections_to_query) <= 3 else f"{len(collections_to_query)} collections"
        return f"🔍 **ChromaRAG Semantic Search**\n\nQuery: {query}\nSearched: {queried_label}\nDocuments matched: {total_docs_retrieved}\n\n{concepts}"

    except Exception as e:
        traceback.print_exc()
        return f"❌ Error querying ChromaRAG: {str(e)}"

@mcp.tool()
def query_graph_from_rag_result(
    n: int = 5,
    scopes: List[int] = [0, 1],
    max_results: int = 100
) -> str:
    """Query graph for top N concepts from last RAG search with specified depth scopes

    Fetches complete graph context for concepts from the last chroma_query() call.
    Scope levels: 0=concept only, 1=1-hop network, 2=2-hop network

    Deduplicates connected concepts across all source concepts globally.

    Args:
        n: Number of top concepts from last RAG query (default: 5)
        scopes: Depth levels to fetch [0, 1, 2] (default: [0, 1])
        max_results: Maximum items to return before pagination (default: 100)

    Returns:
        JSON string with concept graph data at requested scopes
    """
    # SM-GATE (increment 2b): gate this retrieval call. No-op by default.
    _sm_gate_check("query_graph_from_rag_result", repr(n))
    try:
        heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        cache_file = Path(heaven_data_dir) / 'carton_last_rag_query.json'

        if not cache_file.exists():
            return "❌ No RAG query cached. Run chroma_query() first."

        # Read cached RAG results
        cache_data = json.loads(cache_file.read_text())
        top_concepts = cache_data["results"][:n]

        if not top_concepts:
            return "❌ No concepts in cache"

        # Global deduplication tracking
        seen_concepts = {}  # {concept_name: {description, sources: [list of source concepts]}}
        results = []

        logger.info(f"query_graph_from_rag_result: n={n}, scopes={scopes}, processing {len(top_concepts)} concepts")

        for concept_name, score in top_concepts:
            concept_data = {
                "name": concept_name,
                "rank": len(results) + 1,
                "score": score
            }

            # Track source concept
            if concept_name not in seen_concepts:
                seen_concepts[concept_name] = {"sources": [concept_name]}

            # Fetch requested scopes
            if 0 in scopes:
                # Scope 0: Just the concept description + relationships
                scope_0_result = utils.query_wiki_graph(
                    """
                    MATCH (c:Wiki) WHERE c.n = $concept_name AND c.d IS NOT NULL
                    OPTIONAL MATCH (c)-[r]->(related:Wiki)
                    RETURN c.n as name, c.d as description,
                           collect({type: type(r), target: related.n}) as relationships
                    """,
                    {"concept_name": concept_name}
                )

                if scope_0_result.get("success") and scope_0_result.get("data"):
                    concept_info = scope_0_result["data"][0]
                    relationships = [rel for rel in concept_info.get("relationships", []) if rel.get("type")]
                    concept_data["scope_0"] = {
                        "name": concept_info.get("name"),
                        "description": concept_info.get("description"),
                        "relationships": relationships
                    }
                    seen_concepts[concept_name]["description"] = concept_info.get("description")

            if 1 in scopes or 2 in scopes:
                # Collect network results for deduplication
                for scope in [1, 2]:
                    if scope not in scopes:
                        continue

                    scope_result = utils.get_concept_network(concept_name, depth=scope)
                    if scope_result.get("success"):
                        network = scope_result.get("network", [])
                        deduped_network = []
                        skipped_count = 0

                        for item in network:
                            connected_name = item.get("connected_concept")

                            # Track this connected concept globally
                            if connected_name not in seen_concepts:
                                seen_concepts[connected_name] = {
                                    "description": item.get("connected_description"),
                                    "sources": [concept_name]
                                }
                                # First time seeing this concept - include full info
                                deduped_network.append(item)
                            else:
                                # Already seen - just add source reference
                                if concept_name not in seen_concepts[connected_name]["sources"]:
                                    seen_concepts[connected_name]["sources"].append(concept_name)
                                # Skip duplicate - don't add to network
                                skipped_count += 1

                        logger.info(f"  {concept_name} scope_{scope}: {len(network)} total, {len(deduped_network)} new, {skipped_count} skipped")
                        concept_data[f"scope_{scope}"] = deduped_network

            results.append(concept_data)

        # Count total unique concepts across all scopes
        total_unique_concepts = len(seen_concepts)

        response = {
            "success": True,
            "original_query": cache_data.get("query"),
            "cached_at": cache_data.get("timestamp"),
            "requested_n": n,
            "returned_count": len(results),
            "scopes": scopes,
            "total_unique_concepts": total_unique_concepts,
            "deduplication_applied": True,
            "concepts": results
        }

        if total_unique_concepts > max_results:
            response["note"] = f"Total unique concepts ({total_unique_concepts}) exceeds max_results ({max_results}), but showing all due to deduplication"

        return _fmt(response)

    except Exception as e:
        logger.error(f"Error querying graph from RAG result: {e}")
        traceback.print_exc()
        return f"❌ Error: {e}"

# @mcp.tool()
def DetectEvent_sync_needed(trigger: bool = True) -> str:
    """YOU MUST call this ONLY when other event detection tools tell you to (never independently)

    YOU MUST USE THIS TOOL only when triggered by:
    - DetectEvent_concept_update (after updating concepts)
    - When other events explicitly request sync documentation

    Creates a sync entry that overviews what changes are being synchronized.
    """
    if trigger:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"CartON Prompt Chain Triggered! This prompt is for the caller, you reading this. Use add_concept to add this concept: Sync_{timestamp}, with your commit message as the concept arg."
    return ""

@mcp.tool()
def create_collection(
    collection_name: str,
    description: str,
    member_concepts: List[str],
    collection_type: str = "local"
) -> str:
    """Create a new Carton_Collection with HAS_PART relationships

    Collections are concepts that organize related concepts for context engineering.
    Use this to group concepts needed for specific work contexts.

    Args:
        collection_name: Name of the collection (e.g., "OAuth_Implementation_Collection")
        description: Description of what this collection contains and its purpose
        member_concepts: List of concept names that are part of this collection
        collection_type: Type of collection - "global", "local" (default), or "identity"

    Returns:
        Result of collection creation
    """
    try:
        # Bootstrap collection type system if not already done
        utils.bootstrap_collection_types()

        # Map collection_type to appropriate IS_A relationship
        type_mapping = {
            "global": "Global_Collection",
            "local": "Local_Collection",
            "identity": "Identity_Collection"
        }

        if collection_type not in type_mapping:
            return f"❌ Invalid collection_type '{collection_type}'. Must be 'global', 'local', or 'identity'."

        specific_type = type_mapping[collection_type]

        # Build relationships list with HAS_PART and IS_A relationships
        # Note: Only add IS_A to specific type (Global/Local/Identity_Collection)
        # Those types already have IS_A → Carton_Collection, so transitive relationship is implicit
        relationships = [
            {
                "relationship": "has_part",
                "related": member_concepts
            },
            {
                "relationship": "is_a",
                "related": [specific_type]
            }
        ]

        # Create the collection concept with HAS_PART relationships
        from .add_concept_tool import add_concept_tool_func
        result = add_concept_tool_func(collection_name, description, relationships, shared_connection=_neo4j_conn)

        # Now create the inverse PART_OF relationships from members to collection
        if member_concepts:
            cypher_query = """
            MATCH (collection:Wiki {n: $collection_name})
            UNWIND $concept_names as concept_name
            MATCH (concept:Wiki {n: concept_name})
            MERGE (concept)-[:PART_OF]->(collection)
            RETURN count(concept) as linked_count
            """

            inverse_result = utils.query_wiki_graph(
                cypher_query,
                {
                    "collection_name": collection_name,
                    "concept_names": member_concepts
                }
            )

        return f"✅ Carton_Collection created: {collection_name}\nHas {len(member_concepts)} member concepts\n\n{result}"

    except Exception as e:
        traceback.print_exc()
        return f"❌ Error creating collection: {str(e)}"

@mcp.tool()
def activate_collection(collection_name: str) -> str:
    """Activate a Carton_Collection by retrieving all member concepts

    Recursively traverses HAS_PART relationships to get full collection content.
    Use this to load all concepts from a collection for context engineering.

    Args:
        collection_name: Name of the collection to activate

    Returns:
        JSON string with all member concepts in the collection with their descriptions
    """
    try:
        result = utils.get_collection_concepts(collection_name)

        if result.get("success"):
            return _fmt(result)
        else:
            return f"❌ {result.get('error')}"

    except Exception as e:
        traceback.print_exc()
        return f"❌ Error: {e}"

@mcp.tool()
def add_to_collection(
    collection_name: str,
    concept_names: List[str]
) -> str:
    """Add concepts to an existing Carton_Collection

    Creates HAS_PART relationships from the collection to the specified concepts,
    and PART_OF relationships from concepts back to collection.

    Args:
        collection_name: Name of the collection to add concepts to
        concept_names: List of concept names to add as members

    Returns:
        Result of adding concepts to collection
    """
    try:
        # Query to add HAS_PART and PART_OF relationships (both directions)
        # We use MERGE to avoid duplicate relationships
        cypher_query = """
        MATCH (collection:Wiki {n: $collection_name})
        UNWIND $concept_names as concept_name
        MATCH (concept:Wiki {n: concept_name})
        MERGE (collection)-[:HAS_PART]->(concept)
        MERGE (concept)-[:PART_OF]->(collection)
        RETURN count(concept) as added_count
        """

        # Use shared connection directly — this is a write operation,
        # query_wiki_graph blocks MERGE via _validate_query_safety
        if _neo4j_conn:
            result = _neo4j_conn.execute_query(
                cypher_query,
                {
                    "collection_name": collection_name,
                    "concept_names": concept_names
                }
            )
            # execute_query returns list of records
            added_count = len(concept_names)
            return f"✅ Added {added_count} concepts to collection '{collection_name}'"
        else:
            return f"❌ No Neo4j connection available"

    except Exception as e:
        traceback.print_exc()
        return f"❌ Error adding to collection: {str(e)}"

@mcp.tool()
def list_collections() -> str:
    """List all Carton_Collection concepts in the knowledge graph

    Shows all concepts with IS_A Carton_Collection relationship.

    Returns:
        JSON string with list of collections and their member counts
    """
    try:
        result = utils.list_all_collections()

        if result.get("success"):
            return _fmt(result)
        else:
            return f"❌ {result.get('error')}"

    except Exception as e:
        traceback.print_exc()
        return f"❌ Error: {e}"


@mcp.tool()
def substrate_projector(
    substrate: dict = None,
    target: str = None,
    description_only: bool = True,
    template: str = None,
    get_instructions: bool = False
) -> str:
    """Project Carton concept to substrate. Use get_instructions=True for usage.

    Args:
        substrate: Dict with 'type' and type-specific fields (file, discord, registry, env)
        target: Carton concept name to project
        description_only: If True, just description; if False, include relationships
        template: Optional metastack template name (e.g., 'reference_document', 'framework_document')
                  If provided, renders concept through template before projecting
        get_instructions: If True, returns usage instructions
    """
    try:
        from carton_mcp.substrate_projector import build_instructions, substrate_project

        if get_instructions:
            return build_instructions()

        if substrate is None or target is None:
            return "❌ Required: substrate (dict) and target (concept name). Use get_instructions=True for help."

        result = substrate_project(substrate, target, description_only, template)
        return f"✅ {result}"

    except Exception as e:
        traceback.print_exc()
        return f"❌ Error: {str(e)}"


def _ensure_daemon_running():
    """Start the observation worker daemon if not already running."""
    import subprocess
    from pathlib import Path

    # Check if daemon already running
    result = subprocess.run(
        ['pgrep', '-f', 'observation_worker_daemon.py'],
        capture_output=True
    )
    if result.returncode == 0:
        return  # Already running

    # Start daemon with env vars
    github_pat = os.getenv('GITHUB_PAT')
    repo_url = os.getenv('REPO_URL')
    neo4j_uri = os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687')
    neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
    neo4j_password = os.getenv('NEO4J_PASSWORD', 'password')
    heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    openai_api_key = os.getenv('OPENAI_API_KEY')

    env = os.environ.copy()
    env_update = {
        'GITHUB_PAT': github_pat,
        'REPO_URL': repo_url,
        'NEO4J_URI': neo4j_uri,
        'NEO4J_USER': neo4j_user,
        'NEO4J_PASSWORD': neo4j_password,
        'HEAVEN_DATA_DIR': heaven_data_dir,
        'OPENAI_API_KEY': openai_api_key
    }
    env.update({k: v for k, v in env_update.items() if v is not None})

    daemon_path = Path(__file__).parent / 'observation_worker_daemon.py'
    log_path = '/tmp/carton_worker.log'

    subprocess.Popen(
        ['python3', str(daemon_path)],
        env=env,
        stdout=open(log_path, 'w'),
        stderr=subprocess.STDOUT,
        start_new_session=True
    )


def main():
    """Entry point for carton-mcp console script"""
    _ensure_daemon_running()
    transport = _gw_resolve_transport()  # refuses 'sse'; errors on unknowns
    if transport == _GW_STDIO:
        mcp.run(transport=transport)
    else:
        _gw_run_network(mcp)  # bearer-gated streamable HTTP under uvicorn

if __name__ == "__main__":
    main()