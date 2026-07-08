# doc(m): carton_kv.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/carton_kv.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

`carton_kv` is the pure library layer (onion position: innermost) of the CartON KV subsystem. It implements the complete parser, normalizer, editor, and validator for `<CartonObj ...>{JSON-with-bare-refs}</CartonObj>` fences embedded in a concept's `n.d` description field. The module uses only stdlib (`json`, `re`, `dataclasses`, `typing`) — no neo4j, no MCP, no I/O — making it unit-testable in complete isolation. Its functions are the primitives that every higher layer wraps: the neo4j-bound wrappers in `carton_utils.py`, the MCP tool dispatch in `server_fastmcp.py`, the concept linker in `add_concept_tool.py`, and the fence-preservation guard in `observation_worker_daemon.py`. The module docstring (`:32-34`) notes it "is NOT yet wired into any write/read path or MCP tool" — that note is stale; all four consumers above do import from it. The pure-lib / no-neo4j-at-module-level claim remains accurate.

## Surface (1:1 — every public thing, in file order)

- **`_TITLE_UNDERSCORE_RE`** — `carton_kv.py:48`
  - Compiled regex `^[A-Z][A-Za-z0-9]*(_[A-Za-z0-9]+)*$`. Matches a bare carton concept-ref token (Title_Underscore form). Single uppercase words match; trailing or doubled underscores do not.
  - Used by `is_title_underscore` and `refs_to_strict_json`.

- **`_OPEN_TAG_RE`** — `carton_kv.py:52`
  - Compiled regex matching `<CartonObj <attrs>>` open tags (attrs contain no `>`). Used by `find_carton_objs` to locate fence start positions.

- **`_CLOSE_TAG`** — `carton_kv.py:53`
  - String constant `"</CartonObj>"`. Used as a `startswith` literal check inside `find_carton_objs`.

- **`_ATTR_RE`** — `carton_kv.py:56`
  - Compiled regex matching `key=value`, `key="value"`, or `key='value'` attribute pairs in the open tag. Used by `parse_attrs`.

- **`is_title_underscore(token: str) -> bool`** — `carton_kv.py:59`
  - Returns True iff `token` matches `_TITLE_UNDERSCORE_RE` (i.e., is a bare carton concept ref).
  - Called by `refs_to_strict_json` (`:155`) to decide whether to wrap a candidate token as `{"$ref": "Name"}`. Also called directly by `carton_utils.py:207` in `register_kv_schemas` to check schema attribute values.

- **`CartonObjFence`** (dataclass) — `carton_kv.py:67-77`
  - Record for one parsed fence. Fields:
    - `name: str` — the `name=` attribute value.
    - `obj: Any` — parsed python structure; refs as `{"$ref": "Name"}` dicts.
    - `schema: Optional[str]` — `schema=` attribute value or None.
    - `is_schema: bool` — True if `is_schema=true` present in attrs.
    - `attrs: Dict[str, str]` — all raw parsed attributes.
    - `span: Tuple[int, int]` — `[start, end)` of the full fence in the source string.
    - `body_span: Tuple[int, int]` — `[start, end)` of just the JSON body in source.
    - `raw_body: str` — original JSON-with-bare-refs body text as found in source.
  - `span` and `body_span` are the byte-offset anchors that make the splice operations in `replace_carton_obj_body` and `remove_carton_obj` byte-identical on all surrounding text.

- **`scan_json_span(s: str, start: int) -> int`** — `carton_kv.py:83`
  - Given `s[start]` is `{` or `[`, returns the index just after the matching close brace/bracket. Tracks string context (handles `\\` escapes) so braces/brackets/a literal `</CartonObj>` inside a quoted string never affect depth. Raises `ValueError` if `start` is not `{`/`[` or the body is unterminated.
  - Load-bearing invariant: a literal `</CartonObj>` or stray `{}` inside a JSON string value is invisible to the scanner. This is why the body finder is a span scanner and not a regex `.*?`.
  - Called by `find_carton_objs` (`:230`).

- **`refs_to_strict_json(raw_body: str) -> str`** — `carton_kv.py:122`
  - Converts a JSON-with-bare-refs body string to strict JSON by replacing each bare Title_Underscore ref (outside any JSON string) with `{"$ref": "Name"}`. String context tracked identically to `scan_json_span`. Lowercase JSON literals (`true`/`false`/`null`) and numbers pass through unchanged. Non-conforming unquoted tokens pass through as-is (cause `json.loads` to fail with a useful error).
  - Called by `parse_fence_body` (`:183`).

