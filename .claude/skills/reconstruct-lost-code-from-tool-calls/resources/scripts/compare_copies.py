#!/usr/bin/env python3
"""Compare every source file under each repo directory named in the run config's installed_pairs with
its other copy (the installed site-packages copy, a vendored copy): SAME is silent; DIFFERS prints +/- line
counts and whether some commit on any ref holds the copy's blob; MISSING-IN-COPY / ONLY-IN-COPY name the
rest. An installed copy can hold code the repo lost. Read-only.
installed_pairs: [[repo_dir_abs, copy_dir_abs, repo_relative_root], ...]"""
import difflib
import os

from recon_common import CFG, git

EXTS = tuple(CFG.get("copy_exts", [".py", ".pl", ".owl"]))


def files_under(root):
    out = set()
    for d, _, fs in os.walk(root):
        if "__pycache__" in d:
            continue
        for f in fs:
            if f.endswith(EXTS):
                out.add(os.path.relpath(os.path.join(d, f), root))
    return out


def main():
    pairs = CFG.get("installed_pairs", [])
    if not pairs:
        print("installed_pairs unset in the run config: no copies compared")
    for src, dst, relroot in pairs:
        print("=" * 20, src, "VS", dst)
        if not os.path.isdir(dst):
            print("  (no such dir)")
            continue
        a, b = files_under(src), files_under(dst)
        for f in sorted(a | b):
            pa, pb = os.path.join(src, f), os.path.join(dst, f)
            if f not in b:
                print(f"  MISSING-IN-COPY   {f}")
                continue
            if f not in a:
                print(f"  ONLY-IN-COPY      {f}  mtime={os.path.getmtime(pb):.0f}")
                continue
            ta = open(pa, errors="replace").read()
            tb = open(pb, errors="replace").read()
            if ta == tb:
                continue
            diff = list(difflib.unified_diff(ta.splitlines(), tb.splitlines(), lineterm="", n=0))
            plus = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
            minus = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
            blob = git("hash-object", pb).stdout.strip()
            hit = git("log", "--all", "--format=%h %aI", "--find-object=" + blob, "--", f"{relroot}/{f}").stdout.strip().splitlines()
            print(f"  DIFFERS           {f}  copy has +{plus} -{minus} vs repo; copy blob in git: {hit[:2] if hit else 'NO COMMIT HOLDS THIS BLOB'}")
        print(f"  [{len(a)} repo files, {len(b)} copy files]")


if __name__ == "__main__":
    main()
