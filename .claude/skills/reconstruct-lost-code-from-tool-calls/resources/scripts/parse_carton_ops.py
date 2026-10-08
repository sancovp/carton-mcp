#!/usr/bin/env python3
"""Parse raw/carton_toolcalls.jsonl (delinked Tool_Call descriptions) into structured ops.
A Tool_Call description is: '<Tool>\\n\\nArgs:\\n<json>'. Keeps only ops whose file_path matches
path_regex. Writes raw/carton_ops.jsonl and prints a per-(day, file) summary plus every parse failure.
The stored strings are LOSSY (issue 943): runs of spaces collapsed to one and literal [ ] stripped at
storage, so these ops locate edits and never supply their bytes."""
import json
import re

from recon_common import PATH_RX, raw


def main():
    ok = bad = kept = 0
    out = open(raw("carton_ops.jsonl"), "w")
    summary, fails = {}, []
    for line in open(raw("carton_toolcalls.jsonl")):
        r = json.loads(line)
        d = r["d"]
        m = re.match(r"\s*(\w+)\s*\n\s*\n\s*Args:\s*\n(.*)\Z", d, re.S)
        if not m:
            bad += 1
            fails.append((r["n"], "no header", d[:120]))
            continue
        tool, js = m.group(1), m.group(2)
        try:
            args = json.loads(js)
            ok += 1
        except json.JSONDecodeError as e:
            bad += 1
            fails.append((r["n"], f"json: {e}", js[:160]))
            continue
        fp = args.get("file_path") or args.get("notebook_path") or ""
        if not PATH_RX.search(fp):
            continue
        kept += 1
        rec = {"source": "carton", "node": r["n"], "t": r["t"], "tool": tool, "args": args,
               "parents": r["parents"], "files": r["files"], "residue": r["residue"]}
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        key = (r["n"][10:20], tool, fp)
        summary[key] = summary.get(key, 0) + 1
    out.close()
    for (d, tool, fp), c in sorted(summary.items()):
        print(f"{d}\t{tool}\t{c}\t{fp}")
    print(f"parsed ok={ok} failed={bad} kept_target_path={kept}")
    for f in fails:
        print("PARSE-FAIL", f)


if __name__ == "__main__":
    main()
