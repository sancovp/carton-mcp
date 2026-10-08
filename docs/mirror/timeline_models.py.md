# doc(m): timeline_models.py

- **Canonical path:** /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/timeline_models.py
- **Line count:** 77 (measured: `wc -l` = 77, `awk END{print NR}` = 77, 3406 bytes, file ends with a newline)
- **Module role:** A pure Pydantic model declaration file. It defines four `BaseModel` subclasses — `Iteration`, `UserMessage`, `AgentMessage`, `ToolCall` — whose field signatures are the sole input SOMA's `vault()` introspects to derive the SOMA types for the conversation record. The module itself vaults nothing and executes nothing.

## What this module IS (from the code)

The file is 20 lines of module docstring (`timeline_models.py:1-20`), two import lines
(`:22`, `:24`), and four class bodies (`:27-40`, `:43-52`, `:55-60`, `:63-77`). There are no
functions, no `__all__`, no validators, no `model_config`, no constants, and no conditional
logic. Every class inherits `BaseModel` directly and declares only annotated attributes.
Importing the module has no side effects: it touches no filesystem, no network, no graph, and
calls nothing but the two imports.

The field shape is uniform and deliberate. Every one of the four models has a required
`name: str` (`:36`, `:50`, `:58`, `:73`) and, except for `Iteration`, a required parent-pointer
`iteration: str` (`:51`, `:59`, `:74`); `Iteration` instead carries a required
`conversation: str` (`:37`). Every other field is `Optional[...]` with a `None` default. That
required/optional split is the module's actual payload — the module docstring at `:11-14`
states the mechanism it feeds: `vault()` introspects these signatures and derives SOMA
restrictions from them, with required fields becoming CODE-stage (blocking) restrictions and
defaulted fields becoming dchain-stage (non-blocking) ones. So each class's choice of what is
required IS a statement of what SOMA will demand, and each class docstring argues its own case
for that choice:

- `Iteration` (`:27-40`) — `conversation` required because "an iteration that belongs to no
  conversation is not an iteration, it is a loose row" (`:29-30`); the three message lists
  optional because a real iteration may legitimately have no tool calls or no agent text, and
  demanding them "would push honest rows into soup" (`:31-33`).
- `UserMessage` (`:43-52`) — `iteration` required "for the same reason: position in the record
  is what makes it a message rather than a stray string" (`:46-47`).
- `AgentMessage` (`:55-60`) — the only class with a one-line docstring (`:56`) and no stated
  rationale; its shape simply mirrors `UserMessage`.
- `ToolCall` (`:63-77`) — the largest docstring (`:64-71`), all of it justifying `produces` as
  the "EXACT-LOCUS half of the journal join," optional because "the overwhelming majority of
  tool calls produce no journal entry, and a required field here would put every ordinary
  Read/Bash into soup" (`:69-70`).

Each class docstring also records the runtime name-shape the concepts carry in the graph
(`HS: Iteration_{ts}` `:28`, `User_Message_{ts}` `:44`, `Agent_Message_{ts}_A{n}` `:56`,
`Tool_Call_{ts}_T{n}` `:64`) — documentation of the writer's naming, not something this file
enforces.

The module docstring's `NAMING` paragraph (`:16-19`) states the one packaging constraint: these
models must be vaulted **without** a `library=` prefix so they normalize to
`iteration` / `tool_call` / `user_message` / `agent_message` — the atoms `carton_precompact`
already writes as `is_a` targets — because a prefix "would mint DIFFERENT types and leave the
real 281,891 still untyped." That constraint is honored by the caller, not here: the vault call
is bare at `base/soma-prolog/soma_prolog/foundation/timeline.py:111` (`result = vault(model)`),
matching the pattern the docstring cites in `base/soma-prolog/soma_prolog/foundation/framework.py:227`.

## Imports

### stdlib
- `from typing import List, Optional` (`:22`)

### third-party
- `from pydantic import BaseModel` (`:24`)

### local
- none.

## Top-level definitions

| line | definition | fields (required unless noted) |
|---|---|---|
| `:27` | `class Iteration(BaseModel)` | `name: str` (`:36`), `conversation: str` (`:37`), `user_message: Optional[str] = None` (`:38`), `agent_messages: Optional[List[str]] = None` (`:39`), `tool_calls: Optional[List[str]] = None` (`:40`) |
| `:43` | `class UserMessage(BaseModel)` | `name: str` (`:50`), `iteration: str` (`:51`), `text: Optional[str] = None` (`:52`) |
| `:55` | `class AgentMessage(BaseModel)` | `name: str` (`:58`), `iteration: str` (`:59`), `text: Optional[str] = None` (`:60`) |
| `:63` | `class ToolCall(BaseModel)` | `name: str` (`:73`), `iteration: str` (`:74`), `tool: Optional[str] = None` (`:75`), `touches_file: Optional[str] = None` (`:76`), `produces: Optional[List[str]] = None` (`:77`) |

No functions, no methods, no module-level statements other than the two imports.

## What this module CALLS

Nothing. There is no call expression anywhere in the file. The only runtime work is Pydantic's
own metaclass building four model classes at import time from the annotations.

