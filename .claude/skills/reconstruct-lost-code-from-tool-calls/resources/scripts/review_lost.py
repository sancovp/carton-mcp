#!/usr/bin/env python3
"""Print every lost-class op of raw/ops_classified.jsonl (COMMITTED_THEN_LOST, NEVER_COMMITTED, PARTIAL,
DELETION_NOT_IN_HEAD), one block each: file, ts, id, CartON nodes, counts, the unsuperseded missing
lines, and the git history of the probed lines. This is the input to the per-op adjudication.
Usage: review_lost.py [status|-] [file-substring]"""
import json
import sys

from recon_common import LOST, REPO, raw


def main():
    want = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] != "-" else None
    fsub = sys.argv[2] if len(sys.argv) > 2 else ""
    n = 0
    for l in open(raw("ops_classified.jsonl")):
        o = json.loads(l)
        if want and o["status"] != want:
            continue
        if not want and o["status"] not in LOST:
            continue
        fp = o["args"].get("file_path", "")
        if fsub not in fp:
            continue
        n += 1
        print("=" * 110)
        print(o["status"], o.get("partial_kind", ""), o["ts"], o["tool"], fp.replace(REPO + "/", ""))
        print("  id:", o["id"], " carton:", ",".join(o.get("carton_nodes") or []), " lossy:", o.get("lossy"),
              o.get("carton_only_reason", ""))
        print(f"  added={len(o.get('added_lines') or [])} missing_from_head={len(o.get('missing_from_head') or [])} "
              f"unsuperseded={len(o.get('unsuperseded_missing') or [])} "
              f"missing_in_worktree_too={len(o.get('missing_in_worktree_too') or [])}")
        for m in (o.get("unsuperseded_missing") or o.get("removed_still_in_head") or [])[:6]:
            print("   -", m[:160])
        for line, hs in (o.get("history") or {}).items():
            print("  hist[", line[:70], "]:", "; ".join(f"{h['kind']} {h['sha']} {h['date'][:16]}" for h in hs) or "none")
    print(f"[{n} lost-class ops printed]")


if __name__ == "__main__":
    main()
