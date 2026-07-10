# add_concept_tool.py


### HEAVEN CONVERSION
# (removed 2026-06-25) The heaven-tool wrapper import `from heaven_base import BaseHeavenTool,
# ToolArgsSchema, ToolResult` was pulling langchain_core (~53 MB into EVERY carton process) ONLY to
# define the AddConceptTool/RenameConceptTool BaseHeavenTool wrappers at the bottom of this file — which
# NOTHING imports (carton exposes its tools via FastMCP/the MCP, not heaven's tool system; ToolResult was
# never even referenced). The MCP uses add_concept_tool_func / rename_concept_func DIRECTLY. heaven_base's
# package init is light (+0 MB) and the lazy `heaven_base.tool_utils.neo4j_utils` import is light (+4 MB),
# so dropping this import + the unused wrapper classes makes carton import zero langchain. (Verified live.)
from pathlib import Path
from typing import Optional, Dict, Any, List
import subprocess
import shutil
import json
import re
import os
import sys
import traceback
from difflib import get_close_matches
import logging

import urllib.request as _urllib_request  # used by the SOMA integration below
# YOUKNOW removed 2026-06-15: YOUKNOW (:8102) is DEAD CODE — SOMA (:8091) is THE
# validator now (system-type/ontology validation belongs only in SOMA). The old
# youknow_validate / _check_youknow_available / YOUKNOW_AVAILABLE health-check block
# had ZERO live callers and fired a spurious error log on every import; removed.

# SOMA integration - calls the SOMA HTTP daemon (port 8091).
# SOMA has ONE entrypoint: POST /event. Replaces YOUKNOW for concept validation.
# ENV-OVERRIDABLE (2026-06-27): set SOMA_URL to reach a REMOTE (containerized) SOMA,
# e.g. SOMA_URL=http://soma-container:8091/event. Default = local daemon. vault.py is
# already env-ready (vault.py:58); this makes the carton add_concept path match so the
# whole system can point at a mem-isolated SOMA container.
SOMA_URL = os.environ.get("SOMA_URL", "http://localhost:8091/event")

def soma_validate(source, observations, domain="default"):
    body = json.dumps({"source": source, "observations": observations, "domain": domain}).encode()
    req = _urllib_request.Request(SOMA_URL, data=body,
                                  headers={"Content-Type": "application/json"})
    with _urllib_request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data

# CARTON → CRYSTAL BALL fan-out (2026-07-02, canon/CORE-SENTENCE-SPECTRAL-SEQUENCE.md).
# carton SAYS the core sentence, SOMA ENFORCES it (soma_validate above), CB ADDRESSES it
# (places it as a coordinate). carton fans the SAME said sentence to BOTH — no CB→SOMA
# wire — and JOINS {cb_coordinate, cb_encoded, soma_region} onto the one node as PROPERTIES.
# Best-effort: a CB miss NEVER blocks the carton write (fail loud, keep the soup). Default on.
CARTON_CB_STORE = os.environ.get("CARTON_CB_STORE", "1") not in ("0", "false", "False", "")
CARTON_CB_STORE_URL = os.environ.get("CARTON_CB_STORE_URL", "http://localhost:3000/api/cb/store")
CARTON_CB_FLOW_URL = os.environ.get("CARTON_CB_FLOW_URL", "http://localhost:3000/api/cb/flow")
CARTON_CB_KEY_FILE = os.environ.get("CARTON_CB_KEY_FILE", "/tmp/heaven_data/cb_api_key.txt")

def _cb_place(concept_name, relationship_dict, soma_region, want_guidance=False):
    """Best-effort fan-out to Crystal Ball: place the said core sentence as a coordinate.

    Returns (cb_x, cb_y, cb_encoded, guidance_block_or_None). The CB coordinate is a
    2-D PLANE POINT, not the bare local fragment: cb_x = the kernel's global/column id,
    cb_y = the plane position (0.<encoded>, decodes back to (kernelId, localCoord)).
    NEVER raises — a CB failure is logged loud and returns (None, None, '', None) so the
    carton write is unaffected. Default path: POST /api/cb/store (no-auth local lane) →
    the point. When want_guidance: POST the `store` verb over the authed /api/cb/flow,
    which places AND returns the four-layer PROMPTER block (folded into the response).
    """
    rels = {str(k): [str(t) for t in (v or [])] for k, v in (relationship_dict or {}).items()}

    if want_guidance:
        try:
            key = ""
            try:
                with open(CARTON_CB_KEY_FILE) as _f:
                    key = _f.read().strip()
            except Exception:
                key = ""
            # The store VERB sentence: "store <Name> <pred> <targets…> … region <grade>".
            parts = [concept_name]
            for pred in ("is_a", "part_of", "has_part", "has_domain", "instantiates", "produces"):
                ts = rels.get(pred, [])
                if ts:
                    parts.append(pred)
                    parts.extend(ts)
            sentence = "store " + " ".join(parts) + (f" region {soma_region}" if soma_region else "")
            body = json.dumps({"input": sentence}).encode()
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            req = _urllib_request.Request(CARTON_CB_FLOW_URL, data=body, headers=headers)
            with _urllib_request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            store = (data.get("data") or {}).get("store") or {}
            view = data.get("view") or ""
            return store.get("x"), store.get("y"), str(store.get("encoded", "")), (view or None)
        except Exception as e:
            logger.warning(f"CB flow-guidance failed (carton write unaffected): {e}\n{traceback.format_exc()}")
            # fall through to the plain store so the coordinate still lands as a property

    try:
        body = json.dumps({
            "conceptName": concept_name,
            "relationships": rels,
            "region": soma_region,
            "source": "carton",
        }).encode()
        req = _urllib_request.Request(CARTON_CB_STORE_URL, data=body,
                                      headers={"Content-Type": "application/json"})
        with _urllib_request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data.get("x"), data.get("y"), str(data.get("encoded", "")), None
    except Exception as e:
        logger.warning(f"CB store failed (carton write unaffected): {e}\n{traceback.format_exc()}")
        return None, None, "", None

def _check_soma_available():
    try:
        # SOMA only exposes POST /event. A GET returns 404 — a 404 means the daemon
        # is up and responding. ConnectionRefusedError means the daemon is down.
        req = _urllib_request.Request("http://localhost:8091/event", method="GET")
        _urllib_request.urlopen(req, timeout=2)
        return True
    except _urllib_request.HTTPError:
        # 404 from SOMA means daemon is up and responding
        return True
    except Exception as e:
        # A TIMEOUT means UP-BUT-BUSY, not down (2026-07-06): the daemon SERIALIZES
        # events, so whenever any event is in flight a 2s GET loses the race — which
        # is most of the time under the observation daemon's continuous drain. Only
        # a fast failure (connection refused / unreachable) means genuinely down.
        # Before this, a fresh carton process importing during any in-flight event
        # froze SOMA_AVAILABLE=False and silently skipped validation FOREVER.
        if "timed out" in str(e).lower() or isinstance(e, TimeoutError):
            return True
        return False

SOMA_AVAILABLE = _check_soma_available()
if not SOMA_AVAILABLE:
    logging.getLogger(__name__).error(
        "SOMA DAEMON NOT RUNNING on port 8091. "
        "Validation is DISABLED until it answers. Start it: python3 -m soma_prolog.api --port 8091"
    )


def _soma_up() -> bool:
    """Call-time SOMA availability: memoized-UPGRADE re-check (2026-07-06).

    The import-time SOMA_AVAILABLE snapshot could freeze False for the process
    LIFETIME (e.g. carton imported during a SOMA restart window) — silently
    skipping validation on every subsequent add_concept. Re-check on each call
    while False; once True it stays True (soma_validate's own try/except handles
    a later outage loudly per-call, and a down SOMA fails FAST — refused — so
    attempting is cheap).
    """
    global SOMA_AVAILABLE
    if SOMA_AVAILABLE:
        return True
    SOMA_AVAILABLE = _check_soma_available()
    if SOMA_AVAILABLE:
        logging.getLogger(__name__).info("SOMA daemon now reachable — validation re-enabled.")
    return SOMA_AVAILABLE

logger = logging.getLogger(__name__)

# Import the concept config helpers locally
from carton_mcp.concept_config import ConceptConfig
# Removed: queue, threading, atexit - no background threads in MCP

# Module-level shared Neo4j connection (lazy initialized)
_module_neo4j_conn = None

def _get_module_connection():
    """Get or create module-level shared Neo4j connection."""
    global _module_neo4j_conn
    if _module_neo4j_conn is None:
        try:
            from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
            config = ConceptConfig()
            _module_neo4j_conn = KnowledgeGraphBuilder(
                uri=config.neo4j_url,
                user=config.neo4j_username,
                password=config.neo4j_password
            )
            _module_neo4j_conn._ensure_connection()
            logger.info("add_concept_tool: Module-level Neo4j connection established")
        except Exception as e:
            logger.warning(f"Failed to create module Neo4j connection: {e}")
            return None
    return _module_neo4j_conn

# Valid observation tags
OBSERVATION_TAGS = {
    "insight_moment",
    "struggle_point",
    "daily_action",
    "implementation",
    "emotional_state"
}

# Personal domain enum - which strata/area this relates to
PERSONAL_DOMAINS = [
    "paiab",      # building AI/agents
    "sanctum",    # philosophy/life architecture
    "cave",       # business/funnels
    "misc",       # doesn't fit a strata yet
    "personal"    # non-work life stuff
]

# UARL predicates - Universal Alignment Relationship Language
#
# ⚠️ CURRENT STATE: STATIC HARDCODED LIST (WRONG)
#
# WHAT THIS SHOULD BE:
# Dynamic enum that auto-updates when new relationship types with valid origination stacks are created.
#
# HOW IT SHOULD WORK:
# 1. Query Neo4j for concepts where: (concept)-[:IS_A]->(Relationship) AND (concept)-[:HAS_ORIGINATION_STACK]->()
# 2. Those concepts are valid UARL predicates (strongly compressed relationship types)
# 3. When used, they compress logic because they have witnessed origination chains
#
# ORIGINATION STACK VALIDATION (not yet implemented):
# An origination stack proves a relationship is strongly compressed by showing:
# - embodies: implicit structure recognized
# - manifests: structure established in soup
# - reifies: fully composed with all required parts
# Stack witnesses that the relationship type is ontologically valid.
#
# RELATIONSHIP COMPRESSION:
# - weak_compression: arbitrary string, no origination stack, requires evolution
# - simple_strong: UARL predicate with origination stack
# - composite_strong: UARL predicate built from other UARL predicates
#
# CONCEPT COMPRESSION (aggregated from relationships):
# - Concept is STRONGLY COMPRESSED if ALL morphisms to it are strong
# - If ANY morphism is weak → concept is HALLUCINATION (weak compression)
# - Weak concepts get REQUIRES_EVOLUTION marker
#
# ONTOLOGY LAYER:
# Strongly compressed concepts: (concept)-[:IS_A]->(Carton_Ontology_Entity)
# Query param: graph_type="ontology"|"wiki" to filter by layer
#
# CURRENT KNOWN STRONG PREDICATES (have validation logic):
# - is_a: check_is_a_cycle() validates
# - part_of: check_part_of_cycle() validates
# - instantiates: check_instantiates_completeness() validates
#
# TODO: Implement full UARL system
# 1. Create Origination_Stack concept and validation
# 2. Make UARL_PREDICATES dynamic (query graph)
# 3. Implement concept compression aggregation
# 4. Add Carton_Ontology_Entity layer
# 5. Add graph_type query filtering
#
UARL_PREDICATES = {
    "is_a",
    "part_of",
    "instantiates",
    "embodies",
    "manifests",
    "reifies",
    "programs",
    "validates",
    "invalidates"
}

def get_uarl_predicates(config: ConceptConfig) -> set:
    """
    Get dynamic UARL predicates by querying for reified relationship concepts.

    A relationship concept is a valid UARL predicate if:
    - It has a REIFIES relationship (strongly compressed)

    Bootstrap predicates (primitives that don't need REIFIES):
    - is_a, part_of, instantiates

    Args:
        config: ConceptConfig with Neo4j credentials

    Returns:
        Set of valid UARL predicate names

    Note:
        REIFIES creation workflow not yet implemented - returns bootstrap primitives only.
        When formalization workflow is built, uncomment query logic below.
        This prevents 100+ redundant Neo4j queries per observation (CPU spike).
    """
    # Bootstrap primitives (always valid)
    return {"is_a", "part_of", "instantiates"}

    # TODO: Uncomment when REIFIES creation workflow is implemented
    # try:
    #     from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
    #
    #     graph = KnowledgeGraphBuilder(
    #         uri=config.neo4j_url,
    #         user=config.neo4j_username,
    #         password=config.neo4j_password
    #     )
    #
    #     # Bootstrap primitives (always valid)
    #     predicates = {"is_a", "part_of", "instantiates"}
    #
    #     # Query for reified concepts (have REIFIES relationship to Carton_Ontology_Entity)
    #     reified_query = """
    #     MATCH (c:Wiki)-[:REIFIES]->(onto:Wiki {n: "Carton_Ontology_Entity"})
    #     RETURN DISTINCT c.n as predicate
    #     """
    #
    #     result = graph.execute_query(reified_query)
    #     graph.close()
    #
    #     if result:
    #         for record in result:
    #             predicates.add(record['predicate'])
    #
    #     return predicates
    #
    # except Exception as e:
    #     # Fallback to bootstrap primitives if query fails
    #     print(f"[UARL] Could not query dynamic predicates: {e}", file=sys.stderr)
    #     return {"is_a", "part_of", "instantiates"}


def classify_compression_type(rel_type: str, config: ConceptConfig, is_composite: bool = False) -> str:
    """
    Classify relationship compression type.

    - weak_compression: Relationship type not in UARL predicates (not reified)
    - simple_strong: UARL predicate (reified), not composite
    - composite_strong: UARL predicate (reified), composite

    Args:
        rel_type: Relationship type string
        config: ConceptConfig for querying UARL predicates
        is_composite: Whether relationship is built from other relationships

    Returns:
        Compression type: "weak_compression", "simple_strong", or "composite_strong"
    """
    uarl_predicates = get_uarl_predicates(config)

    if rel_type not in uarl_predicates:
        return "weak_compression"

    return "composite_strong" if is_composite else "simple_strong"

# ============================================================================
# File-based queue for observations
def get_observation_queue_dir():
    """Get observation queue directory path"""
    heaven_data_dir = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    queue_dir = Path(heaven_data_dir) / 'carton_queue'
    queue_dir.mkdir(parents=True, exist_ok=True)
    return queue_dir


# ============================================================================
# P0 REJECTION_LEDGER (Griess-Neural-Surrogate exhaust patch #1, 2026-07-06).
# Type-2 contradictions and mereo_error verdicts were DROPPED the moment SOMA
# returned them — logged + relayed to the caller, never persisted. But they are
# oracle-labeled HARD NEGATIVES (SOMA, the symbolic oracle, judged this exact
# claim-structure inadmissible) — the training gold Slot_Fill_Ranker needs, which
# most KG-completion projects have to FAKE by corrupting real triples. This
# ledger captures them as a byproduct of normal operation, continuously, for
# free. Append-only JSONL, same park-file idiom as soma_fillers' human queue.
# BEST-EFFORT: a ledger fault is logged and swallowed — recording a rejection
# must never affect the add_concept verdict path itself.
def rejection_ledger_path() -> str:
    """The SOMA-rejection ledger file (dir created if absent)."""
    base = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'soma_rejections.jsonl')


def record_soma_rejection(concept_name: str, relationships, verdict_kind: str,
                          reason: str) -> None:
    """Append one oracle-labeled hard negative to the rejection ledger. NEVER raises.

    Shape per record: {concept, relationships, verdict_kind, reason, timestamp} —
    the claim-structure SOMA rejected, labeled by WHICH verdict rejected it
    (contradiction = Type-2 geometric reject; mereo_error = Type-1 undefined-is_a
    fill-signal — saved as soup by carton, but still a negative example of a
    well-formed claim) and SOMA's own reason line.
    """
    from datetime import datetime
    try:
        record = {
            "concept": concept_name,
            "relationships": relationships,
            "verdict_kind": verdict_kind,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }
        with open(rejection_ledger_path(), 'a') as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        logger.error(f"rejection ledger append failed (non-fatal): {e}", exc_info=True)


# REMOVED: All Neo4j in-memory queue and threading code
# Threads don't work in MCP isolation - Neo4j writes now happen synchronously


def normalize_concept_name(name: str) -> str:
    """
    Normalize concept name to Title_Case_With_Underscores format.

    This is the single source of truth for concept name normalization.
    Used for filesystem paths, Neo4j node names, and all concept references.

    Args:
        name: Raw concept name (can have spaces, any casing)

    Returns:
        Normalized name in Title_Case_With_Underscores format

    Examples:
        "my cool concept" -> "My_Cool_Concept"
        "NEURAL NETWORK" -> "Neural_Network"
        "hello_world" -> "Hello_World"
    """
    # Replace hyphens with underscores first (UUIDs, session IDs)
    name = name.replace("-", "_")
    # Replace underscores with spaces for title casing
    name_with_spaces = name.replace("_", " ")
    # Apply title case (capitalizes each word)
    title_cased = name_with_spaces.title()
    # Replace spaces with underscores
    return title_cased.replace(" ", "_")