- **`body_from_obj(obj: Any) -> str`** — `carton_kv.py:166`
  - Serializes a python object back to a JSON-with-bare-refs body string. A `{"$ref": "Name"}` dict renders as the bare token `Name`; everything else is strict JSON via `json.dumps`. Whitespace may differ from `raw_body` (structure round-trips, whitespace does not).
  - Called by `replace_carton_obj_body` (`:302`), `serialize_carton_obj` (`:289`), and `apply_carton_obj_op` (via `replace_carton_obj_body` at `:518`).

- **`parse_fence_body(raw_body: str) -> Any`** — `carton_kv.py:180`
  - Parses a JSON-with-bare-refs body into a python object (refs as `{"$ref": "Name"}`). Calls `refs_to_strict_json` then `json.loads`. Raises `ValueError` with context on malformed input.
  - Called by `find_carton_objs` (`:239`).

- **`parse_attrs(attr_str: str) -> Dict[str, str]`** — `carton_kv.py:193`
  - Parses the open-tag attribute string into a dict. Values may be bare or single/double-quoted. Called by `find_carton_objs` (`:221`).

- **`find_carton_objs(text: str, strict: bool = False) -> List[CartonObjFence]`** — `carton_kv.py:208`
  - Finds every well-formed `<CartonObj ...>...</CartonObj>` fence in `text`, returns parsed `CartonObjFence` records in source order. Default (`strict=False`): malformed fences are skipped so a half-typed fence never crashes a read. `strict=True` raises on the first malformed fence. Requires `name=` attr; skips fences without it in non-strict mode.
  - Central routine — called by `get_carton_obj`, `carry_forward_fences`, `expand_refs_in_description`, `apply_carton_obj_op` (via `get_carton_obj`), and externally by `carton_utils.py:189`, `add_concept_tool.py:400`, `observation_worker_daemon.py:236`.

- **`get_carton_obj(text: str, name: str, strict: bool = False) -> Optional[CartonObjFence]`** — `carton_kv.py:259`
  - Returns the first fence named `name` from `find_carton_objs`, or None if absent. `strict` passes through.
  - Called by `replace_carton_obj_body` (`:298`), `remove_carton_obj` (`:309`), `apply_carton_obj_op` (`:477`), and `carton_utils.py:233`.

- **`serialize_carton_obj(name, obj, schema, is_schema, extra_attrs) -> str`** — `carton_kv.py:270`
  - Builds a complete `<CartonObj ...>{body}</CartonObj>` string from parts. Emits `name=`, then optionally `schema=`, `is_schema=true`, then any extra attrs (skipping `name`/`schema`/`is_schema` keys to avoid duplication). Uses `body_from_obj` for the body.
  - UNVERIFIED: no external call site found in the consumer grep; likely used in test code or planned for STEP 2.

- **`replace_carton_obj_body(text: str, name: str, new_obj: Any, strict: bool = True) -> str`** — `carton_kv.py:292`
  - Splices a new body for the fence named `name` back into `text` by original `body_span` offsets. Only `text[body_span[0]:body_span[1]]` is replaced — open tag, close tag, all prose, and every sibling fence remain byte-identical. Raises `KeyError` if no such fence. Minimal-diff primitive that `edit_carton_obj` in `carton_utils.py` (STEP 2) builds on.
  - Called by `apply_carton_obj_op` (`:518`) and indirectly by `carton_utils.py:107`.

- **`remove_carton_obj(text: str, name: str) -> str`** — `carton_kv.py:305`
  - Removes the entire `<CartonObj name=name>...</CartonObj>` fence using `fence.span` offsets. Collapses 3+ consecutive newlines to `\n\n` via `re.sub(r"\n{3,}", "\n\n", result)`. Raises `KeyError` if fence absent.
  - NOTE: `remove_fence` (whole-fence deletion) is NOT one of `_VALID_OPS`. It is handled as a separate code path in `carton_utils.py:100` by calling this function directly when `op == "remove_fence"`.
  - Called by `carton_utils.py:100`.

