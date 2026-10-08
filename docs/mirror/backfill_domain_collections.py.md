# doc(m): backfill_domain_collections.py

- **Canonical path:** /home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/backfill_domain_collections.py
- **Line count:** 353 (measured, `wc -l`)
- **Module role:** A standalone, purely-additive CLI migration tool over the live production Neo4j `:Wiki` graph. It brings HISTORY along to three forward-only fixes shipped 2026-08-27: it writes the `CONTAINS_CONCEPTS` inverse for domain-family edges, states `is_a Idea` on journal entries, and states `has_subdomain`/`has_domain` on journal entries where the coordinate is DERIVABLE. Dry-run by default; `--apply` is the opt-in that mutates.

## What this module IS (from the code)

One file, fourteen module-level functions plus no classes, ending in `raise SystemExit(main())`
(`:352-353`). Nothing imports it (see *What CALLS this module*); it declares no entry point in
`pyproject.toml`. It is run as `python3 backfill_domain_collections.py [--pass X] [--rel R]
[--batch N] [--limit N] [--apply]`.

**Two passes, and `main()` runs them in a fixed order** (`:311-336`): `axis` first, then `inverse`.
The order is load-bearing and the docstring says why (`:52-56`): the axis pass CREATES new
`HAS_DOMAIN`/`HAS_SUBDOMAIN` edges, and those edges then need inverses, so running `inverse` first
leaves them uncovered. `inverse` is idempotent, so re-running it is always safe.

**Everything it writes is a MERGE of a MISSING edge.** There is no `DELETE`, no `SET`, no survivor
choice, no export. Every write query is guarded by a `WHERE NOT (...)` that excludes edges already
present, which is what makes every pass idempotent AND makes the match set shrink each round, which
is in turn what makes the batch loop terminate.

### The batching, which is the one safety property that matters

`run_batched(g, label, build, batch, limit)` (`:130-161`) is the single owner of the slice loop. It
calls `build(take)` to get a query, runs it, adds the returned `c` to a running total, and stops when
a round writes zero or when `limit` is reached. `build` is a CALLABLE, not a format string, and
`:143-147` states the reason: these queries contain Cypher maps (`{n:'X'}`), so a `str.format` pass
would require every literal brace to be doubled and one missed pair would silently corrupt a query
rather than fail loudly. An earlier revision of this module did use `.format` with `{{take}}`; it was
replaced for exactly that reason.

The docstring at `:132-137` records the inherited lesson: `dedupe_wiki_duplicates.py` had this loop
hand-copied per relationship type and one copy was left unbatched, which put ~300k writes into one
transaction, killed the connection and took the neo4j container down. Centralising it is the fix.

### Pass `inverse`

`count_missing_inverse(g, rel)` (`:166-172`) counts `(c:Wiki)-[:rel]->(d:Wiki)` where
`NOT (d)-[:CONTAINS_CONCEPTS]->(c)`. `backfill_inverse` (`:175-183`) MERGEs that inverse in slices.
`DOMAIN_RELS` (`:104-110`) is the five-relationship list, matching the daemon's `inverse_map`
(`observation_worker_daemon.py:521`).

**Why the inverse is `CONTAINS_CONCEPTS` and not `HAS_PART`** is stated at `:33-42` and is the whole
reason a distinct edge name exists: `activate_collection` recurses `HAS_PART` to depth 10, so
materializing the inverse as `HAS_PART` would make every domain a hub that imports the graph on
activation.

### Pass `axis`

`_resolve_subdomain()` (`:188-208`) returns a Cypher FRAGMENT that binds `e` to a journal entry and
`sub` to its ONE true subdomain node. It is a fragment concatenated by its callers, not a complete
query. The resolution:

1. Candidates are the entry's `PART_OF` targets typed `Doc_Mirror_Subdomain`.
2. `stem = left(e.n, size(e.n)-20)` — the entry name minus its fixed-width timestamp (`TS_LEN`,
   `:118`).
