---
name: single-turn-process-carton-edit-desc
description: 'WHAT: Precision editing of CartON concept descriptions

  WHEN: When you need to update a concept description with surgical edits'
---

# CartON Edit Desc

**Category: single_turn_process**

Edit a CartON concept's description (`n.d`). There are now FOUR `desc_update_mode`s on `add_concept`:
`edit` (surgical str-replace, PREFERRED for a targeted change), `replace` (whole value), `append`,
`prepend`. Plus the legacy `path` whole-rewrite flow. Pick the smallest one that does the job.

## PREFERRED: `desc_update_mode="edit"` — surgical in-place str-replace (added 2026-06-17, commit c754f18)

A true in-place edit of `n.d` via heaven_base `EditHelper` — no temp file, no full re-ingest. The
`old_str_for_edit_case` substring must match the STORED `n.d` EXACTLY ONCE; the rest of `n.d` (including
any `<CartonObj>` fence) stays byte-identical, and a per-node undo log is written (daily-clearing,
`$HEAVEN_DATA_DIR/carton_undo/<date>/`). A 0-or->1 match fails GRACEFULLY (n.d unchanged).

```
mcp__carton__add_concept(
  concept_name="Concept_Name",
  is_a=[...], part_of=[...], instantiates=[...],   # same values the concept already has
  desc_update_mode="edit",
  old_str_for_edit_case="<exact existing substring of n.d to find>",
  concept="<the new text to replace it with>")
```

## Legacy: `desc_update_mode="path"` — whole-description rewrite via a file
Use only when you're rewriting the WHOLE description: project to a temp file, Edit it, re-ingest.
```
mcp__carton__substrate_projector(target="Concept_Name", substrate={"type":"file","path":"/tmp/carton_edit.md"}, description_only=true)
# ...edit /tmp/carton_edit.md...
mcp__carton__add_concept(concept_name="Concept_Name", is_a=[...], part_of=[...], instantiates=[...], concept="/tmp/carton_edit.md", desc_update_mode="path")
```

## For STRUCTURED data embedded in n.d → use the CartonObj/KV path, NOT a raw edit
If the edit is to a `<CartonObj>` JSON fence inside the description, use `edit_carton_obj` (set/remove a
leaf, refs validated, prose + sibling fences preserved) — see the **`edit-carton-kv`** skill. Do not
hand-str-replace inside a fence.

CoR: "Now I'll edit the CartON concept's n.d. For a targeted change: desc_update_mode='edit' with
old_str_for_edit_case (exact-once). For a fenced KV change: edit_carton_obj (edit-carton-kv). For a whole
rewrite: the path flow."