def run_git_command(cmd: list[str], cwd: str) -> Dict[str, str]:
    """Run a git command synchronously."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False  # Changed: removed check=True to prevent false failures
        )
        # Changed: check return code manually instead of relying on check=True
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        return {"output": result.stdout.strip()}
    except Exception as e:
        # Changed: catch all exceptions instead of just CalledProcessError
        return {"error": str(e)}

def setup_git_repo(config: ConceptConfig, base_path: str) -> Dict[str, str]:
    """Setup git repo - clone if doesn't exist, use existing if it does."""
    base_path_obj = Path(base_path)

    # Check if repo already exists with valid .git directory
    if base_path_obj.exists() and (base_path_obj / ".git").exists():
        # Repo exists - use it as-is (no pull needed, we're only writing)
        print("Repo exists, using local copy...", file=sys.stderr)
        return {"output": "Using existing repo"}

    # Repo doesn't exist - do fresh clone
    print("Cloning fresh repo...", file=sys.stderr)

    # 1. Remove any partial/corrupted state
    shutil.rmtree(base_path, ignore_errors=True)

    # 2. Set up git credentials BEFORE cloning
    auth_url = f"https://{config.github_pat}@github.com"
    credentials_path = Path.home() / ".git-credentials"
    credentials_path.write_text(auth_url + "\n")

    # 3. Prepare the clean remote URL (no PAT in URL since we use credential helper)
    repo_url = config.private_wiki_url
    if not repo_url.endswith(".git"):
        repo_url += ".git"

    # 4. Clone the latest remote repo into base_path
    result = run_git_command(["git", "clone", repo_url, base_path], ".")
    if "error" in result:
        return {"error": f"Git clone failed: {result['error']}"}

    # 5. Configure identity for future commits
    commands = [
        ["git", "config", "user.email", "bot@example.com"],
        ["git", "config", "user.name", "Concept Bot"],
        ["git", "config", "credential.helper", "store"],
    ]
    for cmd in commands:
        r = run_git_command(cmd, base_path)
        if "error" in r:
            return {"error": f"Git config failed: {r['error']}"}

    return {"output": "Git repo cloned successfully"}

def sync_with_remote(config: ConceptConfig, base_path: str) -> Dict[str, str]:
    """Synchronize local repository with remote."""
    auth_url = f"https://{config.github_pat}@github.com"
    credentials_path = Path.home() / ".git-credentials"
    credentials_path.write_text(auth_url + "\n")

    result = run_git_command(["git", "fetch", "origin"], base_path)
    if "error" in result:
        return {"error": f"Git fetch failed: {result['error']}"}

    result = run_git_command(
        ["git", "pull", "--no-rebase", "origin", config.private_wiki_branch], base_path
    )
    if "error" in result:
        return {"error": f"Git pull failed: {result['error']}"}

    return {"output": "Sync successful"}


def auto_link_description(description: str, base_path: str, current_concept: str, concept_cache: List[str] = None, _automaton_cache: dict = {}) -> str:
    """Public auto-linker with CartON KV FENCE-OPACITY.

    A `<CartonObj name=..>{ JSON-with-bare-refs }</CartonObj>` fence stored in n.d must NEVER
    be touched by linkification: the linker would otherwise (a) linkify the open tag's `name=`
    and every Title_Case word, and (b) EAT JSON array brackets because `[x]` is markdown-link
    syntax (`["clone","install"]` -> `"clone", "[install](..)"`). So before linking we MASK each
    full fence span (open tag + body) with an opaque private-use sentinel char (zero alnum chars
    -> immune to the concept automaton AND to the bracket-strip regexes), run the real linker on
    the rest, then RESTORE the fences VERBATIM. Hooking here covers ALL callers (linker_thread,
    intra-observation linking, retroactive_autolink). The actual linking logic lives in
    _auto_link_core below; this wrapper only adds the mask/restore.
    """
    try:
        from .carton_kv import find_carton_objs
        fences = find_carton_objs(description)
    except Exception:
        fences = []  # carton_kv unavailable -> degrade to plain linking (never crash the linker)

    if not fences:
        return _auto_link_core(description, base_path, current_concept, concept_cache, _automaton_cache)

    # Mask right-to-left (so earlier spans' offsets stay valid); one unique private-use char per fence.
    masked = description
    restore = []
    for i, f in enumerate(sorted(fences, key=lambda x: x.span[0], reverse=True)):
        placeholder = chr(0xE000 + i)  # Private Use Area: not alnum, not [](), not in any concept name
        restore.append((placeholder, description[f.span[0]:f.span[1]]))
        masked = masked[:f.span[0]] + placeholder + masked[f.span[1]:]

    linked = _auto_link_core(masked, base_path, current_concept, concept_cache, _automaton_cache)

    for placeholder, original in restore:
        linked = linked.replace(placeholder, original)  # restore each fence VERBATIM
    return linked


def _auto_link_core(description: str, base_path: str, current_concept: str, concept_cache: List[str] = None, _automaton_cache: dict = {}) -> str:
    """
    Convert concept name mentions in description to markdown links.
    
    Uses Aho-Corasick algorithm for O(text_length) matching instead of O(n*text_length).
    Builds automaton once and caches it for reuse across calls.
    
    Args:
        description: Text to scan for concept mentions
        base_path: Wiki base path for link generation
        current_concept: Concept being processed (exclude from linking)
        concept_cache: List of concept names to match
        _automaton_cache: Internal cache for automaton (mutable default for persistence)
    
    Returns:
        Description with markdown links added
    """
    try:
        import ahocorasick
    except ImportError:
        print("[auto_link] ahocorasick not installed, skipping auto-linking", file=sys.stderr)
        return description

    # Strip existing wiki links FIRST to prevent recursive nesting.
    # Wiki links end with _itself.md) — use that as the literal end anchor.
    # URLs may contain ( ) when concept names have parens (e.g. Orient()), so we
    # cannot delimit the URL with [^)]. Label class excludes [ and ] so the regex
    # matches innermost-first when nested; iterate until idempotent.
    # Also handles orphan residue from prior partial strips (bracketless chains
    # like /X/X_itself.md) and trailing _itself.md) tails with no preceding (.
    import re as _re
    for _ in range(200):
        prev = description
        # Well-formed wiki links: [label](../X_itself.md) → label
        description = _re.sub(r"\[([^\[\]]*?)\]\(\.\./.+?_itself\.md\)", r"\1", description)
        # Orphan parenthesized URL: (../X_itself.md) → empty
        description = _re.sub(r"\(\.\./.+?_itself\.md\)", "", description)
        # Bracketless orphan chain: /<concept>_itself.md)+ residue from prior partial strips
        description = _re.sub(r"/[^/\s]*?_itself\.md\)+", "", description)
        # Bare trailing _itself.md) with no preceding slash
        description = _re.sub(r"_itself\.md\)+", "", description)
        if description == prev:
            break
    description = _re.sub(r"\[([^\[\]]*?)\]", r"\1", description)
    description = _re.sub(r"[\[\]]", "", description)
    description = _re.sub(r"  +", " ", description)

    # Get all existing concept names (use cache if provided, otherwise query Neo4j)
    if concept_cache is not None:
        existing_concepts = [c for c in concept_cache if c != current_concept]
    else:
        from .carton_utils import CartOnUtils
        utils = CartOnUtils(shared_connection=_get_module_connection())
        existing_concepts = utils.get_all_concept_names(exclude_concept=current_concept)
    
    if not existing_concepts:
        return description
    
    # Build or get cached automaton
    cache_key = len(existing_concepts)  # Simple cache invalidation by size
    if cache_key not in _automaton_cache:
        _automaton_cache.clear()  # Evict old automatons to prevent memory accumulation
        print(f"[auto_link] Building Aho-Corasick automaton for {cache_key} concepts...", file=sys.stderr)
        
        A = ahocorasick.Automaton()
        
        # Add each concept and its variations to the automaton
        for concept in existing_concepts:
            if len(concept) <= 1:
                continue
            
            # Generate variations for matching
            variations = [
                concept,                              # Original
                concept.replace('_', ' '),            # Underscores to spaces
                concept.replace('_', ' ').title(),    # Title case
                concept.lower(),                      # Lowercase
                concept.replace('_', ' ').lower(),    # Lowercase with spaces
                concept.upper(),                      # Uppercase
                concept.replace('_', ' ').upper(),    # Uppercase with spaces
            ]
            
            # Add each variation pointing to the canonical concept name
            for var in set(variations):  # dedupe
                if len(var) > 1:
                    # Store (variation, canonical_concept) so we can rebuild the link
                    A.add_word(var.lower(), (var, concept))
        
        A.make_automaton()
        _automaton_cache[cache_key] = A
        print(f"[auto_link] Automaton built", file=sys.stderr)
    
    A = _automaton_cache[cache_key]
    
    # Find all matches in the description (case-insensitive by lowercasing input)
    desc_lower = description.lower()
    matches = []
    
    for end_idx, (matched_text, canonical_concept) in A.iter(desc_lower):
        start_idx = end_idx - len(matched_text) + 1
        
        # Check word boundaries (don't match inside words)
        before_ok = start_idx == 0 or not desc_lower[start_idx - 1].isalnum()
        after_ok = end_idx + 1 >= len(desc_lower) or not desc_lower[end_idx + 1].isalnum()
        
        if before_ok and after_ok:
            # Check if this concept is already linked
            if f"[{canonical_concept}]" not in description:
                matches.append((start_idx, end_idx + 1, matched_text, canonical_concept))
    
    if not matches:
        return description
    
    # Sort by position (reverse) and apply replacements
    # Use longest match when overlapping
    matches.sort(key=lambda x: (-x[0], -(x[1] - x[0])))
    
    # Track replaced ranges to avoid overlaps
    replaced_ranges = []
    result = description
    offset = 0
    
    # Sort by start position for proper offset handling
    matches.sort(key=lambda x: x[0])
    
    for start_idx, end_idx, matched_text, canonical_concept in matches:
        # Check for overlap with already replaced ranges
        overlaps = False
        for r_start, r_end in replaced_ranges:
            if not (end_idx <= r_start or start_idx >= r_end):
                overlaps = True
                break
        
        if overlaps:
            continue
        
        # Get the actual text from original description (preserve case)
        actual_text = description[start_idx:end_idx]
        replacement = f"[{actual_text}](../{canonical_concept}/{canonical_concept}_itself.md)"
        
        # Apply replacement with offset
        adj_start = start_idx + offset
        adj_end = end_idx + offset
        result = result[:adj_start] + replacement + result[adj_end:]
        
        # Update offset for next replacement
        offset += len(replacement) - (end_idx - start_idx)
        replaced_ranges.append((start_idx, end_idx))
    
    return result

def find_auto_relationships(content: str, base_path: str, current_concept: str, concept_cache: List[str] = None) -> List[str]:
    """Find ALL concept mentions in content using the same fuzzy matching as auto-linking."""
    # Get all existing concept names (use cache if provided, otherwise query Neo4j)
    if concept_cache is not None:
        existing_concepts = [c for c in concept_cache if c != current_concept]
    else:
        from .carton_utils import CartOnUtils
        utils = CartOnUtils()
        existing_concepts = utils.get_all_concept_names(exclude_concept=current_concept)
    
    mentioned_concepts = []
    for concept in existing_concepts:
        # Skip single-character concepts (noise from auto-detection)
        if len(concept) <= 1:
            continue

        # Generate the same formatting variations as auto-linking
        variations = set()
        variations.add(concept)
        concept_with_spaces = concept.replace('_', ' ')
        variations.add(concept_with_spaces)
        variations.add(concept_with_spaces.title())
        variations.add(concept.upper())
        variations.add(concept_with_spaces.upper())
        variations.add(concept.lower())
        variations.add(concept_with_spaces.lower())
        
        # Check if any variation appears in content
        import re
        for variation in variations:
            pattern = r'\b' + re.escape(variation) + r'\b'
            if re.search(pattern, content, re.IGNORECASE):
                mentioned_concepts.append(concept)
                break  # Found this concept, don't need to check other variations
    
    return mentioned_concepts


def infer_relationships_for_missing_concept(missing_concept: str, concepts_dir: Path) -> Dict[str, List[str]]:
    """Infer what relationships a missing concept should have based on existing references to it."""
    relationship_inverses = {
        'is_a': 'has_instances',
        'part_of': 'has_parts',
        'depends_on': 'supports',
        'instantiates': 'has_instances',
        'relates_to': 'relates_to',  # bidirectional
        'has_tag': 'has_concepts',  # tag metadata
        'has_personal_domain': 'contains_concepts',  # personal domain categorization (enum)
        'has_actual_domain': 'contains_concepts',  # actual domain categorization (flexible)
        'has_subdomain': 'contains_concepts',  # subdomain categorization
        'has_subsubdomain': 'contains_concepts'  # subsubdomain categorization
    }

    inferred_relationships = {}
    
    # Scan all existing concept relationship files
    for concept_dir in concepts_dir.iterdir():
        if not concept_dir.is_dir():
            continue
            
        components_dir = concept_dir / "components"
        if not components_dir.exists():
            continue
            
        # Check each relationship type directory
        for rel_dir in components_dir.iterdir():
            if not rel_dir.is_dir() or rel_dir.name == "description":
                continue
                
            rel_type = rel_dir.name
            if rel_type not in relationship_inverses:
                continue
                
            # Check relationship files for references to missing concept
            for rel_file in rel_dir.glob("*.md"):
                content = rel_file.read_text(encoding="utf-8")

                # Look for links to the missing concept (../concept/ format)
                link_pattern = re.compile(rf"\[.*?\]\(\.\./({re.escape(missing_concept)})/[^)]*\)")
                if link_pattern.search(content):
                    # Found a reference! Infer the inverse relationship
                    inverse_rel = relationship_inverses[rel_type]
                    if inverse_rel not in inferred_relationships:
                        inferred_relationships[inverse_rel] = []
                    inferred_relationships[inverse_rel].append(concept_dir.name)
    
    return inferred_relationships


def check_missing_concepts_and_manage_file(base_path: str, current_concept: str, concept_cache: List[str] = None) -> List[str]:
    """Check for missing concepts and manage missing_concepts.md file with relationship inference."""
    # Get all existing concept names (use cache if provided, otherwise query Neo4j)
    if concept_cache is not None:
        all_concept_names = concept_cache
    else:
        from .carton_utils import CartOnUtils
        utils = CartOnUtils()
        all_concept_names = utils.get_all_concept_names()
    existing_concepts = {name.lower(): name for name in all_concept_names}

    # Still need filesystem for markdown file scanning
    concepts_dir = Path(base_path) / "concepts"
    if not concepts_dir.exists():
        return []
    
    # Find broken links in markdown files - look for relative path format ../concept_name/
    link_pattern = re.compile(r"\[.*?\]\(\.\./([^/]+)/[^)]*\)")
    missing_concepts = set()
    
    for md_file in concepts_dir.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        for match in link_pattern.findall(content):
            concept_name = match  # match is just the concept_name
            if concept_name.lower() not in existing_concepts:
                missing_concepts.add(concept_name)
    
    # Remove the current concept if it was just created
    if current_concept:
        missing_concepts.discard(current_concept)
        # Also remove case variations
        missing_concepts = {c for c in missing_concepts if c.lower() != current_concept.lower()}
    
    # Path to missing concepts file
    missing_file = Path(base_path) / "missing_concepts.md"
    
    processed = []
    
    if missing_concepts:
        # Create content with relationship inference
        content = ["# Missing Concepts", ""]
        content.append("The following concepts are referenced but don't exist yet.")
        content.append("Relationships are inferred from existing references:")
        content.append("")
        
        for concept_name in sorted(missing_concepts):
            # Infer relationships for this missing concept
            inferred_rels = infer_relationships_for_missing_concept(concept_name, concepts_dir)
            
            # Find similar concepts for suggestions
            suggestions = get_close_matches(
                concept_name.lower(), 
                existing_concepts.keys(), 
                n=3, 
                cutoff=0.6
            )
            suggestion_names = [existing_concepts[s] for s in suggestions]
            
            content.append(f"## {concept_name}")
            
            if inferred_rels:
                content.append("**Inferred relationships:**")
                for rel_type, related_concepts in inferred_rels.items():
                    content.append(f"- {rel_type}: {', '.join(related_concepts)}")
                content.append("")
            
            if suggestion_names:
                content.append(f"**Similar existing concepts:** {', '.join(suggestion_names)}")
            else:
                content.append("**Similar existing concepts:** None")
            content.append("")
        
        missing_file.write_text("\n".join(content))
        processed.append(f"Updated missing_concepts.md with {len(missing_concepts)} missing concepts and inferred relationships")
    else:
        # Remove file if no missing concepts
        if missing_file.exists():
            missing_file.unlink()
            processed.append("Removed missing_concepts.md - all concepts now exist")
        else:
            processed.append("No missing concepts found")
    
    return processed

def commit_and_push(config: ConceptConfig, base_path: str, commit_msg: str) -> Dict[str, str]:
    """Commit and push changes to the remote repository."""
    commands = [
        ["git", "add", "."],
        ["git", "commit", "-m", commit_msg],
        ["git", "push", "origin", config.private_wiki_branch],
    ]

    for cmd in commands:
        result = run_git_command(cmd, base_path)
        if "error" in result:
            return {"error": f"Git command failed: {result['error']}"}
    return {"output": "Changes pushed successfully"}


def check_part_of_cycle(config: ConceptConfig, source: str, target: str) -> Dict[str, Any]:
    """Check if adding (source)-[:PART_OF]->(target) would create a cycle."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Check if source is reachable from target via PART_OF
        # If target can reach source, then adding source->target would create a cycle
        cycle_check_query = """
        MATCH (source:Wiki {n: $source})
        MATCH (target:Wiki {n: $target})
        MATCH path = (target)-[:PART_OF*]->(source)
        RETURN COUNT(path) > 0 as has_cycle
        """

        result = graph.execute_query(cycle_check_query, {'source': source, 'target': target})
        graph.close()

        if result and result[0].get('has_cycle', False):
            return {"error": f"Cycle detected: adding part_of from {source} to {target} would create cycle"}

        return {"valid": True}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Cycle check failed: {str(e)}"}


def check_is_a_cycle(config: ConceptConfig, source: str, target: str) -> Dict[str, Any]:
    """Check if adding (source)-[:IS_A]->(target) would create a cycle."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Check if source is reachable from target via IS_A
        # If target can reach source, then adding source->target would create a cycle
        cycle_check_query = """
        MATCH (source:Wiki {n: $source})
        MATCH (target:Wiki {n: $target})
        MATCH path = (target)-[:IS_A*]->(source)
        RETURN COUNT(path) > 0 as has_cycle
        """

        result = graph.execute_query(cycle_check_query, {'source': source, 'target': target})
        graph.close()

        if result and result[0].get('has_cycle', False):
            return {"error": f"Cycle detected: adding is_a from {source} to {target} would create cycle"}

        return {"valid": True}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Cycle check failed: {str(e)}"}


