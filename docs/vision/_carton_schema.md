# vision: dead_letter (topic — auto-created by `journal`)

<!-- ===VISION DELTA: id-tagged appends below = the gap (`vision diff <m>`); `doc-mirror-commit --realizes <ids>` drops them on build === -->
- [v1]  2026-08-22T18:47:43  FINDING: FINDING: I CAUGHT THE DEAD-LETTER MECHANISM FIRING LIVE, WITH THE WINDOW AND ITS CASUALTY MEASURED TWO SECONDS APART FROM TWO INDEPENDENT SURFACES - and then a hazard it exposed turned out, on measurement, to be one case rather than the systemic contamination I was one step from reporting.

THE CATCH. Dead-letters moved 1674 to 1675 DURING this pass. I noticed only because I now prove quiet with an ordering property rather than an equal count - the newest mtime, which last pass I made the standing check. The count alone would have read as a one-file drift; the mtime said it happened while I was working.

THE MECHANISM CLOSES EXACTLY. The dropped payload is stamped 18:29:35 and is a session_start conversation placeholder for THIS session. neo4j RestartCount went 172 to 173 with StartedAt 18:29:33. TWO SECONDS. Connectivity_Window_Dead_Letters_Graph_Writes has been an inferred mechanism in this record until now; this is the first time the window and the casualty have been measured against each other from two surfaces that know nothing of one another - docker inspect on one side, a queue file mtime on the other.

THEN THE PART THAT NEARLY BECAME A WRONG HEADLINE. Checking whether the dropped node was absent, I found a node WITH THAT EXACT NAME already in the graph - and it is HOLLOW: properties n and linked only, description NULL, no timestamp, no edges. It was minted by the AUTO-LINKER from a mention elsewhere, not by the payload. THE HAZARD IS REAL AND SHARP: the recorded retry discipline says retry ONLY payloads whose node is currently ABSENT, and absence is tested BY NAME. A hollow linker-minted shell answers that test as PRESENT, so a real dropped payload would be skipped permanently while its content is gone.

BUT THE SCOPE IS NOT WHAT I ASSUMED, AND I MEASURED BEFORE REPORTING. I extracted all 1349 distinct concept names from the 1675 dead-letter payloads and intersected them against all 758 distinct hollow names in the graph. THE INTERSECTION IS EXACTLY ONE - the node created minutes ago. So task 21 measured split of 729 absent against 619 present stands essentially intact; it is not contaminated. The reason is mechanical: the auto-linker only mints a shell when the name is MENTIONED in some description, and old precompact names like User_Message stamps are almost never written into prose.

I WANTED IT TO GO THE OTHER WAY. A systemic finding would have invalidated a number I have been carrying for passes, and that is exactly the moment a checker stops checking. It is one of 1349.

WHAT SURVIVES AS A CORRECTION ANYWAY, because the hazard fires precisely where it hurts most: the presence test in any future retry should be description-IS-NOT-NULL, not name-exists. The shell appears for RECENT drops - the ones still mentioned in live prose - which are the drops most likely to carry content someone still needs. A rule that is safe across 1348 old names and unsafe on the newest one is not safe.

ALSO CONFIRMED IN PASSING: 1349 distinct names against task 21 measured 1348, a difference of exactly one, which is the payload that dropped today. The arithmetic checks from both directions.

ALL FOUR OF MY OWN WRITES THIS PASS LANDED AND WERE VERIFIED ON THE STORE, not assumed: three new concepts present with content, and the Defect_Class correction applied with its stale span counting ZERO and kv_edit_error null - the success path clearing a stale error exactly as the code says.  tags:[dead_letter, neo4j_restart, carton_schema]
