"""Backfill the domain axis — DRY-RUN BY DEFAULT. Built 2026-08-27.

WHAT THIS IS FOR. Three fixes shipped on 2026-08-27 are FORWARD-ONLY: they change what NEW
writes look like and leave every historical row exactly as it was.

  * 85e31c3ab  the daemon's inverse_map learned the five domain relationships, so a new
               HAS_DOMAIN / HAS_SUBDOMAIN / HAS_SUBSUBDOMAIN / HAS_ACTUAL_DOMAIN /
               HAS_PERSONAL_DOMAIN edge now gets a CONTAINS_CONCEPTS inverse written back.
  * 85e31c3ab  the journal CLI now states has_domain / has_subdomain on its entries, so
               doc-mirror entries land on the SAME axis as everything add_concept writes,
               instead of only on doc-mirror's private part_of axis.
  * c6dfb64eb  journal entries now carry is_a Idea, giving the band system a producer.

Until history is brought along, activating a domain returns one or two members instead of
the hundreds that are actually tagged with it.

MEASURED LIVE 2026-08-27T20:34, the first real sizing of this job:

    HAS_DOMAIN           66948 edges     203 have the inverse
    HAS_PERSONAL_DOMAIN  18323 edges     273 have the inverse
    HAS_SUBDOMAIN        15664 edges      36 have the inverse
    HAS_ACTUAL_DOMAIN     1725 edges     447 have the inverse
    HAS_SUBSUBDOMAIN         0 edges  -- the relationship does not exist in the graph at
                                         all. It is in the daemon's inverse_map and no
                                         writer has ever produced one. Harmless, and kept
                                         here so the next reader does not re-discover it.
    ------------------------------------------------------------
    TOTAL               102660 edges     959 have the inverse   -> 101700 to write

That 101700 is an order of magnitude above the 62865 figure quoted from the 2026-08-25
pass, because that figure counted ONE relationship type over a rooted subset.

WHY THE INVERSE IS CONTAINS_CONCEPTS AND NOT HAS_PART. This is the whole reason a separate
edge name exists, and reversing it would be a graph-wide mistake. activate_collection
recurses HAS_PART to depth 10, and Infrastructure alone has 7778 incoming has_domain
against 5 outgoing has_part -- so materializing the inverse AS HAS_PART would make every
domain a hub that imports the graph on activation. A distinct edge gives the domain a
one-hop membership query without joining the HAS_PART recursion. (The 2026-08-25 ruling
Activate_Domain_Is_Query_Not_Collection said domain activation is a query, not a
materialized collection; this does not reverse it -- the query stays the way you activate a
domain, and this only gives that query an index-shaped edge to run on.)

THE TWO PASSES, and the ORDER MATTERS:

    --pass axis      derive the domain axis for historical journal entries, THEN
    --pass inverse   give every domain-family edge its inverse, including the new ones

Running inverse first is not wrong, it is just incomplete -- you would have to run it again
after axis. inverse is idempotent, so re-running it is always safe.

DERIVED, NEVER INVENTED — and the naive derivation was WRONG, caught by dry-run before any
write. A journal entry's part_of edges do NOT name only its coordinate: the journal CLI
also writes every --tags value as a part_of, and those tag nodes are typed
Doc_Mirror_Subdomain too. Measured: 3945 "derivable" subdomain edges across only 3585
entries, because 436 entries carry 2 to 4 candidates each. So
Scalable_Publishing_Gnosys_Unification_Fork_Resolutions_2026_06_20T14_39_51 offers
{Equip_Persona, Manifold_Substrate, Fork_Resolutions, Activation_Policy} — one coordinate
and three tags. Stating all four would have fabricated three subdomains for that entry,
which is exactly the failure this tool exists not to commit.

THE DISAMBIGUATOR, and it is exact rather than heuristic: the entry's own NAME is
{Repo}_{Domain}_{Subdomain}_{ts}, and the timestamp is always the trailing 20 characters
(_YYYY_MM_DDTHH_MM_SS). So the STEM is everything before that, and the true subdomain is
the candidate the stem ENDS WITH. Measured over all entries: 3448 resolve to exactly one
candidate, 19 resolve to two because the names NEST (Ijegu_Core_Sentence also ends with
Core_Sentence) and the LONGEST match is the right one, and 20 resolve to none because their
names predate the current scheme (Doc_Mirror_Journal_Entry_Doc_Mirror_System_...). Those 20
are REPORTED AND SKIPPED. The domain is then the candidate d for which the stem ends with
_{d}_{subdomain}, resolved the same way.

An entry with no derivable coordinate is never given one. Filling those in would mean
inventing a domain the writer never recorded.

SAFETY. This tool is PURELY ADDITIVE -- it only ever MERGEs an edge that is missing. It
deletes nothing, chooses no survivor, and discards no content, which is what makes it
categorically safer than dedupe_wiki_duplicates.py and why it ships no export: there is
nothing destroyed to restore. What it inherits from that tool is the lesson that actually
bit: BATCH THE WRITES. Its edge loops were unbatched, so the one name that mattered put
about 300k MERGE plus DELETE into a single transaction, killed the connection and took the
neo4j container down. A 101700-edge backfill written naively does exactly that again.

RUN IT IN SLICES. neo4j on this box has restarted 190 times and was unavailable as recently
as 20:31 today, with swap at 100 percent. Every pass is idempotent and --limit caps the
writes per run, so the honest way to land this is several small runs that each converge,
never one big one. A run that dies halfway has still made real progress and the next run
picks up exactly where it stopped.
"""