- **`carry_forward_fences(old_nd: str, incoming_desc: str, removed_fences=()) -> str`** — `carton_kv.py:318`
  - Fence-preservation guard (pure core). Appends verbatim every `CartonObj` fence present in `old_nd` by name but absent in `incoming_desc`, EXCEPT names in `removed_fences` (explicit deletion). Returns `incoming_desc` unchanged if nothing needs carrying. Separates carried fences with `\n\n`.
  - Prevents an ordinary prose `replace` op from silently deleting fences. `edit_carton_obj` is unaffected because its replacement already contains the edited fence by name.
  - Called by `observation_worker_daemon.py:236`.

- **`_expand_obj(obj, fetch_fn, depth, visited) -> Any`** — `carton_kv.py:349`
  - Private helper. Walks a parsed body; replaces each `{"$ref": name}` with an expansion node `{"$ref": name, "description": ..., "relationships": [...]}` from `fetch_fn(name)`, recursing at `depth-1`. Cycle-guarded via `visited`: already-visited name → `{"$ref": name, "$cycle": True}`; failed fetch → `{"$ref": name, "$unresolved": True}`. `fetch_fn` injected — fully testable without neo4j.
  - Called by `expand_refs_in_description` (`:411`).

- **`_render_expanded(obj: Any) -> str`** — `carton_kv.py:374`
  - Private helper. Renders an expanded object to human-readable text: expanded ref shows as `Name⟨<description> ‖ <rel target; ...>⟩`; cycle as `Name⟨…cycle⟩`; unresolved as `Name⟨…unresolved⟩`; depth-exhausted bare ref as plain `Name`.
  - Called by `expand_refs_in_description` (`:411`).

- **`expand_refs_in_description(description: str, fetch_fn, depth: int, _visited=None) -> str`** — `carton_kv.py:398`
  - Read-time ref-expansion projection. For each `CartonObj` fence in `description`, replaces its body with a rendered expansion where every bare ref is resolved to the referenced concept's description + relationships, recursive to `depth`, cycle-guarded. Processes fences right-to-left (sorted by `span[0]` descending at `:410`) so earlier body_span offsets remain valid after later splices. `depth <= 0` or empty description returns unchanged. RENDER-ONLY — does not mutate stored data.
  - Called by `carton_utils.py:283` (the graph-bound wrapper). Also called recursively by `_expand_obj` (`:365`) for nested description expansion.

- **`_VALID_OPS`** — `carton_kv.py:424`
  - Tuple constant `("set", "append", "remove", "get")`. The four ops recognized by `apply_carton_obj_op`. `remove_fence` (whole-fence deletion) is NOT in this set; handled separately in `carton_utils.py:100`.

- **`split_key_path(key_path: str) -> List[Any]`** — `carton_kv.py:427`
  - Parses a dotted/indexed path string (`"a.b.0.c"`) into a list of segments. Integer segments (including negative, via `s.lstrip("-").isdigit()`) become `int`; everything else stays `str`. Empty or None returns `[]` (the root).
  - Called by `apply_carton_obj_op` (`:482`).

- **`_descend(obj: Any, segs: List[Any]) -> Any`** — `carton_kv.py:442`
  - Private helper. Walks `obj` along `segs` via natural `obj[s]` indexing. Raises `KeyError`, `IndexError`, or `TypeError` on a bad path. Called by `apply_carton_obj_op` for `get` (`:485`), `set` (`:491`), `append` (`:504`), and `remove` (`:513`).

- **`apply_carton_obj_op(description, kvobj_name, key_path, op, value) -> Tuple[str, Any]`** — `carton_kv.py:451`
  - Pure core of `edit_carton_obj`. Returns `(new_description, result_value)`. Op semantics:
    - `get`: returns value at `key_path`; description unchanged.
    - `set`: sets value at `key_path`. Creates the FINAL key on a dict if absent; intermediate missing keys/indices are an error (no silent auto-vivification). `key_path=''` replaces the whole body with `value`.
    - `append`: `key_path` must point at a list; appends `value`; returns the new list.
    - `remove`: deletes the key/index at `key_path` (requires non-empty `key_path`); returns None.
  - `value` is a python object; a ref is `{"$ref": "Name"}` so it round-trips to a bare token. Uses `copy.deepcopy` (lazy import at `:472`) to avoid mutating the parsed object. Raises `ValueError` on unknown op, `KeyError` if fence absent, `KeyError`/`IndexError`/`TypeError` on bad path.
  - Called by `carton_utils.py:107`.

- **`extract_refs(obj: Any) -> List[str]`** — `carton_kv.py:527`
  - Returns every bare-ref name (`{"$ref": "Name"}`) in a parsed body object, in document order, duplicates kept. Uses a recursive `_walk` inner function.
  - Called by `carton_utils.py:239` in `validate_carton_obj` to enumerate refs for existence-checking.

