#!/usr/bin/env python3
"""Rebuild the files whose code was LOST, from the exact tool-call bytes, and write a patch for every
lost-class op in the window.

Inputs: raw/ops_classified.jsonl, and <out_dir>/adjudication.json — the per-op verdict written by READING
each op, its git history and the session record: {"<op id>": {"apply": bool, "verdict": str, "why": str}}.
  apply=true   the op is REAL lost code and is applied to the rebuilt files
  apply=false  a draft, or text a later commit legitimately changed; patch only
An op absent from adjudication.json is patch-only. A CartON-only op is LOSSY and is never applied.

Outputs under out_dir:
  recovered/<path>          base_ref (the committed tree current before the loss, from the run config)
                            + the applied ops dated before cutoff, in time order; skipped when base_ref is unset
  recovered_on_HEAD/<path>  HEAD + every applied op, in time order — the variant to re-adopt from
  a file absent from the base is rebuilt by replaying every non-error exact op on it
  <file>.vs_HEAD.diff       beside each rebuilt file
  patches/NNN_<file>_<id>.patch  one per lost op (HEAD -> HEAD+op when it applies, else old -> new)
  raw/ops_final.jsonl + raw/reconstruct_report.json (incl. byte checks against the config's copy_checks)
Read-only over git."""
import difflib
import filecmp
import json
import os
import sys

from recon_common import CFG, LOST, REPO, ROOT, git, raw

BASE = CFG.get("base_ref")
CUTOFF = CFG.get("cutoff")


def load_adj():
    path = os.path.join(ROOT, "adjudication.json")
    if not os.path.exists(path):
        sys.exit(f"{path} is absent: adjudicate every lost-class op (review_lost.py) and write it first")
    adj = json.load(open(path))
    return {k: (bool(v["apply"]), v["verdict"], v["why"]) for k, v in adj.items()}


def git_show(ref, path):
    p = git("show", f"{ref}:{path}")
    return p.stdout if p.returncode == 0 else None


def canonical(rels):
    for r in rels:
        if git_show("HEAD", r) is not None:
            return r
    return rels[0]


def edits_of(o):
    a = o["args"]
    if o["tool"] == "Edit":
        return [(a.get("old_string", ""), a.get("new_string", ""), bool(a.get("replace_all")))]
    if o["tool"] == "MultiEdit":
        return [(e.get("old_string", ""), e.get("new_string", ""), bool(e.get("replace_all"))) for e in a.get("edits", [])]
    return []


def apply_op(text, o):
    if o["tool"] == "Write":
        return o["args"].get("content", ""), "WRITE"
    out, outcomes = text, []
    for old, new, rall in edits_of(o):
        if old and old in out:
            out = out.replace(old, new) if rall else out.replace(old, new, 1)
            outcomes.append("APPLIED")
        elif new and new in out:
            outcomes.append("ALREADY_PRESENT")
        else:
            outcomes.append("CONFLICT")
    if "CONFLICT" in outcomes:
        return text, "CONFLICT"
    return out, ("APPLIED" if "APPLIED" in outcomes else "ALREADY_PRESENT")


def udiff(a, b, fa, fb):
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), fromfile=fa, tofile=fb))


def first_existing(ref, rels):
    for r in rels:
        t = git_show(ref, r)
        if t is not None:
            return r, t
    return None, None


def default_adj(o):
    if o["source"] == "carton":
        kinds = [h["kind"] for hs in (o.get("history") or {}).values() for h in hs]
        if "ADD" in kinds and "REMOVE" in kinds:
            return (False, "LOSSY; COMMITTED THEN REWRITTEN", "CartON-only op; a later commit changed the text.")
        return (False, "LOSSY; NOT FOUND IN GIT", "CartON-only op; lossy text, so a missing line may be a "
                "bracket/space artefact or a draft a CartON hole hides.")
    return (False, o["status"], "patch only (not adjudicated)")


def write_patch(o, rel, head_rel, head, pn):
    apply_flag, verdict, why = o["adjudication"]["apply"], o["adjudication"]["verdict"], o["adjudication"]["why"]
    name = f"{pn:03d}_{os.path.basename(rel)}_{o['id'][-12:]}.patch"
    hdr = (f"# op {o['id']}  source={o['source']}  carton={','.join(o.get('carton_nodes') or []) or '-'}\n"
           f"# ts={o['ts']}  tool={o['tool']}  status={o['status']}  verdict={verdict}  apply={apply_flag}\n"
           f"# file={o['args'].get('file_path')}\n# why: {why}\n")
    if o["source"] == "carton":
        hdr += "# LOSSY: CartON-only text; runs of spaces collapsed and literal [ ] stripped at storage\n"
    if o["tool"] == "Write":
        body = udiff(head or "", o["args"].get("content", ""), f"a/{head_rel or rel}", f"b/{rel}")
        hdr += "# Write: whole-file content against HEAD\n" if head is not None else "# Write: file absent from HEAD\n"
    elif head is not None and o["source"] == "transcript" and apply_op(head, o)[1] == "APPLIED":
        body = udiff(head, apply_op(head, o)[0], f"a/{head_rel}", f"b/{head_rel}")
        hdr += "# applies cleanly to HEAD\n"
    else:
        olds = "\n".join(e[0] for e in edits_of(o))
        news = "\n".join(e[1] for e in edits_of(o))
        body = udiff(olds + "\n", news + "\n", f"a/{rel} (old_string)", f"b/{rel} (new_string)")
        hdr += "# does NOT apply to HEAD as-is: shown as the op's own old_string -> new_string\n"
    path = os.path.join(ROOT, "patches", name)
    open(path, "w").write(hdr + body)
    return path


