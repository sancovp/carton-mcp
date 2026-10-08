#!/usr/bin/env python3
"""Classify the Bash tool_uses of raw/transcript_ops.jsonl into:
  GIT_DISCARD    git reset / restore / checkout <paths> / stash push|pop|apply|drop / clean (can drop
                 working-tree edits)
  GIT_COMMIT     git commit (records what a commit captured)
  TARGET_WRITE   a command that writes bytes into a path matching path_regex (python write_text or
                 open-w, sed -i, redirect, tee, cp/mv/rm onto it, git apply, patch)
Writes raw/bash_classified.jsonl with the full command, and prints one index line per record."""
import json
import re

from recon_common import CFG, raw

SUBJ = "(?:" + CFG["path_regex"] + ")"
SUBJ_RX = re.compile(SUBJ)
GIT_DISCARD = re.compile(
    r"\bgit\b(?:\s+-C\s+\S+)?\s+(reset\b|restore\b|clean\b|checkout\b(?!\s+-b)|stash\b(?!\s+(list|show)))"
)
GIT_COMMIT = re.compile(r"\bgit\b(?:\s+-C\s+\S+)?\s+commit\b")
TARGET_WRITE = [
    re.compile(r"sed\s+-i[^\n]*" + SUBJ),
    re.compile(r"(write_text|write_bytes)\s*\(", re.S),
    re.compile(r"open\([^)]*['\"][wa]b?['\"]"),
    re.compile(r">>?\s*['\"]?[^\s'\"]*" + SUBJ),
    re.compile(r"\btee\b[^\n|]*" + SUBJ),
    re.compile(r"\b(cp|mv|rm|install|rsync)\b[^\n;|&]*" + SUBJ),
    re.compile(r"\bgit\b[^\n;|&]*\bapply\b"),
    re.compile(r"\bpatch\b\s+-"),
]


def classify(cmd):
    cls = []
    if GIT_DISCARD.search(cmd):
        cls.append("GIT_DISCARD")
    if GIT_COMMIT.search(cmd):
        cls.append("GIT_COMMIT")
    if SUBJ_RX.search(cmd) and any(p.search(cmd) for p in TARGET_WRITE):
        cls.append("TARGET_WRITE")
    return cls


def main():
    n = 0
    with open(raw("bash_classified.jsonl"), "w") as out:
        for line in open(raw("transcript_ops.jsonl")):
            r = json.loads(line)
            if r["name"] != "Bash":
                continue
            cmd = r["input"].get("command", "")
            cls = classify(cmd)
            if not cls:
                continue
            r["classes"] = cls
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
            first = cmd.strip().splitlines()[0] if cmd.strip() else ""
            print(f"{r['timestamp']}\t{','.join(cls)}\terr={r['is_error']}\t{r['tool_use_id']}\t{first[:180]}")
    print("classified records:", n)


if __name__ == "__main__":
    main()