def is_concept_instantiated(config: ConceptConfig, concept_name: str) -> bool:
    """Check if concept has any instantiates relationships pointing to it."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        instantiation_query = """
        MATCH ()-[:INSTANTIATES]->(c:Wiki {n: $concept_name})
        RETURN COUNT(*) > 0 as is_instantiated
        """

        result = graph.execute_query(instantiation_query, {'concept_name': concept_name})
        graph.close()

        return result and result[0].get('is_instantiated', False)

    except Exception as e:
        traceback.print_exc()
        return False


def check_instantiates_completeness(config: ConceptConfig, source: str, target: str, source_parts: List[str] = None) -> Dict[str, Any]:
    """
    Check if source has all parts required to instantiate target label.

    INSTANTIATES is reification: source claims to be a concrete instance of target's abstract pattern.
    Target is defined by IS_A relationships. Each IS_A target has PART_OF requirements.
    Source must have PART_OF to ALL parts from ALL IS_A definitions to instantiate target.

    Args:
        source_parts: Optional list of parts being added. If None, queries Neo4j for existing parts.
    """
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Get what target is defined as (all IS_A relationships)
        # Then get all parts from those definitions
        required_parts_query = """
        MATCH (target:Wiki {n: $target})-[:IS_A]->(definition:Wiki)
        MATCH (part)-[:PART_OF]->(definition)
        RETURN COLLECT(DISTINCT part.n) as required_parts, COLLECT(DISTINCT definition.n) as definitions
        """

        result = graph.execute_query(required_parts_query, {'target': target})

        if not result or not result[0].get('required_parts'):
            graph.close()
            # Target has no IS_A definitions or those definitions have no parts
            return {"error": f"Cannot instantiate {target}: target has no IS_A definitions with parts"}

        required_parts = result[0]['required_parts']
        definitions = result[0]['definitions']

        # Get source parts: either from parameter or query Neo4j
        if source_parts is None:
            source_parts_query = """
            MATCH (source:Wiki {n: $source})-[:PART_OF]->(part:Wiki)
            RETURN COLLECT(part.n) as source_parts
            """

            source_result = graph.execute_query(source_parts_query, {'source': source})
            graph.close()

            if not source_result:
                return {"error": f"Source concept '{source}' not found in Neo4j"}

            source_parts = source_result[0].get('source_parts', [])
        else:
            graph.close()

        # Check if source has PART_OF to all required parts
        missing_parts = [part for part in required_parts if part not in source_parts]

        if missing_parts:
            return {
                "error": f"Cannot instantiate {target}: source '{source}' missing required parts: {', '.join(missing_parts)}. "
                        f"Target IS_A {definitions} which require parts {required_parts}. Source only has {source_parts}."
            }

        return {"valid": True, "required_parts": required_parts, "source_parts": source_parts, "definitions": definitions}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Completeness check failed: {str(e)}"}


def get_next_version_number(config: ConceptConfig, base_name: str) -> str:
    """Find next available version number for a concept."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Find all versions of this concept
        version_query = """
        MATCH (c:Wiki)
        WHERE c.n = $base_name OR c.n =~ $version_pattern
        RETURN c.n as name
        ORDER BY c.n
        """

        params = {
            'base_name': base_name,
            'version_pattern': f"{base_name}_v[0-9]+"
        }

        result = graph.execute_query(version_query, params)
        graph.close()

        if not result:
            return f"{base_name}_v2"

        # Extract version numbers
        import re
        max_version = 1
        for record in result:
            name = record['name']
            match = re.match(rf"{re.escape(base_name)}_v(\d+)", name)
            if match:
                version_num = int(match.group(1))
                max_version = max(max_version, version_num)

        return f"{base_name}_v{max_version + 1}"

    except Exception as e:
        traceback.print_exc()
        return f"{base_name}_v2"


def create_concept_in_neo4j(config: ConceptConfig, concept_name: str, description: str, relationships: Dict[str, List[str]], shared_connection=None) -> str:
    """Create concept in Neo4j with :Wiki namespace using minimal tokens."""
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

        if shared_connection:
            graph = shared_connection
            should_close = False
        else:
            # Try module-level connection first (fast path)
            graph = _get_module_connection()
            if graph:
                should_close = False
            else:
                # Fallback: create temporary connection (slow path)
                graph = KnowledgeGraphBuilder(
                    uri=config.neo4j_url,
                    user=config.neo4j_username,
                    password=config.neo4j_password
                )
                should_close = True

        # Create indexes for Wiki namespace
        index_queries = [
            "CREATE INDEX wiki_concept_name IF NOT EXISTS FOR (c:Wiki) ON (c.n)",
            "CREATE INDEX wiki_concept_canonical IF NOT EXISTS FOR (c:Wiki) ON (c.c)",
        ]
        
        for query in index_queries:
            graph.execute_query(query)
        
        # Create concept node
        # Only set c.t on creation (when null), always update c.last_modified
        concept_query = """
        MERGE (c:Wiki {n: $name, c: $canonical_form})
        SET c.d = $description
        SET c.t = CASE WHEN c.t IS NULL THEN datetime($timestamp) ELSE c.t END
        SET c.last_modified = datetime($timestamp)
        RETURN c.n as node_id
        """
        
        from datetime import datetime
        params = {
            'name': concept_name,
            'canonical_form': concept_name.lower().replace(' ', '_'),
            'description': description or f"No description available for {concept_name}.",
            'timestamp': datetime.now().isoformat()
        }
        
        result = graph.execute_query(concept_query, params)
        
        # Define inverse relationships
        relationship_inverses = {
            'is_a': 'has_instances',
            'part_of': 'has_parts',
            'depends_on': 'supports',
            'instantiates': 'has_instances',
            'relates_to': 'relates_to',  # bidirectional
            'has_tag': 'has_concepts',  # tag metadata
            'has_personal_domain': 'contains_concepts',  # personal domain categorization (enum)
            'has_actual_domain': 'contains_concepts',  # actual domain categorization (flexible)
            'has_subdomain': 'contains_concepts',  # subdomain categorization
            'has_subsubdomain': 'contains_concepts'  # subsubdomain categorization
        }

        # Create relationships
        weak_rel_types = []
        for rel_type, related_concepts in relationships.items():
            # Classify compression type
            compression_type = classify_compression_type(rel_type, config, is_composite=False)

            # Track weak relationship types (concepts that IS_A Relationship but lack REIFIES)
            if compression_type == "weak_compression":
                weak_rel_types.append(rel_type)

            for related_concept in related_concepts:
                # Normalize target concept name to match filesystem convention
                normalized_target = normalize_concept_name(related_concept)

                # Create forward relationship with compression_type metadata
                rel_query = f"""
                MATCH (c1:Wiki {{n: $from_concept}})
                MERGE (c2:Wiki {{n: $to_concept, c: $to_canonical}})
                MERGE (c1)-[r:{rel_type.upper()}]->(c2)
                SET r.ts = datetime($timestamp)
                SET r.compression_type = $compression_type
                """

                rel_params = {
                    'from_concept': concept_name,
                    'to_concept': normalized_target,
                    'to_canonical': normalized_target.lower(),
                    'timestamp': datetime.now().isoformat(),
                    'compression_type': compression_type
                }

                graph.execute_query(rel_query, rel_params)

                # Create inverse relationship if defined
                if rel_type in relationship_inverses:
                    inverse_rel_type = relationship_inverses[rel_type]
                    # Inverse relationship gets same compression type as forward
                    inverse_compression_type = classify_compression_type(inverse_rel_type, config, is_composite=False)

                    inverse_query = f"""
                    MATCH (c1:Wiki {{n: $from_concept}})
                    MATCH (c2:Wiki {{n: $to_concept}})
                    MERGE (c2)-[r:{inverse_rel_type.upper()}]->(c1)
                    SET r.ts = datetime($timestamp)
                    SET r.compression_type = $compression_type
                    """

                    inverse_params = {
                        'from_concept': concept_name,
                        'to_concept': normalized_target,
                        'timestamp': datetime.now().isoformat(),
                        'compression_type': inverse_compression_type
                    }

                    graph.execute_query(inverse_query, inverse_params)

        # Mark weak relationship type concepts with REQUIRES_EVOLUTION
        for rel_type in weak_rel_types:
            rel_evolution_query = """
            MERGE (rel_concept:Wiki {n: $rel_type, c: $canonical})
            MERGE (evolution:Wiki {n: "Requires_Evolution", c: "requires_evolution"})
            MERGE (rel_concept)-[r:REQUIRES_EVOLUTION]->(evolution)
            SET r.ts = datetime($timestamp)
            SET r.reason = "Relationship type lacks REIFIES (not ontology-valid)"
            """

            rel_evolution_params = {
                'rel_type': rel_type,
                'canonical': rel_type.lower(),
                'timestamp': datetime.now().isoformat()
            }

            graph.execute_query(rel_evolution_query, rel_evolution_params)

        # ALSO mark the concept using weak relationships with REQUIRES_EVOLUTION
        if weak_rel_types:
            concept_evolution_query = """
            MATCH (c:Wiki {n: $concept_name})
            MERGE (evolution:Wiki {n: "Requires_Evolution", c: "requires_evolution"})
            MERGE (c)-[r:REQUIRES_EVOLUTION]->(evolution)
            SET r.ts = datetime($timestamp)
            SET r.reason = $reason
            """

            concept_evolution_params = {
                'concept_name': concept_name,
                'timestamp': datetime.now().isoformat(),
                'reason': f"Uses weak relationship types: {', '.join(weak_rel_types)}"
            }

            graph.execute_query(concept_evolution_query, concept_evolution_params)

        # REIFIES validation and auto-promotion
        # If concept has REIFIES relationship, validate and auto-add PROGRAMS + ontology promotion
        if 'reifies' in relationships:
            print(f"[REIFIES] Validating {concept_name} for ontology promotion...", file=sys.stderr)

            # Query all relationships used by this concept
            all_rels_query = """
            MATCH (c:Wiki {n: $concept_name})-[r]->()
            RETURN DISTINCT type(r) as rel_type
            """

            all_rels_result = graph.execute_query(all_rels_query, {'concept_name': concept_name})
            used_rel_types = [record['rel_type'].lower() for record in all_rels_result] if all_rels_result else []

            # Check if ALL relationship types used are in UARL predicates (strong compression)
            uarl_predicates = get_uarl_predicates(config)
            uarl_predicates_lower = {p.lower() for p in uarl_predicates}

            weak_rels_used = [rt for rt in used_rel_types if rt not in uarl_predicates_lower]

            if weak_rels_used:
                print(f"[REIFIES] REJECTED: {concept_name} uses weak relationship types: {weak_rels_used}", file=sys.stderr)
                # Concept has REIFIES but uses weak relationships - invalid origination stack
                # Remove the REIFIES relationship
                remove_reifies_query = """
                MATCH (c:Wiki {n: $concept_name})-[r:REIFIES]->()
                DELETE r
                """
                graph.execute_query(remove_reifies_query, {'concept_name': concept_name})

            else:
                print(f"[REIFIES] VALID: {concept_name} has strong compression - auto-promoting...", file=sys.stderr)

                # All relationships are strong - origination stack valid
                # Auto-add PROGRAMS relationship
                programs_query = """
                MATCH (c:Wiki {n: $concept_name})
                MERGE (ontology_entity:Wiki {n: "Carton_Ontology_Entity", c: "carton_ontology_entity"})
                MERGE (c)-[r:PROGRAMS]->(ontology_entity)
                SET r.ts = datetime($timestamp)
                """

                graph.execute_query(programs_query, {
                    'concept_name': concept_name,
                    'timestamp': datetime.now().isoformat()
                })

                # Auto-add IS_A Carton_Ontology_Entity
                ontology_promotion_query = """
                MATCH (c:Wiki {n: $concept_name})
                MATCH (ontology_entity:Wiki {n: "Carton_Ontology_Entity"})
                MERGE (c)-[r:IS_A]->(ontology_entity)
                SET r.ts = datetime($timestamp)
                """

                graph.execute_query(ontology_promotion_query, {
                    'concept_name': concept_name,
                    'timestamp': datetime.now().isoformat()
                })

                print(f"[REIFIES] {concept_name} promoted to ontology (PROGRAMS + IS_A Carton_Ontology_Entity)", file=sys.stderr)

        if should_close:
            graph.close()

        weak_msg = f" [marked {len(weak_rel_types)} weak relationship types]" if weak_rel_types else ""
        return f"Neo4j: Created concept '{concept_name}' with {sum(len(items) for items in relationships.values())} relationships{weak_msg}"
        
    except ImportError:
        traceback.print_exc()
        return "Neo4j: Driver not available, skipping graph storage"
    except Exception as e:
        traceback.print_exc()
        return f"Neo4j: Failed to create concept - {str(e)}"


def get_update_history_symbol(concept_name: str) -> str:
    """Get the symbol (0-9, A-Z) for organizing update history."""
    normalized_name = normalize_concept_name(concept_name)
    first_char = normalized_name[0].upper()

    if first_char.isdigit():
        return first_char
    elif first_char.isalpha():
        return first_char
    else:
        return "0"  # Default for special characters


def update_concept_history(
    concept_name: str,
    observation_name: str,
    confidence: float,
    timestamp: str
) -> None:
    """Update the {Symbol}_Update_History concept with this mention."""
    symbol = get_update_history_symbol(concept_name)
    history_concept_name = f"{symbol}_Update_History"

    # Format the update entry
    update_entry = f"- **{concept_name}** mentioned in [{observation_name}](../{observation_name}/{observation_name}_itself.md) with confidence {confidence} at {timestamp}"

    print(f"Updating {history_concept_name} for {concept_name}", file=sys.stderr)

    # Try to read existing history
    import os
    from pathlib import Path
    base_path = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    concepts_dir = Path(base_path) / "wiki" / "concepts"
    history_dir = concepts_dir / history_concept_name
    history_file = history_dir / f"{history_concept_name}_itself.md"

    existing_content = ""
    if history_file.exists():
        existing_content = history_file.read_text(encoding="utf-8")

    # Append new entry
    if existing_content:
        new_content = existing_content + "\n" + update_entry
    else:
        new_content = f"# {history_concept_name}\n\nTracking all concept mentions with confidence scores.\n\n{update_entry}"

    # Update or create the history concept (no is_a relationship needed for tracking concepts)
    try:
        add_concept_tool_func(
            concept_name=history_concept_name,
            description=new_content,
            relationships=[{"relationship": "relates_to", "related": ["Observation_System"]}]
        )
    except Exception as e:
        # If it fails, just log it
        print(f"Warning: Could not update history concept: {e}", file=sys.stderr)
        traceback.print_exc()


def link_observation_to_timeline(observation_name: str, timestamp: str, concept_cache: Optional[List[str]] = None) -> None:
    """
    Parse timestamp and link observation to Timeline hierarchy.

    Creates temporal concepts: Year -> Month -> Day
    Links observation via part_of to Day concept.

    Args:
        observation_name: Name of the observation concept
        timestamp: Timestamp string in format YYYY_MM_DD_HH_MM_SS
        concept_cache: Pre-loaded list of all concept names (avoids Neo4j queries)
    """
    from datetime import datetime

    # Parse timestamp components
    try:
        dt = datetime.strptime(timestamp, "%Y_%m_%d_%H_%M_%S")
        year = dt.year
        month = dt.month
        day = dt.day
        month_name = dt.strftime("%B")  # Full month name (e.g., "October")
    except Exception as e:
        print(f"Warning: Could not parse timestamp {timestamp}: {e}", file=sys.stderr)
        return

    # Create temporal concept names
    year_concept = f"{year}_Year"
    month_concept = f"{month_name}_{year}_Month"
    day_concept = f"Day_{year}_{month:02d}_{day:02d}"

    print(f"Linking {observation_name} to timeline: {year_concept} -> {month_concept} -> {day_concept}", file=sys.stderr)

    # Create Year concept if needed
    try:
        add_concept_tool_func(
            concept_name=year_concept,
            description=f"Year {year} in the Timeline hierarchy. Contains all months and days of {year}.",
            relationships=[{"relationship": "part_of", "related": ["Timeline"]}],
            concept_cache=concept_cache
        )
    except Exception as e:
        print(f"Note: {year_concept} might already exist: {e}", file=sys.stderr)

    # Create Month concept if needed
    try:
        add_concept_tool_func(
            concept_name=month_concept,
            description=f"{month_name} {year} in the Timeline hierarchy. Contains all days of this month.",
            relationships=[{"relationship": "part_of", "related": [year_concept]}],
            concept_cache=concept_cache
        )
    except Exception as e:
        print(f"Note: {month_concept} might already exist: {e}", file=sys.stderr)

    # Create Day concept if needed
    try:
        add_concept_tool_func(
            concept_name=day_concept,
            description=f"Day {year}-{month:02d}-{day:02d} in the Timeline hierarchy. Contains all observations and events from this day.",
            relationships=[{"relationship": "part_of", "related": [month_concept]}],
            concept_cache=concept_cache
        )
    except Exception as e:
        print(f"Note: {day_concept} might already exist: {e}", file=sys.stderr)

    # Link observation to Day
    # This is handled by adding the relationship when we create the observation
    # We'll update add_observation() to include this relationship


def sink_concept_globally(concept_name: str, config: ConceptConfig, reason: str) -> Dict[str, Any]:
    """
    Sink concept globally (Phase 1B): rename concept → concept_v1 in Neo4j and filesystem.

    Args:
        concept_name: Concept to sink
        config: ConceptConfig with Neo4j credentials
        reason: Why concept is being sunk (e.g., "cyclic_dependency")

    Returns:
        Result dict with success/error
    """
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        import os
        import shutil

        print(f"[Sinking] Sinking {concept_name} (reason: {reason})", file=sys.stderr)

        # 1. Rename in Neo4j: concept → concept_v1
        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        sink_query = """
        MATCH (c:Wiki {n: $concept_name})
        SET c.n = $sunk_name
        RETURN c.n as new_name
        """

        sunk_name = f"{concept_name}_v1"
        result = graph.execute_query(sink_query, {"concept_name": concept_name, "sunk_name": sunk_name})

        if not result:
            graph.close()
            return {"error": f"Concept {concept_name} not found in Neo4j"}

        # 2. Create requires_evolution relationship
        evolution_query = """
        MATCH (c:Wiki {n: $sunk_name})
        MERGE (re:Wiki {n: "Requires_Evolution", c: "requires_evolution"})
        SET re.d = "Index of all concepts that require evolution due to validation failures"
        MERGE (c)-[r:REQUIRES_EVOLUTION]->(re)
        SET r.reason = $reason, r.ts = datetime($timestamp)
        RETURN c.n as sunk_concept
        """

        from datetime import datetime
        graph.execute_query(evolution_query, {
            "sunk_name": sunk_name,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })
        graph.close()

        # 3. Rename in filesystem: concepts/concept → concepts/concept_v1
        base_dir = config.base_path
        concept_dir = Path(base_dir) / "concepts" / concept_name
        sunk_dir = Path(base_dir) / "concepts" / sunk_name

        if concept_dir.exists():
            shutil.move(str(concept_dir), str(sunk_dir))
            print(f"[Sinking] Renamed filesystem: {concept_name} → {sunk_name}", file=sys.stderr)

        print(f"[Sinking] Successfully sunk {concept_name} → {sunk_name}", file=sys.stderr)
        return {"success": True, "sunk_name": sunk_name, "reason": reason}

    except Exception as e:
        traceback.print_exc()
        return {"error": f"Sinking failed: {str(e)}"}


