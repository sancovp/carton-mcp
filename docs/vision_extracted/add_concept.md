# add_concept

## add_concept_tool.py has a sealed boundary
The module is traced and sealed.

## THE D2 ROLLUP BECOMES THE DESCRIPTION WHEN EVOLUTION ENDS
When a concept's `REQUIRES_EVOLUTION` edge is removed, the D2 description rollup is written as its final
`n.d`.

## THE DOCSTRING STATES REPLACE MODE AS IT IS
`add_concept`'s docstring states replace mode as a full-string overwrite in place.

## A reference to an existing node carries that node's exact stored name
The relationship-target normalizer never re-derives a name that already resolves. A name embedding a hex id, a uuid prefix, a commit sha, a session id or an endeavor id normalizes to the same name it was created under, digits and all. A RELATIONSHIP VALUE THAT IS A PATH IS NOT A NAME AND IS NOT NORMALIZED. A stored path keeps its own casing and resolves on a case-sensitive filesystem. A pointer that cannot be followed is not a pointer.

## THE STUBS NORMALIZATION MINTED ARE MIGRATED
Every stub node that normalization minted from a name carrying an id is migrated onto the real node that name meant. No two nodes stand as shadow twins of one name, differing only by hyphen or underscore.

## EVERY CONCEPT CARRIES ITS VALIDITY INTERVAL
Every concept carries `date_created`, `valid_at` and `invalid_at`, surfaced on `get_concept` and
`chroma_query`. A rename supersession sets `invalid_at` on the old concept.

## A PLACEHOLDER TOKEN IS NEVER A DOMAIN
A placeholder token is refused as a `has_domain` target, and the placeholder-poisoned domain nodes are
repaired.

## A WRITE MADE WHILE THE VALIDATOR IS UNREACHABLE IS MARKED UNGRADED
The store keeps recording when the validator cannot be reached, and every node written in that state
CARRIES A MARK saying it was never graded.
The ungraded population is enumerable from the graph, never a set whose size nobody can know. A node
carrying the mark is regraded when the validator answers again.

## A RELATIONSHIP IS SWAPPED IN ONE WRITE
carton carries a triple swap: replace this relationship with that one, in one write.

## THE ONTOLOGY_GRAPHS DOCSTRING STATES WHAT IT DOES
`ontology_graphs.py`'s module docstring states what its four live functions do.
A carton write never waits out the full SOMA bound while SOMA is down.

## AN INSTANCE OF A TYPE THIS SYSTEM DECLARED NEVER COMES BACK AS SOUP
A type our own programs write instances of is DECLARED, so every instance of it is gradeable.
A soup verdict on such an instance ENGAGES AN ENDEAVOR and states WHY it is soup, rather than being
recorded and passed over.
The declare-a-soma-type skill's examples declare a type with `is_a System_Type` alone.

## A MEREO FILL SIGNAL READS AS AN INSTRUCTION
A mereo verdict names the part-instantiation check to install. It does not read as a form to fill in.

## A TYPING FAILURE IS REPORTED, NEVER SILENT
A multi-target `is_a` fails ATOMICALLY when one target is not known, and the call SAYS SO. It does not report success while the description lands and the typing did not. `add_document_concept` checks the relationships the daemon requires before it reports success, and never reports success for a write the daemon will reject. A CLAIM NEEDING TWO DISJOINT BRANCHES USES `is_a` FOR ONE AND `instantiates` FOR THE OTHER. Two disjoint branches reached by one `is_a` is the geometric contradiction, the single hard refusal, and the claim is RESTATED into that shape rather than the refusal being worked around.

## No edge manufactures a stub
A relationship target that resolves to nothing is refused, not auto-created. A blocker or a parent is
never stubbed into existence.

## THE GRAPH IS ONE HIERARCHY — SOUP IS ALLOWED, DETACHED IS NOT
IT MUST BE ONE HIERARCHY. ALWAYS. EVEN IF IT IS WRONG. THE SOUP MUST ALL BE IN THE HIERARCHY, REGARDLESS. Standing outside the hierarchy is not. The hierarchy is rooted at the manifold root, whose top-level parts are the four HWSS strata: Health, Wealth, Social, Spiritual. Every concept attaches to a domain that climbs part_of through subdomain, domain and stratum to the root, and the root sits above the strata, never under one. A domain is a valid entry only if it fits in the manifold system, which is the hierarchy system.

## A DOMAIN IS A RECURSIVE STACK, AND THE CHAIN YOU CARE ABOUT IS THE SENSE
A domain is a CHAIN climbing to its stratum, never one flat label. Every write carries its domain, so the automatic collection inverse exists and the concept is reachable without a freehand query.

## ADMISSION INTO THE HIERARCHY IS CHECKED AT WRITE TIME
A write that would leave its node reaching no root is decided AT THE MOMENT OF THE WRITE. A name entering
the graph is placed in the one hierarchy at write time, provisionally where its place is unknown. Placement is
never left to a later sweep, and a bare top-level domain that climbs to nothing is not admitted.
