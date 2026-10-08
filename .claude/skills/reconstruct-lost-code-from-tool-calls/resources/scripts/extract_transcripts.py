#!/usr/bin/env python3
"""Extract, losslessly, every tool_use from every Claude Code transcript (main sessions and subagents)
that WROTE to a path matching the run's path_regex, or ran a Bash command naming such a path, or ran a
git verb that can discard working-tree changes. Pairs each tool_use with its tool_result (is_error +
head of text + structuredPatch). Every date is kept, not only the window: a later edit is what proves an
earlier one SUPERSEDED.

Outputs: raw/transcript_ops.jsonl (one record per tool_use, sorted by timestamp) and
raw/transcripts_meta.json (file count, earliest and latest timestamp: where the exact-bytes record starts).
Read-only over the transcripts."""
import glob
import json
import os
import re
import sys

from recon_common import PATH_RX, TRANSCRIPTS_ROOT, raw

GIT_DISCARD = re.compile(r"\bgit\b[^\n;|&]*\b(reset|checkout|restore|stash|clean)\b")
FILE_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}


def result_text(block):
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
    return ""


def scan(path, records, span):
    pending = {}
    with open(path, "r", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            try:
                o = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"skip unparsable line {path}:{lineno}: {e}", file=sys.stderr)
                continue
            ts = o.get("timestamp")
            if ts:
                span[0] = ts if span[0] is None or ts < span[0] else span[0]
                span[1] = ts if span[1] is None or ts > span[1] else span[1]
            msg = o.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(content, list):
                continue
            if o.get("type") == "assistant":
                for b in content:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    name = b.get("name")
                    inp = b.get("input") or {}
                    keep = False
                    if name in FILE_TOOLS:
                        fp = inp.get("file_path") or inp.get("notebook_path") or ""
                        keep = bool(PATH_RX.search(fp))
                    elif name == "Bash":
                        cmd = inp.get("command") or ""
                        keep = bool(PATH_RX.search(cmd) or GIT_DISCARD.search(cmd))
                    if keep:
                        rec = {
                            "transcript": path,
                            "line": lineno,
                            "session": o.get("sessionId"),
                            "timestamp": ts,
                            "cwd": o.get("cwd"),
                            "tool_use_id": b.get("id"),
                            "name": name,
                            "input": inp,
                            "is_error": None,
                            "result_head": None,
                            "structuredPatch": None,
                        }
                        records.append(rec)
                        pending[b.get("id")] = rec
            elif o.get("type") == "user":
                tur = o.get("toolUseResult")
                for b in content:
                    if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                        continue
                    rec = pending.pop(b.get("tool_use_id"), None)
                    if rec is None:
                        continue
                    rec["is_error"] = bool(b.get("is_error"))
                    rec["result_head"] = result_text(b)[:1500]
                    if isinstance(tur, dict) and "structuredPatch" in tur:
                        rec["structuredPatch"] = tur.get("structuredPatch")


def main():
    files = sorted(glob.glob(os.path.join(TRANSCRIPTS_ROOT, "**", "*.jsonl"), recursive=True))
    records, span = [], [None, None]
    for p in files:
        scan(p, records, span)
    records.sort(key=lambda r: r["timestamp"] or "")
    with open(raw("transcript_ops.jsonl"), "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    json.dump({"root": TRANSCRIPTS_ROOT, "files": len(files), "earliest": span[0], "latest": span[1]},
              open(raw("transcripts_meta.json"), "w"), indent=1)
    by = {}
    for r in records:
        by[r["name"]] = by.get(r["name"], 0) + 1
    print(f"transcripts scanned: {len(files)} ({span[0]} .. {span[1]}); records: {len(records)}; by tool: {by}")
    if not files:
        sys.exit(f"ZERO transcript files under {TRANSCRIPTS_ROOT}: nothing was scanned, which is a failed run")


if __name__ == "__main__":
    main()
