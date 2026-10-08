---
name: reconstruct-lost-code-from-tool-calls
description: "WHAT: recover lost code and claimed fixes from carton's tool-call records and transcripts. WHEN: a remembered fix is missing from HEAD."
---

# reconstruct-lost-code-from-tool-calls

**In full:** WHAT: recover lost code and find claimed fixes that are not in the code — find every past edit to a set of files in carton's tool-call records day by day, take the exact bytes from the Claude Code session transcripts, check each edit against git (in HEAD, committed then lost, never committed), and rebuild the lost versions as files, patches and a ledger with one read-only agent; plus a sweep that checks every journal entry naming a commit against HEAD. WHEN: when the user says 'recover the code', 'reconstruct', 'excavate it from carton', 'we had the right code before', 'we fixed that already', 'what happened to the code', 'was this ever committed', 'claimed fixed', 'keep an eye out for it'; or a remembered fix is missing from HEAD, a running system acts like an older version, an issue closed as fixed still reproduces, or a whole-file checkout or a sweep commit may have dropped work (any of).

Isaac 2026-09-27, verbatim, the order this skill carries out: *"this probably happened with a number of
other things that we thought we did, as well. we will have to keep an eye out for it and remember this
reconstruction process imo. this should prob be a carton skill"* (issue 945).

Two tools, one job — a fix the record reports as done can be absent from the code, and nothing else
detects it:

| part | who runs it | what it answers |
|---|---|---|
| THE SWEEP — `resources/scripts/claimed_fixed_sweep.py` | you, directly; read-only | which commits the journal names no longer have their lines in HEAD, and which files a fix claim names no longer exist |
| THE RECONSTRUCTION — `resources/dispatch_prompt.md` | ONE dispatched agent, read-only | for a set of files over a window: every edit ever made, what became of each, and the lost versions rebuilt as files, patches, an INDEX and a ledger |

The sweep FINDS; the reconstruction RECOVERS. Run the sweep to keep an eye out; run the reconstruction
on whatever file and window the sweep, a bug or the user points at.

## THE SWEEP

```bash
S=/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/.claude/skills/reconstruct-lost-code-from-tool-calls/resources/scripts
python3 $S/claimed_fixed_sweep.py --after <ISO instant> --repo-axis <axis> --out <scratchpad dir>
```

- It reads the journal through `docmirror-read --json since`, never by Cypher. `--repo-axis` is spelled
  the way `journal` KEYED the entries: a registered project by its registered name (`soma-prolog`), any
  other by its monorepo path (`knowledge/carton-mcp`). A wrong spelling reads zero entries, and the sweep
  then REFUSES with rc 3 rather than report a clean run.
- rc 0 nothing lost · 1 a named commit's lines are missing from HEAD, or a named file is gone · 3 the
  journal could not be read or read nothing.
- `CLAIMED_FIXED.md` leads with the denominators, then one row per missing-code finding with the commit
  that REMOVED the lines (`removed by`, found by a path-scoped pickaxe from the named commit to HEAD).
  A PARTIAL_LOST row with no remover means the loss happened in a working tree that was later committed
  whole, or the text was rewritten past the pickaxe — run the reconstruction on it.
- A claim naming neither a commit nor a file is COUNTED and cannot be checked against git; the
  reconstruction is what answers it ("was it ever written").
- Every row the sweep flags is triaged the same way: journal it at the flagged thing's own coordinate,
  and a real loss becomes a BUG there (`journal -t BUG`, which files the issue and the card). A
  `journal -t BUG --issue N` comment mints a second card; do not comment that way.
- The issue-side twin is `docmirror-issue check` (commits that claim to fix an issue) with `adjudicate`
  (a verdict per issue and sha). Measured 2026-09-19 and again 2026-09-27 07:08 (`--from 930`): SIGKILLed,
  rc 137 — coordinate `Doc_Mirror_Issue_Mirror/Claimed_Fixed_Check`. Re-measure it with
  `docmirror-issue check --from <a recent issue>` before relying on it; until it answers, this sweep is
  the one that runs.

