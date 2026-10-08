---
name: soma-help
description: "WHAT: what a CartON add_concept or get_concept result means and what to do. WHEN: a result says SOMA help, or has a DO line you cannot act on."
---

# soma-help

**In full:** WHAT: SOMA help, what a CartON add_concept or get_concept result means and what to do about it: the SOMA grade (MEREO, SOUP, CODE, SYSTEM_TYPE, ONT), d-chains pending, the MEREO[n], FILL[n] and SOUP[n] lines and their DO lines, D2, CB, CRITICAL, the DEATH block, REJECTED and REFUSED, hwss_domain, undefined_type_ref, failure_error, and which SOMA or CartON skill to use next. WHEN: when an add_concept result says SOMA help or carries a DO line you do not know how to act on, when the user mentions SOMA help, a SOMA verdict, soup, mereo, a d-chain, or asks what a carton result means (any of).

## The shape of a result

```
✅ X: CartON Files queued, Neo4j queued. Any lines starting DO at the end are the instructions and must be followed.
DEATH soup_system_types= ... DEATH end      only while a declared system type is soup
SOMA: <MEREO | SOUP | CODE | SYSTEM_TYPE>, <d-chains>
MEREO[1]: ...   FILL[1]: ...   SOUP[1]: ...   SOMA's own sentences, numbered
D2: ...
CB: region=... coord=...
<CB PROMPTER block>                          only with cb_guidance
CRITICAL ...
SOMA help: use the soma-help skill if you have not used it yet.
DO SOUP[1]: ...                              the instructions, last; each names its line by token
```

The first line says what CartON wrote. The middle lines are information. The DO lines at the end are what SOMA asks of the writer: follow each one. `DO SOUP[2]` acts on the line `SOUP[2]`; read that line for the detail. A DO line naming several tokens, such as `DO SOUP[2], SOUP[3]: ...`, gives the same instruction for each.

`get_concept` shows Name, Description with its coverage score, Props, Rels, then the same SOMA lines and the DO lines last. `get_concept(details=True)` adds SOMA's raw verdict above the DO lines.

## The grade line

| line | means |
|---|---|
| `SOMA: MEREO: not validly the type it claims, its execution failed; CartON keeps the write so it can be seen.` | the concept's own is_a names a type SOMA has no definition of, so the concept is not validly that type and its execution failed. CartON stores the write anyway, so the failure can be observed. Each such claim is a MEREO[n] line |
| `SOMA: SOUP: not validly the type it claims, its execution failed.` | the concept claims a type whose required parts it does not carry. Isaac 2026-09-29: SOUP IS THE MEREO ERROR — it is not validly that type and its execution failed; the missing param IS the rejection. CartON stores it, SOMA does not admit it. Each missing part is a SOUP[n] line |
| `SOMA: CODE, N d-chains pending` | the signature is filled: every key the type requires is present, so the entry works as a function that makes the thing it is. N d-chains have a requirement this concept does not meet yet |
| `SOMA: SYSTEM_TYPE, all d-chains satisfied` | code plus d-chains: it models and it fires, and no d-chain is pending |
| `SOMA: ONT` | every param is itself a declared type, all the way down |
| `SOMA error: ... The write was not graded.` | the SOMA call failed; the concept is saved ungraded |

A d-chain is a rule attached to a system type. Its premise succeeds when a requirement is met, and its conclusion fires when it is not.

## The numbered lines and their DO lines

