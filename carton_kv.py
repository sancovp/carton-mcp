"""
carton_kv — CartON KV subsystem (LIBRARY layer, onion arch).

STEP 1: the parser/normalizer for <CartonObj ...> fences embedded in a concept's
description (n.d). PURE — stdlib only, no neo4j / no MCP / no I/O — so it is unit-
testable standalone and every higher layer (edit_carton_obj, schema registry,
ref-expansion, the MCP tools) wraps THESE functions.

THE SYNTAX (Locked_Spec):
    <CartonObj name=X schema=Some_Schema_Concept>{ JSON-with-bare-refs }</CartonObj>
- Multiple FLAT (non-nested) fences per description; depth lives in the JSON, not
  nested fences.
- REFS (python-dict-style): a BARE Title_Underscore token as a VALUE = a carton
  concept ref ("variable"); a QUOTED string = literal data. Quoting disambiguates —
  no auto-link guessing.
- Optional attrs: schema=<Concept> (which schema validates this fence),
  is_schema=true (this fence IS a json-schema definition; drives auto-typing later).

THE NORMALIZER (this module):
- FIND each fence's JSON body by a STRING-CONTEXT-AWARE SPAN SCAN (brace/bracket
  depth, strings skipped) — NOT a regex `.*?`. So a literal </CartonObj> (or a stray
  { } ) INSIDE a quoted string value is harmless: it is inside a JSON string, so the
  scanner ignores it and the body ends at the matching top-level close brace; the
  real </CartonObj> is whatever follows.
- Convert bare Title_Underscore refs  <->  {"$ref": "Name"}  <->  strict JSON.
  (Outside a JSON string, any unquoted uppercase-leading identifier is a value ref —
  keys are always quoted, and JSON literals true/false/null are lowercase.)
- Parse to a python object (refs represented as {"$ref": "Name"} dicts), re-serialize
  back to bare-ref body text, and splice a replacement body back by ORIGINAL offsets
  so prose and sibling fences stay byte-identical (the basis for edit_carton_obj).

IS-vs-VISION: everything here IS code in this file, unit-tested at the library level
(test_carton_kv.py). It is NOT yet wired into any write/read path or MCP tool — that
is STEP 2+.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ----------------------------------------------------------------------------- #
# Ref token grammar
# ----------------------------------------------------------------------------- #
# A Title_Underscore concept ref: uppercase-letter start, then alnum runs joined by
# single underscores. Single words (Reality, Concept) match too. Trailing/double
# underscores do NOT match (each segment must be non-empty alnum).
_TITLE_UNDERSCORE_RE = re.compile(r"^[A-Z][A-Za-z0-9]*(_[A-Za-z0-9]+)*$")

# Opening tag: <CartonObj <attrs>> — attrs contain no '>' . We do NOT use a regex to
# find the BODY (that is the span scanner's job); the open tag itself is safe to match.
_OPEN_TAG_RE = re.compile(r"<CartonObj\b([^>]*)>")
_CLOSE_TAG = "</CartonObj>"

# Attribute pair:  key=value  |  key="value"  |  key='value'
_ATTR_RE = re.compile(r"""(\w+)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))""")


def is_title_underscore(token: str) -> bool:
    """True iff token is a bare carton concept ref (Title_Underscore)."""
    return bool(_TITLE_UNDERSCORE_RE.match(token))


# ----------------------------------------------------------------------------- #
# Parsed-fence record
# ----------------------------------------------------------------------------- #
@dataclass
class CartonObjFence:
    """One parsed <CartonObj ...>...</CartonObj> fence found in a description string."""
    name: str
    obj: Any                       # python structure; refs as {"$ref": "Name"} dicts
    schema: Optional[str] = None   # schema=<Concept> attr, or None
    is_schema: bool = False        # is_schema=true attr
    attrs: Dict[str, str] = field(default_factory=dict)  # ALL parsed attrs (raw)
    span: Tuple[int, int] = (0, 0)        # full fence span [start, end) in source
    body_span: Tuple[int, int] = (0, 0)   # JSON body span [start, end) in source
    raw_body: str = ""                    # original JSON-with-bare-refs body text


# ----------------------------------------------------------------------------- #
# Span scanner — find the end of a JSON value (string-context aware)
# ----------------------------------------------------------------------------- #
def scan_json_span(s: str, start: int) -> int:
    """Given s[start] is the opening '{' or '[' of a JSON-with-bare-refs value, return
    the index JUST AFTER the matching close. Strings (with \\ escapes) are skipped so
    braces / brackets / a literal </CartonObj> inside a string never affect depth.
    Bare refs are plain identifiers (no braces) so they are irrelevant to depth.
    Raises ValueError if unterminated or if start is not a container.
    """
    n = len(s)
    if start >= n or s[start] not in "{[":
        raise ValueError(f"CartonObj body must start with {{ or [ at offset {start}")
    depth = 0
    i = start
    in_str = False
    esc = False
    while i < n:
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{" or c == "[":
                depth += 1
            elif c == "}" or c == "]":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    raise ValueError("unterminated CartonObj JSON body")


# ----------------------------------------------------------------------------- #
# Converters: bare-ref body  <->  strict JSON  <->  python obj  <->  bare-ref body
# ----------------------------------------------------------------------------- #
def refs_to_strict_json(raw_body: str) -> str:
    """Convert a JSON-with-bare-refs body string into STRICT JSON by replacing each
    bare Title_Underscore ref (outside any JSON string) with {"$ref": "Name"}.
    String context is tracked so a quoted "Title_Like_This" literal is untouched.
    Lowercase JSON literals (true/false/null) and numbers pass through unchanged.
    """
    out: List[str] = []
    i, n = 0, len(raw_body)
    in_str = False
    esc = False
    while i < n:
        c = raw_body[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c.isalpha() and c.isupper():
            # candidate bare ref: consume the identifier run
            j = i
            while j < n and (raw_body[j].isalnum() or raw_body[j] == "_"):
                j += 1
            token = raw_body[i:j]
            if is_title_underscore(token):
                out.append('{"$ref": ' + json.dumps(token) + "}")
            else:
                out.append(token)  # leave non-conforming token; json.loads will flag it
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def body_from_obj(obj: Any) -> str:
    """Serialize a python object back into a JSON-with-bare-refs BODY string: a
    {"$ref": "Name"} dict renders as the bare token `Name`; everything else is strict
    JSON. Inverse of parse_fence_body at the OBJECT level (whitespace may differ)."""
    if isinstance(obj, dict):
        if len(obj) == 1 and "$ref" in obj and isinstance(obj["$ref"], str):
            return obj["$ref"]  # bare ref
        parts = [json.dumps(k) + ": " + body_from_obj(v) for k, v in obj.items()]
        return "{" + ", ".join(parts) + "}"
    if isinstance(obj, list):
        return "[" + ", ".join(body_from_obj(x) for x in obj) + "]"
    return json.dumps(obj)


def parse_fence_body(raw_body: str) -> Any:
    """Parse a JSON-with-bare-refs body into a python object (refs as {"$ref": "Name"}).
    Raises ValueError with a useful message on malformed bodies."""
    strict = refs_to_strict_json(raw_body)
    try:
        return json.loads(strict)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid CartonObj body: {e} (strict form: {strict[:200]})") from e


# ----------------------------------------------------------------------------- #
# Attribute parsing
# ----------------------------------------------------------------------------- #
def parse_attrs(attr_str: str) -> Dict[str, str]:
    """Parse the open-tag attribute string into a dict. Values may be bare or quoted."""
    attrs: Dict[str, str] = {}
    for m in _ATTR_RE.finditer(attr_str):
        key = m.group(1)
        val = m.group(2) if m.group(2) is not None else (
            m.group(3) if m.group(3) is not None else m.group(4)
        )
        attrs[key] = val
    return attrs


# ----------------------------------------------------------------------------- #
# Find all fences in a description string
# ----------------------------------------------------------------------------- #
def find_carton_objs(text: str, strict: bool = False) -> List[CartonObjFence]:
    """Find every well-formed <CartonObj ...>...</CartonObj> fence in `text` and return
    parsed CartonObjFence records (in source order). Malformed fences are SKIPPED by
    default (strict=False) so a half-typed fence in prose never crashes a read; set
    strict=True to raise on the first malformed fence instead.
    """
    results: List[CartonObjFence] = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _OPEN_TAG_RE.search(text, pos)
        if not m:
            break
        attrs = parse_attrs(m.group(1))
        body_start_search = m.end()
        try:
            if "name" not in attrs:
                raise ValueError("CartonObj fence missing required name= attribute")
            # skip whitespace to the JSON value
            k = body_start_search
            while k < n and text[k].isspace():
                k += 1
            body_end = scan_json_span(text, k)        # raises if not a container / unterminated
            raw_body = text[k:body_end]
            # expect the close tag after optional whitespace
            j = body_end
            while j < n and text[j].isspace():
                j += 1
            if not text.startswith(_CLOSE_TAG, j):
                raise ValueError("CartonObj fence not closed by </CartonObj>")
            fence_end = j + len(_CLOSE_TAG)
            obj = parse_fence_body(raw_body)
            results.append(CartonObjFence(
                name=attrs["name"],
                obj=obj,
                schema=attrs.get("schema"),
                is_schema=str(attrs.get("is_schema", "")).lower() == "true",
                attrs=attrs,
                span=(m.start(), fence_end),
                body_span=(k, body_end),
                raw_body=raw_body,
            ))
            pos = fence_end
        except ValueError:
            if strict:
                raise
            # malformed: advance past this open tag and keep scanning
            pos = m.end()
    return results


def get_carton_obj(text: str, name: str, strict: bool = False) -> Optional[CartonObjFence]:
    """Return the FIRST fence named `name`, or None if absent."""
    for f in find_carton_objs(text, strict=strict):
        if f.name == name:
            return f
    return None


# ----------------------------------------------------------------------------- #
# Serialize / splice (the round-trip + minimal-diff write basis for STEP 2)
# ----------------------------------------------------------------------------- #
def serialize_carton_obj(
    name: str,
    obj: Any,
    schema: Optional[str] = None,
    is_schema: bool = False,
    extra_attrs: Optional[Dict[str, str]] = None,
) -> str:
    """Build a complete <CartonObj ...>{body}</CartonObj> fence string."""
    parts = [f"name={name}"]
    if schema:
        parts.append(f"schema={schema}")
    if is_schema:
        parts.append("is_schema=true")
    if extra_attrs:
        for k, v in extra_attrs.items():
            if k in ("name", "schema", "is_schema"):
                continue
            parts.append(f"{k}={v}")
    attr_str = " ".join(parts)
    return f"<CartonObj {attr_str}>{body_from_obj(obj)}</CartonObj>"


def replace_carton_obj_body(text: str, name: str, new_obj: Any, strict: bool = True) -> str:
    """Splice a NEW body for the fence named `name` back into `text` BY ORIGINAL OFFSETS.
    Only text[body_span[0]:body_span[1]] is replaced — the open tag, the close tag, all
    prose, and every sibling fence remain BYTE-IDENTICAL. Raises KeyError if no such
    fence. This is the minimal-diff primitive edit_carton_obj (STEP 2) builds on.
    """
    fence = get_carton_obj(text, name, strict=strict)
    if fence is None:
        raise KeyError(f"no CartonObj named {name!r} in text")
    bs, be = fence.body_span
    return text[:bs] + body_from_obj(new_obj) + text[be:]


def remove_carton_obj(text: str, name: str) -> str:
    """Remove the ENTIRE <CartonObj name=name>...</CartonObj> fence (open tag + body + close)
    from text, collapsing any blank line the removal would leave. Raises KeyError if absent.
    This is how a whole fence is intentionally deleted (the remove_fence op)."""
    fence = get_carton_obj(text, name, strict=True)
    if fence is None:
        raise KeyError(f"no CartonObj named {name!r} in text")
    s, e = fence.span
    result = text[:s] + text[e:]
    # collapse 3+ newlines (left by removing a fence on its own line) to a clean paragraph break
    return re.sub(r"\n{3,}", "\n\n", result)


def carry_forward_fences(old_nd: str, incoming_desc: str, removed_fences=()) -> str:
    """FENCE-PRESERVATION GUARD core (PURE). Given the CURRENT stored description (old_nd) and a
    REPLACE's incoming description, append VERBATIM every CartonObj fence that exists in old_nd
    but is ABSENT BY NAME from incoming_desc — EXCEPT any name in removed_fences (explicit
    deletion). Returns incoming_desc unchanged if nothing needs carrying. This stops an ordinary
    prose re-derivation (replace) from silently deleting a fence; edit_carton_obj is unaffected
    because its replace-desc already contains the edited fence by name (so it is not carried)."""
    removed = set(removed_fences or ())
    old_fences = find_carton_objs(old_nd or "")
    if not old_fences:
        return incoming_desc
    incoming_names = {f.name for f in find_carton_objs(incoming_desc or "")}
    carried = [
        (old_nd[f.span[0]:f.span[1]])
        for f in old_fences
        if f.name not in incoming_names and f.name not in removed
    ]
    if not carried:
        return incoming_desc
    sep = "" if incoming_desc.endswith("\n") else "\n\n"
    return incoming_desc + sep + "\n\n".join(carried)


# ----------------------------------------------------------------------------- #
# STEP 5 (PURE core) — ref-expansion as a READ-TIME projection
# A render-only expansion: each bare ref inside a CartonObj is replaced (in the RETURNED text)
# with the referenced concept's description + relationships, recursive to depth N, cycle-guarded.
# The STORED description is NEVER mutated (the caller passes a copy of the read text). fetch_fn is
# injected (fetch_fn(name) -> {"description": str, "relationships": [(rel, target), ...]} or None)
# so this is fully unit-testable without neo4j.
# ----------------------------------------------------------------------------- #
def _expand_obj(obj: Any, fetch_fn, depth: int, visited: set) -> Any:
    """Walk a parsed body; replace each {"$ref": name} with an expansion node carrying the
    referenced concept's description + relationships (recursing into its description at depth-1).
    Cycle-guarded via `visited`."""
    if isinstance(obj, dict):
        if len(obj) == 1 and "$ref" in obj and isinstance(obj["$ref"], str):
            name = obj["$ref"]
            if name in visited:
                return {"$ref": name, "$cycle": True}
            data = fetch_fn(name)
            if not data:
                return {"$ref": name, "$unresolved": True}
            node = {"$ref": name,
                    "description": data.get("description", ""),
                    "relationships": data.get("relationships", [])}
            if depth - 1 > 0:
                node["description"] = expand_refs_in_description(
                    node["description"], fetch_fn, depth - 1, visited | {name})
            return node
        return {k: _expand_obj(v, fetch_fn, depth, visited) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_obj(x, fetch_fn, depth, visited) for x in obj]
    return obj


def _render_expanded(obj: Any) -> str:
    """Render an expanded object to readable text: an expanded ref shows as
    `Name⟨<description> ‖ <rel target; ...>⟩`; an unexpanded/cycle/unresolved ref shows compactly."""
    if isinstance(obj, dict):
        if "$ref" in obj:
            name = obj["$ref"]
            if len(obj) == 1:
                return name                                  # unexpanded bare ref (depth exhausted)
            if obj.get("$cycle"):
                return f"{name}⟨…cycle⟩"
            if obj.get("$unresolved"):
                return f"{name}⟨…unresolved⟩"
            rels = obj.get("relationships", []) or []
            rel_str = "; ".join(f"{r} {t}" for r, t in rels)
            desc = obj.get("description", "")
            inner = desc + (f" ‖ {rel_str}" if rel_str else "")
            return f"{name}⟨{inner}⟩"
        parts = [f"{json.dumps(k)}: {_render_expanded(v)}" for k, v in obj.items()]
        return "{" + ", ".join(parts) + "}"
    if isinstance(obj, list):
        return "[" + ", ".join(_render_expanded(x) for x in obj) + "]"
    return json.dumps(obj)


def expand_refs_in_description(description: str, fetch_fn, depth: int, _visited=None) -> str:
    """READ-TIME ref-expansion projection. For each CartonObj fence in `description`, replace its
    body with a rendering where every bare ref is expanded to the referenced concept's
    description + relationships, recursive to `depth`, cycle-guarded. depth<=0 returns the
    description UNCHANGED (raw tokens). Render-only — does NOT mutate stored data."""
    if depth <= 0 or not description:
        return description
    visited = set(_visited or ())
    fences = find_carton_objs(description)
    if not fences:
        return description
    result = description
    for f in sorted(fences, key=lambda x: x.span[0], reverse=True):  # right-to-left keeps spans valid
        rendered = _render_expanded(_expand_obj(f.obj, fetch_fn, depth, visited))
        bs, be = f.body_span
        result = result[:bs] + rendered + result[be:]
    return result


# ----------------------------------------------------------------------------- #
# STEP 2 — the PURE op-applier (key_path navigation + the 4 ops)
# This is the write-path-INDEPENDENT core of edit_carton_obj: it takes a
# description STRING in, applies one op, and returns the NEW description string +
# the read value. No neo4j / no MCP — fully unit-testable. The neo4j read/write
# wrapper (edit_carton_obj) and the MCP tool sit on top of this.
# ----------------------------------------------------------------------------- #
_VALID_OPS = ("set", "append", "remove", "get")


def split_key_path(key_path: str) -> List[Any]:
    """Parse a dotted/indexed path 'a.b.0.c' -> ['a', 'b', 0, 'c']. Integer segments
    are LIST indices; everything else is a DICT key. Empty/None -> [] (the root)."""
    if not key_path:
        return []
    segs: List[Any] = []
    for s in key_path.split("."):
        # a segment that is a (possibly negative) integer is a list index
        if s.lstrip("-").isdigit():
            segs.append(int(s))
        else:
            segs.append(s)
    return segs


def _descend(obj: Any, segs: List[Any]) -> Any:
    """Walk obj along segs, returning the value at that path. Raises KeyError /
    IndexError / TypeError on a bad path (caller turns these into clear errors)."""
    cur = obj
    for s in segs:
        cur = cur[s]   # dict[str] or list[int]; natural exception on miss/oob/type
    return cur


def apply_carton_obj_op(
    description: str,
    kvobj_name: str,
    key_path: str,
    op: str,
    value: Any = None,
) -> Tuple[str, Any]:
    """PURE core of edit_carton_obj. Returns (new_description, result_value).

    op:
      get    -> result_value = the value at key_path; description UNCHANGED.
      set    -> set the value at key_path (creates the FINAL key on a dict if absent;
                an intermediate missing key/index is an error — no silent auto-vivify).
                key_path='' replaces the WHOLE kvobj body with `value`.
      append -> key_path must point at a list; append `value` to it.
      remove -> delete the key/index at key_path.

    `value` is a python object; a ref is the dict {"$ref": "Name"} (so it round-trips
    to a bare Title_Underscore token in the body). Raises KeyError if the fence is
    absent, ValueError on a bad op, and KeyError/IndexError/TypeError on a bad path.
    """
    import copy

    if op not in _VALID_OPS:
        raise ValueError(f"unknown op {op!r}; must be one of {_VALID_OPS}")

    fence = get_carton_obj(description, kvobj_name, strict=True)
    if fence is None:
        raise KeyError(f"no CartonObj named {kvobj_name!r} in description")

    obj = copy.deepcopy(fence.obj)
    segs = split_key_path(key_path)

    if op == "get":
        return description, _descend(obj, segs)

    if op == "set":
        if not segs:
            obj = value  # replace the whole body
        else:
            parent = _descend(obj, segs[:-1])
            last = segs[-1]
            if isinstance(last, int):
                if not isinstance(parent, list):
                    raise TypeError(f"index {last} into non-list at {key_path!r}")
                parent[last] = value          # must be an existing index
            else:
                if not isinstance(parent, dict):
                    raise TypeError(f"key {last!r} into non-dict at {key_path!r}")
                parent[last] = value          # create-or-overwrite the final dict key
        result = value

    elif op == "append":
        target = _descend(obj, segs)
        if not isinstance(target, list):
            raise TypeError(f"append target at {key_path!r} is not a list")
        target.append(value)
        result = target

    else:  # remove
        if not segs:
            raise ValueError("remove requires a non-empty key_path")
        parent = _descend(obj, segs[:-1])
        last = segs[-1]
        del parent[last]   # KeyError/IndexError on a bad final segment
        result = None

    new_description = replace_carton_obj_body(description, kvobj_name, obj)
    return new_description, result


# ----------------------------------------------------------------------------- #
# STEP 4 (PURE parts) — ref extraction + schema validation
# extract_refs / deref_for_validation are pure stdlib. validate_against_schema lazily
# imports jsonschema (kept out of module import so the parser stays standalone).
# ----------------------------------------------------------------------------- #
def extract_refs(obj: Any) -> List[str]:
    """Return every bare-ref name ({"$ref": "Name"}) in a parsed obj, in document order
    (duplicates kept — caller dedupes if needed)."""
    out: List[str] = []

    def _walk(o: Any) -> None:
        if isinstance(o, dict):
            if len(o) == 1 and "$ref" in o and isinstance(o["$ref"], str):
                out.append(o["$ref"])
                return
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for x in o:
                _walk(x)

    _walk(obj)
    return out


def deref_for_validation(obj: Any) -> Any:
    """Replace each {"$ref": "Name"} with the bare string "Name" so json-schema validates
    a ref slot as its concept-name string (a ref is a Title_Underscore token = string-like)."""
    if isinstance(obj, dict):
        if len(obj) == 1 and "$ref" in obj and isinstance(obj["$ref"], str):
            return obj["$ref"]
        return {k: deref_for_validation(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [deref_for_validation(x) for x in obj]
    return obj


def validate_against_schema(body_obj: Any, schema_obj: dict) -> List[dict]:
    """Validate a parsed CartonObj body against a json-schema dict. Refs are dereffed to
    their name strings first. Returns [] if valid, else a list of
    {"path": "<dotted key path or (root)>", "message": "<jsonschema error>"} — one per
    violation, so the caller can report WHICH key failed. Lazily imports jsonschema."""
    import jsonschema  # lazy: keeps the parser importable without jsonschema

    derefed = deref_for_validation(body_obj)
    validator = jsonschema.Draft7Validator(schema_obj)
    errors: List[dict] = []
    for err in sorted(validator.iter_errors(derefed), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in err.path) if err.path else "(root)"
        errors.append({"path": path, "message": err.message})
    return errors
