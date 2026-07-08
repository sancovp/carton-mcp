---
name: understand-carton-stash-and-retry
description: "WHAT: CartON's server-side payload stashing — on a failed/exception add_concept the partial payload is stashed so a retry merges new fields without re-typing everything. WHEN: an add_concept errors and you want to re-send only the missing fields, or you're reasoning about the stash/clear_stash params."
---

# understand-carton-stash-and-retry

## The pattern (IS, current 2026-06-17)

When `add_concept` raises/fails, CartON **stashes the partial payload server-side** (keyed by concept
name) so the next call for that concept **merges** the stashed relationships/description with the new
fields — you re-send only what was missing, not the whole typed payload. Controlled by the `stash` /
`clear_stash` params on `add_concept` (use `clear_stash` to discard a stale stash).

## What actually triggers a reject now (corrected — the old triggers are DEAD)
The old description said stashing fires on "GIINT / template / **YOUKNOW** validation" failure. **All
three of those triggers are gone:** the YOUKNOW validators were removed (SOMA :8091 is THE validator),
and the GIINT `_Unnamed`/template ontology-completion (`ensure_ontology_completeness` + `ONTOLOGY_SCHEMAS`)
is DISABLED. Today the live carton-side reject is a **SOMA `mereo_error`** (the concept's own `is_a` is an
unknown type — `add_concept_tool` #9 returns before the queue write, surfaced verbatim by
`_format_concept_result`), or a plain relationship/typing/exception error. The stash + incremental-merge
mechanism itself is intact — only the named failure-triggers changed.

CoR: Now I understand stash-and-retry: a failed add_concept stashes the partial payload; retry merges new
fields without re-typing; the live reject is a SOMA mereo_error (or an exception), NOT the removed
YOUKNOW/template/GIINT validation.
