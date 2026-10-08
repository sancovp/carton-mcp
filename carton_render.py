"""The carton tool answer render (card 766, issue 1113): pure, no carton, neo4j or MCP import.

`render_answer` lays a tool result out the way `seem` answers and the gnosys router answer are laid out:
scalars lead, every collection follows with its count and one record per block, and each sequence the
answer repeats is said once as an `@N` ref in a leading `refs` legend through `answer_refs.encode_refs`,
the one encoder all three share (card 770). `server_fastmcp._fmt_inner` is the one caller; the
10,000-character overflow stays in `server_fastmcp._fmt`.
"""
from typing import Callable, List

from answer_refs import encode_refs


def _present(v) -> bool:
    return v is not None and v != [] and v != {}


def _lines(value, indent: int, clean: Callable[[str], str]) -> List[str]:
    pad = " " * indent
    if isinstance(value, dict):
        fields = [(k, v) for k, v in value.items() if _present(v)]
        if not fields:
            return [pad + "(empty)"]
        out: List[str] = []
        for k, v in ([f for f in fields if not isinstance(f[1], (dict, list))]
                     + [f for f in fields if isinstance(f[1], (dict, list))]):
            if isinstance(v, list):
                out.append(f"{pad}{k} ({len(v)}):")
                out += _members(v, indent + 4, clean)
            elif isinstance(v, dict):
                out.append(f"{pad}{k}:")
                out += _lines(v, indent + 4, clean)
            else:
                text = clean(v) if isinstance(v, str) else str(v)
                if "\n" in text:
                    out.append(f"{pad}{k}:")
                    out += [" " * (indent + 4) + line if line else "" for line in text.split("\n")]
                else:
                    out.append(f"{pad}{k}: {text}")
        return out
    if isinstance(value, list):
        if not value:
            return [pad + "(none)"]
        return [f"{pad}rows ({len(value)}):"] + _members(value, indent + 4, clean)
    text = clean(value) if isinstance(value, str) else str(value)
    return [pad + line if line else "" for line in text.split("\n")]


def _members(items: list, indent: int, clean: Callable[[str], str]) -> List[str]:
    out: List[str] = []
    for item in items:
        block = _lines(item, indent + 2, clean)
        block[0] = " " * indent + "- " + block[0][indent + 2:]
        out += block
    return out


def render_answer(data, clean: Callable[[str], str] = lambda s: s) -> str:
    """PURE: a tool result as text. A dict carrying `result` renders that value; a string passes
    through `clean`; a dict renders its present fields, scalars first in their order, then each
    collection under `key (count):`; a list renders `rows (count):`, an empty one `(none)`; every
    member of a collection is a block led by `- `, a multi-line string sits indented under its key;
    then each repeated sequence is said once as an @N ref through answer_refs.encode_refs."""
    if isinstance(data, dict) and "result" in data:
        return render_answer(data["result"], clean)
    if isinstance(data, str):
        return encode_refs(clean(data))
    return encode_refs("\n".join(_lines(data, 0, clean)))
