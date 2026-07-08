---
name: skill-carton-relationship-daemon-unwind
description: "WHAT: why CartON relationships are NOT immediately queryable right after add_concept — the node is created instantly but its relationships go through the daemon unwind, so Neo4j traversal queries against the just-created concept come back empty; query from already-committed parent concepts instead. WHEN: any time you query Neo4j right after writing a concept, a relationship you just added is missing from a traversal, or you are debugging timing of when graph data becomes available after a write."
---

CartON add_concept creates the node immediately but relationships go through daemon unwind — they are NOT available for Neo4j traversal queries immediately after add_concept returns. Query from PARENT concepts (already committed) instead of just-created concepts. Replayable skill pattern - understand=context only CartON persistent knowledge graph system Skill category classification Personal domain category enum for observation tagging CartON knowledge graph operations and timing When data is available after writes Relationships not immediately queryable after add_concept Any time you query Neo4j right after writing a concept Query from existing parent concepts not just-created ones

---
## Skill Contents

- `reference.md` — detailed reference (read for full docs)
