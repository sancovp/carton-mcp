#!/usr/bin/env python3
"""Print every raw/bash_classified.jsonl record of one class (GIT_DISCARD, GIT_COMMIT, TARGET_WRITE),
with its full command, its transcript and the head of its result.
Usage: show_class.py <CLASS> [since-ISO] [until-ISO]"""
import json
import sys

from recon_common import raw


def main():
    cls = sys.argv[1]
    since = sys.argv[2] if len(sys.argv) > 2 else ""
    until = sys.argv[3] if len(sys.argv) > 3 else "9999"
    n = 0
    for line in open(raw("bash_classified.jsonl")):
        r = json.loads(line)
        ts = r["timestamp"] or ""
        if cls not in r["classes"] or not (since <= ts < until):
            continue
        n += 1
        print("=" * 100)
        print(ts, r["tool_use_id"], r["transcript"].split("projects/")[-1], "err=", r["is_error"])
        print("--- command:")
        print(r["input"].get("command", ""))
        print("--- result head:")
        print((r["result_head"] or "")[:600])
    print(f"[{n} {cls} records]")


if __name__ == "__main__":
    main()