def validate_observation_background(observation_name: str, all_concept_names: List[str]):
    """
    Background validation job (Phase 1B: actual validation and sinking).

    This runs AFTER observation returns to user. Validates concepts created
    in the observation and sinks any that fail validation.
    """
    import os
    print(f"[BG Validation] Starting validation for {observation_name}...", file=sys.stderr)

    try:
        # Get config
        config = ConceptConfig(
            github_pat=os.getenv('GITHUB_PAT', 'dummy'),
            repo_url=os.getenv('REPO_URL', 'dummy'),
            neo4j_url=os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687'),
            neo4j_username=os.getenv('NEO4J_USER', 'neo4j'),
            neo4j_password=os.getenv('NEO4J_PASSWORD', 'password'),
            base_path=os.getenv('BASE_PATH')
        )

        # Get observation and its parts from Neo4j
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Find all concepts that are part_of this observation
        parts_query = """
        MATCH (part:Wiki)-[:PART_OF]->(obs:Wiki {n: $observation_name})
        RETURN part.n as concept_name
        """

        parts_result = graph.execute_query(parts_query, {"observation_name": observation_name})
        observation_parts = [record["concept_name"] for record in parts_result] if parts_result else []

        print(f"[BG Validation] Found {len(observation_parts)} parts: {observation_parts}", file=sys.stderr)

        # Step 1: Intra-observation auto-linking
        # Build local cache of just this observation's parts for cross-linking
        local_cache = [normalize_concept_name(part) for part in observation_parts]
        print(f"[BG Validation] Running intra-observation auto-linking with local cache: {local_cache}", file=sys.stderr)

        base_path = config.base_path if config.base_path else os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        concepts_dir = Path(base_path) / "wiki" / "concepts"

        for concept_name in observation_parts:
            normalized_name = normalize_concept_name(concept_name)
            concept_dir = concepts_dir / normalized_name
            itself_file = concept_dir / f"{normalized_name}_itself.md"

            if itself_file.exists():
                # Read current content
                current_content = itself_file.read_text(encoding='utf-8')

                # Extract the description section (between "## Overview" and "## Relationships")
                import re
                overview_match = re.search(r'## Overview\n(.+?)(?=\n## )', current_content, re.DOTALL)
                if overview_match:
                    raw_description = overview_match.group(1).strip()

                    # Run auto-linking with local cache (links to other parts in same observation)
                    linked_description = auto_link_description(
                        raw_description,
                        base_path,
                        concept_name,
                        concept_cache=local_cache
                    )

                    # Only update if auto-linking found new links
                    if linked_description != raw_description:
                        updated_content = current_content.replace(raw_description, linked_description)
                        itself_file.write_text(updated_content, encoding='utf-8')
                        print(f"[BG Validation] Updated intra-observation links for {concept_name}", file=sys.stderr)

        print(f"[BG Validation] Intra-observation auto-linking complete", file=sys.stderr)

        # Step 2: Validate each part for IS_A cycles
        for concept_name in observation_parts:
            # Get all is_a relationships for this concept
            is_a_query = """
            MATCH (c:Wiki {n: $concept_name})-[:IS_A]->(target:Wiki)
            RETURN target.n as target_name
            """

            is_a_result = graph.execute_query(is_a_query, {"concept_name": concept_name})

            if is_a_result:
                for record in is_a_result:
                    target = record["target_name"]
                    # Check for cycle
                    cycle_result = check_is_a_cycle(config, concept_name, target)

                    if "error" in cycle_result:
                        print(f"[BG Validation] IS_A CYCLE DETECTED: {concept_name} → {target}", file=sys.stderr)
                        # Sink the concept
                        sink_result = sink_concept_globally(concept_name, config, "cyclic_is_a_dependency")
                        if "error" in sink_result:
                            print(f"[BG Validation] Sinking failed: {sink_result['error']}", file=sys.stderr)
                        break  # Don't check more relationships for this concept

        # Step 3: Validate each part for PART_OF cycles
        for concept_name in observation_parts:
            # Get all part_of relationships for this concept
            rels_query = """
            MATCH (c:Wiki {n: $concept_name})-[:PART_OF]->(target:Wiki)
            RETURN target.n as target_name
            """

            rels_result = graph.execute_query(rels_query, {"concept_name": concept_name})

            if rels_result:
                for record in rels_result:
                    target = record["target_name"]
                    # Check for cycle
                    cycle_result = check_part_of_cycle(config, concept_name, target)

                    if "error" in cycle_result:
                        print(f"[BG Validation] PART_OF CYCLE DETECTED: {concept_name} → {target}", file=sys.stderr)
                        # Sink the concept
                        sink_result = sink_concept_globally(concept_name, config, "cyclic_part_of_dependency")
                        if "error" in sink_result:
                            print(f"[BG Validation] Sinking failed: {sink_result['error']}", file=sys.stderr)
                        break  # Don't check more relationships for this concept

        # Step 4: Validate each part for INSTANTIATES completeness
        for concept_name in observation_parts:
            # Get all instantiates relationships for this concept
            instantiates_query = """
            MATCH (c:Wiki {n: $concept_name})-[:INSTANTIATES]->(target:Wiki)
            RETURN target.n as target_name
            """

            instantiates_result = graph.execute_query(instantiates_query, {"concept_name": concept_name})

            if instantiates_result:
                for record in instantiates_result:
                    target = record["target_name"]
                    # Check for completeness (surjectivity)
                    completeness_result = check_instantiates_completeness(config, concept_name, target)

                    if "error" in completeness_result:
                        print(f"[BG Validation] INSTANTIATES INCOMPLETE: {concept_name} → {target}: {completeness_result['error']}", file=sys.stderr)
                        # Sink the concept
                        sink_result = sink_concept_globally(concept_name, config, "incomplete_instantiation")
                        if "error" in sink_result:
                            print(f"[BG Validation] Sinking failed: {sink_result['error']}", file=sys.stderr)
                        break  # Don't check more relationships for this concept

        graph.close()
        print(f"[BG Validation] Validation complete for {observation_name}", file=sys.stderr)

    except Exception as e:
        traceback.print_exc()
        print(f"[BG Validation] Validation failed: {str(e)}", file=sys.stderr)


def _add_observation_worker(
    observation_data: Dict[str, Any],
    shared_connection=None,
) -> str:
    """
    INTERNAL: Worker function that actually processes observations.
    Called by background daemon, not by MCP tool directly.

    Create an observation with multiple part concepts in batch.

    Observation envelope structure:
    {
        "insight_moment": [{"name": str, "description": str}, ...],
        "struggle_point": [{"name": str, "description": str}, ...],
        "daily_action": [{"name": str, "description": str}, ...],
        "implementation": [{"name": str, "description": str}, ...],
        "emotional_state": [{"name": str, "description": str}, ...],
        "confidence": float
    }

    Creates N+1 concepts:
    - 1 observation wrapper: {datetime}_Observation
    - N part concepts, one per item in all tag lists

    Returns:
        Success message with created concepts summary

    Raises:
        Exception: if any concept creation fails
    """
    from datetime import datetime

    # Query Neo4j ONCE for all concept names (Phase 1A: query-once caching)
    from .carton_utils import CartOnUtils
    utils = CartOnUtils(shared_connection=shared_connection)
    concept_cache = utils.get_all_concept_names()
    print(f"Loaded {len(concept_cache)} concepts into cache", file=sys.stderr)

    # Generate observation timestamp name
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    observation_name = f"{timestamp}_Observation"

    # Extract confidence and hide_youknow (optional)
    confidence = observation_data.get("confidence", 1.0)
    hide_youknow = observation_data.get("hide_youknow", False)

    # Collect all active tags (tags that have concepts)
    active_tags = []
    all_part_concepts = []

    for tag in OBSERVATION_TAGS:
        concepts_list = observation_data.get(tag, [])
        if concepts_list:
            active_tags.append(tag)
            all_part_concepts.extend([(tag, concept) for concept in concepts_list])

    if not all_part_concepts:
        raise Exception("Observation must have at least one concept under an observation tag")

    # Link observation to Timeline before creating wrapper
    # This creates the Year/Month/Day concepts
    link_observation_to_timeline(observation_name, timestamp, concept_cache)

    # Get the day concept name for linking
    dt = datetime.strptime(timestamp, "%Y_%m_%d_%H_%M_%S")
    day_concept = f"Day_{dt.year}_{dt.month:02d}_{dt.day:02d}"

    # UNWIND all observation content into description
    observation_desc_parts = [
        f"# Observation at {timestamp}",
        f"Confidence: {confidence}",
        ""
    ]

    # Group by tag and build sections
    tags_content = {}
    for tag, concept_data in all_part_concepts:
        if tag not in tags_content:
            tags_content[tag] = []
        tags_content[tag].append(concept_data)

    # Build local cache of just this observation's part names for intra-observation linking
    local_part_cache = [normalize_concept_name(concept_data["name"]) for tag, concept_data in all_part_concepts]
    print(f"Built local cache of {len(local_part_cache)} observation parts for intra-linking", file=sys.stderr)

    # Build full description with all content unwound and auto-linked
    base_path = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
    for tag, concepts_list in tags_content.items():
        observation_desc_parts.append(f"## {tag}")
        observation_desc_parts.append("")
        for concept_data in concepts_list:
            concept_name = concept_data["name"]
            concept_description = concept_data["description"]

            # Auto-link description against local parts (intra-observation linking)
            linked_description = auto_link_description(
                concept_description,
                base_path,
                concept_name,
                concept_cache=local_part_cache
            )

            # Create markdown link for concept name
            normalized_name = normalize_concept_name(concept_name)
            concept_link = f"[{concept_name}](../{normalized_name}/{normalized_name}_itself.md)"
            observation_desc_parts.append(f"### {concept_link}")
            observation_desc_parts.append(linked_description)
            observation_desc_parts.append("")

    observation_description = "\n".join(observation_desc_parts)

    observation_relationships = [
        {"relationship": "is_a", "related": ["Concept"]},
        {"relationship": "part_of", "related": [day_concept]},
    ]

    print(f"Creating observation wrapper: {observation_name}", file=sys.stderr)
    add_concept_tool_func(
        concept_name=observation_name,
        description=observation_description,
        relationships=observation_relationships,
        concept_cache=concept_cache,
        hide_youknow=hide_youknow,
        shared_connection=shared_connection,
    )

    # Create each part concept
    created_parts = []
    for tag, concept_data in all_part_concepts:
        concept_name = concept_data["name"]
        concept_description = concept_data["description"]
        user_relationships = concept_data.get("relationships", [])
        desc_update_mode = concept_data.get("desc_update_mode", "append")

        # Validate user relationships have is_a, part_of, has_personal_domain, has_actual_domain
        if user_relationships:
            has_is_a = any(rel.get("relationship") == "is_a" for rel in user_relationships)
            has_part_of = any(rel.get("relationship") == "part_of" for rel in user_relationships)
            has_personal_domain = any(rel.get("relationship") == "has_personal_domain" for rel in user_relationships)
            has_actual_domain = any(rel.get("relationship") == "has_actual_domain" for rel in user_relationships)

            if not (has_is_a and has_part_of and has_personal_domain and has_actual_domain):
                raise Exception(f"Concept '{concept_name}' must have is_a, part_of, has_personal_domain, and has_actual_domain in relationships field. Got: {user_relationships}")

            # Validate personal_domain is in enum
            personal_domain_rel = next((rel for rel in user_relationships if rel.get("relationship") == "has_personal_domain"), None)
            if personal_domain_rel:
                personal_domain_values = personal_domain_rel.get("related", [])
                for pd_value in personal_domain_values:
                    if pd_value not in PERSONAL_DOMAINS:
                        raise Exception(f"Invalid personal_domain '{pd_value}'. Must be one of: {', '.join(PERSONAL_DOMAINS)}")

        # Auto-add tag metadata and observation link
        auto_relationships = [
            {"relationship": "has_tag", "related": [tag]},
            {"relationship": "part_of", "related": [observation_name]}
        ]

        # Merge: user relationships + auto relationships
        part_relationships = user_relationships + auto_relationships

        print(f"Creating part concept: {concept_name} (has_tag: {tag})", file=sys.stderr)
        result = add_concept_tool_func(
            concept_name=concept_name,
            description=concept_description,
            relationships=part_relationships,
            concept_cache=concept_cache,
            desc_update_mode=desc_update_mode,
            hide_youknow=hide_youknow,
            shared_connection=shared_connection,
        )
        created_parts.append(f"{concept_name} ({tag})")

        # Update the concept's history with this observation mention
        update_concept_history(
            concept_name=concept_name,
            observation_name=observation_name,
            confidence=confidence,
            timestamp=timestamp
        )

    summary = f"Observation '{observation_name}' created with {len(created_parts)} parts: {', '.join(created_parts)}"

    # Synchronous validation (no threading in MCP - Neo4j writes already complete)
    print(f"[Validation] Running validation for {observation_name}", file=sys.stderr)
    validate_observation_background(observation_name, concept_cache)

    return summary


def add_observation(
    observation_data: Dict[str, Any],
) -> str:
    """
    Queue an observation for background processing.

    Writes observation_data to file queue and returns immediately.
    Background daemon processes the queue asynchronously.

    Args:
        observation_data: Observation envelope with insight_moment, struggle_point, etc.

    Returns:
        Immediate confirmation that observation was queued
    """
    from datetime import datetime
    import uuid

    try:
        # Get queue directory
        queue_dir = get_observation_queue_dir()

        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        queue_file = queue_dir / f"{timestamp}_{unique_id}.json"

        # Write observation data to file
        with open(queue_file, 'w') as f:
            json.dump(observation_data, f, indent=2)

        print(f"[Observation Queue] Wrote {queue_file.name}", file=sys.stderr)

        return f"✅ Observation queued: {queue_file.name}"

    except Exception as e:
        traceback.print_exc()
        return f"❌ Error queuing observation: {str(e)}"


# DEAD CODE — Commented out 2026-03-29. Python validation that bypasses the reasoner. The reasoner (Pellet + SHACL) runs inside youknow() compiler at _compile_packet() line 498-553. CartON calls youknow(), youknow() runs the reasoner. This function should not exist.
# def validate_giint_hierarchy(concept_name: str, relationship_dict: Dict[str, List[str]]) -> Optional[str]:
    # """
    # Validate GIINT hierarchy constraints (Mar 03 unification).

    # Returns error string if validation fails, None if passes.
    # """
    # # Reject standalone Architecture_ concepts (now GIINT_Project descriptions)
    # if concept_name.startswith("Architecture_"):
        # return (
            # "ERROR: Architecture_ concepts replaced by GIINT_Project (Mar 03 unification). "
            # "Architecture_ is now the DESCRIPTION of a GIINT_Project, not a separate concept type. "
            # "Create a GIINT_Project with 'description' field containing architecture info."
        # )

    # # Check if this IS a GIINT_Project - require valid relationships
    # is_a_list = relationship_dict.get("is_a", [])
    # if "GIINT_Project" in is_a_list or concept_name.startswith("GIINT_Project"):
        # # GIINT_Project must have part_of pointing to system/domain
        # part_of_list = relationship_dict.get("part_of", [])
        # if not part_of_list:
            # return (
                # "ERROR: GIINT_Project must have PART_OF relationship pointing to parent system/domain. "
                # "Example: part_of=['Compound_Intelligence_System']"
            # )

        # # NOTE: has_path validation REMOVED (Mar 13 2026).
        # # GIINT_Projects are auto-created by ensure_ontology_completeness
        # # when a Starsystem_Collection is created. No path dependency.

    # # Check Bug_ prefix - Bug lives UNDER a GIINT_Deliverable or GIINT_Component
    # # Hierarchy: Project → Feature → Component → Deliverable → Bug → Task
    # if concept_name.startswith("Bug_"):
        # if "Bug" not in is_a_list:
            # return (
                # "ERROR: Bug_ concepts must have IS_A Bug. "
                # "Bugs are problems found in Deliverables/Components. "
                # "Hierarchy: Project → Feature → Component → Deliverable → Bug → Task. "
                # "Add: is_a=['Bug']"
            # )
        # part_of_list = relationship_dict.get("part_of", [])
        # has_valid_parent = any(
            # "GIINT_Deliverable" in parent or "GIINT_Component" in parent or
            # "Deliverable" in parent or "Component" in parent
            # for parent in part_of_list
        # )
        # if not has_valid_parent:
            # return (
                # "ERROR: Bug_ must have PART_OF relationship to a GIINT_Deliverable or GIINT_Component. "
                # "Bugs are found IN deliverables/components, not at project/feature level. "
                # "Hierarchy: Project → Feature → Component → Deliverable → Bug → Task. "
                # "Add: part_of=['GIINT_Deliverable_Name' or 'GIINT_Component_Name']"
            # )

    # # Check Potential_Solution_ prefix - lives UNDER a Bug as a proposed fix
    # # Hierarchy: Bug → Potential_Solution → Task (to implement the solution)
    # if concept_name.startswith("Potential_Solution_"):
        # if "Potential_Solution" not in is_a_list:
            # return (
                # "ERROR: Potential_Solution_ concepts must have IS_A Potential_Solution. "
                # "Solutions are proposed fixes for Bugs. "
                # "Hierarchy: Project → Feature → Component → Deliverable → Bug → Potential_Solution → Task. "
                # "Add: is_a=['Potential_Solution']"
            # )
        # part_of_list = relationship_dict.get("part_of", [])
        # has_bug_parent = any("Bug_" in parent or "Bug" in parent for parent in part_of_list)
        # if not has_bug_parent:
            # return (
                # "ERROR: Potential_Solution_ must have PART_OF relationship to a Bug_. "
                # "Solutions address specific bugs. "
                # "Add: part_of=['Bug_Name']"
            # )

    # # Check GIINT_Deliverable - must have proper hierarchy
    # if "GIINT_Deliverable" in is_a_list or concept_name.startswith("GIINT_Deliverable"):
        # part_of_list = relationship_dict.get("part_of", [])
        # has_component_parent = any("GIINT_Component" in parent or "Potential_Solution_" in parent or "Component" in parent for parent in part_of_list)
        # if not has_component_parent:
            # return (
                # "ERROR: GIINT_Deliverable must have PART_OF relationship to GIINT_Component. "
                # "Deliverables are outputs of components. "
                # "Add: part_of=['Potential_Solution_Name' or 'GIINT_Component_Name']"
            # )

    # # Check GIINT_Task - must have proper hierarchy
    # if "GIINT_Task" in is_a_list or concept_name.startswith("GIINT_Task"):
        # part_of_list = relationship_dict.get("part_of", [])
        # has_deliverable_parent = any("GIINT_Deliverable" in parent or "Deliverable" in parent for parent in part_of_list)
        # if not has_deliverable_parent:
            # return (
                # "ERROR: GIINT_Task must have PART_OF relationship to GIINT_Deliverable. "
                # "Tasks are work items that produce deliverables. "
                # "Add: part_of=['GIINT_Deliverable_Name']"
            # )

    # # All checks passed
    # return None


