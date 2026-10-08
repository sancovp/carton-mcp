---
name: build-and-activate-a-bundle
description: "WHAT: roll a neighborhood of CartON concepts into a collection to activate later. WHEN: concepts about one thing should be retrievable as one unit."
---

# build-and-activate-a-bundle

**In full:** WHAT: how to roll a neighborhood of CartON concepts into a Carton_Collection (a bundle) and activate it next session as the retrieval flow — membership discipline, the measured activation constraints, verification of adds, and the remember-it-by-name law. WHEN: a set of concepts about one thing exists loose on the graph and should be retrievable as one unit; starting work that an existing collection could rehydrate; after saying new entailments about a thing that already has a collection; a collection activation returned a huge blast or missing members.

**Every constraint below was MEASURED live 2026-08-06 (the collection findings, journaled at
Carton_Carton_Skillset_Shape), not read off the code — including one where a locally-correct
code-reading produced the WRONG conclusion and a probe corrected it.**

## What a bundle is

A `Carton_Collection` concept whose `HAS_PART` members are the concepts you want retrievable as
ONE unit. **The collection IS the retrieval flow** for that thing: `activate_collection` replaces
re-reading the sources. Building it is the work, not cleanup after the work.

## BUILD

1. `create_collection(collection_name, description, member_concepts, collection_type)` — types:
   global / local (default) / identity.
2. `add_to_collection(collection_name, concept_names)` grows it.
3. **Inverses take care of themselves** [proven by probe]: the observation worker daemon carries
   an `inverse_map` that reciprocates `HAS_PART ↔ PART_OF` on every queue drain. (A code-reading
   that concluded otherwise from `create_collection`'s dead inverse MERGE was WRONG — there were
   two writers, and only the probe found the second. The daemon is the live one.)

## THE MEMBERSHIP DISCIPLINE — leaf-ish or it explodes

`activate_collection` is **UNBOUNDED** [measured]: the `max_depth` parameter is DEAD (accepted,
never used — the Cypher hardcodes `HAS_PART*1..10`), and it returns FULL descriptions, not
previews. There is no depth knob to fall back on, so the only control you have is membership:

- Members must be **LEAF-ISH** — concepts whose own HAS_PART fan-out is small. One hub member
  pulls its entire subtree: the measured failure was a 1743-concept, 6.4 MB activation whose
  seeds were hubs.
- This is the read-time face of the universal-as-value law: hubs are manufactured at write time
  by particulars pointing at universals, and paid for at activation time. Same defect, two ends.

## VERIFY EVERY ADD — the return value lies

`add_to_collection` **reports the count you PASSED, not the count that matched** [measured: one
real + one bogus name → success message for two]. A misspelled or nonexistent name is silently
not added. After every add, verify by query:

```cypher
MATCH (c:Wiki {n:'<Collection>'})-[:HAS_PART]->(m:Wiki) RETURN m.n ORDER BY m.n
```

## REMEMBER IT BY NAME — an unremembered bundle is an unretrievable one

The collection's name must be recorded where the next lifetime will see it (the
`carton-roll-entailments-into-retrievable-collections` rule keeps the list). And the bundle is
CURRENT only if every new entailment you say about that thing is `add_to_collection`'d **in the
same breath** — said-but-not-added means the collection is STALE; fix on sight.

## ACTIVATE

`activate_collection(collection_name)` recursively pulls every member (and their HAS_PART
subtrees, to 10 hops) with full descriptions — this IS the rehydration for that thing. Prefer it
over re-deriving from sources; drill individual members with `get_concept` only where the
activation text is not enough. Remember `activate_collection` output DROPS properties (issue
139 — the props-propagation gap): a member whose state lives in properties needs a follow-up
`get_concept`/Cypher read for the state.

## Cross-refs

`model-anything-in-carton` (GATHER is this skill's one-paragraph form; the ladder that makes the
members worth bundling) · `carton-write-channels` (properties invisible to activation — the
matrix) · the `carton-roll-entailments-into-retrievable-collections` rule (the remember-by-name
law + the collection list).
