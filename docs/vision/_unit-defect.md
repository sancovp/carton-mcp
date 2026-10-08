# vision: parity (topic — auto-created by `journal`)

<!-- ===VISION DELTA: id-tagged appends below = the gap (`vision diff <m>`); `doc-mirror-commit --realizes <ids>` drops them on build === -->
- [v1]  2026-08-22T21:12:43  FINDING: FINDING: THE THREE-SURFACE PARITY CHECK HAS A UNIT DEFECT THAT HAS BEEN INVISIBLE FOR EIGHT PASSES, AND IT MANUFACTURED A THREE-ENTRY DATA-LOSS ALARM THAT WAS FALSE. Second false alarm caught this pass, same shape as the first.

WHAT I SAW. Running parity on the two repos I wrote, carton-mcp came back clean at 170 graph equals 170 flat equals 170 git. carton-saas came back graph 48 against flat 51 and git 51 - a three-entry gap, which is exactly the shape of the dead-lettered-write defect this record has measured before.

I CHECKED THE DEAD-LETTER QUEUE AND THE PAYLOADS WERE NOT THERE. I was one step from concluding that the failed directory is itself lossy - that a write can be dropped without leaving a payload - which would have been a serious claim about the durability layer and would have undermined the recorded retry procedure that keys on those payloads.

THEN THE PATTERN WAS TOO CLEAN TO IGNORE. All three missing entries were type COMMIT, while the FINDING entries interleaved between them at 22:14, 22:56 and 23:02 were all present. A loss caused by a connectivity window does not sort by entry type. So I counted by type instead of investigating further: the flat file holds 38 FINDING, 5 DECISION, 4 INTENT, 1 OPEN and EXACTLY 3 COMMIT. 38 plus 5 plus 4 plus 1 is 48, which is the graph count exactly, and the 3 COMMIT entries are exactly the 3 that were missing.

SO IT IS BY DESIGN AND NOT A LOSS. The journal rules say it plainly - a COMMIT-type entry projects to THE COMMIT BODY. It is a flat-file and changelog record, not a graph record. Nothing was dropped, the dead-letter directory is not implicated, and I withdraw the inference I nearly published about it.

THE INSTRUMENT DEFECT IS REAL EVEN THOUGH THE ALARM WAS FALSE: my parity check counts ALL entry types on the flat side and only graph-PROJECTED types on the graph side. Those are two different populations, so the comparison is only valid where they happen to coincide.

AND HERE IS WHY IT SURVIVED EIGHT PASSES OF CLEAN RESULTS. I measured every repo this record has ever parity-checked: carton-mcp 170 entries with ZERO COMMIT, scalable-publishing 249 with ZERO, doc-mirror-system 20 with ZERO. carton-saas is the FIRST repo I have parity-checked that contains any COMMIT entries at all - three of them - and it produced a false gap on the first contact. A latent unit defect in a check that has passed eight times is indistinguishable from a correct check until the population changes underneath it.

THE CORRECTED PARITY FOR carton-saas: graph 48 equals non-COMMIT flat 48 equals non-COMMIT git 48. It is CLEAN. The corrected instrument excludes COMMIT on the flat side, and the honest statement of the unit is journal entries that project to the graph, which is every type except COMMIT.

A SEPARATE AND REAL MEASUREMENT, recorded because the cursor carries a stale number: THE DEAD-LETTER BASELINE IS NO LONGER 1675. It is 1977, and the newest payload is stamped 20:45:40 TODAY, during this very session, between my rehydration and my first journal write. All 302 of the new ones are source precompact - raw Tool_Call and Agent_Message timeline nodes from this session own compaction at 19:53:54 - and ZERO are journal-CLI payloads, so the thinklog is intact. neo4j RestartCount moved 173 to 174, which is the connectivity window that caused it. Per the recorded mechanism precompact is INCREMENTAL PER SESSION, so a later compaction in this same session re-queues these and they self-heal; that is how 2026-08-11 recovered all 55 of its drops.

MY OWN WRITES WERE VERIFIED RATHER THAN ASSUMED, because they bracket that window: all seven nodes I created this pass - four concepts and three journal entries - are present, ZERO hollow, all seven carrying substantive descriptions. I tested description-not-null rather than name-exists, per the recorded law that a linker-minted shell answers a name check.

AND MY OWN DIFF TOOL FAILED FIRST, caught by its output being nonsense rather than by care: I extracted the trailing timestamp with a rsplit on underscore-two-zero, which also splits inside the TIME - fifteen twenty thirty-seven contains it - so it produced garbage keys and reported five false misses plus two entries that do not exist. An anchored regex on the trailing timestamp gave the true answer of three. The instrument was wrong before the finding was.

THE THROUGH-LINE OF THIS PASS, now three for three: EVERY ALARM I NEARLY PUBLISHED WAS FALSE, AND EACH WAS KILLED BY ONE CHEAP CHECK - a task-count regex that collapsed space-padded ids, a stale premise about the quota gate killed by an unexplained zero, and now a parity unit defect killed by counting entries by type. Wanting a finding is exactly when a checker stops checking, and the direction of all three errors was the same: reporting a working system as broken.

READ-ONLY THROUGHOUT except this entry: cypher reads, filesystem reads, no writes to the store, nothing retried, no payload marked fixed.  tags:[parity, dead-letter, unit-defect]
