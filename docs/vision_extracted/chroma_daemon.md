# chroma_daemon

## THE WRITE PATH RECLAIMS WHAT A DELETE ORPHANS
Deleting a collection removes the segment rows belonging to it in the same act.
A row whose segment no longer exists is reclaimed rather than left standing as an allocated page.

## A COLLECTION IS DROPPED THROUGH A ROUTE
The daemon exposes a route that drops a collection. No caller reaches past the daemon into the store.
A per-run scratch collection is dropped through that route when its run ends.

## A QUERY NEVER RAISES THE HNSW ARRAY ERROR
`coll_query` never raises the HNSW contiguous 2D array error.

## EVERY CHROMA USE GOES THROUGH THE DAEMON
A full `sync_rag` run goes through `/add_texts` end to end.

## THE INDEX NAMES A THING AS THE GRAPH DOES
A concept carries one name in the chroma index and in neo4j.
The index keeps its kinds apart — skills, tools, patterns, dated session notes — and never ranks them as
one flat heterogeneous set.

## GLYPHSTEER STEERS RETRIEVAL ONLY
Glyphsteer, the dual lexical-plus-dense retrieval-steering annotation layer, applies to retrieval only,
over the retrieval-facing description. The D2 rollup stays the canonical description.
The text embedded for retrieval is a separately generated, genuinely varied natural-language description of
a concept's relationships, never its D2 rollup.

## THE LAUNCHER REPORTS A START ONLY WHEN HEALTH ANSWERS
The launcher reports the daemon started only after its health check answers, never on the spawn
returning.

## HEALTH SAYS UP ONLY WHEN THE VECTOR STORE ANSWERS
The daemon's `/health` answers readiness — warm, with the vector store it embeds into answering — never
liveness alone.
The chroma dependency check proves readiness by embedding through the daemon. An answer from `/health`
alone is never the check.
