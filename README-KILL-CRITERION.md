# Aut Kill-Criterion — Phase 0 Verdict (Griess-constructor program; Isaac GO 2026-07-05)

**Run:** 2026-07-05, READ-ONLY against the live carton neo4j graph + the SOMA OWL world
(soma.owl + uarl.owl + starsystem.owl). Zero writes to neo4j, zero POSTs to SOMA.
**Ledger:** `aut_kill_criterion_ledger.tsv` (this directory).
**Code:** `aut_deducer.py` (library), `scripts/run_aut_kill_criterion.py` (the run),
`tests/test_aut_deducer.py` (11 deterministic tests, green).

## Summary block

```
classes examined: 124  (middle_strata=25, definition_bearing=99)
BITES:         0
NO_BITE:       0
THIN_DATA:     0
TRIVIAL_AUT:   124   (verdict added by the data — see below)
NO_DEFINITION: 0
```

## The honest verdict: the kill-criterion CANNOT ENGAGE yet — and that gates M2-M5 closed

Two measured facts (both verified independently of the deducer code, 2026-07-05):

1. **The current ontology's definitions carry NO repeated same-colored slots — anywhere.**
   An independent scan of all 297 OWL classes found **zero** classes with two restrictions sharing
   the same (predicate, kind+cardinality, target) color; every graph template's
   REQUIRES_RELATIONSHIP slots are pairwise-distinct predicates; the core-sentence slots
   (is_a/part_of/instantiates/produces) are four distinct predicates. A slot's color includes its
   predicate, so **Aut_formal(C) is the trivial group for every class examined (124/124)** — there
   is no formal symmetry for provenance to confirm or refute.

2. **The FILLED_FROM provenance substrate is EMPTY: 0 edges graph-wide** (measured by Cypher).
   Even if nontrivial orbits existed, substitution could not be tested — every class would be
   THIN_DATA. The substrate code exists (`soma_fillers.record_fill_provenance`) but no fills have
   been recorded into the live graph yet.

Per the brief's own discipline ("if NO_BITE dominates, the program stops here"): the distribution
is not NO_BITE (that verdict requires nontrivial orbits + rich provenance + zero substitution) —
it is **stronger than NO_BITE for phase 0: there is nothing for the criterion to bite ON.** The
program does **not** proceed to M2-M5 on this evidence.

What could change this (stated so the stop is honest, not frozen — re-run the script to re-check):
- definitions that declare **repeated same-colored slots** (e.g. min-cardinality > 1 part slots
  atomized to multiple HAS_REQUIRED_PART parts of the same type — that edge type currently has
  **zero** instances in the live graph);
- a **populated FILLED_FROM substrate** (fills actually recorded), so substitution becomes testable.

## Middle-strata caveat (the spec's selection, measured)

The middle strata (`region IN {code, system_type}`, 441 nodes live) turned out to be treeshell
node concepts and test probes: **zero** of them carry REQUIRES_RELATIONSHIP or OWL definitions;
their only slots are the 4 universal core-sentence declarations (hence slot_count=4, TRIVIAL_AUT
in the ledger). The `definition_bearing` cohort (7 graph templates + every restriction-bearing OWL
class) was added so the ledger evaluates classes that HAVE definitions — labeled per row, reported
as a deviation, not hidden.

## Example rows (from the ledger)

| class | slots | aut_order | orbits | note |
|---|---|---|---|---|
| Skillspec_Template | 13 | 1 | 13 singletons | 9 REQUIRES_RELATIONSHIP (Has_Domain … Has_Starsystem) + 4 core-sentence |
| Skill_Template | 26 | 1 | 26 singletons | 22 REQUIRES_RELATIONSHIP + 4 core-sentence |
| Event | 7 | 1 | 7 singletons | both surfaces compose: 3 OWL restrictions (hasObservation min 1, hasTimestamp exactly 1, producedBy exactly 1) + 4 core-sentence |

## Soundness restriction (carried structurally on every output)

`restriction_R`: Aut_formal is computed over the slots **as expressible in the current ontology**;
soundness Aut_true ⊆ Aut_formal — the ontology cannot distinguish what it cannot express. Textual
claims derived from these outputs grade G4-G5, never G1.

## Reproduce

```
pip install --no-deps .                      # carton_mcp maps to this repo root
python3 scripts/run_aut_kill_criterion.py --n 25
python3 tests/test_aut_deducer.py            # script-style; or pytest on the file from a
                                             # directory OUTSIDE this repo's package ancestry
                                             # (the repo-root __init__.py breaks in-tree pytest
                                             # collection repo-wide — pre-existing condition)
```