Every DO line for a MEREO, FILL or SOUP line opens `this is important to fill next, but only if ... is inside the meaning you meant`. Isaac 2026-09-29, verbatim: *"you need to tell the AI this is important to fill next but only if it's inside of the meaning they meant. they shouldnt just merely expand it because SOMA says they can. SOMA will always say that."* So fill the named part when it is inside what you meant to say; when it is not, drop the claim that demands it (or leave another concept's gap alone) instead of expanding to satisfy SOMA.

| information line | DO line | do |
|---|---|---|
| `MEREO[n]: X is_a Y (not a known/defined type). X is not validly Y: its execution failed. ...` | `DO MEREO[n]: this is important to fill next, but only if Y is inside the meaning you meant: define Y (...); otherwise drop the is_a Y claim.` | `add_concept Y` with is_a, part_of, produces and instantiates when Y is what you meant; otherwise stop claiming `is_a Y`. Use `model-anything-in-carton` and `declare-a-soma-type` |
| `MEREO[n]: X is_a Y (defined but not DECLARED)` | `DO MEREO[n]: ... declare Y a type ...` | add `System_Type` to Y's is_a only when Y is code (its params exist) and is what you meant; otherwise drop the claim. Use `declare-a-soma-type` |
| `FILL[n]: X is_a Y, which is not a defined type. The claim does not demote X, a declared system type ...` | `DO FILL[n]: ... define Y ...` | as for MEREO: define Y or drop the claim; X keeps its grade meanwhile |
| `SOUP[n]: X claims to be T. T requires has_content, has_name (each string_value). X does not have them, so X is not validly T: its execution failed.` | `DO SOUP[n]: this is important to fill next, but only if it is inside the meaning you meant: add_concept X with properties has_content and has_name, each filled from what X is; otherwise drop the is_a T claim.` | give each param as a property: `properties={"has_content": "..."}`. A `has_` string property reaches SOMA as the string value. Or stop claiming `is_a T` |
| `SOUP[n]: ... requires P (K) ...` with K a concept type | `DO SOUP[n]: ... relationships P to a K concept ...` | `relationships=[{"relationship": "P", "related": ["an existing K concept"]}]` |
| `SOUP[n]: [A, B] all claim to be T and are missing P (K). Provide it. ...` | `DO SOUP[n]: this is important to fill next, but only if A and B are inside the meaning you meant: give A and B ...; otherwise leave it.` | other concepts, usually your domain tags, lack P; give it only when they are part of what you meant |
| `SOUP[n]: ... requires undefined_type_ref (T) ...` | `DO SOUP[n]: leave it: undefined_type_ref means T was not loaded ...` | SOMA did not have T loaded as a declared type while grading this write, so it named a placeholder param instead of T's real params; for a vaulted type such as hwss_domain or personal_domain this is SOMA's own residency, not yours. Leave it |
| `SOUP[n]: Tool call X references unknown needs_P: K. Explain it.`, `SOUP[n]: SKILL: ...`, `SOUP[n]: Ask human_domain_expert for P ...`, `SOUP[n]: X has untyped strings ...` | `DO SOUP[n]: this is important to fill next, but only if it is inside the meaning you meant for X: do what it says; otherwise leave it.` | SOMA's own sentence: act on it when it names your concept and is part of what you meant; ask the user when it asks for a human |
| `CONTRADICTION: X is_a both A and B ...` | `DO CONTRADICTION: remove the contradicting is_a claim ...` | the is_a claims reach two disjoint top branches (such as endurant and perdurant); the only hard reject; nothing was stored |

Value kinds in `(K)`: `string_value` a string, `int_value` an integer, `float_value` a number, `bool_value` true or false, `list_value` a list, `dict_value` a mapping, `concept_ref` a relationship to an existing concept. Any other kind names the concept type to point at.

## The other lines

| line | means | do |
|---|---|---|
| `D2: N% of the declared relationships are traced in the description; not mentioned: ...` | how many relationship targets the description names; informational, never a gate | name the missing ones in the description when they matter |
| `CB: region=R coord=C` | the Crystal Ball plane: the SOMA region the concept was placed in and its coordinate | nothing |
| the CB PROMPTER block | Crystal Ball's guidance for the concept, only when `cb_guidance` asks for it | read it |
| `CRITICAL vaulted_not_code=N: ...` | N vaulted registrations are not code, so their d-chains do not work; system-level, on every verdict until fixed | not yours per write; re-vault with `vault-a-library-into-soma` when working on SOMA |
| `DEATH soup_system_types= ... DEATH end` | declared system types that grade soup; SOMA opens every verdict with it until they are fixed | not about your write; fixing it is `declare-a-soma-type` or `vault-a-library-into-soma` work |
| `❌ X REJECTED: geometric contradiction ...` | nothing was stored | follow its DO line |
| `❌ ... REFUSED (not written)` | a CartON guard refused the write before SOMA | follow the reason it gives |

## Domains

`has_domain` and `has_subdomain` tags are typed `hwss_domain`, SOMA's domain algebra: every domain roots by part_of into one of the four strata Health, Wealth, Social, Spiritual. `hwss_rooted (hwss_stratum)` asks which stratum a domain roots in; `part_of (hwss_domain_or_stratum)` asks for its parent; `has_about` is optional prose. `personal_domain` is the enum paiab, sanctum, cave, misc, personal.

## The raw verdict in get_concept details

| field | means |
|---|---|
| `event=` | the SOMA event name for this grading |
| `triples=N` | facts SOMA asserted for the event |
| `deduction_chains_fired=N unmet=M` | d-chains that fired; M whose requirement is not met |
| `fired_chains=`, `dchain_errors=` | which d-chains fired; which premises raised |
| `all_core_requirements_met` or `failure_error(unmet_core_requirements=N)` | every hard requirement is met, or N hard requirements (d-chain conclusions of kind unmet_requirement) are not |
| `status=<concept>:<grade>` | the grade per concept, the source of the SOMA line |
| `mereo_errors=`, `system_type_isa_fills=`, `soup_gaps=`, `contradictions=` | the sources of the MEREO, FILL, SOUP and CONTRADICTION lines |
| `release_effects=` | handlers the CartON daemon runs once the concept is complete |
| `composed=`, `compose_suggestions=` | edges SOMA derived; a unique candidate for an empty slot, accepted by adding it with `soma_run_id` |
| `info=`, `soma_requests=`, `ews_closed=`, `store_parity=` | SOMA's notes, its requests, closure of the concept's boundary, and whether its store matches CartON |

## Which skill next

| skill | use it to | path |
|---|---|---|
| `model-anything-in-carton` | climb the modelling ladder (say, fill, declare, state, machine, d-chains) and know where to stop | `knowledge/carton-mcp/.claude/skills/model-anything-in-carton/SKILL.md` |
| `carton-write-channels` | know which read surface sees which write, before writing and before concluding a read is empty | `knowledge/carton-mcp/.claude/skills/carton-write-channels/SKILL.md` |
| `declare-a-soma-type` | define a type, then declare it `is_a System_Type` so it can be an is_a target | `base/soma-prolog/.claude/skills/declare-a-soma-type/SKILL.md` |
| `carton-projection-flows` | make a concept leave the graph as a file or artifact through a release effect | `knowledge/carton-mcp/.claude/skills/carton-projection-flows/SKILL.md` |
| `build-and-activate-a-bundle` | roll a finished set of concepts into an activatable collection | `knowledge/carton-mcp/.claude/skills/build-and-activate-a-bundle/SKILL.md` |
| `atomize-a-seed` | decompose one idea into its part concepts and stop at the atom level | `knowledge/carton-mcp/.claude/skills/atomize-a-seed/SKILL.md` |
| `vault-a-library-into-soma` | turn code into SOMA system types with `vault()` | `base/soma-prolog/gnosys-vault/.claude/skills/vault-a-library-into-soma/SKILL.md` |
| `understand-soma-programming` | know how SOMA grades, runs conventions and fires d-chains | `base/soma-prolog/.claude/skills/understand-soma-programming/SKILL.md` |
| `understand-soma-vault-system` | know how vaulted types, restrictions and d-chains are registered | `base/soma-prolog/.claude/skills/understand-soma-vault-system/SKILL.md` |

Paths are relative to the monorepo root `/home/GOD/gnosys-plugin-v2`. When the Skill tool does not list one, Read its path.