import argparse
import sys

DOMAIN_RELS = [
    'HAS_DOMAIN',
    'HAS_SUBDOMAIN',
    'HAS_SUBSUBDOMAIN',
    'HAS_ACTUAL_DOMAIN',
    'HAS_PERSONAL_DOMAIN',
]

INVERSE = 'CONTAINS_CONCEPTS'

JOURNAL_ENTRY = 'Doc_Mirror_Journal_Entry'

# _YYYY_MM_DDTHH_MM_SS — the fixed-width suffix every journal entry name carries.
TS_LEN = 20


def _rows(r):
    return (r[0] if isinstance(r, tuple) else r) or []


def _count(g, query):
    return _rows(g.execute_query(query, {}))[0]['c']


def connect():
    from carton_mcp.observation_worker_daemon import _create_shared_neo4j
    return _create_shared_neo4j()


def run_batched(g, label, build, batch, limit):
    """Run an additive MERGE query in slices until it stops matching.

    ONE place owns the batching, deliberately. The precedent tool
    (dedupe_wiki_duplicates.py) had this loop written out per relationship type and one of
    the copies was left unbatched, which put ~300k writes in a single transaction, killed
    the connection and took the neo4j container down. Three hand-copied loops is three
    chances to make that same mistake again.

    `build` is a callable taking the slice size and returning the query, which must RETURN
    the number of rows it wrote as `c`. It is a callable rather than a format string on
    purpose: these queries contain Cypher maps, and a str.format pass over them means every
    literal brace has to be doubled, so one missed pair silently corrupts a query instead
    of failing loudly.

    Because every caller only ever MERGEs a MISSING edge, the match set shrinks each round
    and the loop terminates on its own; a run that dies partway has still made real
    progress and the next run resumes from exactly there.
    """
    written = 0
    while limit is None or written < limit:
        take = batch if limit is None else min(batch, limit - written)
        n = _rows(g.execute_query(build(int(take)), {}))[0]['c']
        if not n:
            break
        written += n
        print(f"    {label}: +{n} (running total {written})", flush=True)
    return written


# ---------------------------------------------------------------- pass: inverse

