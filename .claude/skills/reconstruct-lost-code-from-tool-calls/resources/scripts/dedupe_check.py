#!/usr/bin/env python3
"""Check how many file-tool records of raw/transcript_ops.jsonl share a tool_use_id (a transcript copied
into a subagent file is read twice), and show the distinct result heads of the errored ones — read-gate
refusals, stale-read refusals and user rejections wrote nothing."""
import json
from collections import defaultdict

from recon_common import raw


def main():
    by_id = defaultdict(list)
    for r in map(json.loads, open(raw("transcript_ops.jsonl"))):
        if r["name"] != "Bash":
            by_id[r["tool_use_id"]].append(r)
    print("file-tool records:", sum(len(v) for v in by_id.values()), "distinct ids:", len(by_id))
    dups = {k: v for k, v in by_id.items() if len(v) > 1}
    print("ids with >1 record:", len(dups))
    for k, v in list(dups.items())[:5]:
        for r in v:
            print(" ", k, r["transcript"].split("/")[-1], r["line"], r["timestamp"], r["is_error"],
                  (r["result_head"] or "")[:120].replace("\n", " "))
    errs = [r for v in by_id.values() for r in v if r["is_error"]]
    print("errored records:", len(errs))
    seen = set()
    for r in errs:
        h = (r["result_head"] or "")[:160].replace("\n", " ")
        if h in seen:
            continue
        seen.add(h)
        print("  ERR", r["timestamp"], r["input"].get("file_path", "")[-60:], "|", h)


if __name__ == "__main__":
    main()
