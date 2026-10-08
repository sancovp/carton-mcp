#!/usr/bin/env python3
"""Print the full command (Bash) or full input (Edit/Write) and the result head for the given tool_use
ids from raw/transcript_ops.jsonl. The way to read one op in full while adjudicating it.
Usage: show_ids.py <tool_use_id> [...]"""
import json
import sys

from recon_common import raw


def main():
    ids = set(sys.argv[1:])
    n = 0
    for line in open(raw("transcript_ops.jsonl")):
        r = json.loads(line)
        if r["tool_use_id"] not in ids:
            continue
        n += 1
        print("=" * 100)
        print(r["timestamp"], r["tool_use_id"], r["name"], "err=", r["is_error"], r["transcript"].split("projects/")[-1])
        if r["name"] == "Bash":
            print(r["input"].get("command", ""))
        else:
            print(json.dumps(r["input"], indent=1, ensure_ascii=False))
        print("--- result head:")
        print((r["result_head"] or "")[:1200])
    print(f"[{n} of {len(ids)} ids found]")


if __name__ == "__main__":
    main()