3. Keep candidates the stem `ENDS WITH ('_' + x.n)`.
4. Take the LONGEST survivor via `head([x IN m WHERE all(y IN m WHERE size(x.n) >= size(y.n))])`.

`_resolve_domain()` (`:211-221`) extends that fragment, binding `dom` to the `Doc_Mirror_Domain`-typed
candidate for which the stem ends with `_{dom}_{sub}`, resolved by the same longest-match rule.

`backfill_idea` (`:255-271`) states `is_a Idea`. It **MATCHes** the `Idea` node rather than MERGEing
it (`:268`), and `:260-263` states why: MERGEing an inline unbound type node is the
anonymous-inline-type-merge defect that shattered the graph into 41,751 copies of `System_Event`
(`.claude/rules/wiki-type-shattering-repair.md`). If `Idea` does not exist this writes nothing and
reports zero rather than minting a duplicate universal.

## Imports

### stdlib
- `argparse` (`:99`) — used in `main()` (`:301-315`).
- `sys` (`:100`) — `file=sys.stderr` on the connect failure (`:319`) and the per-rel failure (`:344`).
- `traceback` — imported locally inside the `except` at `:343`.

### third-party
None directly. The Neo4j driver is reached through the daemon helper.

### local
- `carton_mcp.observation_worker_daemon._create_shared_neo4j` — imported inside `connect()` (`:126`),
  so importing this module does not touch Neo4j.

## Top-level definitions

- **`_rows(r)`** (`:121-122`) — normalise a query result to a list (tuple-unwrap, falsy → `[]`).
  Identical to the helper in `dedupe_wiki_duplicates.py:45-46`.
- **`_count(g, query)`** (`:125-126`) — run a query and return its `c` column.
- **`connect()`** (`:129-131`) — delegate to `_create_shared_neo4j()`. That helper catches its own
  exceptions and returns `None`, and unlike the dedupe tool, `main()` CHECKS for it (`:317-320`) and
  returns exit code 2 with a message instead of an `AttributeError`.
- **`run_batched(...)`** (`:134-161`) — the slice loop, described above.
- **`count_missing_inverse` / `backfill_inverse`** (`:166-183`).
- **`_resolve_subdomain` / `_resolve_domain`** (`:188-221`) — Cypher fragment builders.
- **`count_subdomain_gap` / `count_domain_gap`** (`:224-236`), **`backfill_subdomain` /
  `backfill_domain`** (`:239-253`).
- **`_resolve_entry_domain` / `count_entry_domain_gap` / `backfill_entry_domain`** (added
  2026-08-27) — the ENTRY-DOMAIN leg. It recovers the domain from the entry's OWN NAME rather than
  from its `PART_OF` candidates, because for most history the true domain is not among them: the
  candidate is the REPO or a tag, so `_resolve_domain` bound only 236 of 3467. An entry is
  `{Repo}_{Domain}_{Subdomain}_{ts}`, and by the time this runs BOTH ends are known as real nodes —
  the repo from a `PART_OF` to a `Doc_Mirror_Repo`, the subdomain from the `HAS_SUBDOMAIN` the
  earlier calls just wrote — so the domain is exactly what lies between them, with nothing ambiguous
  because the repo must be a literal prefix of the stem and the subdomain a literal suffix.
  **It cannot mint a universal:** `MATCH (dom:Wiki {n: domname})` is a MATCH, never a MERGE, so a
  derived name with no node simply does not bind. Measured before any write, all **168** distinct
  derived names ALREADY EXISTED — this corrects an earlier claim that finishing this half "would
  mean minting domain nodes that do not exist"; the nodes were never missing from the GRAPH, only
  from each entry's candidate set. It runs LAST in the axis pass, and that order is load-bearing
  because it reads the `HAS_SUBDOMAIN` edge the preceding calls write.
- **`count_unresolvable`** — entries whose name resolves NO candidate. Reported, never
  written.
- **`count_missing_idea` / `backfill_idea`** (`:267-289`).
- **`report_axis` / `report_inverse`** (`:294-309`) — the dry-run output.
- **`main()`** (`:312-350`) — arg parsing, connect check, the two passes, the dry-run notice.