# D2 rollup — WHY this exists (archaeology, carton_mcp_LEGACY_BACKUP commit b14cef5,
# CONCEPT_VISION.md, 2026-07-03): on the original markdown substrate, "description" and "the
# graph" were the SAME substance — auto_link_description scanned free-form prose for concept
# mentions and turned them into the graph edges. On the neo4j substrate, relationships are
# supplied FIRST as structured params, so the reverse direction (render the supplied graph BACK
# into a natural description) was never built. `_compute_description_rollup` + its three clause
# helpers below are that missing reverse-rendering piece, rendering Isaac's exact template
# (verbatim, 2026-07-03): "{X} {is_a}, {part_of} in the {subdomain} subdomain of {domain} domain.
# X has {has-part list}, which instantiates {instantiates}. {X} instantiating that graph produces
# {produces}." — never a generic per-relationship-type sentence dump.

ADMIN_ROLLUP_KEYS = {
    "is_a", "part_of", "instantiates", "produces",
    "has_domain", "has_subdomain", "has_personal_domain",
}


def _rollup_sentence_isa_partof(concept_name: str, is_a: List[str], part_of: List[str],
                                 domain: List[str], subdomain: List[str]) -> str:
    """Renders clause 1: "{X} is_a {is_a}, part_of {part_of} in the {subdomain} subdomain of
    {domain} domain." is_a/part_of are each independently optional; the domain/subdomain tail is
    appended only when at least one of them has a value. Returns "" if is_a and part_of are both
    empty (no sentence to render)."""
    clause = []
    if is_a:
        clause.append(f"is_a {', '.join(is_a)}")
    if part_of:
        clause.append(f"part_of {', '.join(part_of)}")
    if not clause:
        return ""
    sentence = f"{concept_name} " + ", ".join(clause)
    if subdomain and domain:
        sentence += f" in the {subdomain[0]} subdomain of {domain[0]} domain"
    elif subdomain:
        sentence += f" in the {subdomain[0]} subdomain"
    elif domain:
        sentence += f" in the {domain[0]} domain"
    return sentence + "."


def _rollup_sentence_has_instantiates(concept_name: str, has_parts: List[str],
                                       instantiates: List[str]) -> str:
    """Renders clause 2: "{X} has {has-part list}, which instantiates {instantiates}." has-parts
    and instantiates are each independently optional. Returns "" if both are empty."""
    if has_parts and instantiates:
        return f"{concept_name} has {', '.join(has_parts)}, which instantiates {', '.join(instantiates)}."
    if has_parts:
        return f"{concept_name} has {', '.join(has_parts)}."
    if instantiates:
        return f"{concept_name} instantiates {', '.join(instantiates)}."
    return ""


def _rollup_sentence_produces(concept_name: str, produces: List[str]) -> str:
    """Renders clause 3: "{X} instantiating that graph produces {produces}." Returns "" if
    produces is empty."""
    if not produces:
        return ""
    return f"{concept_name} instantiating that graph produces {', '.join(produces)}."


def _compute_description_rollup(concept_name: str, relationship_dict: Dict[str, List[str]]) -> str:
    """D2: render the concept's supplied relationships into Isaac's exact natural-paragraph
    template (see the module comment above `_compute_description_rollup` for the template + why),
    via the three `_rollup_sentence_*` clause helpers, joined with a space. Each clause is omitted
    if its data is empty — no relationship_dict key is required to exist. Empty relationship_dict
    produces an empty string. Multiple targets within one clause are comma-joined in their
    supplied order (no re-sorting — order is caller-meaningful).
    """
    if not relationship_dict:
        return ""

    is_a = relationship_dict.get("is_a", [])
    part_of = relationship_dict.get("part_of", [])
    instantiates = relationship_dict.get("instantiates", [])
    produces = relationship_dict.get("produces", [])
    domain = relationship_dict.get("has_domain", [])
    subdomain = relationship_dict.get("has_subdomain", [])

    # "has {has-part list}" = every OTHER has_* relationship (e.g. has_desc_content, has_step_1) —
    # the concept's real constituent parts, never the administrative domain/subdomain/personal_domain.
    has_parts: List[str] = []
    for rel_type, targets in relationship_dict.items():
        if rel_type in ADMIN_ROLLUP_KEYS or not rel_type.startswith("has_"):
            continue
        has_parts.extend(targets)

    sentences = [
        _rollup_sentence_isa_partof(concept_name, is_a, part_of, domain, subdomain),
        _rollup_sentence_has_instantiates(concept_name, has_parts, instantiates),
        _rollup_sentence_produces(concept_name, produces),
    ]
    return " ".join(s for s in sentences if s)


def _compute_d2_coverage(description: str, relationship_dict: Dict[str, List[str]]):
    """D2: a READ-ONLY coverage check, never a gate (Isaac 2026-07-03).

    D2 must NEVER modify, truncate, or reject the caller's description — the
    description is stored verbatim regardless of what this returns. This
    function only measures whether the relationships the caller DECLARED are
    actually TRACED somewhere in the prose they wrote, so a decoherence
    between "what I said in the graph" and "what I said in English" becomes a
    visible, informational [D2: ...] tag on the response — never a rejection.

    This is a heuristic, not a claim of full semantic coverage: it checks each
    relationship TARGET name (underscored -> spaced, case-folded) for a literal
    substring hit in the description. It does not catch paraphrase. It DOES
    catch the case D2 exists for: a concept graphed with relationships that the
    prose never mentions at all.

    Returns (coverage_pct: Optional[int], unmatched_targets: List[str]).
    coverage_pct is None when there are no relationship targets to check.
    """
    if not relationship_dict:
        return (None, [])
    targets = [t for tgts in relationship_dict.values() for t in (tgts or [])]
    if not targets:
        return (None, [])
    desc_lower = (description or "").lower()
    unmatched = []
    matched = 0
    for t in targets:
        t_str = str(t).lower()
        t_plain = t_str.replace("_", " ")
        if (t_str and t_str in desc_lower) or (t_plain and t_plain in desc_lower):
            matched += 1
        else:
            unmatched.append(str(t))
    coverage = round(100 * matched / len(targets))
    return (coverage, unmatched)


def merge_optional_domain_fields(
    relationships: List[Dict[str, Any]],
    domain: Optional[str],
    subdomain: Optional[str],
    personal_domain: Optional[str],
    produces: Optional[List[str]],
) -> List[Dict[str, Any]]:
    """Pure helper for add_concept_tool_func's OPTIONAL domain/subdomain/personal_domain/
    produces params (Isaac 2026-07-04). Mirrors the add_concept MCP tool's has_domain/
    has_subdomain/has_personal_domain/produces convenience-building (server_fastmcp.py's
    add_concept), except every field here is OPTIONAL — this internal function is the one
    chokepoint every existing caller already passes through (Dragonbones, sm_gate.py,
    split_content_concept, the migration scripts — see Concept_Provenance_Enforcement_Gap);
    requiring these fields here would break every one of those callers until each is
    individually audited and updated, which has not been done. This function only gives
    callers the ABILITY to pass them correctly; it enforces nothing.

    personal_domain, if given, IS enum-validated regardless of the others being optional —
    the enum-check is not optional, only the field's presence is (raises Exception if
    invalid, matching this file's existing validation-failure convention).

    Operates on the RELATIONSHIPS LIST (the [{"relationship":..., "related":...}, ...]
    shape), NOT relationship_dict — relationship_dict is a derived, SOMA/D2-validation-
    only view built FROM this list; add_concept_tool_func's queue write persists the LIST
    verbatim (queue_data["relationships"] = relationships), so merging only into
    relationship_dict would make these fields validate correctly but never actually reach
    the graph. Returns a NEW list (does not mutate the input list or its dict entries) with
    each provided field's relationship type merged in — appended as a new entry if that
    relationship type is not already present, or deduped into the existing entry's
    "related" list if it is (so a caller passing has_domain both ways does not end up with
    a duplicate target).
    """
    if personal_domain is not None and personal_domain not in PERSONAL_DOMAINS:
        raise Exception(
            f"Invalid personal_domain '{personal_domain}'. Must be one of: {', '.join(PERSONAL_DOMAINS)}"
        )
    merged = [{"relationship": rel["relationship"], "related": list(rel["related"])} for rel in (relationships or [])]
    by_type = {rel["relationship"]: rel for rel in merged}
    for rel_type, values in (
        ("has_domain", [domain] if domain else None),
        ("has_subdomain", [subdomain] if subdomain else None),
        ("has_personal_domain", [personal_domain] if personal_domain else None),
        ("produces", produces),
    ):
        if not values:
            continue
        if rel_type in by_type:
            existing = by_type[rel_type]["related"]
            for item in values:
                if item not in existing:
                    existing.append(item)
        else:
            entry = {"relationship": rel_type, "related": list(values)}
            merged.append(entry)
            by_type[rel_type] = entry
    return merged


