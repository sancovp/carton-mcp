---
name: make-a-neuromorphic-system
description: "WHAT: design a brain for a thing with the neuromorphic SDK on carton, and vault it. WHEN: making a neuromorphic system or using NeuromorphicComputer."
---

# make-a-neuromorphic-system

**In full:** WHAT: how to make a neuromorphic system on carton — design a brain for a thing with the neuromorphic SDK (spreading activation, Hebbian wiring, growth cones, warrant plasticity, the three learning loops, softmax bandits, d-chains firing on completion), run it in the lab or over the real graph, and vault it into SOMA. WHEN: making a neuromorphic system, designing a brain for a thing, using the neuromorphic SDK or NeuromorphicComputer, wiring softmax or d-chains into a choice point, deciding warrant/decay/potentiation on edges, running a Brain over carton, or vaulting a computer organization.

**Measured 2026-08-09: the SDK read in full (`knowledge/carton-mcp/neuromorphic/` — computer,
substrate, dto, loops + 3 suites), lab suites 13/13 + 13/13, the host adapter proven 16/16 on the
real graph (commit 66a69c45e), the warrant field live on sm_gate edges (commit dc0a9d5b4).**

## THE DEFINITION (Isaac 2026-08-09, near-verbatim — what makes a system neuromorphic)

The main difference between neuro and not-neuro: **neuro is MASSIVELY OVERLOADING EVERYTHING WITH
SOFTMAX OR D-CHAINS EVERYWHERE.** The bandit is entirely made from softmax or d-chains, and then
just FIRES STUFF AS IT COMPLETES. The main chain runs through FORWARD, and as it goes it COMPLETES
PARTIALS; the completions KICK OFF D-CHAINS for whatever types they are, and this keeps DOGFOODING
as SOMA keeps FANNING OUT to whomever it needs llm_expert-wise. The two primitives already exist
proven: softmax selection (sm_gate `select_branch`; loops.py `SoftmaxBandit`) and d-chains (SOMA's
validation + release machinery). Overloading = every choice point becomes one of the two.

## THE MACHINE MAP — carton's mechanisms ARE the neuroanatomy (computer.py's five verbs)

| verb | carton mechanism it exposes | law |
|---|---|---|
| `wire_by_comention` / `describe` | the AUTOLINKER as Hebbian synapse formation | born COLD — association is not operation |
| growth cones (`toward:<name>`) | the AUTO-STUBS as demands the graph grows toward | arrival resolves the cone into cold wiring |
| `fire` | spreading activation (traversal, not querying) | conducts over WARRANTED wiring only, gated by an inhibition seat — ungated association is literally the hallucination failure mode |
| `potentiate` / `decay` | warrant IS the plasticity rule | evidence recorded VERBATIM, never defaulted; unwarranted wiring decays toward pruning |
| `grade` / `to_observations` | self-grading + the SOMA vault bridge | gaps are NAMED (the mereo-fill architecture at SDK grain) |

## THE PROCEDURE — design a brain FOR a thing (dto.py `design_brain`)

Not a model OF the thing — a design surface that AIMS the machinery AT a subject. Produce a
**thing reading** (a body scan, every value provenance-traced, absence left absent — the reader
precedent is `soma_prolog.extractor.read_thing`): `{name, strata, regions, io, speech, apex}`.
Then `design_brain(reading)` composes, adding NO machinery:

1. **LAY ANATOMY** — strata + regions from the thing's structure ("gross anatomy").
2. **ATTACH CHANNELS** — the thing's I/O surfaces become afferents (seats) and motor connectors.
3. **LET EXPERIENCE WIRE** — `describe()` grows Hebbian synapses from the thing's OWN
   speech/documents (born cold), growth cones toward what the docs demand but the thing lacks.

The `Brain` carries `.apex()` (the 7-part hyper_agent completeness condition — graph_residence,
gate, percept_channel, motor_connector, heartbeat, ratchet, governor_seat — filled IFF read, never
staged), `.checkup()` (the honest sentence: "perceives, acts; cannot ratchet; cortex is COLD"),
and `.to_observations()` (the SOMA vault payload). **Instantiation IS neurodevelopment**: a tenant
= a brain grown from the same plan; the moat is the wiring only that tenant's operation could have
grown.