- **`deref_for_validation(obj: Any) -> Any`** — `carton_kv.py:547`
  - Replaces each `{"$ref": "Name"}` with the bare string `"Name"` so json-schema validation sees a ref slot as a plain string. Bridge between the internal `$ref` representation and `jsonschema` validators.
  - Called by `validate_against_schema` (`:566`).

- **`validate_against_schema(body_obj: Any, schema_obj: dict) -> List[dict]`** — `carton_kv.py:559`
  - Validates a parsed `CartonObj` body against a json-schema dict. Calls `deref_for_validation` first, then runs `jsonschema.Draft7Validator(schema_obj).iter_errors(derefed)`, sorted by `err.path`. Returns `[]` if valid, else a list of `{"path": "<dotted key path or (root)>", "message": "<jsonschema error>"}` dicts. Lazily imports `jsonschema` (`:564`) so the module is importable without jsonschema installed.
  - Called by `carton_utils.py:253` in `validate_carton_obj`.

## Dependencies

**stdlib (module-level):**
- `json` — serialization/deserialization throughout.
- `re` — regex compilation (`_TITLE_UNDERSCORE_RE`, `_OPEN_TAG_RE`, `_ATTR_RE`); `re.sub` in `remove_carton_obj`.
- `dataclasses` — `@dataclass`, `field` for `CartonObjFence`.
- `typing` — `Any`, `Dict`, `List`, `Optional`, `Tuple`.

**lazy (imported inside functions, not at module level):**
- `copy` (stdlib) — `copy.deepcopy` inside `apply_carton_obj_op:472`.
- `jsonschema` (third-party) — inside `validate_against_schema:564` only; keeps the module importable without jsonschema.

**Consumers (who imports this module):**
- `carton_utils.py` — neo4j-bound wrapper layer; lazy imports at `:76, 121, 186, 228, 267`. Calls: `remove_carton_obj`, `apply_carton_obj_op`, `find_carton_objs`, `is_title_underscore`, `get_carton_obj`, `extract_refs`, `validate_against_schema`, `expand_refs_in_description`.
- `add_concept_tool.py` — concept linker; lazy import of `find_carton_objs` at `:400`. Degrades gracefully on import error (`:403`).
- `observation_worker_daemon.py` — daemon; lazy import of `carry_forward_fences` at `:236`.
- `server_fastmcp.py` — MCP layer; imports `carton_kv as _ckv` at `:436`.
- `test_carton_kv.py` — unit test suite; direct imports of all public symbols.
- `test_carton_kv_schema.py` — schema-focused tests (FakeGraph stub, no real neo4j).
- `test_edit_carton_obj.py` — integration tests for op logic.

## Notes

- **Onion position is load-bearing.** Zero non-stdlib imports at module level. Any edit introducing a neo4j, MCP, or I/O import at module level breaks the unit-testability guarantee and the `validate_against_schema` lazy-import guarantee.

- **`remove_fence` vs `remove` op distinction is a sharp edge.** `remove_carton_obj` (whole-fence deletion) is NOT one of `_VALID_OPS`. The `"remove"` op in `apply_carton_obj_op` deletes a key/index WITHIN a fence body. Whole-fence deletion goes through `carton_utils.py:100` calling `remove_carton_obj` directly when `op == "remove_fence"`. Conflating these two causes silent data errors.

- **Byte-identical splice invariant.** `replace_carton_obj_body` and `remove_carton_obj` operate solely on `body_span` or `span` offsets recorded at parse time. All prose and sibling fences outside those spans are guaranteed byte-identical in output. Any code that iterates fences and splices the source string must operate right-to-left (as `expand_refs_in_description` does at `:410`) or reparse after each splice.

- **`carry_forward_fences` `removed_fences` parameter default is `()`.** A caller that intentionally deletes a fence MUST pass the fence name in `removed_fences`; omitting it causes the guard to re-append the fence, silently undoing the deletion.

- **`set` op does not auto-vivify intermediate keys.** Intentional per docstring (`:464`). Only the final key on a dict is created if absent; missing intermediate path segments raise.

- **Module docstring IS-vs-VISION note at `:32-34` is stale.** States "NOT yet wired into any write/read path or MCP tool." As of this derivation it is wired via all four consumers listed above. The pure-lib claim remains accurate.
