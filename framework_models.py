"""Framework system Pydantic models — the CODE models vaulted into SOMA.

THE FRAMEWORK LAW (Isaac 2026-07-11, verbatim): "every single blog is supposed
to be *about frameworks*. Frameworks *definitionally* cannot be SDKs, APIs, or
anything except for instructions about agent skills to give to agents, inside
some SkillTome somewhere."

These models are the type source for the framework crystallization system
(GNOSYS-VAULT doctrine: a library's SOMA types come ONLY from vault()-ing its
Pydantic CODE models). They live in carton-mcp because frameworks are typed
CARTON structures operated on by carton skills (Isaac 2026-07-11: "we would
probably just do this all thru CartON... this probably is all carton skills at
the end of the day"), and their projection (project_framework) lives in
carton_mcp.substrate_projector. soma_prolog/foundation/framework.py imports
these and vaults them at SOMA boot — the same shape as foundation/skill.py
(models in skill_manager) and foundation/rule.py (model in paia_builder).

Field semantics:
- REQUIRED fields (no default) become CODE-stage restrictions in SOMA — their
  absence grades an instance SOUP with a fill instruction (soup accumulates
  until the gates pass; that is the climb, not a rejection).
- OPTIONAL fields become DCHAIN-stage restrictions — reported, non-blocking;
  the law d-chains in foundation/framework.py enforce their MEANING (e.g.
  links require megaframework resolution before they are linkable).
- GRAPH EDGES ARE NOT FIELDS. The classification vocabulary edges (discusses /
  exemplifies / instantiates / closes / contradicts / has_receipt /
  part_of_framework) are relationships written on the graph, because
  composition is only computable over triples (Isaac 2026-07-11: props =
  scalar state only; classifications must be graph).

Merged document shape sources (the conversation-ingestion legacy, Jan 2025):
- hero's-journey journey metadata obstacle/overcome/dream (journey_tools.py:14-90;
  dream = what becomes possible after mastering this framework)
- the framework-scorer mimetic-desire bar (author-pain grounded, journey shown
  not solution described, accessible path present) — the Prolog-computable
  structural gate is the journey d-chain; the semantic 1-10 score lands in
  scorer_score and is LLM-filled
- FRAMEWORK_ORGANIZATION_METHODOLOGY.md Layer x State x Type x Phase hierarchy
"""

from typing import Optional

from pydantic import BaseModel


class Framework(BaseModel):
    """A framework: instructions about agent skills to give to agents, living
    in a SkillTome — never the SDK/API/code itself (THE FRAMEWORK LAW).

    Required = the definitional minimum for the framework DOCUMENT to exist
    (identity + definition + the hero's-journey core). Everything else is the
    climb: four-facts publish fields, Layer/State/Type/Phase classification,
    links, provenance.
    """

    # identity + definition (required — the document core)
    name: str
    definition: str
    # hero's-journey journey metadata (required — the crystallization core)
    obstacle: str
    overcome: str
    dream: str

    # THE FOUR FACTS every blog about this framework carries (publish-time;
    # optional here, enforced by law d-chains when the framework links out):
    # fact 1 "it IS a framework" = the is_a edge itself.
    skilltome_location: Optional[str] = None   # fact 2: which SkillTome it lives in
    github_url: Optional[str] = None           # fact 3: you can see it on github
    build_time_estimate: Optional[str] = None  # fact 4: build it yourself in N
    #                                            (N grounded from receipts, never fabricated)

    # Layer x State x Type x Phase classification (the legacy hierarchy)
    layer: Optional[str] = None            # PAIAB | SANCTUM | CAVE
    state: Optional[str] = None            # Actual | Aspirational
    framework_type: Optional[str] = None   # Reference | Operating_Context | Workflow | Library
    phase: Optional[int] = None            # 1-5

    # links (wired at publish; linkability gated by megaframework resolution)
    deep_dive_url: Optional[str] = None
    plugin_url: Optional[str] = None

    # naming is controlled: the user knows the name because they came up with
    # it, or they find out about it from the system (Isaac 2026-07-11)
    name_provenance: Optional[str] = None  # user_coined | system_surfaced

    # the mimetic-desire scorer bar (LLM-filled; >= 8 to pass when present)
    scorer_score: Optional[float] = None


# ── Classification vocabulary (what the L6 classifier writes) ────────────────
# Small, boring, typed. The EDGES (discusses / exemplifies / instantiates /
# closes / contradicts / has_receipt / part_of_framework) are graph
# relationships on instances of these types — never fields here.


class MentalModel(BaseModel):
    """A mental model surfaced in a conversation — a way of seeing that a
    framework can be composed from."""

    name: str
    statement: str


class Technique(BaseModel):
    """A concrete technique/procedure surfaced in a conversation."""

    name: str
    statement: str


class Claim(BaseModel):
    """An archival claim (something asserted as having happened / being true).

    THE RECEIPT PRINCIPLE (Isaac 2026-07-11): every claim must carry a
    has_receipt edge to a resolving timeline or journal node — "really did
    this actually happen" / "this needs a ref". The receipt-typing d-chain
    (foundation/framework.py) returns the instruction when it is missing.
    """

    name: str
    statement: str


class FrameworkCandidate(BaseModel):
    """A composed-but-not-yet-named framework candidate (stage 3 output).

    Candidates surface in chat for the AC-click naming moment — Isaac names
    (or confirms a seeded name); no auto-naming, no auto-creation of named
    frameworks. proposed_name holds a seeded name when one exists.
    """

    name: str
    statement: str
    proposed_name: Optional[str] = None


# ── Conversation types (what the hierarchical-summarize ladder writes) ──────
# These TYPE the nodes HS already writes (Conversation_* / phase nodes /
# Iteration_Summary_*) so classifier observations against them validate and
# d-chains can fire on them. They do NOT change HS node shapes — name is the
# node identity; summary is optional because HS carries the text in the node
# description (n.d), not a field.


class Conversation(BaseModel):
    """A conversation container node (HS: Conversation_{id})."""

    name: str
    summary: Optional[str] = None


class ConversationPhase(BaseModel):
    """A phase within a conversation (HS L2 output)."""

    name: str
    summary: Optional[str] = None


class IterationSummary(BaseModel):
    """One iteration's summary (HS L1 output: Iteration_Summary_{ts})."""

    name: str
    summary: Optional[str] = None