## THE RECONSTRUCTION — dispatch

1. Make the run directory in the session scratchpad. Copy `resources/specifics_template.json` to
   `<run dir>/recon_config.json` and fill it: `subject` with the issue and the user's verbatim order,
   `path_regex`, `path_aliases` for any moved file, the window, `out_dir` = the run dir,
   `priority_subjects` in the record's own words, `journal_axis` (the registered name for a registered
   project, else the monorepo path), and any `copy_checks` / `installed_pairs` /
   `scratch_key_regex` you know of. Leave `base_ref` and `cutoff` null; the agent sets them.
2. Record `git -C <repo> status --porcelain` BEFORE dispatch, to prove afterwards the repo was not touched.
3. Dispatch ONE agent with the Agent tool — `subagent_type: general-purpose`, `model: opus`, never a
   MiniMax agent — and this prompt and nothing else:
   `Here are the specifics: <run dir>/recon_config.json. Go read the prompt at /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/.claude/skills/reconstruct-lost-code-from-tool-calls/resources/dispatch_prompt.md and apply these specifics.`
4. CHECK THE ARTIFACT YOURSELF — the agent's report is a claim. At `check-level: FULL_E2E`, all of:
   - `git status --porcelain` equals the pre-dispatch capture;
   - `INDEX.md` carries its eight sections, and `COVERAGE.md` has one row per window day with every
     zero-node day named a HOLE;
   - every patch whose header says "applies cleanly to HEAD" passes YOUR `git apply --check`;
   - for each applied op, `python3 $S/show_ids.py <tool_use id>` (with `RECON_CONFIG` exported) shows the
     transcript input whose text the patch's `+` lines carry;
   - every `copy_checks` pair is byte-identical (`cmp`);
   - each priority subject's answer in INDEX §1 cites a node, id or sha, and one of its shas reads back
     with `git show`.
   At `SANITY`: the porcelain check, one `git apply --check`, and one priority answer against git.
5. Record the trial in RELIABILITY below: a PASS/FAIL log line naming what you checked, `runs` +1,
   `verified-good` +1 on PASS, `score` recomputed, `last-verified` set. On FAIL fix
   `resources/dispatch_prompt.md` or the script that failed, and stay at FULL_E2E.
6. Journal the result at the subject's coordinate. Every real loss is a BUG there, and restoring it is
   that bug's own card — it is proved on its own boundary, never folded into this run.

## WHAT THE METHOD STANDS ON — each measured on the 2026-09-27 run

- CartON Tool_Call nodes (`Tool_Call_<YYYY_MM_DD>T<hh_mm_ss>_T<n>`, description `<Tool>\n\nArgs:\n<json>`)
  locate every edit from 2026-08-01 on. Their text is LOSSY (issue 943): every run of spaces collapsed to
  one and every literal `[ ]` that is not an auto-link removed. So they LOCATE; they never supply bytes.
- The Claude Code transcripts under `/home/GOD/.claude/projects` (main sessions and subagents) hold the
  exact bytes, and only from the day the earliest one starts. Before it, CartON is the only record, and
  a CartON-only op is patched as LOSSY and never applied.
- CartON has days with ZERO Tool_Call nodes (2026-08-07, 08-14, 08-15 in that run). A zero day is a
  HOLE, never "no edits", and every run names its holes.
- Two git events are how code went missing, and the scripts look for both: a whole-file
  `git checkout -- <file>` or `git checkout <sha> -- <file>` run to revert PART of a file, which also drops
  every other uncommitted change in it (`destructive.py`); and a later commit of the whole file under an
  unrelated subject, which makes the working-tree loss permanent (the removing sha in the classification,
  `removed by` in the sweep).
