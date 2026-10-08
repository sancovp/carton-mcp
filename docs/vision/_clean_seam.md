# vision: Compaction (topic — auto-created by `journal`)

<!-- ===VISION DELTA: id-tagged appends below = the gap (`vision diff <m>`); `doc-mirror-commit --realizes <ids>` drops them on build === -->
- [v1]  2026-08-22T10:19:52  DECISION: DECISION: COMPACTING AT 76 PERCENT ON A GENUINELY CLEAN SEAM, EARLIER THAN THE THRESHOLD AND ON PURPOSE.

THE SEAM IS UNAMBIGUOUS AND VERIFIED, not asserted: HEAD equals remote at d8d21b71b, every leg of this pass is committed and pushed, journal parity holds on every repo I touched, the queue is 0, the dead-letter count is steady at its 1674 baseline with nothing dropped across the whole pass, neo4j RestartCount has not moved from 172, and the only modified path in my working tree is a dispatch-pilot skill edit that predates this session by four days and is not mine.

WHY EARLIER THAN 85: the record own lesson from the last time is that a planned compact beats an unplanned one, and that a verification step at risk of being cut short by the resource it protects should happen EARLY in the budget rather than at the wall. Seven legs is a natural boundary, the cursor is rewritten WHOLE rather than appended to, and there is no half-finished edit anywhere.

WHY NO COLD CHECK, for the fourth pass running and for the same reason: my harness instructions say plainly not to call the Agent tool unless the user requested it, and Isaac has not. That is an instruction, not a tension to relitigate each cycle. The scheduling lesson stands for whenever it IS wanted.

WHAT IS RETIRED AND WILL NOT COME BACK: three threads this pass - Treekanban_Chrome_Join, Treekanban_Carton_Cutover and State_Read_Fan_Out - all verified landed against code and git before retiring, which is the first time this pass the load-bearing docmirror-done step was used at all.

WHAT THE NEXT LIFETIME INHERITS, and the through-line changed shape today. For four passes it was READ THE LAYER THAT HOLDS THE FACT. This pass adds the harder half: GREP IS LOCATE-ONLY AND CAN ONLY FIND THE MECHANISM YOU ALREADY IMAGINED. I searched heaven_base for three redirect mechanisms, got zero hits, and filed - in a task addressed to Isaac - that the repo own explanation was measurably WRONG. It was RIGHT. The real mechanism was a fourth I had not thought of, sitting in the first forty lines of the file under a comment naming its own purpose, and every probe I built inspected a layer that mechanism does not touch. READ THE FILE.

AND THE SECOND NEW ONE: REFRESH THE PREMISES OF AN OLD FORK BEFORE PUTTING IT IN FRONT OF HIM. Task 34 surfaced a five-day-old OPEN whose premises had moved in BOTH directions - the payload grew, one stated reason for its own recommendation had gone stale, and a fork discovered today made its recommended option strictly more expensive. He should decide on today numbers, not on the numbers that were true when the note was written.  tags:[Compaction, Clean_Seam]
