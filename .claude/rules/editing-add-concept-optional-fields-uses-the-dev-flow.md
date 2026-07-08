# Editing add_concept_tool_func's Optional Provenance Fields Uses The `edit-add-concept-optional-fields` Dev-Flow FIRST — repo-scoped, NON-NEGOTIABLE

When you are about to edit `add_concept_tool_func`'s `domain`/`subdomain`/`personal_domain`/`produces`
params, `merge_optional_domain_fields`, or `PERSONAL_DOMAINS` in `add_concept_tool.py` — you MUST FIRST
use the `edit-add-concept-optional-fields` skill and do its COMPLETE Part-2 coherence edit-set, then its
Part-3 E2E gate. NEVER edit one place only.

This capability's correctness is DISTRIBUTED and has already burned one build attempt: `merge_optional_
domain_fields` MUST operate on the `relationships` LIST (`[{"relationship":..., "related":...}, ...]`),
NOT on `relationship_dict`, and `add_concept_tool_func` MUST reassign `relationships =
merge_optional_domain_fields(relationships, ...)` BEFORE `relationship_dict` is built — because
`relationship_dict` is a DERIVED view used only for SOMA/D2 validation, while the daemon queue write
(`queue_data["relationships"] = relationships`) persists the LIST verbatim. A version that merges only
into `relationship_dict` validates correctly (SOMA and D2 both see the fields, the response even shows a
plausible `[D2: ...]` coverage message) but the fields SILENTLY NEVER REACH THE GRAPH — this exact bug
was built, unit-tested green, and only caught by a live `query_wiki_graph` re-check during this
capability's own E2E verification (2026-07-04). Do not trust green unit tests or a correct-looking D2
message as proof this capability works — only a live graph query proves it.

**Why:** this is the project-scoped enforcement required by the global law
`every-build-ends-in-a-development-flow-skill`. See `edit-add-concept-optional-fields` for the full
edit-set and the only valid test — the unit gate (`test_concept_provenance_optional_fields.py` green)
PLUS the E2E gate through the real live surface (a direct `add_concept_tool_func` call with all four
optional fields → `query_wiki_graph` confirms all four relationship types actually landed, PLUS a
zero-kwarg old-style call proves backward compatibility for every existing bypass caller).
