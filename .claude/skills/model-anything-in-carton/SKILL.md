---
name: model-anything-in-carton
description: "WHAT: the ladder for modelling any thing into CartON and integrating it with SOMA. WHEN: putting a new thing on the graph, or a concept sits in soup."
---

# model-anything-in-carton

**In full:** WHAT: the full ladder for modelling any thing into CartON and progressively integrating it with SOMA — say it, fill the mereo, DECLARE the types (define != declare), state into properties, state machines, d-chains on top. Includes the stopping rule (most things stay soup) and the stub-evolution loop. WHEN: putting any new thing on the graph; a concept grades mereo_error or sits in soup; deciding whether something needs a type, a d-chain, or nothing; evolving auto-created stubs; modelling a design, a system, a status, or a domain into carton.

**2026-08-09 — written hot from the session that proved the spine; rung 5 firmed same day from
full reads of sm_gate.py + the server wiring. Every claim marked [proven] was verified through
the live surface or a controlled pair; [stated] is Isaac's design ruling; [read from code] means
a full read, not a live fire. Re-derive nothing from reasoning that a probe can answer.**

Modelling is a LADDER you climb, not a form you fill. Most things stop at the bottom rungs — that
is correct, not lazy. The gradient: **say → fill → declare → state → machine → d-chains**.

## RUNG 0 — before you write: the checks

1. **Meaning or state?** Meaning is an EDGE (relationships). State is a PROPERTY. Prose is
   annotation only — a fact that exists only in `n.d` is invisible to every structural reader and
   to SOMA. [proven — the visibility matrix, `carton-write-channels`]
2. **The universal-as-value law** [stated, Isaac 2026-08-06; live evidence: the wrecked `Cave`
   hub]: universal-to-universal containment is legitimate; particular-to-universal is not.
   `X has_a Task_List` where X is a particular names a MISSING INSTANCE — mint the instance, have
   IT `instantiates Task_List`. Pointing particulars at universals smears the universal's
   definition and manufactures hubs (the read-time activation explosion is the same defect).
3. **Every field derived, never stamped.** `is_a`/`part_of`/`domain`/`subdomain` come from what
   THIS concept actually is. Identical fields across everything = typing that carries zero
   information.
4. **Coordinate names must not be concept names** [proven, the hard way]: a journal entry whose
   SUBDOMAIN shares a name with a real concept MERGES the axis node onto that concept — it then
   carries `is_a Doc_Mirror_Subdomain` and mereos on that claim. One namespace. Pick coordinate
   names that are not content names.

## RUNG 1 — SAY IT (soup is a legitimate resting state)

`add_concept` with the core sentence honestly derived. It lands, it is retrievable, SOMA grades
it. **Most things should stay here.** Soup is "said, not yet proven" — a real region, not a
failure. [stated — the architecture; proven daily]

The verdict comes back in the tool print. READ IT. `mereo_error` is a FILL SIGNAL naming exactly
what is missing — never a rejection. Only `contradiction` (two disjoint DOLCE branches) refuses.

## RUNG 2 — FILL THE MEREO (the stub-evolution loop)