def count_missing_inverse(g, rel):
    """How many <rel> edges lack the CONTAINS_CONCEPTS inverse."""
    return _count(g, f"""
        MATCH (c:Wiki)-[:{rel}]->(d:Wiki)
        WHERE NOT (d)-[:{INVERSE}]->(c)
        RETURN count(*) AS c
    """)


def backfill_inverse(g, rel, batch, limit):
    """MERGE the inverse for every <rel> edge missing it. Returns edges written."""
    return run_batched(g, rel, lambda take: f"""
        MATCH (c:Wiki)-[:{rel}]->(d:Wiki)
        WHERE NOT (d)-[:{INVERSE}]->(c)
        WITH c, d LIMIT {take}
        MERGE (d)-[:{INVERSE}]->(c)
        RETURN count(*) AS c
    """, batch, limit)


# ------------------------------------------------------------------- pass: axis

def _resolve_subdomain():
    """Cypher binding `e` to a journal entry and `sub` to its ONE true subdomain node.

    Candidates come from the entry's part_of edges, which include its --tags as well as
    its coordinate; the stem-suffix test is what separates them, and the longest match
    wins when the names nest. An entry whose stem matches no candidate binds nothing and
    therefore falls out of every query built on this — that is the skip, expressed as an
    absence rather than as a guess.
    """
    return f"""
        MATCH (e:Wiki)-[:INSTANTIATES]->(:Wiki {{n:'{JOURNAL_ENTRY}'}})
        WHERE size(e.n) > {TS_LEN}
        MATCH (e)-[:PART_OF]->(d:Wiki)-[:IS_A]->(:Wiki {{n:'Doc_Mirror_Subdomain'}})
        WITH e, left(e.n, size(e.n)-{TS_LEN}) AS stem, collect(DISTINCT d) AS ds
        WITH e, stem, [x IN ds WHERE stem ENDS WITH ('_' + x.n)] AS m
        WHERE size(m) > 0
        WITH e, stem,
             head([x IN m WHERE all(y IN m WHERE size(x.n) >= size(y.n))]) AS sub
    """


def _resolve_domain():
    """Extends _resolve_subdomain, binding `dom` to the segment before the subdomain."""
    return _resolve_subdomain() + """
        MATCH (e)-[:PART_OF]->(c:Wiki)-[:IS_A]->(:Wiki {n:'Doc_Mirror_Domain'})
        WITH e, sub, stem, collect(DISTINCT c) AS cs
        WITH e, sub,
             [x IN cs WHERE stem ENDS WITH ('_' + x.n + '_' + sub.n)] AS m2
        WHERE size(m2) > 0
        WITH e, sub,
             head([x IN m2 WHERE all(y IN m2 WHERE size(x.n) >= size(y.n))]) AS dom
    """


def count_subdomain_gap(g):
    return _count(g, _resolve_subdomain() + """
        WHERE NOT (e)-[:HAS_SUBDOMAIN]->(sub)
        RETURN count(*) AS c
    """)


def count_domain_gap(g):
    return _count(g, _resolve_domain() + """
        WHERE NOT (e)-[:HAS_DOMAIN]->(dom)
        RETURN count(*) AS c
    """)


def backfill_subdomain(g, batch, limit):
    return run_batched(g, 'HAS_SUBDOMAIN', lambda take: _resolve_subdomain() + f"""
        WHERE NOT (e)-[:HAS_SUBDOMAIN]->(sub)
        WITH e, sub LIMIT {take}
        MERGE (e)-[:HAS_SUBDOMAIN]->(sub)
        RETURN count(*) AS c
    """, batch, limit)


def backfill_domain(g, batch, limit):
    return run_batched(g, 'HAS_DOMAIN', lambda take: _resolve_domain() + f"""
        WHERE NOT (e)-[:HAS_DOMAIN]->(dom)
        WITH e, dom LIMIT {take}
        MERGE (e)-[:HAS_DOMAIN]->(dom)
        RETURN count(*) AS c
    """, batch, limit)


