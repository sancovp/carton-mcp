"""Timeline record types — the conversation record as CODE, so SOMA can type it.

WHY THIS FILE EXISTS (measured 2026-08-23/24). `carton_precompact` writes a fully-formed
conversation graph — Conversation -> Iteration -> User_Message / Agent_Message / Tool_Call, with
part_of on every child and the daemon adding the HAS_PART inverse. The DATA was always correct.
What was missing is that four of those five types were DECLARED NOWHERE, so 281,891 concepts
claiming them sat in permanent mereo_error: their own is_a named a type SOMA had never heard of,
and per the persist filter a mereo_error is never written, so they could not be reasoned over at
all. Vaulting these models is what turns the existing, correct data into typed data.

THE VAULT KEYSTONE: the code is the ONLY type source. vault() introspects these signatures and
derives the restrictions, so what these classes say IS what SOMA will demand. Required fields
become CODE-stage (blocking) restrictions; fields with a default become dchain-stage (non-blocking)
ones. Everything optional here is optional ON PURPOSE — see the note on each.

NAMING: vaulted WITHOUT a library prefix (foundation/timeline.py calls vault(model) bare, exactly
as framework.py does for Conversation), so they normalize to iteration / tool_call / user_message /
agent_message — the atoms carton_precompact already writes as is_a targets. A library= prefix here
would mint DIFFERENT types and leave the real 281,891 still untyped.
"""

from typing import List, Optional

from pydantic import BaseModel


class Iteration(BaseModel):
    """One turn of a conversation (HS: Iteration_{ts}).

    `conversation` is REQUIRED: an iteration that belongs to no conversation is not an iteration,
    it is a loose row — that is precisely the containment we want SOMA able to check.
    The message lists are OPTIONAL because a real iteration may legitimately have no tool calls,
    or no agent text; demanding them would push honest rows into soup for no reason.
    """

    name: str
    conversation: str
    user_message: Optional[str] = None
    agent_messages: Optional[List[str]] = None
    tool_calls: Optional[List[str]] = None


class UserMessage(BaseModel):
    """The literal user text of an iteration (HS: User_Message_{ts}).

    `iteration` is REQUIRED for the same reason: position in the record is what makes it a message
    rather than a stray string.
    """

    name: str
    iteration: str
    text: Optional[str] = None


class AgentMessage(BaseModel):
    """One agent text block within an iteration (HS: Agent_Message_{ts}_A{n})."""

    name: str
    iteration: str
    text: Optional[str] = None


class ToolCall(BaseModel):
    """One tool invocation within an iteration (HS: Tool_Call_{ts}_T{n}).

    `produces` is the EXACT-LOCUS half of the journal join (Isaac 2026-08-24): "it exists in the
    tool call". When this call invoked the journal CLI, it names the entry it produced — so the
    entry is reachable from the conversation by pure graph traversal, positioned at the precise
    iteration it was written in. OPTIONAL because the overwhelming majority of tool calls produce
    no journal entry, and a required field here would put every ordinary Read/Bash into soup.
    """

    name: str
    iteration: str
    tool: Optional[str] = None
    touches_file: Optional[str] = None
    produces: Optional[List[str]] = None