def add_concept_tool_func(
    concept_name: str,
    description: Optional[str] = None,
    relationships: Optional[List[Dict[str, Any]]] = None,
    concept_cache: Optional[List[str]] = None,
    desc_update_mode: str = "append",
    hide_youknow: bool = False,
    shared_connection=None,
    _skip_ontology_healing: bool = False,
    source: str = "agent",
    target_descs: Optional[Dict[str, str]] = None,
    typed_values: Optional[List] = None,
    old_str_for_edit_case: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
    cb_guidance: bool = False,
    domain: Optional[str] = None,
    subdomain: Optional[str] = None,
    personal_domain: Optional[str] = None,
    produces: Optional[List[str]] = None,
) -> str:
    """
    Create a new concept with its component files.

    Args:
        concept_name: Name of the concept
        description: Description text
        relationships: List of relationship objects
        concept_cache: Pre-loaded concept names cache
        domain: OPTIONAL (Isaac 2026-07-04). Mirrors the add_concept MCP tool's REQUIRED
            domain param — becomes a has_domain relationship. OPTIONAL HERE, not required,
            because this internal function is the one chokepoint every existing caller
            already passes through (Dragonbones, sm_gate.py, split_content_concept, the
            migration scripts — see Concept_Provenance_Enforcement_Gap); making it required
            here would break every one of those callers until each is individually audited
            and updated, which has not been done. This just gives callers the ABILITY to
            pass it correctly (merged into relationship_dict below, deduped against
            anything already supplied via `relationships`) — it enforces nothing.
        subdomain: OPTIONAL, same status as domain — becomes a has_subdomain relationship.
        personal_domain: OPTIONAL, same status as domain — becomes a has_personal_domain
            relationship. If provided, IS validated against PERSONAL_DOMAINS (paiab/sanctum/
            cave/misc/personal) and raises if invalid — the enum-check is not optional, only
            the field's presence is.
        produces: OPTIONAL, same status as domain — merged into the produces relationship
            (deduped against any produces already supplied via `relationships`).
        desc_update_mode: How to update description if concept exists
            - "append": Add new description after existing (default)
            - "prepend": Add new description before existing
            - "replace": Sink old version, use only new description
            - "edit": Surgical str-replace WITHIN the existing n.d. old_str_for_edit_case
              is the string to find (must match EXACTLY ONCE); the description arg is
              the replacement (new_str). The daemon applies it via EditHelper.str_replace,
              writes a per-node undo log, and the rest of n.d (incl. any CartonObj fence
              elsewhere) is left byte-identical. A 0-or->1 match fails gracefully (n.d
              unchanged).
        old_str_for_edit_case: ONLY used when desc_update_mode == "edit": the exact
            substring of the existing n.d to replace with the description arg.
        hide_youknow: If False (default), SOMA validates and warns if invalid.
            If True, skip validation - silent add to soup.
        typed_values: Optional list of (value, type) pairs declaring programming
            types for relationship targets. Each entry is either a [value, type]
            list/tuple or {"value": ..., "type": ...} dict. Used by SOMA to
            assert typed observations. Unknown values default to string_value.
        properties: Optional dict of {key: value} NODE PROPERTIES to set on the
            concept via the carton property surface (set_concept_properties =
            scratch lane, per the-property-layer-doctrine). This is the SECOND
            meaning-channel beside relationships: relationships become graph edges;
            properties become neo4j node properties (status/order/gates/sm config/
            …). Values are scalars (str/int/float/bool) or flat lists of those —
            NEVER nested objects or concept-refs (those are relationships). Carried
            in the queue JSON; the daemon applies set_concept_properties AFTER the
            node is written (the node already exists in the same drain → no race,
            which is why the SM gates/steps no longer need <sm_spec> JSON in n.d).
            Reserved/managed keys (n/d/t/c/region/source/…) are refused by the
            property surface. This makes add_concept the universal carton write
            (relationships AND properties), so dragonbones can set both via a single
            add_concept call — the 🏷 property notation flows here.

    Raises:
        Exception: if relationships are empty or missing required fields.
    """
    from datetime import datetime
    import uuid

    # Validate relationships exist (checked BEFORE the optional-fields merge below —
    # domain/subdomain/personal_domain/produces alone must not satisfy "declare something
    # real"; the caller still must supply at least one core relationship such as is_a/
    # part_of/instantiates).
    if not relationships or len(relationships) == 0:
        raise Exception("ERROR: There is no reason you cannot put a WIP is_a, part_of, or has_type. Relationships cannot be empty or none.")

    # NODE-QUOTA gate (hosted carton boxes — carton-saas-DESIGN §4; the whole
    # capability lives in carton_quota.py). A NO-OP unless CARTON_MAX_NODES is
    # set (local/self-hosted default: unlimited, zero queries). At/over quota:
    # edits to EXISTING concepts still pass; NEW nodes raise QuotaExceeded.
    # Sits HERE — on the live path, before the queue write below — so a
    # rejection provably never reaches the graph.
    from carton_mcp.carton_quota import check_quota
    check_quota(concept_name, shared_connection=shared_connection)

    # OPTIONAL domain/subdomain/personal_domain/produces passthrough (Isaac 2026-07-04).
    # Mirrors the add_concept MCP tool's has_domain/has_subdomain/has_personal_domain/
    # produces convenience-building (server_fastmcp.py's add_concept), but every field
    # here is OPTIONAL, not required — see the domain/subdomain/personal_domain/produces
    # docstring entries above for why. Reassigns `relationships` (not just a derived
    # dict) BEFORE relationship_dict is built below, so the merge is visible both to
    # SOMA/D2 validation (which reads relationship_dict) AND to the queue write further
    # down (queue_data["relationships"] = relationships, the actual graph persistence —
    # merging only into relationship_dict would validate correctly but never land).
    relationships = merge_optional_domain_fields(relationships, domain, subdomain, personal_domain, produces)

    # Convert relationships list to dict for YOUKNOW
    relationship_dict = {}
    for rel in relationships:
        rel_type = rel["relationship"]
        rel_items = rel["related"]
        relationship_dict[rel_type] = rel_items

    # ACCUMULATE: merge existing CartON relationships with new ones so YOUKNOW
    # validates the FULL set. This enables SOUP→CODE evolution — each add_concept
    # call fills more fields, and YOUKNOW sees the accumulated state.
    try:
        from carton_mcp.carton_utils import CartOnUtils
        _utils = CartOnUtils(shared_connection=shared_connection)
        _existing = _utils.query_wiki_graph(
            "MATCH (c:Wiki {n: $name})-[r]->(t:Wiki) "
            "WHERE type(r) <> 'REQUIRES_EVOLUTION' "
            "RETURN toLower(type(r)) as rel, t.n as target",
            {"name": concept_name}
        )
        if _existing.get("success") and _existing.get("data"):
            for row in _existing["data"]:
                rel_type = row["rel"].lower()
                target = row["target"]
                if rel_type not in relationship_dict:
                    relationship_dict[rel_type] = [target]
                elif target not in relationship_dict[rel_type]:
                    relationship_dict[rel_type].append(target)
    except Exception:
        pass  # Can't query — validate with what we have

    # SOMA validation BEFORE queuing (warns, doesn't block).
    # YOUKNOW call abandoned (kept in file as dead code) — SOMA is the validator now.
    # SOMA does mereological regression on each typed value; every relationship value
    # gets a programming type. typed_values overrides default string_value for refs
    # that the caller knows are concept_ref / domain / etc.
    #
    # SOMA result string (from core.ingest_event) looks like:
    #   "triples=N deduction_chains_fired=M unmet=K\n
    #    <all_core_requirements_met | failure_error(...) block>\n
    #    [soup_gaps=N\n  - <gap sentence>\n  - ...]"
    #
    youknow_msg = ""
    soup_items = []
    _yk_healed_concepts = []  # SOMA does not heal — keep empty so healing loop no-ops
    yk_data = {}  # SOMA returns no inferred fills — keep empty so legacy block no-ops
    soma_result = ""
    # PRE-GATE INIT (pre-existing bug fix, surfaced by the CB-store step-2 acceptance):
    # queue_data references _fillable_requests, but it was ONLY assigned inside the
    # `if SOMA_AVAILABLE and not hide_youknow:` block below — so hide_youknow=True (or
    # SOMA down) left it UNBOUND → UnboundLocalError before the queue write. Default it
    # here alongside the other pre-gate vars, exactly like soup_items/soma_result.
    _fillable_requests = []

    # Build lookup of explicit typed values: target_value → programming_type.
    tv_lookup = {}
    if typed_values:
        for pair in typed_values:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                tv_lookup[str(pair[0])] = str(pair[1])
            elif isinstance(pair, dict) and "value" in pair and "type" in pair:
                tv_lookup[str(pair["value"])] = str(pair["type"])

    if _soma_up() and not hide_youknow:
        try:
            # SOMA preferred observation shape per soma-http-event-shape rule:
            #   {source, name, description, relationships: [{relationship,
            #    related: [{value, type}]}]}
            # Unknown types default to string_value.
            soma_relationships = []
            for rel_type, targets in relationship_dict.items():
                related = []
                for target in targets:
                    t_str = str(target)
                    t_type = tv_lookup.get(t_str, "string_value")
                    related.append({"value": t_str, "type": t_type})
                soma_relationships.append({
                    "relationship": str(rel_type),
                    "related": related,
                })

            soma_obs = [{
                "source": source,
                "name": concept_name,
                "description": description or "",
                "relationships": soma_relationships,
            }]

            soma_data = soma_validate(source=source, observations=soma_obs)
            soma_result = soma_data.get("result", "") if isinstance(soma_data, dict) else ""

            # AUTHORIZATION-TYPED REQUESTS (Isaac 2026-06-28). SOMA surfaces every gap whose fill
            # authority is NOT observing_agent — those (human_domain_expert / human_architect /
            # human_end_user / system_deduction / a manufactured LLM expert) are the cases the
            # caller-relay does NOT already cover. The SOMA SDK parses the verdict's soma_requests=
            # block into typed FillableRequest objects; we carry them in the queue so the daemon can
            # dispatch each to its filler (queue a human, manufacture an LLM expert, …). The
            # observing_agent case stays exactly as-is — SOMA's gap is relayed straight back to the
            # caller below; we do NOT duplicate it.
            _fillable_requests = []
            try:
                from soma_sdk import SomaResponse as _SomaResponse
                _soma_resp = _SomaResponse.from_verdict(soma_result)
                _fillable_requests = [
                    {**r.model_dump(), "authorization": r.authorization}
                    for r in _soma_resp.fillable_requests
                ]
            except Exception:
                _fillable_requests = []

            # Parse SOMA result for SOUP/CODE indicators.
            #
            # Doc 27 fix: SOMA now emits explicit per-concept status lines
            # (status=<concept>:<level>) and separates structural SOUP gaps
            # from informational INFO gaps (optional code args on a CODE
            # concept used to be lumped under soup_gaps=, causing CODE concepts
            # to surface here as is_soup=True). We honour the status= line for
            # THIS concept_name when present; we still collect soup_gaps text
            # so the agent sees the structural problems (which may include
            # other concepts in the graph), but is_soup for OUR concept is
            # determined by its explicit status, not by the global soup count.
            #
            # soup_gaps block lists unfilled slots ("  - <gap sentence>").
            if "soup_gaps=" in soma_result:
                in_soup = False
                for line in soma_result.split("\n"):
                    if line.startswith("soup_gaps="):
                        in_soup = True
                        continue
                    if in_soup:
                        stripped = line.strip()
                        if stripped.startswith("- "):
                            soup_items.append(stripped[2:].strip())
                        elif stripped.startswith("info=") or stripped.startswith("status="):
                            # Hit the next section — soup block ended.
                            break
                        elif not stripped:
                            continue

            # failure_error block = unmet deduction-chain requirements.
            if "failure_error" in soma_result:
                # Surface the failure_error preview as SOUP for the agent.
                for line in soma_result.split("\n"):
                    if "failure_error" in line and line.strip() not in soup_items:
                        soup_items.append(line.strip())
                        break

            # Per-concept SOMA status for THIS concept (doc 27): one of
            # "soup" / "code" / "unvalidated". Authoritative — overrides the
            # is_soup-from-soup_gaps inference below when present.
            _soma_concept_status = None
            # Compare the status= concept name UNDERSCORE-INSENSITIVELY. SOMA and
            # CartON canonicalize names DIFFERENTLY: SOMA's build_obs_list_string does
            # camelCase->snake ("TreeShell_Node" -> "tree_shell_node"), while CartON's
            # normalize_concept_name title-cases whole words ("TreeShell_Node" ->
            # "Treeshell_Node"). So a plain `nm.lower() == concept_name.lower()` FAILS
            # for any camel-humped name (`tree_shell_...` != `treeshell_...`) -> the
            # per-concept verdict is silently LOST -> the concept mis-records as soup
            # even when SOMA graded it code. Stripping `_` from both sides makes the
            # match invariant to WHERE each system places underscores, so the verdict
            # propagates; every previously-matching name still matches (strip is a
            # superset). (The deeper carton<->soma canonicalization unification is a
            # separate, larger item — see Understand_Soma_Observation_To_Carton_Canonicalization_Case.)
            _cn_key = concept_name.lower().replace("_", "")
            for line in soma_result.split("\n"):
                if line.startswith("status="):
                    body = line[len("status="):]
                    if ":" in body:
                        nm, lvl = body.split(":", 1)
                        if nm.strip().lower().replace("_", "") == _cn_key:
                            _soma_concept_status = lvl.strip().lower()
                            break

            if soup_items:
                soup_msg = "; ".join(soup_items[:5])
                youknow_msg = f" [SOUP: {soup_msg}]"
        except Exception as e:
            logger.warning(f"SOMA validation error: {e}\n{traceback.format_exc()}")
            if not hide_youknow:
                youknow_msg = f" [SOMA error: {str(e)}]"

    # TYPE-2 CONTRADICTION = REJECTED COMPLETELY, EVEN BY CARTON (Isaac 2026-06-22). This
    # is the ONE case where saying is NOT free. Unlike a Type-1 undefined-is_a (saved as
    # soup + fill, below), a geometric CONTRADICTION — SOMA status `contradiction`, the
    # concept's is_a reaching two disjoint DOLCE top branches ("you cannot be both") —
    # would DECOHERE THE GEOMETRY even in the soup region subgraph. So CartON does NOT save
    # it: return early, BEFORE the queue write, relaying SOMA's reason. (FactualInconsistency
    # / contradicts_existing_chain in uarl.owl. Type-1, which is FactualFabrication /
    # produces_unknown_target, is fillable soup and falls through to the save below.)
    if locals().get("_soma_concept_status") == "contradiction":
        _contra_reason = ""
        _cn_key2 = concept_name.lower().replace("_", "")
        if "contradictions=" in soma_result:
            for line in soma_result.split("\n"):
                stripped = line.strip()
                if stripped.startswith("- ") and _cn_key2 in stripped.lower().replace("_", ""):
                    _contra_reason = stripped[2:].strip()
                    break
        logger.warning(f"CONTRADICTION (REJECTED, not saved): {concept_name}: {_contra_reason}")
        # P0 Rejection_Ledger: the Type-2 reject is an oracle-labeled hard negative —
        # capture it before it evaporates (this return is the ONLY record otherwise).
        record_soma_rejection(concept_name, relationships, "contradiction", _contra_reason)
        return (
            f"❌ {concept_name} REJECTED — geometric contradiction"
            f"{(' (' + _contra_reason + ')') if _contra_reason else ''}. "
            f"This claim cannot be: it would decohere the geometry even as soup, so CartON "
            f"did NOT store it. Fix the contradicting is_a claims and re-add."
        )

    # MEREO_ERROR = a SOMA FILL SIGNAL, never a CartON rejection (Isaac 2026-06-22).
    # CartON is a SOUP store of EVERYTHING that gets mentioned. A mereo_error means the
    # thing is not yet mereo-DEFINED in SOMA (you mentioned something whose is_a /
    # referenced type has not been given its [is_a],[part_of],[produces],[instantiates]).
    # That is a thing the LLM must FILL — NOT grounds for refusing to store the node.
    # Rejecting-because-undefined is the ordinary must-declare-your-contents program we
    # are explicitly NOT building. So CartON SAVES the node (a valid soup entry) and
    # RELAYS SOMA's fill instruction; the save falls through to the queue write below.
    # (SOMA's OWN quadstore still mirrors code-or-higher only — that is correct and
    # separate; CartON, the soup store, keeps everything said. Once you add the four
    # lists the thing becomes defined in SOMA and is admissible wherever mentioned.)
    if locals().get("_soma_concept_status") == "mereo_error":
        _mereo_reason = ""
        if "mereo_errors=" in soma_result:
            _in_m = False
            for line in soma_result.split("\n"):
                if line.startswith("mereo_errors="):
                    _in_m = True
                    continue
                if _in_m:
                    stripped = line.strip()
                    if stripped.startswith("- ") and concept_name.lower() in stripped.lower():
                        _mereo_reason = stripped[2:].strip()
                        break
                    elif stripped.startswith(("soup_gaps=", "info=", "status=",
                                              "release_effects=", "deduction_chains_fired=")):
                        break
        logger.info(f"MEREO (saved as soup; fill needed): {concept_name}: {_mereo_reason}")
        # P0 Rejection_Ledger: the mereo_error verdict is an oracle-labeled hard negative
        # (SOMA judged this claim-structure not-yet-admissible) even though carton SAVES the
        # node as soup — the verdict itself was dropped before this patch.
        record_soma_rejection(concept_name, relationships, "mereo_error", _mereo_reason)
        youknow_msg = (
            f" [MEREO — saved as soup. SOMA needs this mereo-defined: provide "
            f"[is_a],[part_of],[produces],[instantiates] for the undefined type"
            f"{(' (' + _mereo_reason + ')') if _mereo_reason else ''} so SOMA can admit it. "
            f"CartON has stored it; mention stays valid.]"
        )
        # fall through to the queue write — CartON saves it.

    # HAS_VALIDATOR: check parent template requirements before queuing
    # If any part_of parent has REQUIRES_RELATIONSHIP entries, child must have those rel types
    part_of_targets = relationship_dict.get("part_of", [])
    if part_of_targets:
        from carton_mcp.carton_utils import CartOnUtils
        utils = CartOnUtils(shared_connection=shared_connection)
        for parent_name in part_of_targets:
            req_query = """
            MATCH (p:Wiki {n: $name})-[:REQUIRES_RELATIONSHIP]->(r:Wiki)
            RETURN r.n as required_rel
            """
            req_result = utils.query_wiki_graph(req_query, {"name": parent_name})
            if req_result.get("success") and req_result.get("data"):
                required_rels = [r["required_rel"] for r in req_result["data"]]
                provided_types = {k.lower() for k in relationship_dict.keys()}
                missing = [r for r in required_rels if r.lower() not in provided_types]
                if missing:
                    missing_str = ", ".join(missing)
                    raise Exception(
                        f"TEMPLATE VALIDATION: '{parent_name}' requires relationships: [{missing_str}]. "
                        f"Compose on scratchpad, add missing rels, submit when complete."
                    )

    # GIINT validation happens inside youknow() compiler via system_type_validator
    # + recursive restriction walk. Do NOT duplicate that here — CartON calls
    # youknow(), youknow() validates against OWL restrictions and returns CODE/SOUP.

    # D2 (Isaac 2026-07-03): D2 NEVER touches, truncates, or rejects the caller's
    # description — it is stored VERBATIM, always, no matter what D2 finds. D2's
    # only job is to run a read-only coverage check AFTER the fact and surface an
    # INFORMATIONAL [D2: ...] tag in the response (see the youknow_msg append near
    # the return) — a warning, never a gate. This replaces a prior version of this
    # comment that claimed the rollup REPLACED the stored description (it never
    # did; _caller_raw_description below has always been the verbatim string that
    # gets queued).
    _caller_raw_description = description or ""
    _d2_coverage, _d2_unmatched = _compute_d2_coverage(_caller_raw_description, relationship_dict)

    # Write to queue for async processing by daemon
    queue_dir = get_observation_queue_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    queue_file = queue_dir / f"{timestamp}_{unique_id}_concept.json"

    # Parse THREE-LEVEL status from SOMA result.
    #
    # SOMA's report carries enough information to distinguish three admissibility
    # levels (see SOMA's deduce_validation_status + the soup_gaps / unmet split):
    #
    #   SOUP        — any missing_slot present (code-stage restriction unmet,
    #                  i.e. a structural arg is missing). soup_items is non-empty.
    #                  Cannot project; cannot run d-chains meaningfully.
    #   CODE        — no soup_items AND all_core_requirements_met BUT unmet > 0.
    #                  Code args are present (structure is valid) but at least
    #                  one deduction chain is still unmet (additional admissibility
    #                  logic still to satisfy). Projection NOT yet allowed.
    #   SYSTEM_TYPE — no soup_items AND all_core_requirements_met AND unmet == 0.
    #                  Fully admissible: structure valid, every d-chain proved,
    #                  every restriction satisfied. Projection d-chains are free
    #                  to fire.
    #
    # Parse `unmet=N` from the "deduction_chains_fired=X unmet=Y" line in the
    # SOMA report. core.py emits this twice (once in the prolog_report header
    # and once in the trailing summary); both carry the same N, so we take the
    # first match. The pattern is anchored on "unmet=" to avoid matching the
    # word "unmet" in failure_error text.
    import re as _re_status
    _unmet_count = 0
    _m = _re_status.search(r'\bunmet=(\d+)', soma_result)
    if _m:
        try:
            _unmet_count = int(_m.group(1))
        except (ValueError, TypeError):
            _unmet_count = 0

    # Parse the fired_chains= verdict section (P0 Verdict_Chain_Granularity, 2026-07-06).
    # SOMA now names WHICH deduction chains fired (one `  - chain: <name>` per chain), not
    # just the count — the training substrate Chain_Prioritizer needs. Carried into the
    # queue AND appended to the fired-chains exhaust ledger below (the verdict string alone
    # is displayed then dropped; without persisting, every real event's chain-firing record
    # evaporates — the compounding-cost item).
    _fired_chains = []
    if "fired_chains=" in soma_result:
        _in_fc = False
        for line in soma_result.split("\n"):
            if line.startswith("fired_chains="):
                _in_fc = True
                continue
            if _in_fc:
                stripped = line.strip()
                if stripped.startswith("- chain:"):
                    _fired_chains.append(stripped[len("- chain:"):].strip())
                elif stripped.startswith(("soup_gaps=", "info=", "status=", "mereo_errors=",
                                          "contradictions=", "release_effects=",
                                          "soma_requests=", "composed=",
                                          "compose_suggestions=", "failure_error")):
                    break
                elif not stripped:
                    continue
    if _fired_chains:
        # Fired-chains exhaust ledger: {concept, fired_chains, unmet, status, timestamp} per
        # event — same append-only JSONL idiom as the rejection ledger above. Best-effort.
        try:
            from datetime import datetime as _dt_fc
            with open(os.path.join(os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data'),
                                   'soma_fired_chains.jsonl'), 'a') as _fc_f:
                _fc_f.write(json.dumps({
                    "concept": concept_name,
                    "fired_chains": _fired_chains,
                    "status": locals().get("_soma_concept_status"),
                    "timestamp": _dt_fc.now().isoformat(),
                }) + "\n")
        except Exception as _fc_e:
            logger.error(f"fired-chains ledger append failed (non-fatal): {_fc_e}", exc_info=True)

    # Parse release_effects from the SOMA verdict (FIX-5 step 3 — RELEASE-LAW).
    # SOMA's projection d-chains (dchain_skill_project / dchain_rule_project) surface
    # release_effect(handler, arg) facts; core.py serializes them into a
    # `release_effects=N` verdict section, one `  - effect: <module>:<func> | <arg>`
    # per effect. SOMA does NOT run them (it is the inner reflection — it releases
    # them up); the daemon (the outer layer that called /event) imports + dispatches
    # each handler AFTER the neo4j write. We carry them into the queue so it can.
    _release_effects = []
    if "release_effects=" in soma_result:
        _in_eff = False
        for line in soma_result.split("\n"):
            if line.startswith("release_effects="):
                _in_eff = True
                continue
            if _in_eff:
                stripped = line.strip()
                if stripped.startswith("- effect:"):
                    payload = stripped[len("- effect:"):].strip()
                    if " | " in payload:
                        _eh, _ea = payload.split(" | ", 1)
                        _release_effects.append({"handler": _eh.strip(), "arg": _ea.strip()})
                elif stripped.startswith(("soup_gaps=", "info=", "status=", "deduction_chains_fired=")):
                    break
                elif not stripped:
                    continue

    # Parse the composed= verdict section (CARTON-BUNDLE-BACK, Isaac 2026-06-28). L3a's
    # curried backward-chain compose accepted matches from the store and SURFACED a
    # composed_triple(concept, prop, value) for each; core.py serialized them into a
    # `composed=N` section, one `  - composed: <concept> | <prop> | <value>` per triple.
    # These are SOMA's DEDUCED graph additions — facts the user never stated (e.g. SOMA
    # found spaghetti's cuisine is italian from its ingredients). SOMA is the INNER
    # reflection: it deduces them and releases them UP; it does NOT touch carton's KG.
    # WE — the outer layer — must realize them into neo4j or carton stays dumb (that is
    # literally SOMA's job). We carry them into the queue; the daemon (Phase 2.5e) MERGEs
    # each as a graph edge AFTER the node write. Mirrors release_effects exactly — without
    # this parse they are surfaced by SOMA but never land in the KG.
    _composed_triples = []
    if "composed=" in soma_result:
        _in_comp = False
        for line in soma_result.split("\n"):
            if line.startswith("composed="):
                _in_comp = True
                continue
            if _in_comp:
                stripped = line.strip()
                if stripped.startswith("- composed:"):
                    payload = stripped[len("- composed:"):].strip()
                    parts = [p.strip() for p in payload.split(" | ")]
                    if len(parts) == 3:
                        _c, _p, _v = parts
                        _composed_triples.append({"concept": _c, "prop": _p, "value": _v})
                elif stripped.startswith(("soup_gaps=", "info=", "status=",
                                          "release_effects=", "soma_requests=",
                                          "deduction_chains_fired=")):
                    break
                elif not stripped:
                    continue

    # Parse the compose_suggestions= verdict section (L3b — pure-mereo suggestion, Isaac 2026-06-28).
    # SOMA found a unique admissible candidate for a still-empty required slot with NO authorizing
    # d-chain, so it SUGGESTS the candidate for review (it did NOT auto-compose — that is L3a). One
    # `  - suggestion: <concept> | <prop> | <expected_type> | <candidate> | <reviewer_role>` per
    # suggestion. We carry them into the queue; the daemon (Phase 2.5f) PARKS each durably for review
    # (mints a run-id for the L3c review/resume). Mirrors the composed= / release_effects= parses.
    _compose_suggestions = []
    if "compose_suggestions=" in soma_result:
        _in_sg = False
        for line in soma_result.split("\n"):
            if line.startswith("compose_suggestions="):
                _in_sg = True
                continue
            if _in_sg:
                stripped = line.strip()
                if stripped.startswith("- suggestion:"):
                    payload = stripped[len("- suggestion:"):].strip()
                    parts = [p.strip() for p in payload.split(" | ")]
                    if len(parts) == 5:
                        _sc, _sp, _st, _sv, _srole = parts
                        _compose_suggestions.append({
                            "concept": _sc, "prop": _sp, "expected_type": _st,
                            "candidate": _sv, "reviewer_role": _srole,
                        })
                elif stripped.startswith(("soup_gaps=", "info=", "status=",
                                          "release_effects=", "soma_requests=",
                                          "composed=", "deduction_chains_fired=")):
                    break
                elif not stripped:
                    continue

    _has_soup = bool(soup_items)
    _all_core_met = ("all_core_requirements_met" in soma_result) and ("failure_error" not in soma_result)

    # Doc 27: PREFER the explicit per-concept status= line for THIS concept
    # when SOMA emitted one. Fall back to the legacy soup_gaps inference only
    # when the new line is missing (older SOMA daemon / hide_youknow path /
    # SOMA call failed). The old inference labels CODE concepts as SOUP when
    # they have optional_code_arg missing_slots, because compose_all_gap_sentences
    # dumped those under soup_gaps=. With status= the answer is authoritative.
    if locals().get("_soma_concept_status") is not None:
        _status = _soma_concept_status
        if _status == "soup":
            _is_soup, _is_code, _is_system_type = True, False, False
        elif _status == "mereo_error":
            # Not yet mereo-defined in SOMA → CartON keeps it as a SOUP entry (a thing
            # to fill), never rejected. The youknow_msg relay (above) carries the fill.
            _is_soup, _is_code, _is_system_type = True, False, False
        elif _status in ("code", "ont"):
            # Code-stage args complete. Whether it's still CODE vs SYSTEM_TYPE
            # depends on d-chains. SYSTEM_TYPE requires zero unmet d-chains.
            # ONT (strong compression, full core sentence + closed targets +
            # Cat gate) is a STRICT superset of code, so it maps the same way
            # for backward compat — never SOUP. (The richer ont vs code/
            # system_type distinction can surface separately later.)
            if _unmet_count == 0:
                _is_soup, _is_code, _is_system_type = False, False, True
            else:
                _is_soup, _is_code, _is_system_type = False, True, False
        else:
            # unvalidated / unknown — preserve legacy inference as fallback.
            _is_soup = _has_soup
            _is_code = (not _has_soup) and _all_core_met and (_unmet_count > 0)
            _is_system_type = (not _has_soup) and _all_core_met and (_unmet_count == 0)
    else:
        _is_soup = _has_soup
        _is_code = (not _has_soup) and _all_core_met and (_unmet_count > 0)
        _is_system_type = (not _has_soup) and _all_core_met and (_unmet_count == 0)

    if _is_system_type:
        youknow_msg = " [SYSTEM_TYPE: all d-chains satisfied]"
    elif _is_code:
        youknow_msg = f" [CODE: {_unmet_count} d-chain(s) pending]"

    # SOMA does not currently emit a projection target (gen_target) — projection
    # is a d-chain, not a SOMA response field. Leave gen_target=None for now;
    # projection d-chains will compute their own targets when wired.
    _gen_target = None

    # ── CARTON → CB FAN-OUT + JOIN (canon/CORE-SENTENCE-SPECTRAL-SEQUENCE.md §5).
    # carton SAYS the sentence, SOMA ENFORCED it (above), CB ADDRESSES it. Derive
    # soma_region from carton's OWN SOMA verdict (no second SOMA call — the same
    # three-level status just computed), place the said sentence on CB best-effort,
    # and JOIN {soma_region, cb_coordinate, cb_encoded} onto the node as PROPERTIES
    # (the daemon's set_concept_properties lane below; `region` is reserved so the
    # key is `soma_region`). A CB miss never blocks the write. Type-2 contradiction
    # already returned early (the plane holds it, the graph refuses it) — it never
    # reaches here, so member/born-0 are the only shifts stamped.
    if _is_system_type:
        soma_region = "system_type"
    elif _is_code:
        soma_region = "code"
    elif _is_soup:
        soma_region = "mereo_error" if locals().get("_soma_concept_status") == "mereo_error" else "soup"
    else:
        soma_region = "unvalidated"

    _cb_props = {"soma_region": soma_region}
    _cb_guidance_block = None
    if CARTON_CB_STORE:
        _cb_x, _cb_y, _cb_enc, _cb_guidance_block = _cb_place(
            concept_name, relationship_dict, soma_region, want_guidance=cb_guidance)
        if _cb_enc:
            # THE CB coordinate is the 2-D PLANE POINT (planePlacement), not the bare
            # local fragment: cb_x = the kernel's column/global id, cb_y = the plane
            # position (decodes back to (kernelId, localCoord)). cb_encoded is the full
            # address string — lossless (cb_y, a float, can lose precision for deep coords).
            _cb_props["cb_x"] = _cb_x
            _cb_props["cb_y"] = _cb_y
            _cb_props["cb_encoded"] = _cb_enc
    _merged_properties = {**(properties or {}), **_cb_props}

    queue_data = {
        "raw_concept": True,
        "concept_name": concept_name,
        "description": _caller_raw_description,
        "raw_staging": _caller_raw_description,
        "relationships": relationships,
        "desc_update_mode": desc_update_mode,
        # CartON KV 'edit' mode: surgical str-replace within the existing n.d. The
        # description above is the new_str; this is the old_str to find (exactly once).
        # Applied by the daemon's batch_create_concepts_neo4j edit pre-step.
        "old_str_for_edit_case": old_str_for_edit_case,
        "hide_youknow": hide_youknow,
        # Three-level SOMA status. Mutually exclusive: exactly one is True
        # (or all False when SOMA was unavailable / hide_youknow=True).
        # SOUP        = missing_slots present (structure missing)
        # CODE        = structure valid, d-chains still unmet (admissibility incomplete)
        # SYSTEM_TYPE = structure valid AND all d-chains proved (fully admissible;
        #               projection d-chains are free to fire)
        "is_soup": _is_soup,
        "soup_reason": "; ".join(soup_items) if soup_items else None,
        "is_code": _is_code,
        "is_system_type": _is_system_type,
        # SOMA's unmet-d-chain count (kept verbatim so the daemon can show progress
        # toward SYSTEM_TYPE as more d-chains land).
        "unmet_dchains": _unmet_count,
        # P0 Verdict_Chain_Granularity: WHICH deduction chains fired for this event
        # (from the fired_chains= verdict block), not just the count. Empty when SOMA
        # fired none / was unavailable / predates the block. Also appended to the
        # fired-chains exhaust ledger above (Chain_Prioritizer's training substrate).
        "fired_chains": _fired_chains,
        "gen_target": _gen_target,
        # RELEASE-LAW projection effects (FIX-5 step 3): the release_effect facts
        # SOMA surfaced in the verdict, [{handler, arg}]. The daemon's Phase 2.5a
        # imports + dispatches each AFTER writing the concept to neo4j (gated on
        # is_system_type). Empty when SOMA emitted none / was unavailable.
        "release_effects": _release_effects,
        # AUTHORIZATION-TYPED fillable requests (Isaac 2026-06-28): SOMA gaps whose fill
        # authority is NOT observing_agent, parsed by the SOMA SDK into typed objects
        # [{authorization, concept, gap, reason, reply_contract, request_id}]. The daemon
        # dispatches each to its filler (human queue / LLM expert / …). Empty when SOMA
        # surfaced only observing-agent gaps (already relayed to the caller) or was unavailable.
        "fillable_requests": _fillable_requests,
        # CARTON-BUNDLE-BACK composed triples (Isaac 2026-06-28): SOMA's backward-chain
        # compose DEDUCED these graph additions and surfaced them in the composed= verdict
        # section; [{concept, prop, value}]. The daemon's Phase 2.5e MERGEs each as a neo4j
        # edge AFTER the node write so carton's KG realizes what SOMA deduced (facts the
        # user never stated). Empty when SOMA composed nothing / was unavailable. Mirrors
        # release_effects — without carrying it here SOMA's deductions never reach the KG.
        "composed_triples": _composed_triples,
        # L3b PURE-MEREO SUGGESTIONS (Isaac 2026-06-28): unique admissible candidates SOMA found
        # for still-empty required slots with no authorizing d-chain; [{concept, prop, expected_type,
        # candidate, reviewer_role}]. The daemon's Phase 2.5f PARKS each durably for review (mints a
        # run-id for the L3c review/resume). NOT auto-composed (that is composed_triples / L3a). Empty
        # when SOMA suggested nothing / was unavailable.
        "compose_suggestions": _compose_suggestions,
        # Ontology healing flag — daemon Phase 2.5 skips concepts with this set
        "skip_ontology_healing": _skip_ontology_healing,
        # Timeline source — who/what created this concept (agent, dragonbones_hook, precompact, etc.)
        "source": source,
        # Target descriptions — cached KV from EC desc= on +{} claims.
        # Daemon writes these to target nodes when auto-creating relationship targets.
        "target_descs": target_descs or {},
        # NODE PROPERTIES (the 🏷 property channel — scratch lane per the-property-layer-
        # doctrine). The daemon applies these via set_concept_properties AFTER it writes
        # the node (node already exists in the same drain → no race; reserved/managed keys
        # refused). Scalars or flat lists only — NEVER concept-refs/nested (those are
        # relationships). Empty dict when none. This is what lets add_concept carry
        # properties (status/order/sm gates/…) so dragonbones never has to smuggle config
        # through n.d as JSON. cb_coordinate/cb_encoded/soma_region ride here too
        # (the carton↔CB join — merged into _merged_properties above).
        "properties": _merged_properties,
    }

    with open(queue_file, 'w') as f:
        json.dump(queue_data, f, indent=2)

    # Prolog fact injection happens INSIDE PrologRuntime.validate() — not here.
    # CartON does not manipulate Prolog directly. Prolog is the outer runtime.

    # REFACTOR-PLAN [SOMA-UNIFICATION 2026-06-16] — DEAD NO-OP. journal ...Soma_Unification_Removal (14:10).
    #   _yk_healed_concepts is hardcoded EMPTY (see top of this fn), so this whole block never runs.
    #   YOUKNOW is dead (SOMA is the validator). ENACT: DELETE this block (L~2288-2317) AND the now-vestigial
    #   skip_ontology_healing plumbing: the _skip_ontology_healing param (def), the "skip_ontology_healing"
    #   queue field, and the _yk_healed_concepts/yk_data dead vars. Update the 2 external callers that pass
    #   the kwarg (weld_world_graph.py:434, soma-prolog/tests/test_d2_integration.py:55) to drop it.
    #   (No SOMA replacement needed — there is nothing real here to replace.)
    # ONTOLOGY SELF-HEALING: Now driven by YOUKNOW's OWL restriction index.
    # The UARLValidator._validate_chain() auto-heals system types by creating
    # SOUP placeholders for missing required graph elements. Healed concepts
    # are stored on the validator singleton after youknow() runs.
