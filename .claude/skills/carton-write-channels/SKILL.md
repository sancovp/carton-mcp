---
name: carton-write-channels
description: "WHAT: the four ways to write a fact into CartON and which reads see each. WHEN: before add_concept or set_properties, or a write does not show up."
---

# carton-write-channels

**In full:** WHAT: the four ways to write a fact into CartON — description prose, relationships, properties, and a split-off content node — and which read surfaces can actually see each one. Includes the one modelling law that governs every write. WHEN: before you add_concept or set_properties; when deciding whether something is a property or an edge; when a concept you wrote back does not show up where you expected; when you are about to split content off a description; when a read returned less than you know is in the graph.

There are FOUR ways to put a fact on a concept, and **what sees what is not uniform**. Almost every
wrong read comes from a cell of this matrix someone assumed instead of checking.

## THE MATRIX — measured 2026-08-09, not designed

One probe concept carried a distinct marker in each channel; each surface was then read and the
markers counted. This is what came back:

| write channel | `get_concept` | `get_concept_network` | Cypher (`query_wiki_graph`) |
|---|---|---|---|
| **prose** (`n.d`) | ✅ | ❌ | ✅ |
| **properties** | ✅ | ❌ | ✅ — you must name the keys |
| **relationships** | ✅ | ✅ | ✅ |
| **split content** (`_Desc_Content`) | ❌ — edge only | ✅ — as a neighbour's description | ✅ — via the edge |

**THE TWO DEFAULT SURFACES ARE COMPLEMENTARY, NOT OVERLAPPING. Neither alone shows you the whole
node.** `get_concept` cannot see split-off content. `get_concept_network` cannot see prose or
properties. If you need the whole node, you need Cypher and you must ask for each channel by name —
a bare `RETURN c` still misses the content, because that lives on a different node.

**Chroma — measured 2026-08-09 (the natural-language redo; probe `Chroma_Channel_Probe_2026_08_09`):**
- **split content: INDEXED** — the `_Desc_Content` node is its own document and returns rank 1 for a
  semantic query of its text, within seconds of the queue drain.
- **properties: NOT indexed** — a distinctive property sentence returned a genuine semantic neighbor
  of its words (`Metallurgy_Annealing` for "annealing") but never the probe.
- **prose (`n.d`): a LAGGED lane** — the fresh concept was absent ~4 minutes after drain even for
  its own exact name, while older concepts are clearly indexed; main-concept indexing does not ride
  the drain the way the split-content upsert does. Re-query later or use Cypher for fresh writes.
- **READ THE RESULT SHAPE RIGHT** [inferred from the invariant result shape, not read from code]:
  `chroma_query` searches ~7 collections and INTERLEAVES each collection's winner (ranks 2-5 are
  reliably Skill_/Flight_/Tool_/Pattern_ entries), with scores QUANTIZED into bands (1.00/0.50) —
  so unrelated 1.00 hits are other collections' winners, NOT evidence the embedding is broken, and
  RANK 1 is the only strong relevance signal. The earlier "degenerate scoring" read of this surface
  was this shape misread.

## WHEN A QUEUED WRITE IS VISIBLE — measured 2026-10-07 (card 857)

An `add_concept` RETURNS when its payload is queued, not when it is on the graph. The observation worker
lands queued payloads in DRAIN BATCHES, and every node of one batch carries ONE `t`, the batch's landing
time, whatever order the writes were made in. A node's PROPERTIES land after the node itself: a batch
read 0 of 21 nodes with `canonical_intent` two minutes after landing and 21 of 21 fifty minutes later.

- **Measure write lag on the GRAPH:** the entry's own authored stamp (the `_YYYY_MM_DDTHH_MM_SS` its name
  ends with) against its landing `t`. Never from a file count under `carton_queue`: a drained payload
  stays there, in `processed/` or `failed/`. The backlog is the top-level `*.json` only —
  `add_concept_tool.queue_status()` answers it as `waiting`, on the machine whose worker drains it.
- **Ask whether ONE entry landed:** on the box, `queue_status([<the entry's name>])` → `queued` ·
  `processed` · `failed` · `absent`; `processed` means the batch holding it was written. Off the box,
  read the concept back through `query_wiki_graph` after the next drain, bounded, and report what has
  not landed as unlanded, never as absent.
- **Never order by `t` alone** where writes from one batch must stay in sequence: ties are a batch, so
  break them by the authored stamp, then the name. A tied `t` also hides a batch-mate from any
  `n.t < x` search.
- **Code that verifies its own write** reads it back after the next batch, bounded, and reports what has
  not landed as unlanded, never as absent.

