#!/usr/bin/env python3
"""Rebuild the scripts written to SCRATCHPADS (not the repo) from the exact transcript bytes in
raw/scratch_writes.jsonl: per path, replay every non-error Write/Edit in time order. Only .py / .sh files
under a /tmp/claude-*/*/scratchpad/ directory. Writes each to recovered/_scratchpad_scripts/<session>/<name>
and reports whether the on-disk scratchpad copy still exists and matches — when it differs, the ON-DISK
file is the complete one (the replay kept only writes whose text matched scratch_key_regex).
Writes raw/scratch_scripts_report.json. Read-only over everything else."""
import filecmp
import json
import os
import re

from recon_common import ROOT, raw


def main():
    src = raw("scratch_writes.jsonl")
    if not os.path.exists(src):
        print(f"{src} is absent: scratch_writes.py found nothing to rebuild")
        return
    by_path = {}
    for r in map(json.loads, open(src)):
        if re.search(r"^/tmp/claude-[^/]+/.+/scratchpad/[^/]+\.(py|sh)$", r["path"]):
            by_path.setdefault(r["path"], []).append(r)
    rows = []
    for p, rs in sorted(by_path.items()):
        text, log = None, []
        for r in sorted(rs, key=lambda x: x["ts"]):
            if r["is_error"]:
                log.append((r["ts"], r["id"], r["tool"], "TOOL_ERROR"))
                continue
            inp = r["input"]
            if r["tool"] == "Write":
                text = inp.get("content", "")
                log.append((r["ts"], r["id"], "Write", "WRITE"))
            else:
                old, new = inp.get("old_string", ""), inp.get("new_string", "")
                if text is not None and old in text:
                    text = text.replace(old, new) if inp.get("replace_all") else text.replace(old, new, 1)
                    log.append((r["ts"], r["id"], "Edit", "APPLIED"))
                else:
                    log.append((r["ts"], r["id"], "Edit", "CONFLICT (no prior Write in window, or old_string absent)"))
        if text is None:
            continue
        session = p.split("/")[4]
        dest = os.path.join(ROOT, "recovered", "_scratchpad_scripts", session, os.path.basename(p))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "w").write(text)
        disk = "absent"
        if os.path.exists(p):
            disk = "on disk, identical" if filecmp.cmp(dest, p, shallow=False) else "on disk, DIFFERS"
        rows.append({"path": p, "dest": dest, "ops": log, "disk": disk})
        print(f"{dest}\t{disk}\t" + "; ".join(f"{t[:19]} {i} {k} {o}" for t, i, k, o in log))
    json.dump(rows, open(raw("scratch_scripts_report.json"), "w"), indent=1)
    print(f"[{len(rows)} scratchpad scripts rebuilt of {len(by_path)} paths]")


if __name__ == "__main__":
    main()