def rebuild(rel, rels, fops, to_apply, head_rel, head, report):
    variants = [("recovered_on_HEAD", "HEAD", None)]
    if BASE:
        variants.insert(0, ("recovered", BASE, CUTOFF))
    for variant, ref, cutoff in variants:
        base_rel, text = first_existing(ref, rels)
        if text is None:
            chosen = [o for o in fops if o["source"] == "transcript" and not o.get("is_error")
                      and (cutoff is None or o["ts"] < cutoff)]
            note = f"absent at {ref}; replayed every non-error exact op on the file"
            text = ""
        else:
            chosen = [o for o in to_apply if cutoff is None or o["ts"] < cutoff]
            note = f"{ref}:{base_rel}"
        if not chosen:
            continue
        for o in sorted(chosen, key=lambda x: x["ts"]):
            text, outc = apply_op(text, o)
            o.setdefault("outcomes", {})[variant] = outc
            report.append({"variant": variant, "file": rel, "op": o["id"], "ts": o["ts"], "status": o["status"], "outcome": outc})
        dest = os.path.join(ROOT, variant, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "w").write(text)
        open(dest + ".vs_HEAD.diff", "w").write(
            f"# {variant}/{rel}  base={note}  cutoff={cutoff or 'none'}\n"
            + udiff(head or "", text, f"HEAD:{head_rel or rel}", f"{variant}:{rel}"))
        report.append({"variant": variant, "file": rel, "op": "(file)", "ts": "", "status": "", "outcome": f"WROTE {dest}  base={note}"})


def main():
    adj = load_adj()
    os.makedirs(os.path.join(ROOT, "patches"), exist_ok=True)
    ops = [json.loads(l) for l in open(raw("ops_classified.jsonl"))]
    by_file = {}
    for o in ops:
        if o.get("rels"):
            key = canonical(o["rels"])
            o["canonical"] = key
            by_file.setdefault(key, []).append(o)
    report, pn = [], 0
    for rel, fops in sorted(by_file.items()):
        rels = sorted({r for o in fops for r in o["rels"]}, key=lambda r: (r != rel, r))
        lost = [o for o in fops if o["status"] in LOST]
        if not lost:
            continue
        head_rel, head = first_existing("HEAD", rels)
        for o in sorted(lost, key=lambda x: x["ts"]):
            apply_flag, verdict, why = adj.get(o["id"], default_adj(o))
            o["adjudication"] = {"apply": apply_flag, "verdict": verdict, "why": why}
            pn += 1
            o["patch"] = write_patch(o, rel, head_rel, head, pn)
        to_apply = [o for o in lost if o["adjudication"]["apply"] and o["source"] == "transcript"]
        if to_apply:
            rebuild(rel, rels, fops, to_apply, head_rel, head, report)
    checks = []
    for rel, other in CFG.get("copy_checks", []):
        rec = os.path.join(ROOT, "recovered_on_HEAD", rel)
        if os.path.exists(rec) and os.path.exists(other):
            checks.append((rel, other, filecmp.cmp(rec, other, shallow=False)))
        else:
            checks.append((rel, other, f"not compared: recovered exists={os.path.exists(rec)}, copy exists={os.path.exists(other)}"))
    json.dump({"base_ref": BASE, "cutoff": CUTOFF, "report": report, "copy_checks": checks},
              open(raw("reconstruct_report.json"), "w"), indent=1)
    with open(raw("ops_final.jsonl"), "w") as f:
        for o in ops:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    for r in report:
        print(f"{r['variant']:18s} {r['file'][:64]:64s} {r['op'][-14:]:14s} {r['ts'][:19]:19s} {r['status'][:15]:15s} {r['outcome'][:150]}")
    for c in checks:
        print("COPY-CHECK", c)
    if not BASE:
        print("base_ref unset in the run config: the recovered/ variant was NOT written")
    print(f"patches written: {pn}; lost-class ops without an adjudication entry: "
          f"{sum(1 for o in ops if o['status'] in LOST and o['id'] not in adj)}")


if __name__ == "__main__":
    main()
