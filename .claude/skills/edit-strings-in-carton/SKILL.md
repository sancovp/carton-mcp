---
name: edit-strings-in-carton
description: "WHAT: carton's description write modes: append, prepend, replace, edit, path. WHEN: editing a concept description in place, or an edit did not land."
---

# edit-strings-in-carton

**In full:** WHAT: carton's full string write/edit/replace tool system — the five desc_update_mode modes on add_concept (append, prepend, replace, edit = surgical exactly-once str-replace with an undo log, path = ingest a file's content as the description), with the measured caveats. WHEN: editing a concept's description in place instead of rewriting it; fixing one wrong sentence in a big n.d; absorbing a file from disk into the graph; an edit silently did not land; needing to undo a description edit; deciding between append, replace, and edit.

**Measured live 2026-08-09 (probe `Str_Edit_Probe_2026_08_09`) after reading the daemon's
`_apply_carton_kv_edits` in full. Carton manipulates strings in neo4j directly — the description
is an editable surface with Write/Edit/str-replace semantics, not an append-only blob.**

## THE FIVE MODES — all on `add_concept(desc_update_mode=...)`

| mode | what it does | proven |
|---|---|---|
| `append` (default) | merge-append to existing `n.d`; DEDUPED — if `n.d` already CONTAINS the new text, it is skipped unchanged | [daily use; the dedup is the split-content rule's own mechanism] |
| `prepend` | same, at the front | [read from code] |
| `replace` | the new text REPLACES `n.d` wholesale | [proven via path mode, which becomes a replace] |
| `edit` | SURGICAL str-replace WITHIN `n.d`: `old_str_for_edit_case` found EXACTLY ONCE and replaced by the `concept` arg; the rest byte-identical | [proven: `bravo` → `BRAVO-SURGICALLY-EDITED`, remainder untouched] |
| `path` | the `concept` arg is a FILE PATH; the file's content is read and becomes the description (internally a replace) | [proven: file content landed verbatim] — **this is the file→graph ABSORBER primitive** (issue 141's ingestion half) |

## EDIT MODE — the mechanism and the three measured caveats

The daemon (`_apply_carton_kv_edits`): fetches the CURRENT `n.d` → writes the pre-edit state to
an UNDO LOG → runs heaven_base's `EditHelper` (exactly-once enforced) → on success the row
becomes a replace carrying the edited whole (so the fence-preservation guard is satisfied); on
ANY failure (no existing `n.d`, 0 or >1 match, helper error) the row flips to `skip` — **`n.d` is
left untouched and the outcome is PERSISTED on the node** (fixed 2026-08-09, issue 142): a
failure lands as the `kv_edit_error` property (+ `kv_edit_error_at`), which `get_concept` and
Cypher both surface [proven live], and a later SUCCESSFUL edit clears it. The add_concept
response itself still looks normal (the edit applies at queue drain) — check `kv_edit_error`
or read `n.d` back to confirm.

1. **Undo files are attempt-timestamped** (fixed 2026-08-09, issue 142):
   `$HEAVEN_DATA_DIR/carton_undo/<YYYY-MM-DD>/<node>.<HHMMSS_micros>.json`, one per attempt,
   never clobbered [proven live: three attempts, three files]. (Before the fix a failed
   attempt overwrote the successful edit's undo from the same day.)
2. **`old_str` must match the CURRENT STORED text, and the autolinker mutates it** [measured]:
   between two edits the linker rewrote the stored `n.d` with wiki-link syntax
   (`[edit](../Edit/Edit_itself.md)`), so an `old_str` copied from what you WROTE may no longer
   match what is STORED. **MITIGATED 2026-08-09 (Isaac's ruling, issue 142): the linker now
   DEBOUNCES** — it only links nodes untouched for 30 minutes (`CARTON_LINKER_DEBOUNCE_S`,
   default 1800), and every write/edit restarts the window, so an actively-edited node is never
   linked mid-session [proven live: a just-touched node stayed unlinked through linker cycles].
   The read-before-compose discipline still applies to nodes you have NOT touched in 30+ minutes
   — those may carry link syntax.
3. **Exactly-once is a feature**: a 0-match or multi-match refuses rather than guessing — same
   contract as the Edit tool on files. Make `old_str` unique by widening it.

## THE PATH-MODE ABSORBER

`add_concept(concept="/abs/path/to/file", desc_update_mode="path")` ingests the file's content
verbatim as the concept's description. Nonexistent path returns an ERROR string (no write). This
is the ingestion half of file→graph absorption; what it does NOT do: version the prior `n.d`
(path is a replace — no undo log; snapshot first if the prior description matters), split
content off, or atomize. Compose: `path` → `split_content_concept` (if the ingested blob should
be a content node) → `atomize-a-seed` (decompose it) → the modelling ladder.

## ALSO ON THE SURFACE, UNMEASURED

A STASH mechanism exists (`clear_stash` discards a stashed payload for the concept before
processing) — stash semantics not yet probed; do not rely on them from this skill.

## Cross-refs

`carton-write-channels` (which surface sees the description you just edited) ·
`atomize-a-seed` (what to do after a path-mode ingest) · `model-anything-in-carton` (the ladder)
· issue 141 (projector content-source + version-before-overwrite — path mode is its ingestion
half; the undo log is the edit-lane sibling of the `_v1` sinking backup).