# DISABLED 2026-06-16 (SOMA-unification): dead youknow OWL self-heal no-op. _yk_healed_concepts is hardcoded empty (SOMA is the validator), so this block never ran. journal Soma_Unification_Removal. delete-for-niceness pending. The _skip_ontology_healing param/queue-field/dead-vars stay for now (cross-file param removal is the later niceness step).
    # if not _skip_ontology_healing:
        # try:
            # if _yk_healed_concepts:
                # healed = _yk_healed_concepts
                # for h in healed:
                    # try:
                        # h_rels = [
                            # {"relationship": "is_a", "related": [h["type"]]},
                            # {"relationship": "part_of", "related": [h["parent_name"]]},
                        # ]
                        # add_concept_tool_func(
                            # concept_name=h["name"],
                            # description=f"SOUP placeholder for {h['parent_type']} {h['relationship_from_parent']} requirement",
                            # relationships=h_rels,
                            # hide_youknow=True,
                            # shared_connection=shared_connection,
                            # _skip_ontology_healing=True,
                        # )
                        # import sys
                        # print(f"[ONTOLOGY] Auto-healed: {h['name']} (required by {h['parent_name']})", file=sys.stderr)
                    # except Exception as he:
                        # logger.warning(f"[ONTOLOGY] Failed to heal {h['name']}: {he}")
                # if healed:
                    # youknow_msg += f" [+{len(healed)} healed from OWL]"
        # except Exception as e:
            # logger.warning(f"[ONTOLOGY] OWL self-healing failed for {concept_name}: {e}")

    # D2 tag (Isaac 2026-07-03): informational only, never a gate — the description
    # above was already queued verbatim regardless of this coverage result.
    if _d2_coverage is not None:
        if _d2_unmatched:
            _unmatched_preview = ", ".join(f'"{u}"' for u in _d2_unmatched[:5])
            youknow_msg += (
                f" [D2: {_d2_coverage}% of declared relationships traced in the "
                f"description; not mentioned: {_unmatched_preview}]"
            )
        else:
            youknow_msg += f" [D2: {_d2_coverage}% — every declared relationship is traced in the description]"

    # CB tag (Isaac 2026-07-03): CARTON_CB_STORE places EVERY concept on the plane by
    # default (line ~51) but the coordinate was previously only surfaced when the
    # caller passed cb_guidance=True — so every add_concept silently placed a point
    # and never said so. Always surface the coordinate/region; cb_guidance still
    # gates the larger four-layer PROMPTER block below (a bigger, opt-in payload).
    _cb_coord = _cb_props.get("cb_encoded")
    if _cb_coord:
        youknow_msg += f" [CB: region={soma_region} coord={_cb_coord}]"

    # Concise output - always include youknow_msg (has SOUP and errors). When
    # cb_guidance was requested and CB returned its four-layer PROMPTER block,
    # fold it in (the CB FLOW/GRIESS/MINESPACE/SOMA guidance for this concept).
    if _cb_guidance_block:
        youknow_msg += f"\n\n{_cb_guidance_block}"
    return f"✅ {concept_name}{youknow_msg}"


# # Dead code removed - daemon handles: auto-linking, file writes, Neo4j writes
# # See observation_worker_daemon.py batch_create_concepts_neo4j()


# class _DeadCodeDeleted:
#     """Placeholder - large block of dead code was here, deleted during async refactor."""
#     pass
#     concept_path = Path(base_dir) / "concepts" / concept_name
#     components_path = concept_path / "components"

#     # Auto-link the description to create proper Zettelkasten connections
#     if description:
#         linked_description = auto_link_description(description, base_dir, concept_name, concept_cache=concept_cache)
#     else:
#         linked_description = f"No description available for {concept_name}."

#     # Handle desc_update_mode: check if concept exists and apply update logic
#     # IMPORTANT: This must happen BEFORE directory creation
#     from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder

#     # Use shared connection if provided, otherwise use module-level connection
#     if shared_connection:
#         graph = shared_connection
#         should_close = False
#     else:
#         # Try module-level connection first (fast path)
#         graph = _get_module_connection()
#         if graph:
#             should_close = False
#         else:
#             # Fallback: create temporary connection (slow path)
#             graph = KnowledgeGraphBuilder(
#                 uri=config.neo4j_url,
#                 user=config.neo4j_username,
#                 password=config.neo4j_password
#             )
#             should_close = True

#     check_query = "MATCH (c:Wiki {n: $name}) RETURN c.d as description"
#     existing_result = graph.execute_query(check_query, {'name': concept_name})
#     if should_close:
#         graph.close()

#     if existing_result and existing_result[0].get('description'):
#         existing_description = existing_result[0]['description']

#         if desc_update_mode == "append":
#             # Add new description after existing
#             linked_description = existing_description + "\n\n" + linked_description
#             print(f"[DESC UPDATE] Appending to {concept_name}", file=sys.stderr)
#         elif desc_update_mode == "prepend":
#             # Add new description before existing
#             linked_description = linked_description + "\n\n" + existing_description
#             print(f"[DESC UPDATE] Prepending to {concept_name}", file=sys.stderr)
#         elif desc_update_mode == "replace":
#             # Sink old version, use only new description
#             print(f"[DESC UPDATE] Replacing {concept_name} (sinking old version)", file=sys.stderr)
#             sink_result = sink_concept_globally(concept_name, config, "explicit_description_replacement")
#             if "error" in sink_result:
#                 raise Exception(sink_result["error"])
#             # linked_description stays as new description only
#         else:
#             raise Exception(f"Invalid desc_update_mode: {desc_update_mode}. Must be 'append', 'prepend', or 'replace'.")

#     # NOW create directories (after sinking has renamed old directory if needed)
#     concept_path.mkdir(parents=True, exist_ok=True)
#     components_path.mkdir(exist_ok=True)

#     # Build full concept content first to scan for auto-relationships
#     full_content = f"{concept_name}\n{linked_description}"

#     # Find auto-relationships by scanning content for existing concept names
#     auto_mentioned = find_auto_relationships(full_content, base_dir, concept_name, concept_cache=concept_cache)
    
#     relationship_dict = {}
#     if relationships:
#         for rel in relationships:
#             rel_type = rel["relationship"]
#             rel_items = rel["related"]
#             relationship_dict[rel_type] = rel_items
    