## What this module CALLS

- `carton_mcp.observation_worker_daemon._create_shared_neo4j()` — via `connect()`, `:126`.
- `g.execute_query(query, {})` on the returned `KnowledgeGraphBuilder` — every read and write.
- `traceback.print_exc()` — `:345`.

## What CALLS this module (grep-confirmed)

**No Python caller exists.** It is invoked only as a command line. Referenced from the journal at
`knowledge/carton-mcp/context/journal/2026-08.md` (the 2026-08-27T20:34 and T20:45 entries) and from
the doc-mirror cursor pathway.

## Notes / discrepancies

**Test coverage is ZERO.** No `test_backfill_domain_collections.py` exists. Every safety property —
idempotence, batching, the resolution rule — is asserted by the docstring and by the verified live
run below, not by a test. This matches the precedent (`dedupe_wiki_duplicates.py` is also untested)
and is a real gap, not an accepted one.

**VERIFIED live 2026-08-27T20:43, through the tool's own CLI** (this is IS, not VISION): a bounded
slice `--pass inverse --rel HAS_ACTUAL_DOMAIN --limit 500 --batch 250 --apply` reported
`missing inverse: 1278`, wrote two batches of 250, and an independent re-count then reported
`missing inverse: 778`. Exactly 500 written, and the count converged. The dry-run, the bounded apply,
and the convergence are all confirmed on the real graph.

**The `has_domain` half of the axis pass is LARGELY INERT, and that is a finding rather than a bug in
this file.** `count_domain_gap` resolves only 236 of 3467 entries. Measured: 1209 entries have no
`Doc_Mirror_Domain`-typed candidate at all, and ~2022 have a candidate that is the REPO or a TAG
rather than the domain (`Scalable_Publishing_Publishing_Video_Studio_Framework_Definition` offers
only `Scalable_Publishing`, the repo; its true domain `Publishing_Video_Studio` is absent). So for
most history the domain is NOT derivable from the graph, and completing it would require minting
domain nodes that do not exist — a decision, not a migration. The module deliberately writes nothing
in that case.

**`--limit` is per-relationship, not per-run.** In `backfill_inverse` the same `limit` is passed to
each relationship in the loop (`:340`), so `--limit 500` with no `--rel` writes up to 500 edges per
relationship, i.e. up to 2500 total across the five. The help text (`:307-309`) says "per
relationship this run", which is accurate, but a reader skimming for a total cap will misread it.

**`HAS_SUBSUBDOMAIN` does not exist in the graph.** Confirmed by the dry-run, which emits a neo4j
`UnknownRelationshipTypeWarning` and counts 0. It is in `DOMAIN_RELS` because it is in the daemon's
`inverse_map`; no writer has ever produced one. Harmless, and recorded at `:25-28` so the next reader
does not re-discover it.

**The census in the header is a 2026-08-27T20:34 measurement stated with its date** (`:17-31`), and
`HAS_ACTUAL_DOMAIN` is already stale by the 500 edges the verification run wrote. The numbers carry
their timestamp, so they read as a measurement rather than as current state — but re-measure with a
dry-run rather than quoting them.

**Relationship types are interpolated into Cypher by f-string** (`:168`, `:177`, and the axis
queries). The values come from the module's own `DOMAIN_RELS` constant and from `--rel`, so `--rel`
is an injection surface reachable from the command line. It is a local operator tool, so this is a
sharp edge rather than a vulnerability; there is no allow-list check that `--rel` is in
`DOMAIN_RELS`.

**A `--apply` run returns 1 on the first relationship that raises** (`:346`), unlike the dedupe tool
which always returns 0. The axis pass has no such guard: an exception there propagates out of
`main()` as a traceback.

**No logging.** All output is `print` to stdout, which is the CLI-result carve-out in
`print-is-banned-log-to-know-assert-to-gate` — the printed counts ARE the deliverable. A long
`--apply` run therefore leaves no persisted record; the operator's terminal is the only trace.
