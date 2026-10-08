#!/usr/bin/env python3
"""Summarize raw/transcript_ops.jsonl. Mode `files` (default): file-tool ops per (date, tool, file) with
error counts. Mode `bash`: Bash commands that can WRITE a target path or DISCARD working-tree changes,
one line each. Usage: summarize_ops.py [files|bash]"""
import json
import re
import sys
from collections import defaultdict

from recon_common import CFG, raw

WRITE_BASH = re.compile(
    r"sed\s+-i|\btee\b|>>?\s*\S*(?:" + CFG["path_regex"] + r")|\bcp\b|\bmv\b|\brm\b|\bpatch\b|"
    r"git\s+(reset|checkout|restore|stash|clean|apply|am|cherry-pick|revert|rm)\b|write_text|open\([^)]*['\"]w|\.write\(|pip\s+install"
)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "files"
    recs = [json.loads(l) for l in open(raw("transcript_ops.jsonl"))]
    if mode == "files":
        agg = defaultdict(lambda: [0, 0])
        for r in recs:
            if r["name"] == "Bash":
                continue
            key = ((r["timestamp"] or "")[:10], r["name"], r["input"].get("file_path", ""))
            agg[key][0] += 1
            agg[key][1] += bool(r["is_error"])
        for (d, n, fp), (c, e) in sorted(agg.items()):
            print(f"{d}\t{n}\t{c}\terr={e}\t{fp}")
        print(f"[{sum(c for c, _ in agg.values())} file-tool ops over {len(agg)} (day, tool, file) groups]")
    elif mode == "bash":
        n = 0
        for r in recs:
            if r["name"] != "Bash":
                continue
            cmd = r["input"].get("command", "")
            if WRITE_BASH.search(cmd):
                n += 1
                one = cmd.replace("\n", " \\n ")
                print(f"{r['timestamp']}\terr={r['is_error']}\t{r['tool_use_id']}\t{one[:400]}")
        print(f"[{n} bash commands that can write or discard]")
    else:
        sys.exit(f"unknown mode {mode!r}: files | bash")


if __name__ == "__main__":
    main()