## What CALLS this module (grep-confirmed)

- `base/soma-prolog/soma_prolog/foundation/timeline.py:36` —
  `from carton_mcp.timeline_models import Iteration, UserMessage, AgentMessage, ToolCall`.
  This is the **only import of the module anywhere in the monorepo**. Those four classes are
  placed in `_MODELS` at `foundation/timeline.py:39` (alongside `Conversation`, imported from
  `carton_mcp.framework_models` at `:35`) and vaulted in the loop at `:109-111`.

Non-import references found by grep, all prose:
- `knowledge/carton-mcp/framework_models.py:161` — a docstring cross-reference naming
  `ToolCall.produces` as "the EXACT half" of the journal join.
- `base/soma-prolog/soma_prolog/foundation/__init__.py:24` — a docstring line describing the
  `timeline` foundation module as "the conversation-record types (carton_mcp.timeline_models + …)".
- `knowledge/carton-mcp/context/journal/2026-08.md:607,616`,
  `knowledge/carton-mcp/docs/vision/_rule-bypass-invalidation.md:10,19`,
  `knowledge/carton-mcp/docs/vision/_conversation-journal-join.md:61`,
  `context/journal/2026-08.md:1956,2006` — journal/vision entries about this module's creation.

Import resolution is real, not nominal: `pyproject.toml` sets
`package-dir = {"carton_mcp" = "."}` (`knowledge/carton-mcp/pyproject.toml:38`), so the repo
root **is** the `carton_mcp` package and `carton_mcp.timeline_models` resolves. An installed
copy exists at
`/home/GOD/.pyenv/versions/3.11.6/lib/python3.11/site-packages/carton_mcp/timeline_models.py`
and is **byte-identical** to the source (verified by `diff -q`).

## Notes / discrepancies

- **The module vaults nothing.** Its docstring (`:11-14`) is written in the voice of the vault
  mechanism ("vault() introspects these signatures and derives the restrictions"), which can
  read as though this file performs the vaulting. It does not; `vault()` is never imported or
  called here. The vaulting happens entirely in
  `base/soma-prolog/soma_prolog/foundation/timeline.py:109-111`. This is accurate as written —
  the docstring describes what will be done *to* these signatures — but it is the one place a
  reader could mis-attribute behavior to this module.

- **`Conversation` is not in this file.** The docstring names five types at `:5-6`
  (Conversation → Iteration → User_Message / Agent_Message / Tool_Call) and says "four of those
  five types were DECLARED NOWHERE" (`:6-7`). The four are the ones defined here; the fifth,
  `Conversation`, lives at `knowledge/carton-mcp/framework_models.py:145` and is vaulted by
  both `foundation/framework.py:210,221` and `foundation/timeline.py:39`.

- **The docstring's cross-reference to `framework.py` checks out.** `:16-17` claims
  "foundation/timeline.py calls vault(model) bare, exactly as framework.py does for
  Conversation." Verified: `foundation/timeline.py:111` and `foundation/framework.py:227` both
  read `result = vault(model)` with no `library=` argument, and `Conversation` is in
  framework.py's model list at `:210`/`:221`.

- **Prose/type mismatch on `ToolCall.produces`.** The docstring speaks of it in the singular —
  "it names **the entry** it produced" (`:67`) — while the field is `Optional[List[str]]`
  (`:77`), i.e. plural. Nothing in this file constrains the list to one element. Whether one or
  many is intended is not determinable from the code; the caller and the writer that populates
  the field would settle it.

- **Field-name asymmetry inside `Iteration`.** `user_message` is a singular `Optional[str]`
  (`:38`) while `agent_messages` and `tool_calls` are plural `Optional[List[str]]` (`:39-40`) —
  implying at most one user message per iteration. The docstring does not state this; it only
  calls all three "the message lists" (`:31`). What IS: one is scalar, two are lists.

- **No validation beyond types.** There are no Pydantic validators, no `Field(...)`
  constraints, no `model_config`, and no `__all__`. A `name` of `""` or a `conversation`
  pointing at a nonexistent concept is accepted by these models; any such checking lives in the
  d-chains registered in `foundation/timeline.py:42-103`, not here.

- **Every quantitative claim in the docstring is about the live graph, not the code.** The
  "281,891 concepts" and "four of those five types were DECLARED NOWHERE" (`:6-9`, `:19`) are
  measurements stated as of 2026-08-23/24 and cannot be confirmed or refuted from this file. I
  did not verify them; they would be settled by querying the store, not by reading source.

- **File state: untracked in git, yet installed.** `git status --porcelain` reports
  `?? knowledge/carton-mcp/timeline_models.py` — the module has never been committed — while a
  byte-identical copy is already present in site-packages, so the running system imports it.

- **The repo's own record flags this module as unre-checked.** `docs/vision/_rule-bypass-invalidation.md:10`
  and `context/journal/2026-08.md:607` state that this module (among others) was produced under
  rule-bypass and "should not be trusted or committed until re-checked." That is a status claim
  in the doc layer, not a property of the code; recorded here as a pointer, not as a verdict on
  correctness.
