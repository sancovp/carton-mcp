#!/usr/bin/env python3
"""Classify every file-writing tool call (Edit / Write / MultiEdit) on the target paths against git.

Sources, merged: raw/transcript_ops.jsonl (exact bytes, Claude Code transcripts) and raw/carton_ops.jsonl
(CartON Tool_Call nodes). A CartON op whose signature (tool, file, old and new text with ALL whitespace
and [ ] squashed out) matches a transcript op within 6 h is merged into it: the transcript bytes are used
and the CartON node is recorded. An unmatched CartON op is LOSSY (issue 943, measured 2026-09-27 on
Tool_Call_2026_09_22T21_17_30_T11: runs of spaces collapsed to one and every literal [ ] not part of an
auto-link removed), so it is compared bracket- and whitespace-insensitively (normb) and never applied.

Status per op in the run window (an op outside it is OUT_OF_WINDOW, and still counts as a LATER op):
  IN_HEAD              every distinctive added line (>= 8 chars) is in HEAD
  SUPERSEDED           each added line missing from HEAD was changed again by a LATER recorded op: its
                       old text holds the line and its new text does not, or a >= 6-char fragment of its
                       old text sits inside the line, or it is a Write whose content lacks the line
  COMMITTED_THEN_LOST  every added line is missing, unsuperseded, and some commit on some ref ADDED it
  NEVER_COMMITTED      every added line is missing, unsuperseded, and no commit ever added it
  PARTIAL              only some added lines are missing (partial_kind: committed-then-lost | never-committed)
  DELETION_IN_HEAD / DELETION_NOT_IN_HEAD   the op only removed lines
  NO_CHANGE / TOOL_ERROR (refused or failed: nothing was written) / OUTSIDE_REPO
History is PATH-SCOPED (both spellings of a moved file): a line another file carries says nothing about
this edit. Writes raw/ops_classified.jsonl. Read-only over git (log, grep, show)."""
import datetime as dt
import json
import re
from collections import defaultdict

import recon_common as C


def normb(s):
    return re.sub(r"\s+", " ", re.sub(r"[\[\]]", "", s)).strip()


def squash(s):
    return re.sub(r"[\s\[\]]", "", s or "")


def lines_by(text, f):
    return [f(l) for l in (text or "").split("\n")]


_head_b = {}


def head_set(rels, f):
    key = (tuple(rels), f.__name__)
    if key not in _head_b:
        s, ex = set(), False
        for r in rels:
            p = C.git("show", f"HEAD:{r}")
            if p.returncode == 0:
                ex = True
                s |= set(lines_by(p.stdout, f))
        _head_b[key] = (ex, s)
    return _head_b[key]


def wt_set(rels, f):
    s, ex = set(), False
    for r in rels:
        try:
            s |= set(lines_by(open(f"{C.REPO}/{r}", errors="replace").read(), f))
            ex = True
        except FileNotFoundError:
            pass
    return ex, s


def ere_b(line):
    out = []
    for ch in line:
        if ch == " ":
            out.append("[][[:space:]]+")
        else:
            out.append(re.sub(r"([.\[\]()*+?{}|^$\\])", r"\\\1", ch) + "[][]*")
    return "".join(out)


_hist_p = {}


def history_path(line, rels, lossy):
    """Commits on ANY ref that changed the occurrence count of `line` IN THIS FILE (every spelling of it),
    oldest first, tagged ADD / REMOVE by comparing the count in the commit and its first parent."""
    key = (line, tuple(rels), lossy)
    if key in _hist_p:
        return _hist_p[key]
    rx = ere_b(line) if lossy else C.ere(line)
    p = C.git("log", "--all", "--reverse", "--format=%H|%aI|%s", "--pickaxe-regex", f"-S{rx}", "--", *rels)
    out = []
    for row in p.stdout.splitlines():
        sha, date, subj = row.split("|", 2)

        def count(ref):
            g = C.git("grep", "-c", "-E", rx, ref, "--", *rels)
            return sum(int(x.rsplit(":", 1)[1]) for x in g.stdout.splitlines() if ":" in x)
        c1, c0 = count(sha), count(sha + "^")
        out.append({"sha": sha[:9], "date": date, "subject": subj, "kind": "ADD" if c1 > c0 else "REMOVE",
                    "count_before": c0, "count_after": c1})
    _hist_p[key] = out
    return out


def texts(o):
    a = o["args"]
    if o["tool"] == "Edit":
        return a.get("old_string", ""), a.get("new_string", "")
    if o["tool"] == "Write":
        return "", a.get("content", "")
    return ("\n".join(e.get("old_string", "") for e in a.get("edits", [])),
            "\n".join(e.get("new_string", "") for e in a.get("edits", [])))


