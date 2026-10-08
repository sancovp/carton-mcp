#!/usr/bin/env python3
"""THE CLAIMED-FIXED SWEEP: for every journal entry since a moment, check each commit it names against
HEAD — are the lines that commit added to the files it touched still in HEAD — and check that every file
an entry names without a commit still exists. Needs no run config.

The journal is read through `docmirror-read --json since` (the sanctioned read surface), never by Cypher.
Git is read with rev-parse, merge-base, show, log and grep only.

Verdict per (entry, commit, file):
  INTACT          every distinctive line (>= 8 chars) the commit added to the file is in HEAD
  PARTIAL_LOST    some are missing from HEAD; removed_by names the first commit after it that lowered the
                  count of a missing line in that file, when git finds one (none = lost in the working tree
                  and never committed back, or rewritten beyond the pickaxe)
  LOST            none are in HEAD
  FILE_GONE       the file does not exist at HEAD
  NO_ADDED_LINES  the commit only deleted lines in the file (nothing to look for)
  prefix NOT_IN_HEAD_HISTORY  the commit exists but is not an ancestor of HEAD (another branch, or rewritten)
Per commit token: UNKNOWN_SHA when it is not a commit of this repository.
Per entry naming files and no commit: NO_COMMIT_NAMED, with each file's existence at HEAD (PATH_GONE).
A claim naming neither a commit nor a file cannot be checked against git at all; those are COUNTED, and
the reconstruction prompt in this skill is what answers them.

Outputs <out>/claimed_fixed.jsonl and <out>/CLAIMED_FIXED.md. rc 0 nothing lost · 1 something lost or gone
· 3 the journal could not be read.
Usage: claimed_fixed_sweep.py --after 2026-09-03T00:00:00Z --out <dir> [--repo-axis <monorepo path>]
       [--git-repo /home/GOD/gnosys-plugin-v2] [--limit 100000] [--max-files 40]"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter

SHA_RX = re.compile(r"(?<![0-9A-Za-z_])(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![0-9A-Za-z_])")
CLAIM_RX = re.compile(r"\b(fix(?:es|ed)?|landed|committed|restored|repaired|resolved|shipped|built|pushed)\b", re.I)
PATH_RX = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)+[\w.-]+\.[A-Za-z]\w*|[\w-]+\.(?:py|pl|owl|sh|ts|tsx|js|json|toml|yml|yaml))(?::\d+(?:-\d+)?)?")
MANAGED = re.compile(r"(^|/)(docs/mirror|docs/vision|docs/vision_extracted|context/journal|\.docmirror)/")
MINLEN = 8


def norm(s):
    return re.sub(r"\s+", " ", s.strip())


def ere(line):
    return "[[:space:]]+".join(re.sub(r"([.\[\]()*+?{}|^$\\])", r"\\\1", t) for t in line.split(" "))


class Git:
    def __init__(self, repo):
        self.repo = repo
        self._head = {}
        self._tracked = None

    def run(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True)

    def tracked_match(self, path):
        """The tracked files at HEAD that a named path (full, partial or a bare basename) can mean."""
        if self._tracked is None:
            self._tracked = self.run("ls-files").stdout.splitlines()
        p = path[2:] if path.startswith("./") else path.lstrip("/")
        return [f for f in self._tracked if f == p or f.endswith("/" + p)]

    def resolve(self, token):
        p = self.run("rev-parse", "--verify", "--quiet", token + "^{commit}")
        return p.stdout.strip() if p.returncode == 0 else None

    def is_ancestor(self, sha):
        return self.run("merge-base", "--is-ancestor", sha, "HEAD").returncode == 0

    def touched(self, sha):
        return [l for l in self.run("show", "--name-only", "--format=", sha).stdout.splitlines() if l]

    def head_lines(self, path):
        if path not in self._head:
            p = self.run("show", f"HEAD:{path}")
            self._head[path] = None if p.returncode else {norm(l) for l in p.stdout.split("\n")}
        return self._head[path]

    def added_lines(self, sha, path):
        out = self.run("show", "--format=", "--unified=0", sha, "--", path).stdout
        seen = []
        for l in out.split("\n"):
            if l.startswith("+") and not l.startswith("+++"):
                n = norm(l[1:])
                if len(n) >= MINLEN and n not in seen:
                    seen.append(n)
        return seen

    def count(self, rx, ref, path):
        g = self.run("grep", "-c", "-E", rx, ref, "--", path)
        return sum(int(x.rsplit(":", 1)[1]) for x in g.stdout.splitlines() if ":" in x)

    def removed_by(self, sha, path, lines):
        for line in sorted(lines, key=len, reverse=True)[:3]:
            rx = ere(line)
            log = self.run("log", "--reverse", "--format=%H|%aI|%s", "--pickaxe-regex", f"-S{rx}", f"{sha}..HEAD", "--", path)
            for row in log.stdout.splitlines():
                c, date, subj = row.split("|", 2)
                if self.count(rx, c, path) < self.count(rx, c + "^", path):
                    return {"sha": c[:9], "date": date, "subject": subj, "line": line[:120]}
        return None


def read_journal(after, repo_axis, limit):
    cmd = ["docmirror-read", "--json", "since", "--after", after, "--limit", str(limit)]
    if repo_axis:
        cmd += ["--repo", repo_axis]
    p = subprocess.run(cmd, capture_output=True, text=True)
    text = p.stdout
    start = text.find("\n[")
    start = 0 if text.startswith("[") else (start + 1 if start >= 0 else -1)
    if start < 0:
        if p.returncode == 1:
            return []
        sys.stderr.write(f"docmirror-read returned no JSON (rc {p.returncode}): {p.stderr[-800:]}\n")
        sys.exit(3)
    return json.JSONDecoder().raw_decode(text[start:])[0]


def check_commit(g, full, paths, max_files, cache):
    anc = g.is_ancestor(full)
    touched = g.touched(full)
    named = [f for f in touched if any(f.endswith(p) or p.endswith(f) for p in paths)]
    files = named or [f for f in touched if not MANAGED.search(f)]
    note = "files the entry names" if named else "every file the commit touched (the entry names none of them)"
    rows = []
    for f in files[:max_files]:
        key = (full, f)
        if key not in cache:
            head = g.head_lines(f)
            added = g.added_lines(full, f)
            if head is None:
                v, missing = "FILE_GONE", added
            elif not added:
                v, missing = "NO_ADDED_LINES", []
            else:
                missing = [l for l in added if l not in head]
                v = "INTACT" if not missing else ("LOST" if len(missing) == len(added) else "PARTIAL_LOST")
            if not anc:
                v = "NOT_IN_HEAD_HISTORY+" + v
            rb = g.removed_by(full, f, missing) if missing and head is not None else None
            cache[key] = {"sha": full[:9], "file": f, "verdict": v, "added": len(added), "missing": len(missing),
                          "removed_by": rb, "missing_sample": [m[:160] for m in missing[:3]], "scope": note}
        rows.append(dict(cache[key]))
    if len(files) > max_files:
        rows.append({"sha": full[:9], "verdict": "TRUNCATED", "file": f"{len(files) - max_files} more files not checked"})
    return rows


def lost_verdict(v):
    return v not in ("INTACT", "NO_ADDED_LINES", "UNKNOWN_SHA", "TRUNCATED") and not v.startswith("NO_COMMIT_NAMED")


def write_report(path, a, stats, cache, rows):
    verdicts = Counter(r["verdict"] for r in rows)
    groups = {}
    for r in rows:
        if lost_verdict(r["verdict"]):
            groups.setdefault((r["sha"], r["file"]), []).append(r)
    unknown = sorted({r["sha"] for r in rows if r["verdict"] == "UNKNOWN_SHA"})
    gone = sorted({(r["entry"], r["file"], str(r["ts"])[:19]) for r in rows if r["verdict"] == "NO_COMMIT_NAMED+PATH_GONE"},
                  key=lambda x: x[2])
    with open(path, "w") as f:
        f.write(f"# Claimed-fixed sweep: journal entries since {a.after}{' on repo axis ' + a.repo_axis if a.repo_axis else ''}\n\n")
        f.write(f"Read {stats['entries']} entries; {stats['entries_naming_a_commit']} name at least one commit "
                f"({stats['entry_commit_pairs']} entry-commit pairs, {len(cache)} distinct commit-file checks, "
                f"{len(unknown)} hex tokens that are no commit). {stats['claims_naming_files_no_commit']} claim a fix and "
                f"name files but no commit; {stats['claims_naming_nothing_checkable']} claim a fix and name neither "
                f"(not checkable against git).\n\n")
        f.write("Verdicts over rows: " + ", ".join(f"{k} {v}" for k, v in sorted(verdicts.items())) + "\n\n")
        f.write(f"## Code a named commit added that HEAD no longer has — {len(groups)} commit-file pairs\n\n")
        f.write("Each row is a FINDING to adjudicate, not a verdict of loss: a later commit may have rewritten the text on "
                "purpose. `removed by` is where to start reading.\n\n")
        f.write("| commit | file | verdict | added | missing | removed by | entries naming it (first .. last) | a missing line |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for (sha, fname), rs in sorted(groups.items(), key=lambda kv: str(kv[1][0]["ts"])):
            r = rs[0]
            rb = r.get("removed_by") or {}
            ents = sorted({x["entry"] for x in rs})
            f.write(f"| {sha} | {fname} | {r['verdict']} | {r.get('added', '')} | {r.get('missing', '')} | "
                    f"{rb.get('sha', '')} {rb.get('subject', '')[:70]} | {len(ents)}: {ents[0]} .. {ents[-1]} | "
                    f"{(r.get('missing_sample') or [''])[0][:100].replace('|', '/')} |\n")
        f.write(f"\n## Files a fix claim names, without a commit, that match no tracked file at HEAD — {len(gone)}\n\n")
        for entry, fname, ts in gone:
            f.write(f"- {ts} {entry}: {fname}\n")
        f.write(f"\n## Hex tokens that look like commits and are none in this repository — {len(unknown)}\n\n")
        f.write(", ".join(unknown) + "\n")
    return groups, gone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--after", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repo-axis", default="")
    ap.add_argument("--git-repo", default="/home/GOD/gnosys-plugin-v2")
    ap.add_argument("--limit", type=int, default=100000)
    ap.add_argument("--max-files", type=int, default=40)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    g = Git(a.git_repo)
    entries = read_journal(a.after, a.repo_axis, a.limit)
    if not entries:
        sys.stderr.write(f"ZERO journal entries since {a.after}{' on repo axis ' + a.repo_axis if a.repo_axis else ''}: "
                         "nothing was checked, which is a failed run, not a clean one. Check the axis spelling "
                         "with docmirror-read since --help, or drop --repo-axis.\n")
        sys.exit(3)
    cache, rows, stats = {}, [], Counter()
    for e in entries:
        text = e.get("full_text") or ""
        paths = list(dict.fromkeys(m.group(1) for m in PATH_RX.finditer(text)))
        claim = bool(CLAIM_RX.search(text))
        stats["entries"] += 1
        base = {"entry": e.get("entry"), "ts": e.get("ts"), "claim_word": claim}
        resolved = {}
        for tok in dict.fromkeys(SHA_RX.findall(text)):
            full = g.resolve(tok)
            if full:
                resolved.setdefault(full, tok)
            else:
                rows.append({**base, "sha": tok, "verdict": "UNKNOWN_SHA", "file": ""})
        if resolved:
            stats["entries_naming_a_commit"] += 1
            for full in resolved:
                stats["entry_commit_pairs"] += 1
                for r in check_commit(g, full, paths, a.max_files, cache):
                    rows.append({**base, **r})
        elif claim and paths:
            stats["claims_naming_files_no_commit"] += 1
            for p in paths:
                gone = not g.tracked_match(p) and not os.path.exists(os.path.join(a.git_repo, p))
                rows.append({**base, "verdict": "NO_COMMIT_NAMED" + ("+PATH_GONE" if gone else ""), "file": p})
        elif claim:
            stats["claims_naming_nothing_checkable"] += 1
    with open(os.path.join(a.out, "claimed_fixed.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    report = os.path.join(a.out, "CLAIMED_FIXED.md")
    groups, gone = write_report(report, a, stats, cache, rows)
    print(open(report).read())
    sys.exit(1 if groups or gone else 0)


if __name__ == "__main__":
    main()