def _resolve_entry_domain():
    """Cypher binding `e` to a journal entry and `dom` to the domain named in its OWN name.

    WHY THIS EXISTS SEPARATELY FROM `_resolve_domain`. That one reads the domain off the entry's
    PART_OF candidates, and for most history the true domain is simply not among them — the
    candidate is the REPO or a tag, so only 236 of 3467 entries resolved. The name, however, always
    carries it: an entry is `{Repo}_{Domain}_{Subdomain}_{ts}`, and by this point in the run BOTH
    ends are already known as real nodes — the repo from a PART_OF to a `Doc_Mirror_Repo`, the
    subdomain from the HAS_SUBDOMAIN the axis pass just wrote. So the domain is exactly what is left
    between them, and no parse is ambiguous: the repo must be a literal prefix of the stem and the
    subdomain a literal suffix of it.

    IT CANNOT MINT A UNIVERSAL. `MATCH (dom:Wiki {n: domname})` — a MATCH, never a MERGE. An entry
    whose derived name has no node simply does not bind and is skipped. Measured 2026-08-27 before
    writing anything: all 168 distinct derived names ALREADY EXIST, so zero would be created anyway;
    the MATCH is what guarantees that stays true if the data changes. This corrects my own earlier
    report to Isaac, which said completing this half "would mean minting domain nodes that do not
    exist" — the nodes were never missing from the GRAPH, only from each entry's candidate set.
    """
    return f"""
        MATCH (e:Wiki)-[:INSTANTIATES]->(:Wiki {{n:'{JOURNAL_ENTRY}'}})
        WHERE size(e.n) > {TS_LEN}
        MATCH (e)-[:HAS_SUBDOMAIN]->(s:Wiki)
        MATCH (e)-[:PART_OF]->(r:Wiki)-[:IS_A]->(:Wiki {{n:'Doc_Mirror_Repo'}})
        WITH e, left(e.n, size(e.n)-{TS_LEN}) AS stem, r, s
        WHERE stem STARTS WITH (r.n + '_') AND stem ENDS WITH ('_' + s.n)
          AND size(stem) - size(r.n) - size(s.n) - 2 > 0
        WITH e, substring(stem, size(r.n)+1, size(stem)-size(r.n)-size(s.n)-2) AS domname
        MATCH (dom:Wiki {{n: domname}})
    """


def count_entry_domain_gap(g):
    return _count(g, _resolve_entry_domain() + """
        WHERE NOT (e)-[:HAS_DOMAIN]->(dom)
        RETURN count(*) AS c
    """)


def backfill_entry_domain(g, batch, limit):
    return run_batched(g, 'HAS_DOMAIN (from name)', lambda take: _resolve_entry_domain() + f"""
        WHERE NOT (e)-[:HAS_DOMAIN]->(dom)
        WITH e, dom LIMIT {take}
        MERGE (e)-[:HAS_DOMAIN]->(dom)
        RETURN count(*) AS c
    """, batch, limit)


def count_unresolvable(g):
    """Entries whose own name resolves NO subdomain candidate — skipped, never guessed."""
    return _count(g, f"""
        MATCH (e:Wiki)-[:INSTANTIATES]->(:Wiki {{n:'{JOURNAL_ENTRY}'}})
        OPTIONAL MATCH (e)-[:PART_OF]->(d:Wiki)-[:IS_A]->(:Wiki {{n:'Doc_Mirror_Subdomain'}})
        WITH e, left(e.n, size(e.n)-{TS_LEN}) AS stem, collect(DISTINCT d) AS ds
        WITH e, [x IN ds WHERE stem ENDS WITH ('_' + x.n)] AS m
        WHERE size(m) = 0
        RETURN count(*) AS c
    """)


def count_missing_idea(g):
    return _count(g, f"""
        MATCH (e:Wiki)-[:INSTANTIATES]->(:Wiki {{n:'{JOURNAL_ENTRY}'}})
        WHERE NOT (e)-[:IS_A]->(:Wiki {{n:'Idea'}})
        RETURN count(*) AS c
    """)


