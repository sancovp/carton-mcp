#!/usr/bin/env python3
"""Print, per Claude Code transcript JSONL (main sessions and subagents), its size, first and last
timestamp, line count and tool_use count: which sessions hold the exact bytes for which dates.
Read-only; needs no run config. Usage: transcript_ranges.py [root] [out_file]
(default root /home/GOD/.claude/projects; with out_file the same table is also written there)"""
import glob
import json
import os
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/home/GOD/.claude/projects"
OUT = sys.argv[2] if len(sys.argv) > 2 else None


def scan(path):
    first = last = None
    n_lines = n_tool = n_bad = 0
    with open(path, "r", errors="replace") as f:
        for line in f:
            n_lines += 1
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                n_bad += 1
                continue
            ts = o.get("timestamp")
            if ts:
                if first is None:
                    first = ts
                last = ts
            msg = o.get("message") or {}
            c = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        n_tool += 1
    return first, last, n_lines, n_tool, n_bad


def main():
    files = sorted(glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True))
    lines = []
    for p in files:
        first, last, nl, nt, nb = scan(p)
        lines.append(f"{p}\t{os.path.getsize(p)}\t{first}\t{last}\tlines={nl}\ttool_use={nt}\tunparsable={nb}")
    lines.append(f"[{len(files)} transcript files under {ROOT}]")
    print("\n".join(lines))
    if OUT:
        with open(OUT, "w") as f:
            f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