Every relationship target you name mints an auto-stub (`AUTO CREATED: ... Not yet fully
defined`). **The stubs are the worklist, not debris** [stated, Isaac's tip 3]. The loop:

1. The verdict names an unknown type or an auto-stub surfaces in a network read.
2. Give the stub its own real core sentence (`add_concept` on the stub's name — it merges).
3. **If the stub is used as an `is_a` target, defining it is NOT enough — go to RUNG 3.**

## RUNG 3 — DECLARE THE TYPES (define != declare — the load-bearing rung)

[proven by controlled pair, 2026-08-09] A concept can grade SYSTEM_TYPE *for itself* and still be
unusable as an `is_a` target. `is_known_type/1` accepts exactly: a primitive, a seed fact, an OWL
class, or **`triple(T, is_a, system_type)` — the declaration.** Everything claiming `is_a` an
undeclared type sits in mereo forever, no matter how well you define the type.

- Code-backed type → `vault(Model)` (the `vault-a-library-into-soma` dev-flow).
- Abstract type → shell-declare: `is_a ["system_type", "<real DOLCE kind>"]`. Multi-is_a is safe —
  `is_code_typed` exempts system_types from DOLCE disjointness.
- Full mechanics + stopping rule: the **`declare-a-soma-type`** skill.
- **The stopping rule**: declare ONLY what other concepts will claim `is_a` against. The tell you
  need it: a claimant graded `mereo_error` naming your concept. Over-declaring makes `system_type`
  carry no information — ten doc-mirror bookkeeping kinds sitting in that namespace with zero
  required parts is the cautionary instance [proven 2026-08-05].
- Verify through a CLAIMANT, not the declaring call — the type's own verdict grades the type, not
  its usability. [proven]
- The fill signal itself now routes here: a mereo whose type exists at code+ says "add system_type
  to its is_a. Use the /declare-a-soma-type skill." [proven, deployed]

A declared type with no parts and no d-chains **admits any claimant** — SOMA validates it exactly
like code. Sometimes that is the point: the RESERVED ADDRESS pattern [stated, Isaac — the starlog
entry kinds; llm_expert]: declare the type now so the handling can be authored as words in carton
later. Empty is the point, not a defect — but say so in the concept.

## RUNG 4 — STATE INTO PROPERTIES

Anything that CHANGES lives in properties, never prose [stated — the property doctrine; the
status-phase rule]. Designs and specs especially: their state is properties. Two lanes: scratch
(status/order/gates/timestamps — sync, no SOMA trail) and trail (ontology-bearing classes also
emit a SOMA observation).

Caveats, all measured: `get_concept_network` and `activate_collection` DROP properties (issue
139) — a property-blind reader sees identity and no state. Seven system-written properties sit
beside yours (`source, linked, last_modified, score, timeline_linked, region, soma_region`).
`add_to_collection` reports the count you passed, not the count that matched — verify membership
by querying. [all proven]

## RUNG 5 — STATE MACHINES [read from code 2026-08-09: sm_gate.py + server_fastmcp.py wiring, in full]

Two different machines live at this rung — do not conflate them:

**5a. Status-phase modelling** (the simple case): phases are TOPOLOGY, the current phase is a
PROPERTY — a `Status_Phase_Table` (declared type). Documents reference the concept and read the
live value; they never freeze status as prose.

**5b. Retrieval state machines (sm_gate)** — an SM is GRAPH DATA you program through the same
`add_concept`/`set_properties` surface as everything else:
`State_Machine -HAS_STEP-> Traversal_Step -NEXT_STEP{weight, required_pattern}-> Traversal_Step`;
each step carries `required_pattern` (regex) + `text` (the instruction) as properties. A concept
is gated via a stack: `concept -HAS_SM_CHAIN-> Sm_Chain -SM_CHAIN_RUNS{order}-> State_Machine`,
and the ACTIVATION RULE is stack size: **>1 SM = gated; a single show-SM = OFF**. The per-actor
cursor is `actor -HAS_LIFECYCLE-> Execution_State{status} -CURRENT_STEP-> step`.

The semantics [all read from code]: a gated concept **never withholds content** — visiting it ARMS
a require-next (`⛓ REQUIRED NEXT` appended to the `get_concept` output), and the actor's NEXT
call must `re.search` the step's pattern or is refused, with the refusal message carrying the
pattern + instruction (the refusal IS the instruction). Multiple eligible branches are chosen by
softmax over edge weight, and the taken edge is reinforced +0.1 persisted on the graph — the SM
LEARNS its routing. Since 2026-08-09 the reinforcement also records a **warrant** on the edge
(`r.warrant` = the lived-traversal evidence verbatim — who traversed, which pattern matched —
plus `r.warrant_at`; an empty or mock-tagged warrant is refused from moving weights, the
neuromorphic B5 law), so warranted wiring is distinguishable from born-cold wiring. Every
lock/branch/refusal/unlock appends to `$HEAVEN_DATA_DIR/sm_episodes.jsonl` (training exhaust,
now carrying the warrant in `branch_chosen` records).

How you AUTHOR one → the **`dragonbones-state-machine-ec`** skill (the authoring half moved
there 2026-08-09 per the issue-140 per-EC disposition; it carries the TWO-LANE split — the
compiler lane reads 🏷 properties via `project_state_machine`, the inline treeshell lane reads
🟰 customs via `create_sm_chain_live` — plus the parallel-flat-lists branching idiom and the
required domain fields). Direct programmatic paths: `create_branching_sm` (MCP tool →
`create_sm_chain_live`), `skill_to_sm`.

Live status [checked 2026-08-09]: the gate wiring EXISTS on every read tool
(query_wiki_graph/get_concept/get_concept_network/chroma_query/…) but is **double default-off** —
it engages only when `/tmp/heaven_data/carton_sm_gate_enabled` exists (currently absent) and no
kill switch; unlocked actors pass; every fault FAILS OPEN. Programming an Sm_Chain today builds
real graph structure that gates nothing until the flag is set.

## RUNG 6 — D-CHAINS (what a signature cannot say)

The validity line [stated, Isaac 2026-08-05, after two of mine were retracted for crossing it]:
a d-chain constrains WHAT A TYPE SIGNATURE CANNOT SAY — conditional logic among a concept's own
fields, or cross-node requirements. An enum is a Literal; a required field is a signature. Neither
is EVER a d-chain — both belong on the Pydantic model where vault derives them. Every d-chain that
is secretly a type check is a counterexample to the neurosymbolic claim sitting in our own code.

Authoring: `add_dchain` per the `vault-a-library-into-soma` skill. Through dragonbones ECs
[stated, Isaac's tip 4 — "ideally"]: currently unreachable (the output-style is disconnect #4);
the self-extending path is the EC button, issue 140.

## GATHER — loose graphs → collections → collections of collections [stated, Isaac]

Once a neighborhood of concepts exists, roll it into a `Carton_Collection` so it is ACTIVATABLE
next session — the collection IS the retrieval flow. Measured constraints [all proven]:
activation is UNBOUNDED (the `max_depth` param is dead; hardcoded 10 hops; full descriptions
returned) so membership must be LEAF-ISH — a hub member pulls thousands of concepts. Verify adds
by querying, never by the return string. The daemon reciprocates `HAS_PART ↔ PART_OF` on drain,
so inverses take care of themselves.

## THE VERIFY DISCIPLINE (every rung)

The cheapest correction is a probe, not a harder read. [proven three times in one session: the
collection inverse chain — wrong; the in-slice is_a discriminator — wrong twice; each settled by
one live write.] Write a claimant, read it back through a surface that can SEE the channel you
wrote (`carton-write-channels` matrix), and treat your own causal chains from code as hypotheses.

## Cross-refs

`carton-write-channels` (the matrix + channel law) · `carton-projection-flows` (how a modelled
concept leaves the graph — projectors + which channel each reads) · `declare-a-soma-type` (rung 3 mechanics) ·
`vault-a-library-into-soma` (rung 3 code-backed + rung 6) · `understand-soma-programming` /
`understand-soma-vault-system` (the verdict machinery) · issues: 139 (props propagation),
140 (EC button), 123 (store fall-through), 124 (CA catalog), 129 (SOMA↔CA runtime link).
