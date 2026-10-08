# vision: instrument-reliability (topic — auto-created by `journal`)

<!-- ===VISION DELTA: id-tagged appends below = the gap (`vision diff <m>`); `doc-mirror-commit --realizes <ids>` drops them on build === -->
- [v1]  2026-08-22T20:39:00  FINDING: FINDING: A LOUD FAILURE RENDERED SILENT BY MY OWN TRUNCATION - I turned an exit-2 error into what read as a success echo, twice, and then wrote the false claim into two commit messages.

WHAT HAPPENED. I updated the cursor three times this pass using --last-gate and --open-fork. The real flags are --gate and --open. Every one of those writes FAILED. Only --pathway, which I happened to spell correctly, ever landed. I discovered it only when a later git commit reported nothing staged - the file was byte-identical to HEAD because nothing had been written to it.

THE CLI IS NOT AT FAULT AND I CHECKED RATHER THAN ASSUMING. It uses parse_args, not parse_known_args, so an unknown flag is a hard error. Probed directly: it prints usage, prints unrecognized arguments, and exits 2. Correct behaviour, loudly.

THE MECHANISM IS MINE AND IT IS THE PART WORTH CARRYING. Argparse ECHOES THE ENTIRE UNRECOGNIZED ARGUMENT back inside its error text. My argument was many lines of prose. I piped the command through tail -1. So the last line of the ERROR was the last line of MY OWN TEXT - which is exactly what a success echo from this CLI looks like, because on success it prints the whole cursor and my text is the last field. Two indistinguishable outputs, and I never looked at the exit code.

SO THE TRUNCATION DID THE DAMAGE, NOT THE ERROR. The system told me clearly and I filtered the telling out. tail -1 on a command whose error quotes a multi-line argument shows you your own words back, and your own words are the thing you are least likely to read skeptically.

WHAT IT COST: two commit messages this pass assert the cursor was rewritten whole. Both are false as written. I cannot rewrite pushed history and would not, so the correction lives in the cursor own last_gate, ahead of the claim, and in the message of the commit that actually landed it.

THE DISCIPLINE, general past this CLI: NEVER PIPE A WRITE COMMAND THROUGH tail, AND CHECK THE EXIT CODE. If output volume is the reason for the pipe, send stdout to /dev/null and print the exit code, then VERIFY BY READ-BACK - which is what I did to fix it, and both fields are now confirmed present in the stored cursor rather than assumed from an echo.

IT IS THE SAME FAMILY AS THE OTHER FALSE-NEGATIVES THIS PASS, and that is three in one session from three different layers: a phrase search defeated by auto-linking, a coverage matcher defeated by an early-terminating suffix walk, and now a shell pipeline defeated by an error that quotes its input. Each produced a confident, well-formed, WRONG answer, and each was caught by a cheap check I nearly skipped.  tags:[instrument-reliability, shell-discipline]
