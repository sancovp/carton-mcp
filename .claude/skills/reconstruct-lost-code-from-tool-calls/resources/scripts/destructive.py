#!/usr/bin/env python3
"""From the GIT_DISCARD records of raw/bash_classified.jsonl, keep only the verbs that can change
WORKING-TREE bytes: reset --hard/--merge/--keep, checkout with a path or `--` (or a bare ref switch),
restore without a --staged-only flag, stash push/save/pop/apply/bare, clean -f — and only those that
reach the target (they name a path matching path_regex, or name no path at all). Prints each in full
and writes raw/git_discards.jsonl. `destructive(verb, rest)` is imported by carton_bash.py.
Usage: destructive.py [since-ISO] [until-ISO]   (default: the whole record)"""
import json
import re
import sys

from recon_common import PATH_RX, raw

SEG = re.compile(r"\bgit\b(?:\s+-C\s+\S+)?\s+(reset|restore|clean|checkout|stash)\b([^\n;|&]*)")


def destructive(verb, rest):
    rest = rest.strip()
    if verb == "reset":
        return bool(re.search(r"--hard|--merge|--keep", rest))
    if verb == "restore":
        return not (re.search(r"--staged", rest) and not re.search(r"--worktree|-W\b", rest))
    if verb == "clean":
        return bool(re.search(r"-\w*f", rest))
    if verb == "checkout":
        return not rest.startswith("-b") and rest != ""
    if verb == "stash":
        return not re.match(r"(list|show)\b", rest)
    return False


def reaches_target(seg):
    """A segment reaches the target when it names a target path, or names no path at all
    (whole-tree verbs such as reset --hard, bare stash, checkout <ref>, restore .)."""
    if PATH_RX.search(seg):
        return True
    args = [a for a in seg.split()[2:] if not a.startswith("-")]
    pathish = [a for a in args if "/" in a or a == "." or "." in a.split("/")[-1]]
    return not pathish


def main():
    since = sys.argv[1] if len(sys.argv) > 1 else ""
    until = sys.argv[2] if len(sys.argv) > 2 else "9999"
    n = 0
    with open(raw("git_discards.jsonl"), "w") as out:
        for line in open(raw("bash_classified.jsonl")):
            r = json.loads(line)
            ts = r["timestamp"] or ""
            if "GIT_DISCARD" not in r["classes"] or not (since <= ts < until):
                continue
            cmd = r["input"].get("command", "")
            hits = [m.group(0) for m in SEG.finditer(cmd) if destructive(m.group(1), m.group(2))]
            hits = [h for h in hits if reaches_target(h)]
            if not hits:
                continue
            n += 1
            out.write(json.dumps({"ts": ts, "tool_use_id": r["tool_use_id"], "segments": hits,
                                  "is_error": r["is_error"], "command": cmd, "result_head": r["result_head"],
                                  "transcript": r["transcript"]}, ensure_ascii=False) + "\n")
            print("=" * 100)
            print(ts, r["tool_use_id"], r["transcript"].split("projects/")[-1], "err=", r["is_error"])
            print("destructive segments:", hits)
            print("--- command:")
            print(cmd[:3000])
            print("--- result head:")
            print((r["result_head"] or "")[:800])
    print(f"[{n} working-tree-discarding git commands reach the target]")


if __name__ == "__main__":
    main()
