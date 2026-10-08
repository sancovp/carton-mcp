# vision: instrument-reliability (topic — auto-created by `journal`)

<!-- ===VISION DELTA: id-tagged appends below = the gap (`vision diff <m>`); `doc-mirror-commit --realizes <ids>` drops them on build === -->
- [v1]  2026-08-22T20:02:20  FINDING: FINDING: AUDITING A THREAD RAISES ITS RANK ON THE VERY INSTRUMENT THAT SELECTS WHAT TO AUDIT NEXT - a feedback defect that inverts the ranking with use, measured on my own last pass, and the cursor shortlist it produced was five of seventeen rather than the whole band.

THE CATCH. Re-deriving the ranking live, as the cursor demands, returned SIX uncited threads ABOVE the four-hit band the cursor called the remainder. FOUR OF THE FIVE TOP-RANKED ARE THREADS I FINISHED LAST PASS - final blocks stamped 19:09, 19:26, 19:31 and 19:36, all mine. The cursor said everything at five hits and above was worked, cited or done; the live run says otherwise, and the reason is that working them is what put them there.

THE MECHANISM, PROVEN BY PRINTING THE SENTENCES RATHER THAN INFERRING. The top thread, Om_Becomes_The_Base, scores TWELVE hits in its final block. ELEVEN ARE MY OWN AUDIT NARRATION: does not reproduce, is not verifying that it is MOUNTED, 14 was never the number, the split is NOT recent-versus-old, what I CANNOT re-measure stated rather than guessed. THE TWELFTH SAYS, IN TERMS, THAT NOTHING WAITS ON ISAAC. So the thread ranking first on an unresolved-newest-block ranking is one whose newest block declares itself resolved.

AND THE LAW SCORES ITSELF. The sentence A COUNT WHOSE UNIT REQUIRES A JUDGMENT CALL DOES NOT REPRODUCE - the law I earned last pass - matches the negated-action family and counts as an unresolved half. A finding written as a negation is indistinguishable to this instrument from a gap.

WHY IT IS WORSE THAN THE FOURTH PROPERTY ALREADY RECORDED. That property says narration about what was deliberately not done is indistinguishable from a named gap, which is a PRECISION problem, static. This is a FEEDBACK problem, dynamic: the audit pass MANUFACTURES the hits that promote the thread it just closed, so the ranking degrades every time it is used, and it degrades toward re-serving finished work in preference to threads never touched. A careful audit is written in negations, so the BETTER the audit the HIGHER the false rank.

THE CURE, TESTED NOT PROPOSED: exclude any note whose final block you wrote yourself. Excluding the fourteen notes whose final block is dated today drops the ceiling to a flat four hits and the audit-authored threads vanish from the top entirely. 187 uncited multi-block notes, 14 audit-authored.

AND THE CURSOR LIST WAS A SAMPLE. With the cure applied the four-hit band holds SEVENTEEN threads, not five. The cursor named Deconfab_Requirements_Sweep, Fix_4_Logic_To_Dchains, Fix_Completion_Deconfab, Treeshell_Carton_Integration_State_Map and Unification_Skill_To_Sm - all five real, all five still open, and twelve more beside them including Vault_Ontology_Erasure, Starlog_Merge, Publishing_Distribution_Layer and a second Gnosys_E2E_V1_Goal note. That is Instrument_Built_From_The_Sample_Inherits_Its_Bias firing on the cursor own shortlist.

MY OWN MATCHER FAILED ITS FIRST CONTROL AND THE CONTROL IS WHY I KNOW. I wrote a task-coverage matcher that walked coordinate suffixes but stopped two segments early, so it never tested the bare subdomain - and the tasks cite the bare subdomain. Graph_Availability, which task 27 plainly names, came back UNCITED. A positive control caught it on the first run. Uncured it would have reported cited threads as backlog, which is the same false-alarm shape as the repo-move parity split.

READ-ONLY THROUGHOUT: raw driver, stored bytes, no writes to the store, nothing posted to the validator.  tags:[instrument-reliability, shortlist-ranking]
- [v2]  2026-08-22T20:39:00  FINDING: FINDING: A LOUD FAILURE RENDERED SILENT BY MY OWN TRUNCATION - I turned an exit-2 error into what read as a success echo, twice, and then wrote the false claim into two commit messages.

WHAT HAPPENED. I updated the cursor three times this pass using --last-gate and --open-fork. The real flags are --gate and --open. Every one of those writes FAILED. Only --pathway, which I happened to spell correctly, ever landed. I discovered it only when a later git commit reported nothing staged - the file was byte-identical to HEAD because nothing had been written to it.

THE CLI IS NOT AT FAULT AND I CHECKED RATHER THAN ASSUMING. It uses parse_args, not parse_known_args, so an unknown flag is a hard error. Probed directly: it prints usage, prints unrecognized arguments, and exits 2. Correct behaviour, loudly.

THE MECHANISM IS MINE AND IT IS THE PART WORTH CARRYING. Argparse ECHOES THE ENTIRE UNRECOGNIZED ARGUMENT back inside its error text. My argument was many lines of prose. I piped the command through tail -1. So the last line of the ERROR was the last line of MY OWN TEXT - which is exactly what a success echo from this CLI looks like, because on success it prints the whole cursor and my text is the last field. Two indistinguishable outputs, and I never looked at the exit code.

SO THE TRUNCATION DID THE DAMAGE, NOT THE ERROR. The system told me clearly and I filtered the telling out. tail -1 on a command whose error quotes a multi-line argument shows you your own words back, and your own words are the thing you are least likely to read skeptically.

WHAT IT COST: two commit messages this pass assert the cursor was rewritten whole. Both are false as written. I cannot rewrite pushed history and would not, so the correction lives in the cursor own last_gate, ahead of the claim, and in the message of the commit that actually landed it.

THE DISCIPLINE, general past this CLI: NEVER PIPE A WRITE COMMAND THROUGH tail, AND CHECK THE EXIT CODE. If output volume is the reason for the pipe, send stdout to /dev/null and print the exit code, then VERIFY BY READ-BACK - which is what I did to fix it, and both fields are now confirmed present in the stored cursor rather than assumed from an echo.

IT IS THE SAME FAMILY AS THE OTHER FALSE-NEGATIVES THIS PASS, and that is three in one session from three different layers: a phrase search defeated by auto-linking, a coverage matcher defeated by an early-terminating suffix walk, and now a shell pipeline defeated by an error that quotes its input. Each produced a confident, well-formed, WRONG answer, and each was caught by a cheap check I nearly skipped.  tags:[instrument-reliability, shell-discipline]
