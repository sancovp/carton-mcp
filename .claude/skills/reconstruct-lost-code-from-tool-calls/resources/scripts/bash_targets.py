#!/usr/bin/env python3
"""For each TARGET_WRITE record of raw/bash_classified.jsonl, find the files matching path_regex that it
WRITES (not merely reads): python `Path("<file>")` bound to a var that later gets `.write_text(`;
`open("<file>", "w")`; `sed -i ... <file>`; redirect `> <file>`; `cp|mv|install <src> <file>`;
`tee <file>`. Prints one line per record that has at least one written target. Read-only.
`targets(cmd)` is imported by carton_bash.py."""
import json
import re

from recon_common import PATH_RX, raw

CAND = r"[\w./~-]+\.[A-Za-z0-9]+"


def targets(cmd):
    t = set()
    for m in re.finditer(r"(\w+)\s*=\s*(?:Path|pathlib\.Path)\(\s*['\"](" + CAND + r")['\"]\s*\)", cmd):
        var, path = m.group(1), m.group(2)
        if re.search(r"\b" + re.escape(var) + r"\.write_(text|bytes)\(", cmd):
            t.add(path)
    for m in re.finditer(r"open\(\s*['\"](" + CAND + r")['\"]\s*,\s*['\"][wa]", cmd):
        t.add(m.group(1))
    for m in re.finditer(r"sed\s+-i\S*\s+(?:-e\s+)?(?:'[^']*'|\"[^\"]*\"|\S+)\s+((?:\S+\s+)*)", cmd):
        for p in re.findall(CAND, m.group(1)):
            t.add(p)
    for m in re.finditer(r"(?<![<>0-9&])>>?\s*['\"]?(" + CAND + ")", cmd):
        t.add(m.group(1))
    for m in re.finditer(r"\b(?:cp|mv|install)\b(?:\s+-\S+)*\s+\S+\s+['\"]?(" + CAND + ")", cmd):
        t.add(m.group(1))
    for m in re.finditer(r"\btee\b(?:\s+-a)?\s+['\"]?(" + CAND + ")", cmd):
        t.add(m.group(1))
    return sorted(p for p in t if PATH_RX.search(p))


def main():
    n = 0
    for line in open(raw("bash_classified.jsonl")):
        r = json.loads(line)
        if "TARGET_WRITE" not in r["classes"]:
            continue
        t = targets(r["input"].get("command", ""))
        if not t:
            continue
        n += 1
        print(f"{r['timestamp']}\terr={r['is_error']}\t{r['tool_use_id']}\t{' '.join(t)}")
    print("records with written target files:", n)


if __name__ == "__main__":
    main()
