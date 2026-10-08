---
name: atomize-a-seed
description: "WHAT: decompose a seed thing into its part concepts on CartON, with the stop rule. WHEN: a big undifferentiated thing on the graph needs structure."
---

# atomize-a-seed

**In full:** WHAT: how to recursively decompose any seed thing (a document, a blob concept, a pasted design, a dense description) into its part concepts on CartON — with the STOP RULE: stop when the next parts would be uniform across all decompositions, never recurse to the bottom. The traced part-web spans the seed's EWS. WHEN: a big undifferentiated thing landed on the graph and needs real structure; after split_content_concept left a content node to decompose; harvesting a document into claim atoms; deciding how deep to decompose anything; a decomposition that keeps recursing without converging.

## THE DEFINITION [Isaac, 2026-08-09, near-verbatim]

Atomize means to decompose into parts recursively. This is NOT the whole
"until-D∞-closure-of-the-beginning" recursion — it is: **recursively decompose until the next
part is uniform across all decompositions.** The lfp of general decomposition = stop, because
some point EARLIER was the actual selection you want. From another pov, this is **spanning the
EWS.**

## THE STOP RULE (the whole skill — everything else is mechanics)

Decompose the seed into parts; recurse into each part; **stop the moment the parts you would
produce NEXT are no longer specific to the seed** — when every branch's next decomposition yields
the same generic substrate (words, sentences, primitives, foundation types). Uniformity is the
signal you have gone one level too far: **the level BEFORE uniformity is the atom level.** The
atoms are the actual selection; the part-web you traced is the seed's EWS (interior = the
decomposed levels; frontier = the atoms, whose further parts go uniform).

The tell you crossed the line: two DIFFERENT branches decompose into the SAME next-level parts.
Back up one level.

The tell you stopped too early: an "atom" still contains parts that would discriminate — a
paragraph holding three separable claims, a component holding two unrelated behaviors.

**Corroboration in the code you already run** [read from code]: SOMA's recursive walkers —
`find_weak_compression_target` and mechanism C's `could_instantiate` — bottom out at
`is_known_type`, the read-side stop at the same uniform substrate. Atomizing is the WRITE-side
dual of that read-side stop: you author the part-web down to exactly where the walkers stop
walking.

## THE MECHANICS (each atom rides the modelling ladder)

1. **Seed intake.** If the seed is raw content sitting in a description, `split_content_concept`
   it first — its own docstring leaves atomization as the caller's judgment step; this skill IS
   that step. If the seed is a document on disk, ingest it as a `Source_Document` node first (the
   receipts anchor).
2. **Decompose one level, breadth-complete** (SOT: the whole seed at one grain before descending).
   Each part becomes its OWN concept: `add_concept` with `part_of` → the seed (or the intermediate
   part), every field DERIVED from what that part actually is — never stamped. One level down may
   be auto-stubs; the level you are authoring may not.
3. **Apply the stop rule per branch.** Branches reach uniformity at different depths — a document's
   claims stop at one level; a system's components may go three. Do not force uniform depth.
4. **Receipts for harvested content** [the proven instance, 2026-08-02]: a document atomizes into
   claim atoms — each `is_a Claim`, `part_of` the source, `has_receipt` → the Source_Document,
   approval flags untouched — plus ONE thin index node. Keep a NO-MATCH LEDGER: every section NOT
   emitted, with why (meta-framing, illustration-of, restatement-of) — the ledger is what makes
   "atomized" checkable instead of claimed.
5. **GATHER when done**: roll the atom set into a collection (`build-and-activate-a-bundle`) so the
   decomposition is retrievable as one unit. Atoms are leaf-ish by construction — that is exactly
   what the membership discipline wants.

## WHAT ATOMIZING IS NOT

- Not full-depth recursion: never decompose atoms into the uniform substrate "for completeness" —
  past the lfp you add nodes that carry zero distinguishing information (the flat-stub disease).
- Not summarizing: atoms are the seed's OWN parts, verbatim-faithful, not compressions of them.
- Not typing: atomize gives PARTS; declaring any part's type is rung 3 of
  `model-anything-in-carton` and follows its stopping rule separately.

## Cross-refs

`model-anything-in-carton` (each atom's core sentence; rung 2's stub-evolution is atomize seen
from the fill side) · `build-and-activate-a-bundle` (gather the atoms) · `carton-write-channels`
(which channel each atom's content goes in) · `split_content_concept` (the intake step for
blob-descriptions) · the webbing agent (`webbing_agent.py` — the automated batch form of this
skill for underdeveloped concepts; same recursion guard discipline).
