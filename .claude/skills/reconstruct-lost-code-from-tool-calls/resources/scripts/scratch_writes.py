#!/usr/bin/env python3
"""List Write/Edit tool_uses to paths OUTSIDE the target (scratchpads, /tmp) whose content matches the
run config's scratch_key_regex, in the window: the scripts that did the real work on the subject but were
written somewhere no commit reaches. Prints ts, tool, error flag, tool_use id, size and path; writes
raw/scratch_writes.jsonl with the full inputs. Read-only. Skipped, and says so, when the config has no
scratch_key_regex."""
import glob
import json
import os
import re
import sys

from recon_common import CFG, FROM, TO, PATH_RX, TRANSCRIPTS_ROOT, raw


def main():
    key = CFG.get("scratch_key_regex")
    if not key:
        print("scratch_key_regex unset in the run config: scratch writes not searched")
        return
    kx = re.compile(key)
    lo, hi = FROM, TO + "T99"
    n = 0
    out = open(raw("scratch_writes.jsonl"), "w")
    for p in sorted(glob.glob(os.path.join(TRANSCRIPTS_ROOT, "**", "*.jsonl"), recursive=True)):
        pending = {}
        with open(p, errors="replace") as f:
            for line in f:
                if '"tool_use"' not in line and '"tool_result"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError as e:
                    print("skip", p, e, file=sys.stderr)
                    continue
                ts = o.get("timestamp") or ""
                msg = o.get("message") or {}
                content = msg.get("content") if isinstance(msg, dict) else None
                if not isinstance(content, list):
                    continue
                if o.get("type") == "assistant" and lo <= ts <= hi:
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Write", "Edit"):
                            inp = b.get("input") or {}
                            fp = inp.get("file_path", "")
                            if PATH_RX.search(fp):
                                continue
                            if kx.search(inp.get("content", "") + inp.get("new_string", "")):
                                pending[b.get("id")] = {"ts": ts, "id": b.get("id"), "tool": b.get("name"), "path": fp,
                                                        "input": inp, "transcript": p, "is_error": None}
                elif o.get("type") == "user":
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                            rec = pending.pop(b.get("tool_use_id"))
                            rec["is_error"] = bool(b.get("is_error"))
                            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                            n += 1
                            body = rec["input"].get("content", "") or rec["input"].get("new_string", "")
                            print(f"{rec['ts']}\t{rec['tool']}\terr={rec['is_error']}\t{rec['id']}\t{len(body)}\t{rec['path']}")
    out.close()
    print(f"[{n} scratch writes matching scratch_key_regex in {FROM}..{TO}]")


if __name__ == "__main__":
    main()