def load():
    start = C.transcript_start()
    ops = []
    for l in open(C.raw("transcript_ops.jsonl")):
        r = json.loads(l)
        if r["name"] == "Bash":
            continue
        ops.append({"source": "transcript", "id": r["tool_use_id"], "ts": r["timestamp"], "tool": r["name"],
                    "args": r["input"], "is_error": bool(r["is_error"]), "result_head": (r["result_head"] or "")[:400],
                    "transcript": r["transcript"], "structuredPatch": r["structuredPatch"], "carton_nodes": [],
                    "lossy": False})
    carton = [json.loads(l) for l in open(C.raw("carton_ops.jsonl"))]
    for c in carton:
        m = re.match(r"Tool_Call_(\d{4})_(\d\d)_(\d\d)T(\d\d)_(\d\d)_(\d\d)_T(\d+)", c["node"])
        c["ts"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}:{m.group(5)}:{m.group(6)}Z"

    def sig(tool, args):
        old, new = texts({"tool": tool, "args": args})
        return (tool, args.get("file_path"), squash(old), squash(new))
    by_sig = defaultdict(list)
    for o in ops:
        by_sig[sig(o["tool"], o["args"])].append(o)
    unmatched = []
    for c in sorted(carton, key=lambda x: x["ts"]):
        tc = dt.datetime.fromisoformat(c["ts"].replace("Z", "+00:00"))
        scored = []
        for o in by_sig.get(sig(c["tool"], c["args"]), []):
            d = abs((dt.datetime.fromisoformat(o["ts"].replace("Z", "+00:00")) - tc).total_seconds())
            if d <= 6 * 3600:
                scored.append((len(o["carton_nodes"]) > 0, d, o))
        scored.sort(key=lambda x: (x[0], x[1]))
        if scored:
            scored[0][2]["carton_nodes"].append(c["node"])
        else:
            unmatched.append(c)
    for c in unmatched:
        ops.append({"source": "carton", "id": c["node"], "ts": c["ts"], "tool": c["tool"], "args": c["args"],
                    "is_error": None, "result_head": "", "transcript": None, "structuredPatch": None,
                    "carton_nodes": [c["node"]], "lossy": True,
                    "carton_only_reason": ("before transcript coverage" if c["ts"] < start
                                           else "no matching transcript tool_use (another session, or an attempt the transcript does not hold)")})
    ops.sort(key=lambda o: o["ts"])
    return ops


def superseders(o, missing, later):
    sup = {}
    for l in missing:
        for o2 in later:
            g = normb if (o["lossy"] or o2["lossy"]) else C.norm
            lb = normb(l) if g is normb else l
            o2old, o2new = texts(o2)
            nlines = set(lines_by(o2new, g))
            if o2["tool"] == "Write":
                if lb not in nlines:
                    sup[l] = o2["id"]
                    break
                continue
            if lb in g(o2old) and lb not in nlines:
                sup[l] = o2["id"]
                break
            if any(len(frag) >= 6 and frag in lb and frag != lb and lb not in nlines for frag in lines_by(o2old, g)):
                sup[l] = o2["id"]
                break
    return sup


def classify(o, files):
    if not C.in_window(o["ts"]):
        o["status"] = "OUT_OF_WINDOW"
        return
    if o["is_error"]:
        o["status"] = "TOOL_ERROR"
        return
    if not o["rels"]:
        o["status"] = "OUTSIDE_REPO"
        return
    f = normb if o["lossy"] else C.norm
    exists, hl = head_set(o["rels"], f)
    wexists, wl = wt_set(o["rels"], f)
    o["head_exists"], o["worktree_exists"] = exists, wexists
    added, removed = o["added_lines"], o["removed_lines"]
    if not added:
        if not removed:
            o["status"] = "NO_CHANGE"
        else:
            still = [l for l in removed if l in hl]
            o["status"] = "DELETION_IN_HEAD" if not still else "DELETION_NOT_IN_HEAD"
            o["removed_still_in_head"] = still
        return
    missing = [l for l in added if l not in hl]
    o["missing_from_head"] = missing
    o["missing_in_worktree_too"] = [l for l in missing if l not in wl]
    if not missing:
        o["status"] = "IN_HEAD"
        return
    later = [o2 for o2 in files[tuple(sorted(set(o["rels"])))] if o2["ts"] > o["ts"] and not o2.get("is_error")]
    sup = superseders(o, missing, later)
    o["superseded_lines"] = sup
    unsup = [l for l in missing if l not in sup]
    o["unsuperseded_missing"] = unsup
    probe = sorted(unsup or missing, key=len, reverse=True)[:3]
    hist = {l: history_path(l, o["rels"], o["lossy"]) for l in probe}
    o["history"] = hist
    ever_added = any(h["kind"] == "ADD" for hs in hist.values() for h in hs)
    if not unsup:
        o["status"] = "SUPERSEDED"
    elif len(unsup) == len(added):
        o["status"] = "COMMITTED_THEN_LOST" if ever_added else "NEVER_COMMITTED"
    else:
        o["status"] = "PARTIAL"
        o["partial_kind"] = "committed-then-lost" if ever_added else "never-committed"


def main():
    ops = load()
    files = defaultdict(list)
    for o in ops:
        o["rels"] = C.rel_paths(o["args"].get("file_path", ""))
        files[tuple(sorted(set(o["rels"])))].append(o)
    for o in ops:
        f = normb if o["lossy"] else C.norm
        old, new = texts(o)
        ol, nl = lines_by(old, f), lines_by(new, f)
        so, sn = set(ol), set(nl)
        o["added_lines"] = [l for l in dict.fromkeys(nl) if l not in so and len(l) >= C.MINLEN]
        o["removed_lines"] = [l for l in dict.fromkeys(ol) if l not in sn and len(l) >= C.MINLEN]
    for o in ops:
        classify(o, files)
    with open(C.raw("ops_classified.jsonl"), "w") as fh:
        for o in ops:
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")
    counts = defaultdict(int)
    for o in ops:
        counts[(o["status"], o["source"])] += 1
    for k, v in sorted(counts.items()):
        print(v, *k)
    inwin = sum(1 for o in ops if o["status"] != "OUT_OF_WINDOW")
    print(f"[{len(ops)} ops loaded; {inwin} in window {C.FROM}..{C.TO}; "
          f"{sum(1 for o in ops if o['status'] in C.LOST)} lost-class]")


if __name__ == "__main__":
    main()
