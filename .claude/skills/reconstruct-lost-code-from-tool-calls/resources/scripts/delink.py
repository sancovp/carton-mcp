"""Exact inverse of the CartON auto-linker markup, for text read RAW from n.d.

The auto-linker wraps a mention as `[text](../Target/Target_itself.md)` (paths render as
`[/a/b](..//A/B//A/B_itself.md)`). Only that form is undone: the target must start with `..` and end
with `_itself.md)`, so a markdown link written by a person, or code such as `x[i](y)`, is left alone.
Nested wraps are undone inside-out by iterating to a fixed point. Nothing else is changed — in
particular whitespace is NOT touched (the read facade collapses runs of spaces; this does not)."""
import re

_LINK = re.compile(r"\[([^\[\]]*)\]\(\.\.[^\n]*?_itself\.md\)")


def delink(text):
    if not isinstance(text, str):
        return text
    prev = None
    while prev != text:
        prev = text
        text = _LINK.sub(lambda m: m.group(1), text)
    return text


def residue(text):
    """Count leftover `_itself.md` fragments after delinking — non-zero means an unhandled form."""
    return text.count("_itself.md")