def backfill_idea(g, batch, limit):
    """Every journal entry is an Idea — the band system's entry point (c6dfb64eb).

    MATCHes the Idea node rather than MERGEing it: if `Idea` does not exist this writes
    nothing and reports zero, instead of minting an unbound duplicate universal. That is
    the anonymous-inline-type-merge defect the wiki-type-shattering repair exists to undo.
    """
    return run_batched(g, 'IS_A Idea', lambda take: f"""
        MATCH (e:Wiki)-[:INSTANTIATES]->(:Wiki {{n:'{JOURNAL_ENTRY}'}})
        WHERE NOT (e)-[:IS_A]->(:Wiki {{n:'Idea'}})
        WITH e LIMIT {take}
        MATCH (i:Wiki {{n:'Idea'}})
        MERGE (e)-[:IS_A]->(i)
        RETURN count(*) AS c
    """, batch, limit)


# ------------------------------------------------------------------------- main

def report_axis(g):
    print("PASS axis — derive the domain axis for historical journal entries")
    print(f"  entries not yet is_a Idea:            {count_missing_idea(g)}")
    print(f"  resolved HAS_SUBDOMAIN to write:      {count_subdomain_gap(g)}")
    print(f"  resolved HAS_DOMAIN to write:         {count_domain_gap(g)}")
    print(f"  HAS_DOMAIN from the entry NAME:       {count_entry_domain_gap(g)}")
    print(f"  ⚠ name resolves no coordinate (SKIPPED, never guessed): "
          f"{count_unresolvable(g)}")


def report_inverse(g, rels):
    print(f"PASS inverse — write the {INVERSE} inverse for domain-family edges")
    total = 0
    for rel in rels:
        missing = count_missing_inverse(g, rel)
        total += missing
        print(f"  {rel:<22} missing inverse: {missing}")
    print(f"  {'TOTAL':<22} missing inverse: {total}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pass', dest='which', choices=['inverse', 'axis', 'both'],
                    default='both', help="which pass to run (default both, axis first)")
    ap.add_argument('--apply', action='store_true',
                    help='EXECUTE. Default is DRY-RUN: count the gap, write nothing.')
    ap.add_argument('--batch', type=int, default=500,
                    help='edges per transaction (default 500 — small on purpose, this '
                         'neo4j has restarted 190 times)')
    ap.add_argument('--limit', type=int, default=None,
                    help='cap edges written per relationship this run, so a slice is '
                         'resumable. Omit for no cap.')
    ap.add_argument('--rel', default=None,
                    help='inverse pass only: one relationship, e.g. HAS_SUBDOMAIN')
    args = ap.parse_args()

    g = connect()
    if g is None:
        print("could not connect to neo4j (see the daemon helper's own error)",
              file=sys.stderr)
        return 2

    if args.which in ('axis', 'both'):
        report_axis(g)
        if args.apply:
            print("  applying...", flush=True)
            backfill_idea(g, args.batch, args.limit)
            backfill_subdomain(g, args.batch, args.limit)
            backfill_domain(g, args.batch, args.limit)
            # LAST in the axis pass, and the order is load-bearing: it reads the HAS_SUBDOMAIN edge
            # the two calls above have just written, so running it earlier would resolve almost
            # nothing.
            backfill_entry_domain(g, args.batch, args.limit)
        print()

    if args.which in ('inverse', 'both'):
        rels = [args.rel] if args.rel else DOMAIN_RELS
        report_inverse(g, rels)
        if args.apply:
            print("  applying...", flush=True)
            for rel in rels:
                try:
                    backfill_inverse(g, rel, args.batch, args.limit)
                except Exception as e:
                    import traceback
                    print(f"  FAILED {rel}: {e}", file=sys.stderr, flush=True)
                    traceback.print_exc()
                    return 1
        print()

    if not args.apply:
        print("DRY-RUN: nothing was modified. Re-run with --apply to execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
