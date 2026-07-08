# doc(m): test_carton_kv.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/test_carton_kv.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

The PURE unit suite for `carton_kv.py` (the CartonObj fence parser/normalizer/op-applier) — no neo4j, no MCP, no fixtures. 56 `test_` functions covering the lib's whole public surface, grouped by the lib's build STEPs (1 parser, 2 op-applier, 4 ref/schema validation, 4B remove + carry-forward, 5 ref-expansion). It is one of the four lib-gate test files named by the `edit-carton-kv` dev-flow: all green = the lib layer of the gate.

## How to run

- Standalone: `python3 test_carton_kv.py` — its own runner (`test_carton_kv.py:576-590`) collects `test_*` callables in sorted order, prints `PASS/FAIL` per test + a summary, exits 1 on any failure.
- Or `pytest test_carton_kv.py`.

## What the suite proves (invariants asserted, in file order)

### Ref grammar + span scanner (STEP 1)
- `is_title_underscore` accepts `Title_Underscore_2`-shaped tokens; rejects lowercase-start, trailing/leading/double underscore, JSON literals, bare numbers (`:44-54`).
- `scan_json_span` finds the exact end of a JSON object/array; braces/brackets AND a literal `</CartonObj>` INSIDE a quoted string do not end the span (`:60-86` — the headline crux at `:76-80`); escaped quotes handled; unterminated JSON raises `ValueError` (`:89-94`).

### Converters
- `refs_to_strict_json`: bare Title_Underscore tokens become `{"$ref": name}` as dict-values AND array-elements; quoted look-alikes stay literal strings; `true/false/null/numbers` untouched (`:100-113`).
- `body_from_obj` renders `$ref` dicts back as BARE tokens (no `$ref` text in the body) and round-trips through `parse_fence_body` (`:116-121`); malformed body raises `ValueError` (`:124-129`).

### Attrs + find_carton_objs
- `parse_attrs` handles bare and quoted attribute values (`:135-142`).
- `find_carton_objs`: exact `span`/`body_span` offsets; multiple FLAT fences; deeply-nested JSON; refs as dict-values + array-elements; quoted literal not a ref; a literal `</CartonObj>` inside a string value does not end the fence (the fence closes at the REAL tag — `:196-204`); `is_schema=true` parsed to bool; a MALFORMED fence is skipped and the scanner recovers to find the next good fence (`:214-219`); `get_carton_obj` by name returns None when absent.

### Serialize + minimal-diff splice
- `serialize_carton_obj` round-trips (incl. `schema=` and `is_schema=true` attrs).
- `replace_carton_obj_body` is MINIMAL-DIFF: only the named fence's body changes; surrounding prose and sibling fences stay byte-identical; missing name raises `KeyError` (`:245-273`). Full parse→serialize→parse round-trip on a mixed literal/ref/nested object (`:276-288`).

### STEP 2 — pure op-applier (`apply_carton_obj_op`)
- `split_key_path`: dotted paths, numeric segments → int indices (incl. negative), `""` → `[]` (`:294-299`).
- Against a two-fence description (`_DESC`, `:302-308`): `get` never mutates; `get` of a ref returns the `$ref` dict; `set` of a leaf is minimal-diff (prose + sibling fence + sibling leaves byte-identical); `set` adds new dict keys; `set` of a `$ref` value stores a BARE token (no `$ref` in `raw_body`); list-index `set`; `append` to list; `append` to non-list raises `TypeError`; `remove` of dict key and list index; `key_path=""` `set` replaces the whole body while the sibling fence stays intact; missing fence `KeyError`; unknown op `ValueError`; bad path raises; editing one fence leaves the other byte-identical (`:311-413`).

### STEP 4 — ref extraction + schema validation
- `extract_refs` walks nested dicts/lists in order; returns `[]` when no refs (`:419-425`).
- `deref_for_validation` replaces `$ref` dicts with their bare name strings (`:428-430`).
- `validate_against_schema` (json-schema): good payload → `[]`; type violation reports the offending `path` ("tier") + message; missing required key reported (`:433-457`).

### STEP 4B — remove + the fence-preservation guard core
- `remove_carton_obj` deletes ONLY the named fence (sibling + prose preserved); missing raises `KeyError` (`:463-476`).
- `carry_forward_fences` (the guard that stops a prose re-write from dropping fences): a fence absent from incoming text is APPENDED back verbatim; a fence present-by-name in incoming wins (no double-add); `removed_fences=[name]` makes the removal stick (THE `remove_fence` regression case — `:495-499`); partial carry with multiple fences; no-op when old text had no fences (`:479-511`).

### STEP 5 — ref-expansion (read-time projection)
- Against a fake fetcher graph (`_GRAPH`, `:518-525`): depth 0 = raw text unchanged; depth 1 expands one hop inline (`Name⟨…⟩` with description + relationships) without recursing into the target's own refs; depth 2 recurses the second hop; an A↔B cycle terminates with a `cycle` marker at depth 5; an unresolvable ref renders `Name⟨…unresolved⟩`; prose with no fence is untouched even if it contains ref-shaped words (`:535-570`).

## Data contracts

- `REF = lambda name: {"$ref": name}` (`:38`) — the strict-JSON ref representation the lib normalizes to.
- The suite encodes the WIRE contract: stored fence bodies use BARE refs; parsed objects use `$ref` dicts; expansion is render-only.

## Deps

- `carton_kv` (the 18 imported functions, `:17-36`); stdlib `json`. Nothing else — provable purity of the lib layer.

## Defects / dead code

- `New_Ref_obj()` is defined AFTER its use site (`:253` uses it, defined `:264`) — works because the test body executes at call time, but reads oddly.
- The standalone runner counts ANY callable named `test_*` in globals; a helper accidentally named `test_…` would be executed. Currently none.