## THE WARRANT DISCIPLINE (the plasticity law — now live carton-side)

Everything is born cold; only LIVED OPERATION warrants. Evidence is recorded verbatim and never
defaulted; an empty warrant refuses to potentiate; a MOCK-tagged warrant is HARD-REFUSED from
moving real weights (the B5 law, `loops.py`). This is live on carton's own edges since
2026-08-09: `sm_gate.reinforce_transition(..., warrant=...)` records `r.warrant`+`r.warrant_at`
on the NEXT_STEP edge, and `auto_progress` passes real lived-traversal evidence (actor + matched
pattern) — so warranted wiring is distinguishable from born-cold wiring, which is what makes
`fire`-over-warranted-only and decay-of-cold-autolinker-synapses buildable.

## THE THREE LOOPS (loops.py `LearningMachine` — one machine, three learning loops)

- **INNER / routing** — the sm_gate mechanic verbatim: a non-match is REFUSED with pattern +
  instruction (the refusal IS the instruction); a match advances through a pluggable selector over
  ADMISSIBLE (warranted) transitions — `argmax_weight` or `SoftmaxBandit(pressure, mutation_rate)`.
- **MIDDLE / plasticity** — `reward()` moves weight on the traversed path ONLY with warrant.
- **OUTER / neurogenesis** — `evolve_topology()`: GP (lfpoop) over the machine's OWN config; a
  GP-proposed transition enters COLD and physically cannot conduct until `apply_champion()` gets
  an EXTERNAL handler acceptance — **the machine cannot crown its own rewiring** (the catastrophe
  guard as conduction law). The whole machine is DATA (`to_data`/`from_data`).

## SUBSTRATES — where the brain runs

- **`InMemorySubstrate`** — the lab. A REAL run, not a mock: identity = the connectivity pattern.
  The lab never touches production neo4j (hard rule).
- **`CartonSubstrate`** — the host, over the REAL graph on the direct-cypher lane (synchronous,
  read-after-write; NOT the observation queue). Proven 16/16 incl. substrate-swap identity
  (`neuromorphic/test_carton_substrate.py`). Its shape: write-through edge attrs (in-place
  `potentiate`/`decay` persist), growth cones as `neuro_stub` marker nodes (arrival = `add_node`
  clears it), `neuro:true` scoping (the computer never sees or mutates carton's IS_A/PART_OF web;
  `has_node`/`node` DO see real concepts — co-mention against the real graph is a feature).
  KNOWN BOUNDS: `node()` returns a snapshot, not a live dict (`LearningMachine` mutates node
  dicts and pins InMemory deliberately); names land in the shared `:Wiki` namespace (use
  distinctive names; tests use unique prefixes + cleanup); `loops.py` needs lfpoop at
  `~/repo/lfpoop` (public, cloned here 2026-08-09).

## GAPS ARE FILL SIGNALS (the same architecture as SOMA's mereo)

`grade()` names what is missing — unresolved growth cones, regions with no afferents, unwarranted
wiring — and the SOMA side re-derives the same gaps as d-chains once vaulted. Route each gap to
the carton skill that fills it (breadcrumbs, never repetition): modelling the thing's concepts →
`model-anything-in-carton`; making its types real → `declare-a-soma-type` /
`vault-a-library-into-soma`; where a projection should fire → `carton-projection-flows`.

## VAULTING (to_observations → SOMA)

`brain.to_observations()` emits the /event wire shape (regions as `cortical_region`, wiring with
warrant, channels, the apex instance). **ORDER MATTERS**: connectivity FIRST, regions LAST — the
engine checks concepts sequentially within an event, so a region's afferent grade must see its
wiring already asserted (found empirically 2026-07-26). The SOMA-side types live in
`base/soma-prolog` foundation (`computer.py`, `computer_projector.py`).

## Cross-refs (breadcrumbs — the single-source law from issue 140)

`model-anything-in-carton` rung 5 (the SM semantics + warrant note) · `carton-write-channels`
(which surface sees what) · `vault-a-library-into-soma` (the vault dev-flow) ·
`edit-soma-validation` (touching SOMA's side) · the design web: `Neuromorphic_Core_Collection`
(activate it — 11 members, the full design incl. this skill's plan).
