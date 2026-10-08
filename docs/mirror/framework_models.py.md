# doc(m): framework_models.py

- **Canonical path:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/framework_models.py`
- **Line count:** 192 (measured: `wc -l` = 192, `awk 'END{print NR}'` = 192)
- **Module role:** A pure Pydantic type-declaration module. It declares eight `BaseModel` subclasses — five for the framework crystallization system and three for the conversation/hierarchical-summarizer layer — and nothing else. It contains no functions, no validators, no configuration, no I/O, and no runtime behavior of any kind; its entire purpose is to be a set of class objects that another package (`soma_prolog`) imports and passes to `vault()` so that SOMA derives system types and restrictions from their field signatures.

## What this module IS (from the code)

The file is 192 lines, of which lines 1-39 are the module docstring, lines 41-43 are the only two imports, and lines 46-192 are eight class definitions. Every class body consists exclusively of a docstring, comments, and annotated field declarations. There is not a single statement in the file that executes anything beyond class construction at import time.

The module docstring (lines 1-39) states the reason the file exists and the reason it lives in this package rather than in `soma-prolog`. It records a doctrine it calls GNOSYS-VAULT: a library's SOMA types come only from vaulting its Pydantic code models (lines 8-10), and it places these models in `carton-mcp` because frameworks are typed CartON structures operated on by carton skills (lines 10-14). It names two consumers by path: `project_framework` in `carton_mcp.substrate_projector` for projection, and `soma_prolog/foundation/framework.py` for the vaulting at SOMA boot (lines 14-16). Both references resolve: `project_framework` is defined at `knowledge/carton-mcp/substrate_projector.py:1195`, and the vaulting import is at `base/soma-prolog/soma_prolog/foundation/framework.py:204`.

The load-bearing property of this file is **field optionality**, and the docstring says so explicitly at lines 18-24. A field declared with no default (for example `name: str`) becomes a CODE-stage restriction in SOMA — its absence grades an instance as SOUP with a fill instruction. A field declared `Optional[...] = None` becomes a DCHAIN-stage restriction — reported, non-blocking, with its meaning enforced by law d-chains in `soma_prolog/foundation/framework.py` rather than by the type. This means the choice between `str` and `Optional[str] = None` on any line in this file is a semantic declaration about SOMA's verdict gradient, not a Python-level convenience. Nothing in this module enforces or checks that; the enforcement lives entirely in `vault()` and the d-chains downstream.

The second load-bearing statement is that **graph edges are not fields** (lines 25-29). The classification vocabulary — `discusses`, `exemplifies`, `instantiates`, `closes`, `contradicts`, `has_receipt`, `part_of_framework` — is deliberately absent from every model, because those are relationships written on the graph rather than scalar state. That absence is confirmed by the code: none of the eight classes declares any field with any of those names. Those edge names appear instead in the d-chain bodies of the consuming module, for example `part_of_framework` and `has_receipt` at `base/soma-prolog/soma_prolog/foundation/framework.py:115`, `:141`, `:263`, and `:275`.

The file holds two distinct families, separated by comment banners.

**Family one — the framework crystallization types** (lines 46-134). `Framework` (line 46) is the head of the family and carries a stated split between its required and optional halves: the required five (`name`, `definition`, `obstacle`, `overcome`, `dream`, lines 57-62) are the identity plus definition plus the hero's-journey core, and everything after that is described in its own docstring (lines 50-53) as "the climb." The optional fields are grouped by comment into four blocks: the four-facts publish fields (lines 64-70), the Layer/State/Type/Phase classification (lines 72-76), the publish-time links (lines 78-80), and two singletons — `name_provenance` (line 84) and `scorer_score` (line 87). The remaining four classes of this family — `MentalModel` (line 96), `Technique` (line 104), `Claim` (line 111), `FrameworkCandidate` (line 124) — are deliberately minimal: each is a `name` plus a `statement`, with `FrameworkCandidate` adding one optional `proposed_name`. The banner at lines 90-93 states the intent directly: "Small, boring, typed." `Claim`'s docstring (lines 111-118) carries the receipt principle, and `FrameworkCandidate`'s (lines 124-130) records that naming is a human moment with no auto-naming — but neither statement is expressed in code here; both are enforced elsewhere.

**Family two — the conversation types** (lines 137-192). The banner at lines 137-143 states these exist to TYPE nodes that the hierarchical-summarize ladder already writes, so that classifier observations against them validate and d-chains can fire on them, and that they do not change the node shapes the summarizer produces. It gives the reason `summary` is optional throughout this family: the summarizer carries the text in the node description (`n.d`), not in a field.

`Conversation` (line 145) is the largest class in the file and the only one whose docstring records a change with a date and a rationale (lines 146-163). It states that before 2026-08-24 the model was `name` plus `summary` only — a label, not a container — so `vault()` derived exactly one restriction and SOMA had no basis on which to demand or check that a conversation HAS anything. The docstring is explicit that the data was already webbed correctly by `carton_precompact` and only the type failed to say so. Its parts are declared in two blocks: `session_id`, `iterations`, `journal_entries` (lines 167-169), and then the hierarchical summary layer added the same day — `iteration_summaries`, `phases`, `subphases`, `executive_summary` (lines 175-178). Every one of these is `Optional` and defaults to `None`. The docstring (lines 154-158) argues that this is what makes the addition purely additive: optional fields become dchain-stage restrictions, so no existing conversation can be pushed into soup by them. Lines 160-163 record that `journal_entries` is the coarse half of a two-part journal join whose exact half is `ToolCall.produces` in `carton_mcp.timeline_models` — a sibling module which exists at `knowledge/carton-mcp/timeline_models.py`.

`ConversationPhase` (line 181) and `IterationSummary` (line 188) close the file, each a two-field `name` plus optional `summary`, labelled in their docstrings as the summarizer's L2 and L1 outputs respectively.

## Imports

### stdlib
- `from typing import List, Optional` (line 41)

### third-party
- `from pydantic import BaseModel` (line 43). Installed version in this environment measured at 2.10.6, so these are Pydantic v2 models.

### local
- None. This module imports nothing from `carton_mcp` or from any other project package. It is a leaf.

## Top-level definitions

There are eight class definitions and zero functions.

**`Framework(BaseModel)` — line 46.** The framework document type.
- Required (no default), lines 57-62: `name: str`, `definition: str`, `obstacle: str`, `overcome: str`, `dream: str`.
- Optional, lines 67-69: `skilltome_location: Optional[str] = None`, `github_url: Optional[str] = None`, `build_time_estimate: Optional[str] = None`. Comments label these facts 2, 3 and 4; the comment at line 66 states that fact 1 ("it IS a framework") is the `is_a` edge itself and therefore has no field.
- Optional, lines 73-76: `layer: Optional[str] = None`, `state: Optional[str] = None`, `framework_type: Optional[str] = None`, `phase: Optional[int] = None`. Their permitted values appear only as trailing comments (`PAIAB | SANCTUM | CAVE`; `Actual | Aspirational`; `Reference | Operating_Context | Workflow | Library`; `1-5`).
- Optional, lines 79-80: `deep_dive_url: Optional[str] = None`, `plugin_url: Optional[str] = None`.
- Optional, line 84: `name_provenance: Optional[str] = None` (comment: `user_coined | system_surfaced`).
- Optional, line 87: `scorer_score: Optional[float] = None` (comment: LLM-filled, ">= 8 to pass when present").

**`MentalModel(BaseModel)` — line 96.** Fields: `name: str` (100), `statement: str` (101).

**`Technique(BaseModel)` — line 104.** Fields: `name: str` (107), `statement: str` (108).

**`Claim(BaseModel)` — line 111.** Fields: `name: str` (120), `statement: str` (121). Its docstring states the receipt principle (every claim must carry a `has_receipt` edge) and names the receipt-typing d-chain in `foundation/framework.py` as the thing that returns the instruction when it is missing.

**`FrameworkCandidate(BaseModel)` — line 124.** Fields: `name: str` (132), `statement: str` (133), `proposed_name: Optional[str] = None` (134).

**`Conversation(BaseModel)` — line 145.** Fields: `name: str` (165), `summary: Optional[str] = None` (166), `session_id: Optional[str] = None` (167), `iterations: Optional[List[str]] = None` (168), `journal_entries: Optional[List[str]] = None` (169), `iteration_summaries: Optional[List[str]] = None` (175), `phases: Optional[List[str]] = None` (176), `subphases: Optional[List[str]] = None` (177), `executive_summary: Optional[str] = None` (178). This is the only use of `List` in the file — four of the nine fields are `Optional[List[str]]`, and `List` is imported solely for them.

**`ConversationPhase(BaseModel)` — line 181.** Fields: `name: str` (184), `summary: Optional[str] = None` (185).

**`IterationSummary(BaseModel)` — line 188.** Fields: `name: str` (191), `summary: Optional[str] = None` (192). This is the last line of the file.

## What this module CALLS

Nothing, at runtime. The only outward dependency exercised is subclassing `pydantic.BaseModel` and evaluating the `typing.List` / `typing.Optional` annotations, both of which happen at class-construction time during import. There are no function calls, no network or filesystem access, no database access, no logging, no `vault()` call, and no reference to `soma_prolog`, `carton_mcp.substrate_projector`, or `carton_mcp.timeline_models` in code — those three appear only as prose inside docstrings. Importing this module has no side effects other than defining eight classes.

## What CALLS this module (grep-confirmed)

Executable imports (a real `import` statement resolving this module):
- `base/soma-prolog/soma_prolog/foundation/framework.py:204` — a lazy import inside `register()` (the function begins at line 195) pulling all eight classes, which are then collected into a `models` list and passed one at a time to `vault(model)`. The comment at lines 202-203 states the import is lazy to keep SOMA's foundation boot decoupled from carton at module-import time.
- `base/soma-prolog/soma_prolog/foundation/timeline.py:35` — a module-level `from carton_mcp.framework_models import Conversation`. Line 38 collects `Conversation` first in its `_MODELS` list, with the comment that it is re-vaulted first so its new optional parts land before the d-chains reference them.

Dynamic import by string path (no `import` statement, resolved at runtime):
- `base/soma-prolog/scripts/register_foundation.py:36-43` — eight tuples in the `_VAULTED_MODELS` table (declared line 29), each naming `("carton_mcp.framework_models", "<ClassName>")` for all eight classes. The table is consumed by a helper that calls `__import__(module_path, fromlist=[class_name])` and `getattr(mod, class_name)` (lines 54-55), driven by the loop at line 78.

Prose references only (docstrings and comments — no code dependency):
- `scalable-publishing/manualcore/register_content_rungs.py:13`
- `base/soma-prolog/soma_prolog/foundation/__init__.py:14` and `:25`
- `base/soma-prolog/soma_prolog/foundation/timeline.py:13`
- `base/soma-prolog/tests/test_framework_foundation.py:6`
- `not-unified/quarantine/2026-07-25-rigged-session/base/soma-prolog/soma_prolog/foundation/__init__.py:14` (a quarantined copy, not live source)

Callers inside `knowledge/carton-mcp` itself: none found by grep. A search for the string `framework_models` across the package returned no hits at all outside this file's own path, so nothing in carton-mcp imports its own type module — including `substrate_projector.py`, which the module docstring names as the home of `project_framework`. `project_framework` exists at `substrate_projector.py:1195` but does not import these models.

## Notes / discrepancies

**No validation backs any of the enumerations or thresholds stated in comments.** Every constrained-looking field is a bare `str`, `int`, or `float` with the permitted values written only in a trailing comment. `layer` (line 73), `state` (line 74), `framework_type` (line 75) and `name_provenance` (line 84) are `Optional[str]` and accept any string; `phase` (line 76) is `Optional[int]` with the comment `1-5` and accepts any integer; `scorer_score` (line 87) carries the comment ">= 8 to pass when present" and accepts any float. There is no `Literal`, no `Enum`, no `Field(...)` constraint, and no `@field_validator` anywhere in the file. This is consistent with the module's stated design (SOMA and the d-chains hold the meaning; the model holds the shape) but it means a reader who takes a comment as a constraint will be wrong at the Python level.

**No model configuration is declared.** There is no `model_config` and no nested `Config` on any class, so all eight use Pydantic v2 defaults — notably, unknown extra fields are ignored rather than rejected. Nothing in this file makes any statement about extra-field behavior.

**Every cross-reference in the module docstring resolves.** Checked individually: `project_framework` exists (`knowledge/carton-mcp/substrate_projector.py:1195`); `soma_prolog/foundation/framework.py` imports and vaults these models (line 204); `carton_mcp.timeline_models` exists as a sibling file; `journey_tools.py` exists at `integration/conversation-ingestion/conversation_ingestion_mcp/journey_tools.py` and the cited range 14-90 does contain the `obstacle`/`overcome`/`dream` metadata (`dream: str` at relative line 1 of that range, with the three documented at relative lines 11-13 and a presence check at relative lines 57-63); `FRAMEWORK_ORGANIZATION_METHODOLOGY.md` exists at `integration/conversation-ingestion/FRAMEWORK_ORGANIZATION_METHODOLOGY.md`. The docstring's `foundation/skill.py` and `foundation/rule.py` shape comparison (line 16) was not checked.

**One internal date inconsistency in the docstring.** Line 31 labels the merged document-shape sources as "the conversation-ingestion legacy, Jan 2025", while every other date in the file is 2026 (Isaac 2026-07-11 at lines 3, 11, 28, 83; 2026-08-24 at lines 147 and 170). Whether "Jan 2025" is a typo for 2026 or a genuine reference to older material cannot be determined from this file.

**A frozen count appears inside a docstring.** Line 157 states "it cannot push any of the 1,192 existing conversations into soup." That number was true when written (2026-08-24 per line 147) and nothing keeps it current; it is a snapshot, not a live fact, and this module has no way to observe it.

**`Framework.name` versus the docstring's fact-1 claim.** The comment at line 66 says fact 1, "it IS a framework", is the `is_a` edge itself. That is a claim about the graph, not about this file; no code here creates, requires, or checks any `is_a` edge. The same holds for the `has_receipt` requirement stated in `Claim`'s docstring (lines 114-117) — the type declares two plain string fields and knows nothing about receipts.

**`MentalModel`, `Technique` and `Claim` are structurally identical.** All three are exactly `name: str` plus `statement: str` (lines 100-101, 107-108, 120-121). They differ only in class name and docstring, which is what makes them distinguishable to `vault()` (which derives a system type per class) and to the d-chains that match on `is_a mental_model` versus `is_a technique` versus `is_a claim` — for example at `base/soma-prolog/soma_prolog/foundation/framework.py:141`. Nothing in this file distinguishes them.

**The two families in one file share no code and no base class beyond `BaseModel`.** The filename and module docstring lead with "Framework system Pydantic models", but roughly a quarter of the file (lines 137-192) declares conversation/summarizer types that are not part of the framework family and are consumed by a different registrar (`foundation/timeline.py`, which imports only `Conversation`). This is an observation about the file's current contents, not a defect claim.