## WHICH CHANNEL FOR WHICH MEANING

- **relationships — the knowledge.** What a thing IS, what it is PART OF, what it INSTANTIATES,
  what it PRODUCES. If it is meaning, it is an edge. The graph is the knowledge; everything else
  annotates it.
- **properties — state.** Status, order, timestamps, flags, gates, paths. Especially designs and
  specs: their state lives in properties. Scratch-lane properties write synchronously and never
  touch `n.d`. A value is a str/int/float/bool or a flat list of those; `None` unsets the key; a
  nested value is refused — JSON-encode it and store the string.
- **prose (`n.d`) — annotation only.** It describes; it does not carry knowledge. A fact that exists
  only in prose is invisible to every structural reader and to SOMA.
- **split content (`split_content_concept`) — raw content that was mistakenly a description.** Use it
  when a description turns out to be a pasted document rather than an account of what the thing is.

**CartonObj KV fences are LEGACY — do not reach for them** (Isaac, 2026-08-06). The `properties`
channel superseded their main job, which was config-as-JSON-in-description. What they uniquely did,
recorded once so nobody has to rediscover it: bare-token refs that expand to concepts via
`get_concept --expand_refs`, and schema validation against an `is_schema` fence. Properties are flat
scalars and lists and cannot hold a resolving ref. `expand_refs` leaves the taught surface with them,
since it only operates on fences.

## THE ONE MODELLING LAW — it governs every write

**Universal-to-universal containment is legitimate. Particular-to-universal is not.**

`Task_List has_part Task` is a true statement about the types — fine.
`X has_a Task_List` where X is a particular is **wrong**, and wrong in a way that damages the graph:
X does not have the universal, X has an *instance* of it. Mint the instance and have IT instantiate
the type.

The correct shape already exists and is proven — it is what `vault()` does. It never points a slot at
a type; it mints a part-node and has that instantiate the type:
`T has_required_part P` · `P has_arg_property has_<field>` · `P instantiates <Type>`.

**Why it is not pedantry.** In CartON the subgraph IS the meaning, so every particular pointing at a
universal adds an inbound edge to that universal and smears its definition with its own usage. This
is the mechanism that **manufactures hubs** — and a hub is what makes a traversal explode later. The
write-time problem and the read-time problem are the same problem.

**Live evidence, in production right now:** the `Cave` node — pointed at by every concept tagged
`personal_domain: cave` — has a wrecked description: a recursively mangled `/tmp` path repeated many
times, followed by four duplicate copies of an enum docstring. That is a universal that got smeared.

## FOUR THINGS THAT SURPRISE PEOPLE — all measured

**`get_concept` is not a pure read.** Its response carries a SOMA verdict block with
`source=get_concept observations=1`. Reading POSTs an event and re-runs validation. Reads have side
effects and cost a validation cycle.

**Seven system-written properties sit alongside yours**: `source`, `linked`, `last_modified`, `score`,
`timeline_linked`, `region`, `soma_region`. Note there are TWO region properties — understand both
before writing to either. Reserved keys (`n`, `d`, `t`, `c`, and the managed set) are refused by
`set_properties` and reported.

**Every relationship target you name mints an auto-created stub** whose description literally says
`AUTO CREATED: stub node referenced as <REL> target by <you>. Not yet fully defined.` Naming a target
creates it. That is fine one level down and NOT fine at the level you are authoring — your own
concepts must be real.

**A mereo verdict is a FILL SIGNAL, not a rejection.** `MEREO_ERROR` means your `is_a` names a type
SOMA does not know yet; CartON stores the concept and SOMA tells you what to define. Filling it is
the work. Only a geometric `contradiction` — an `is_a` reaching two disjoint DOLCE branches — is
actually refused.

## THE CHECK, BEFORE YOU WRITE

1. Is this **meaning** or **state**? Meaning is an edge. State is a property.
2. Is my subject a **particular**? Then no slot may point at a universal — mint the instance.
3. Is every field **derived from what this concept actually is**? Stamping the same `is_a`/`domain`
   across everything makes the typing carry zero information.
4. Will the surface I plan to read this back through **actually see the channel I am writing**?
   Check the matrix. This is the one people skip.

## THE CHECK, WHEN A READ LOOKS EMPTY

Before concluding the fact is not there: which surface did you use, and can that surface see the
channel the fact was written to? A missing split-content is the common case — you read with
`get_concept` and it only shows you the edge.

---
## Skill contents

- The matrix above is the measured artifact. Re-measure it if the read layer changes; do not
  hand-edit the table from reasoning.
