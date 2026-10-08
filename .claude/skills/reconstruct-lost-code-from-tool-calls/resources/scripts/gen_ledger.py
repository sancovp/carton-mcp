#!/usr/bin/env python3
"""Build the ledger (ledger.json + LEDGER.md) and the per-day coverage table (COVERAGE.md) from
raw/ops_final.jsonl, raw/bash_classified.jsonl, raw/carton_bash.jsonl and raw/carton_coverage.tsv.
For ops whose added lines are in HEAD, the adding commit is found with a path-scoped pickaxe on the
longest added line. Every day of the window gets a row; a day with zero CartON Tool_Call nodes is named a
HOLE. Read-only over git."""
import datetime as dt
import json
import os
import re
from collections import defaultdict

import classify_ops as K
from recon_common import FROM, TO, LOST, ROOT, raw, transcript_start


def summary(o):
    if o.get("is_error"):
        return "TOOL ERROR: " + re.sub(r"\s+", " ", (o.get("result_head") or ""))[:110]
    a = o["args"]
    txt = a.get("new_string") if o["tool"] == "Edit" else a.get("content", "")
    added = o.get("added_lines") or []
    pick = next((l for l in added if len(l) > 20 and not l.startswith(("#", "%", '"""'))), None) or (added[0] if added else "")
    if not pick:
        pick = re.sub(r"\s+", " ", (txt or ""))[:110]
    return pick[:110].replace("|", "\\|")


def shas(o):
    hs = [h for v in (o.get("history") or {}).values() for h in v]
    add = next((h for h in hs if h["kind"] == "ADD"), None)
    rem = next((h for h in hs if h["kind"] == "REMOVE" and (not add or h["date"] >= add["date"])), None)
    return (add["sha"] if add else ""), (rem["sha"] if rem else "")


def ledger_rows(ops):
    for o in ops:
        if o["status"] in ("IN_HEAD", "PARTIAL") and o.get("rels") and o.get("added_lines") and not o.get("history_in_head"):
            present = [l for l in o["added_lines"] if l not in (o.get("missing_from_head") or [])]
            if present:
                line = max(present, key=len)
                o["history_in_head"] = {line: K.history_path(line, o["rels"], o["source"] == "carton")}
    rows = []
    for o in ops:
        add, rem = shas(o)
        if not add and o.get("history_in_head"):
            hs = [h for v in o["history_in_head"].values() for h in v]
            a = next((h for h in hs if h["kind"] == "ADD"), None)
            add = a["sha"] if a else ""
        adj = o.get("adjudication") or {}
        rel = o.get("canonical") or (o.get("rels") or [o["args"].get("file_path", "")])[0]
        rows.append({
            "tool_call_node": ",".join(o.get("carton_nodes") or []) or "(none: not in CartON)",
            "tool_use_id": o["id"] if o["source"] == "transcript" else "",
            "source": o["source"], "lossy": bool(o.get("lossy")), "ts": o["ts"], "tool": o["tool"], "file": rel,
            "summary": summary(o), "status": o["status"], "partial_kind": o.get("partial_kind", ""),
            "adding_sha": add, "removing_sha": rem,
            "verdict": adj.get("verdict", ""), "applied_to_recovered_file": adj.get("apply", False),
            "why": adj.get("why", ""), "patch": o.get("patch", ""), "outcomes": o.get("outcomes", {}),
            "transcript": o.get("transcript"), "result_head": o.get("result_head", ""),
            "old_string": o["args"].get("old_string"), "new_string": o["args"].get("new_string"),
            "content": o["args"].get("content"), "replace_all": o["args"].get("replace_all"),
            "edits": o["args"].get("edits"),
        })
    rows.sort(key=lambda r: r["ts"])
    return rows


def coverage(rows):
    tstart = transcript_start()
    counts = {}
    for line in open(raw("carton_coverage.tsv")):
        f = line.rstrip("\n").split("\t")
        if f[0] != "day":
            counts[f[0]] = (int(f[1]), int(f[3]))
    tr_all, tr_ok, carton_only, lost = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    for r in rows:
        d = r["ts"][:10]
        if r["source"] == "transcript":
            tr_all[d] += 1
            tr_ok[d] += r["status"] != "TOOL_ERROR"
        else:
            carton_only[d] += 1
        lost[d] += r["status"] in LOST
    start, end = dt.date.fromisoformat(FROM), dt.date.fromisoformat(TO)
    holes = 0
    with open(os.path.join(ROOT, "COVERAGE.md"), "w") as f:
        f.write("| day | CartON Tool_Call nodes (all tools) | CartON target file-write nodes | transcript target file ops "
                "(all / not errored) | CartON-only ops (no transcript twin) | lost-class ops | coverage note |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for i in range((end - start).days + 1):
            d = (start + dt.timedelta(days=i)).isoformat()
            n, cw = counts.get(d, (0, 0))
            note = []
            if n == 0:
                holes += 1
                note.append("**HOLE: zero Tool_Call nodes** — nothing known from CartON, not 'no edits'")
            elif n < 250:
                note.append(f"thin: {n} Tool_Call nodes")
            if d < tstart[:10]:
                note.append("no transcript (CartON is the only, lossy, source)")
            elif d == tstart[:10]:
                note.append(f"transcripts start {tstart[11:16]}Z")
            f.write(f"| {d} | {n} | {cw} | {tr_all.get(d, 0)} / {tr_ok.get(d, 0)} | {carton_only.get(d, 0)} | "
                    f"{lost.get(d, 0)} | {'; '.join(note)} |\n")
    return holes


def main():
    ops = [o for o in map(json.loads, open(raw("ops_final.jsonl"))) if o["status"] != "OUT_OF_WINDOW"]
    rows = ledger_rows(ops)
    bash = []
    for l in open(raw("bash_classified.jsonl")):
        r = json.loads(l)
        bash.append({"ts": r["timestamp"], "tool_use_id": r["tool_use_id"], "classes": r["classes"],
                     "is_error": r["is_error"], "command": r["input"].get("command", ""),
                     "result_head": r.get("result_head"), "transcript": r["transcript"]})
    carton_bash = [json.loads(l) for l in open(raw("carton_bash.jsonl"))]
    json.dump({"window": [FROM, TO], "file_ops": rows, "bash_transcript": bash, "bash_carton_only_days": carton_bash},
              open(os.path.join(ROOT, "ledger.json"), "w"), ensure_ascii=False, indent=1)
    with open(os.path.join(ROOT, "LEDGER.md"), "w") as f:
        f.write(f"# Tool-call ledger {FROM} .. {TO}: every Edit / Write on the target paths\n\n")
        f.write("Sources: CartON Tool_Call nodes merged with Claude Code transcripts (exact bytes). `lossy` = "
                "CartON-only text (spaces collapsed, literal [ ] stripped). Full old/new strings are in ledger.json.\n\n")
        f.write("| ts (UTC) | Tool_Call node | tool_use id | src | tool | file | status | add sha | remove sha | verdict | summary |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['ts'][:19]} | {r['tool_call_node']} | {r['tool_use_id']} | {r['source'][:4]}{' LOSSY' if r['lossy'] else ''} | "
                    f"{r['tool']} | {r['file']} | {r['status']}{(' '+r['partial_kind']) if r['partial_kind'] else ''} | "
                    f"{r['adding_sha']} | {r['removing_sha']} | {r['verdict']} | {r['summary']} |\n")
    holes = coverage(rows)
    print(f"rows {len(rows)}, bash {len(bash)}, carton_bash {len(carton_bash)}, HOLE days {holes}")


if __name__ == "__main__":
    main()