#     # Add auto-discovered relationships as "auto_related_to"
#     if auto_mentioned:
#         if "auto_related_to" not in relationship_dict:
#             relationship_dict["auto_related_to"] = []
#         relationship_dict["auto_related_to"].extend(auto_mentioned)

#     # ========================================================================
#     # VALIDATION: Relationship constraints
#     # ========================================================================

#     # 0. Check is_a for cycles
#     if "is_a" in relationship_dict:
#         for target in relationship_dict["is_a"]:
#             cycle_result = check_is_a_cycle(config, concept_name, target)
#             if "error" in cycle_result:
#                 raise Exception(cycle_result["error"])

#     # 1. Validate part_of targets are NOT tags (must be concepts)
#     if "part_of" in relationship_dict:
#         for target in relationship_dict["part_of"]:
#             if target in OBSERVATION_TAGS:
#                 raise Exception(
#                     f"part_of relationship cannot point to observation tags. "
#                     f"'{target}' is a tag, not a concept. part_of must point to concepts."
#                 )

#     # 2. Check part_of for cycles and instantiation conflicts
#     if "part_of" in relationship_dict:
#         for target in relationship_dict["part_of"]:
#             # Check if this would create a cycle
#             cycle_result = check_part_of_cycle(config, concept_name, target)
#             if "error" in cycle_result:
#                 raise Exception(cycle_result["error"])

#             # Check if target is instantiated (immutable)
#             if is_concept_instantiated(config, target):
#                 # Auto-version: create new version of target
#                 new_version = get_next_version_number(config, target)
#                 raise Exception(
#                     f"Cannot add part_of to instantiated concept '{target}'. "
#                     f"Target is immutable. Please create '{new_version}' instead or modify your relationships."
#                 )

#     # 3. Check instantiates for completeness (surjectivity)
#     if "instantiates" in relationship_dict:
#         source_parts = relationship_dict.get("part_of", [])
#         for target in relationship_dict["instantiates"]:
#             completeness_result = check_instantiates_completeness(config, concept_name, target, source_parts)
#             if "error" in completeness_result:
#                 raise Exception(completeness_result["error"])

#     # Define inverse relationships for filesystem sync
#     relationship_inverses = {
#         'is_a': 'has_instances',
#         'part_of': 'has_parts',
#         'depends_on': 'supports',
#         'instantiates': 'has_instances',
#         'relates_to': 'relates_to',  # bidirectional
#         'has_tag': 'has_concepts',  # tag metadata
#         'has_personal_domain': 'contains_concepts',  # personal domain categorization (enum)
#         'has_actual_domain': 'contains_concepts',  # actual domain categorization (flexible)
#         'has_subdomain': 'contains_concepts',  # subdomain categorization
#         'has_subsubdomain': 'contains_concepts'  # subsubdomain categorization
#     }

#     for rel_type, rel_items in relationship_dict.items():
#         # Create forward relationship file
#         rel_dir = components_path / rel_type
#         rel_dir.mkdir(exist_ok=True)

#         rel_file = rel_dir / f"{concept_name}_{rel_type}.md"
#         content = [
#             f"# {rel_type.title()} Relationships for {concept_name}",
#             "",
#         ]
#         for item in rel_items:
#             # Normalize the target concept name to match directory structure
#             normalized_item = normalize_concept_name(item)
#             item_url = f"../{normalized_item}/{normalized_item}_itself.md"
#             content.append(f"- {concept_name} {rel_type} [{item}]({item_url})")
#         rel_file.write_text("\n".join(content))

#         # Create inverse relationship files on target concepts
#         if rel_type in relationship_inverses:
#             inverse_rel = relationship_inverses[rel_type]

#             for item in rel_items:
#                 normalized_item = normalize_concept_name(item)
#                 target_concept_dir = Path(base_dir) / "concepts" / normalized_item
#                 target_components = target_concept_dir / "components"

#                 # Create target directories if needed (target concept might not exist yet)
#                 target_concept_dir.mkdir(parents=True, exist_ok=True)
#                 target_components.mkdir(exist_ok=True)

#                 # Create/update inverse relationship directory and file
#                 inverse_dir = target_components / inverse_rel
#                 inverse_dir.mkdir(exist_ok=True)
#                 inverse_file = inverse_dir / f"{normalized_item}_{inverse_rel}.md"

#                 # Build inverse relationship entry
#                 source_url = f"../{concept_name}/{concept_name}_itself.md"
#                 inverse_entry = f"- {normalized_item} {inverse_rel} [{concept_name}]({source_url})"

#                 # Append to existing file or create new
#                 if inverse_file.exists():
#                     existing_content = inverse_file.read_text()
#                     # Only append if this entry doesn't already exist (avoid duplicates)
#                     if inverse_entry not in existing_content:
#                         inverse_file.write_text(existing_content.rstrip() + "\n" + inverse_entry + "\n")
#                 else:
#                     # Create new inverse relationship file
#                     inverse_content = [
#                         f"# {inverse_rel.title()} Relationships for {normalized_item}",
#                         "",
#                         inverse_entry
#                     ]
#                     inverse_file.write_text("\n".join(inverse_content))

#     description_file = components_path / "description.md"
#     description_file.write_text(linked_description)

#     main_file = concept_path / f"{concept_name}.md"
#     main_content = [
#         f"# {concept_name}",
#         "",
#         "## Overview",
#         linked_description,
#         "",
#         "## Relationships",
#     ]

#     for rel_type, items in relationship_dict.items():
#         main_content.append(f"### {rel_type.title()} Relationships")
#         for item in items:
#             main_content.append(f"- {item}")
#     main_file.write_text("\n".join(main_content))

#     # Generate the _itself.md file by combining description and relationships
#     itself_file = concept_path / f"{concept_name}_itself.md"
#     itself_content = [
#         f"# {concept_name}",
#         "",
#         "## Overview",
#         linked_description,
#         "",
#         "## Relationships"
#     ]
    
#     # Add relationships from component files (extract just the - lines)
#     # Sort relationship types for consistent display order
#     for rel_type in sorted(relationship_dict.keys()):
#         items = relationship_dict[rel_type]
#         itself_content.extend(["", f"### {rel_type.title()} Relationships", ""])
#         for item in items:
#             # Normalize the target concept name to match directory structure
#             normalized_item = normalize_concept_name(item)
#             item_url = f"../{normalized_item}/{normalized_item}_itself.md"
#             itself_content.append(f"- {concept_name} {rel_type} [{item}]({item_url})")
    
#     itself_file.write_text("\n".join(itself_content))

#     # DISABLED: Missing concepts file scan takes 30s - run in background daemon later
#     # try:
#     #     file_updates = check_missing_concepts_and_manage_file(base_dir, concept_name, concept_cache=concept_cache)
#     #     file_summary = "; ".join(file_updates) if file_updates else "No file updates needed"
#     # except Exception as e:
#     #     traceback.print_exc()
#     #     file_summary = f"Missing concept file update failed: {e}"
#     file_summary = "Missing concepts check disabled (run in bg daemon)"

#     # NO GIT OPERATIONS - handled by background daemon after batch

#     # Synchronous Neo4j write (no threading in MCP)
#     neo4j_result = create_concept_in_neo4j(config, concept_name, linked_description, relationship_dict, shared_connection=shared_connection)
#     if "Failed to create concept" in neo4j_result:
#         raise Exception(f"Neo4j storage failed: {neo4j_result}")

#     # YOUKNOW validation (warns, doesn't block)
#     youknow_msg = ""
#     if not hide_youknow and YOUKNOW_AVAILABLE:
#         try:
#             youknow = YOUKNOW()
#             # Convert CartON concept to PIOEntity
#             entity = PIOEntity(
#                 name=concept_name,
#                 description=linked_description,
#                 is_a=relationship_dict.get("is_a", []),
#                 part_of=relationship_dict.get("part_of", []),
#                 instantiates=relationship_dict.get("instantiates", []),
#             )
#             youknow.add_entity(entity)
            
#             # Use UARL validation directly (not check_and_respond)
#             result = youknow.validate_entity(concept_name)
#             if not result.valid:
#                 youknow_msg = f" [YOUKNOW: {result.message}]"
#                 print(f"[YOUKNOW] {result.message}", file=sys.stderr)
#             # UARL validation now handles existence checking via domain.owl
#             # No need for redundant in-memory check
#         except Exception as e:
#             logger.warning(f"YOUKNOW validation error: {e}\n{traceback.format_exc()}")
def rename_concept_func(
    old_concept_name: str,
    new_concept_name: str,
    reason: str = "Conceptual refinement"
) -> str:
    """
    Rename a concept by creating new concept and updating all references.

    This is proactive evolution (vs defensive sinking with _v1 suffix).
    Operations:
    1. Create new concept with better terminology (copies description from old)
    2. Query Neo4j for ALL edges pointing to old concept
    3. Update all edges to point to new concept
    4. Create bidirectional evolution links (evolved_from/evolved_to)
    5. Keep old concept as historical record

    Distinction from sinking:
    - Sinking (_v1): automatic on validation failures, marks broken concepts
    - Renaming: user-initiated refinement, improves terminology while preserving graph

    Args:
        old_concept_name: Current concept name to be evolved
        new_concept_name: New improved concept name
        reason: Explanation for the rename (stored in evolution relationship)

    Returns:
        Status message describing the rename operation

    Raises:
        Exception if old concept doesn't exist or new concept already exists
    """
    try:
        from heaven_base.tool_utils.neo4j_utils import KnowledgeGraphBuilder
        from datetime import datetime
        import os
        from pathlib import Path

        # Normalize both concept names
        old_normalized = normalize_concept_name(old_concept_name)
        new_normalized = normalize_concept_name(new_concept_name)

        # Get config
        config = ConceptConfig(
            github_pat=os.getenv('GITHUB_PAT', 'dummy'),
            repo_url=os.getenv('REPO_URL', 'dummy'),
            neo4j_url=os.getenv('NEO4J_URI', 'bolt://host.docker.internal:7687'),
            neo4j_username=os.getenv('NEO4J_USER', 'neo4j'),
            neo4j_password=os.getenv('NEO4J_PASSWORD', 'password'),
            base_path=os.getenv('BASE_PATH')
        )

        # Initialize graph connection
        graph = KnowledgeGraphBuilder(
            uri=config.neo4j_url,
            user=config.neo4j_username,
            password=config.neo4j_password
        )

        # Step 1: Verify old concept exists and new concept doesn't
        check_old_query = "MATCH (c:Wiki {n: $name}) RETURN c.d as description"
        old_result = graph.execute_query(check_old_query, {'name': old_normalized})

        if not old_result:
            graph.close()
            raise Exception(f"Old concept '{old_normalized}' does not exist in Neo4j")

        old_description = old_result[0]['description'] if old_result else f"Description from {old_normalized}"

        check_new_query = "MATCH (c:Wiki {n: $name}) RETURN c"
        new_result = graph.execute_query(check_new_query, {'name': new_normalized})

        if new_result:
            graph.close()
            raise Exception(f"New concept '{new_normalized}' already exists - cannot rename")

        # Step 2: Create new concept with old concept's description
        print(f"[Rename] Creating new concept '{new_normalized}'...", file=sys.stderr)

        # Note: We don't call add_concept_tool_func here because we want the NEW concept
        # to inherit the old concept's description, not get a fresh description
        create_new_query = """
        CREATE (c:Wiki {n: $name, c: $canonical_form})
        SET c.d = $description
        SET c.t = datetime($timestamp)
        RETURN c.n as node_id
        """

        create_params = {
            'name': new_normalized,
            'canonical_form': new_normalized.lower().replace(' ', '_'),
            'description': old_description,
            'timestamp': datetime.now().isoformat()
        }

        graph.execute_query(create_new_query, create_params)

        # Step 3: Query for ALL relationships pointing TO old concept
        print(f"[Rename] Querying relationships pointing to '{old_normalized}'...", file=sys.stderr)

        incoming_query = """
        MATCH (source:Wiki)-[r]->(target:Wiki {n: $old_name})
        RETURN source.n as source_name, type(r) as rel_type, properties(r) as rel_props
        """

        incoming_rels = graph.execute_query(incoming_query, {'old_name': old_normalized})

        # Step 4: Update all incoming relationships to point to new concept
        print(f"[Rename] Updating {len(incoming_rels)} incoming relationships...", file=sys.stderr)

        for rel_data in incoming_rels:
            source_name = rel_data['source_name']
            rel_type = rel_data['rel_type']

            # Delete old relationship
            delete_query = f"""
            MATCH (source:Wiki {{n: $source}})-[r:{rel_type}]->(target:Wiki {{n: $old_name}})
            DELETE r
            """

            graph.execute_query(delete_query, {
                'source': source_name,
                'old_name': old_normalized
            })

            # Create new relationship to new concept
            create_rel_query = f"""
            MATCH (source:Wiki {{n: $source}})
            MATCH (target:Wiki {{n: $new_name}})
            CREATE (source)-[r:{rel_type}]->(target)
            SET r.ts = datetime($timestamp)
            SET r.renamed_from = $old_name
            """

            graph.execute_query(create_rel_query, {
                'source': source_name,
                'new_name': new_normalized,
                'old_name': old_normalized,
                'timestamp': datetime.now().isoformat()
            })

        # Step 5: Query for ALL relationships pointing FROM old concept
        print(f"[Rename] Querying relationships pointing from '{old_normalized}'...", file=sys.stderr)

        outgoing_query = """
        MATCH (source:Wiki {n: $old_name})-[r]->(target:Wiki)
        RETURN target.n as target_name, type(r) as rel_type, properties(r) as rel_props
        """

        outgoing_rels = graph.execute_query(outgoing_query, {'old_name': old_normalized})

        # Step 6: Copy all outgoing relationships from old to new concept
        print(f"[Rename] Copying {len(outgoing_rels)} outgoing relationships...", file=sys.stderr)

        for rel_data in outgoing_rels:
            target_name = rel_data['target_name']
            rel_type = rel_data['rel_type']

            # Create relationship from new concept to same targets
            copy_rel_query = f"""
            MATCH (source:Wiki {{n: $new_name}})
            MATCH (target:Wiki {{n: $target}})
            MERGE (source)-[r:{rel_type}]->(target)
            SET r.ts = datetime($timestamp)
            SET r.copied_from = $old_name
            """

            graph.execute_query(copy_rel_query, {
                'new_name': new_normalized,
                'target': target_name,
                'old_name': old_normalized,
                'timestamp': datetime.now().isoformat()
            })

        # Step 7: Create bidirectional evolution links
        print(f"[Rename] Creating evolution links...", file=sys.stderr)

        evolution_forward_query = """
        MATCH (old:Wiki {n: $old_name})
        MATCH (new:Wiki {n: $new_name})
        CREATE (old)-[r:EVOLVED_TO]->(new)
        SET r.ts = datetime($timestamp)
        SET r.reason = $reason
        """

        evolution_backward_query = """
        MATCH (old:Wiki {n: $old_name})
        MATCH (new:Wiki {n: $new_name})
        CREATE (new)-[r:EVOLVED_FROM]->(old)
        SET r.ts = datetime($timestamp)
        SET r.reason = $reason
        """

        evolution_params = {
            'old_name': old_normalized,
            'new_name': new_normalized,
            'timestamp': datetime.now().isoformat(),
            'reason': reason
        }

        graph.execute_query(evolution_forward_query, evolution_params)
        graph.execute_query(evolution_backward_query, evolution_params)

        # Step 8: Create filesystem concept for new name (if needed)
        base_path = os.getenv('HEAVEN_DATA_DIR', '/tmp/heaven_data')
        concepts_dir = Path(base_path) / "wiki" / "concepts"
        new_concept_dir = concepts_dir / new_normalized

        if not new_concept_dir.exists():
            print(f"[Rename] Creating filesystem directory for '{new_normalized}'...", file=sys.stderr)
            new_concept_dir.mkdir(parents=True, exist_ok=True)

            # Copy the description file
            old_concept_dir = concepts_dir / old_normalized
            old_itself_file = old_concept_dir / f"{old_normalized}_itself.md"

            if old_itself_file.exists():
                new_itself_file = new_concept_dir / f"{new_normalized}_itself.md"

                # Read old content and update concept name references
                old_content = old_itself_file.read_text(encoding='utf-8')
                new_content = old_content.replace(old_normalized, new_normalized)

                # Add evolution note at the top
                evolution_note = f"*This concept evolved from [{old_normalized}](../{old_normalized}/{old_normalized}_itself.md) on {datetime.now().strftime('%Y-%m-%d')}. Reason: {reason}*\n\n"
                new_content = f"# {new_normalized}\n\n{evolution_note}{new_content.split('## Overview')[1] if '## Overview' in new_content else new_content}"

                new_itself_file.write_text(new_content, encoding='utf-8')

        # Commit filesystem changes
        result = run_git_command(["git", "add", "."], base_path)
        if "error" not in result:
            result = run_git_command(["git", "commit", "-m", f"Rename: {old_normalized} -> {new_normalized}"], base_path)

        graph.close()

        summary = f"Renamed '{old_normalized}' to '{new_normalized}'. Updated {len(incoming_rels)} incoming and {len(outgoing_rels)} outgoing relationships. Evolution links created. Old concept preserved as historical record."
        print(f"[Rename] {summary}", file=sys.stderr)

        return summary

    except ImportError as e:
        traceback.print_exc()
        return f"Rename failed: Neo4j driver not available - {str(e)}"
    except Exception as e:
        traceback.print_exc()
        return f"Rename failed: {str(e)}"


# (removed 2026-06-25) The AddConceptTool / RenameConceptTool BaseHeavenTool wrappers + their
# ArgsSchema classes lived here. They were heaven-tool wrappers around add_concept_tool_func /
# rename_concept_func — NOTHING in the monorepo imported them (verified). carton exposes these as MCP
# tools via server_fastmcp (FastMCP), calling the funcs directly; it never used the heaven-tool wrappers.
# Their only effect was forcing `from heaven_base import BaseHeavenTool, ToolArgsSchema, ToolResult` at
# module top, which pulled langchain_core (~53 MB) into every carton process. Removed for that reason.
# If a heaven AGENT ever genuinely needs add-concept as a heaven tool, define that wrapper IN
# heaven-framework's tool system (where BaseHeavenTool lives), not here in the MCP.