- A fix can be designed in a journal entry and never written. Only the tool-call record can say "no
  session ever edited that code"; the reconstruction answers it per priority subject.

## Resources

- `resources/dispatch_prompt.md` — the prompt the agent reads: persona, the chains it holds, the
  12-step pipeline, the adjudication, the INDEX.md sections, the report.
- `resources/specifics_template.json` — the run config, every field described.
- `resources/scripts/` — the run's third-generation scripts, driven by `RECON_CONFIG`:
  `recon_common.py` (config, git helpers) · `transcript_ranges.py` · `extract_transcripts.py` ·
  `carton_coverage.py` · `parse_carton_ops.py` · `delink.py` · `classify_bash.py` · `bash_targets.py` ·
  `destructive.py` · `carton_bash.py` · `classify_ops.py` · `review_lost.py` · `reconstruct.py` ·
  `gen_ledger.py` · `gen_lost_table.py` · `scratch_writes.py` · `scratch_scripts.py` · `compare_copies.py`,
  plus the lookers `show_ids.py` · `show_class.py` · `summarize_ops.py` · `dedupe_check.py` · `rawq.py` ·
  `nodes.py`, and the standalone `claimed_fixed_sweep.py`.

## RELIABILITY
- score: 1.00
- runs: 2  verified-good: 2  last-verified: 2026-09-27
- check-level: FULL_E2E
- log (newest first):
  - 2026-09-27 PASS — FIRST RUN OF THIS PROMPT-FILE, the known case: `soma_prolog/soma_partials\.pl`
    2026-09-03..09-22, one Opus agent dispatched with the one-line form (run dir
    `recon_test_soma_partials_2026_09_27/` in session 14b15dfa's scratchpad). Checked by the commander end
    to end: its patch for toolu_01QiNBkzydwhQM6ZfB2o1ddd (the issue 302 scope lines) has a unified-diff
    body byte-identical to origin patch 049 (1560 bytes) and its patch for toolu_01JhrMZMgYyGZUwk7oKp8mDd
    (the transitive guard) to origin patch 050 (1489 bytes); both pass `git apply --check` on HEAD a0ab29df0;
    `git status --porcelain` equals the pre-dispatch capture; INDEX.md carries all 8 sections; COVERAGE.md
    has all 20 window days (0 holes); `show_ids.py` shows the transcript new_string carrying exactly the
    patch's + lines; its cited 5d138fced message and 07ddf9779 stat read back from git as quoted. It set
    base_ref 1efe61b5b / cutoff 2026-09-22T21:39:42Z itself, the base the origin run used. Beyond the
    origin run it found a RECORD CONFLICT (a 2026-09-04 entry records Isaac reversing the 302 approach and
    naming 07ddf9779 to revert) and a classifier artefact (a fragment-rule superseder); prompt step 7 now
    names both checks. Its report also measured the journal read: unbounded, `docmirror-read since`
    stopped at 100 rows (ending 09-14), and `--repo base/soma-prolog` returned `[]`; the INPUT REQUEST now
    passes `--repo <journal_axis> --limit 5000` and checks the count against the limit, and the run config
    carries `journal_axis`.
  - 2026-09-27 PASS — ORIGIN RUN, before this prompt-file existed: one Opus agent on an ad hoc prompt
    carrying the same method, SOMA (`soma[-_]prolog|gnosys[-_]vault`) 2026-08-01..09-23, 585 ops, 12 ops
    of real lost code in 8 files. Checked by the commander end to end: commit 2d8f15285 exists and is in
    HEAD; patches 049 (issue 302 scope lines, issue 939) and 050 (the dropped transitive guard) pass
    `git apply --check` on HEAD; the guard-drop tool_use toolu_01AWiGjzsDbDNWes7VnYdNGe is in the
    bfc48122 transcript; the 5 recovered files that still have a copy elsewhere are byte-identical to it.
    The scripts here are that run's third generation, generalized onto `RECON_CONFIG`.
