# doc(m): smart_chroma_rag.py

**Module:** `/home/GOD/gnosys-plugin-v2/knowledge/carton-mcp/smart_chroma_rag.py`  •  **Mirrors:** the module 1:1  •  **Last derived:** 2026-06-10

## Purpose (one paragraph)

`smart_chroma_rag.py` is a thin pragmatic RAG engine around ChromaDB that provides incremental ingest (manifest with file hashes), single-document upsert/update/delete, and budget-aware hybrid retrieval (MMR + keyword boost, optional multi-query / HyDE expansions, optional reranker callback). It also defines the concept-name routing table (`route_concept_to_collection`) used to partition CartON concepts into named ChromaDB collections (`skillgraphs`, `flightgraphs`, `toolgraphs`, `patterns`, `conversations`, `observations`, `domain_knowledge`). The module connects to the shared ChromaDB HTTP server started by `observation_worker_daemon` at `localhost:8101`; it does not own the ChromaDB process.

## Surface (1:1 — every public thing, in file order)

### Token counter — `smart_chroma_rag.py:6`

```python
_count_tokens(text: str) -> int
```
- Uses `tiktoken` (`cl100k_base`) when available; falls back to `max(1, words // 0.75)`. Private but used throughout for budget packing.

### `LocalChromaEmbeddings` class — `smart_chroma_rag.py:23`

- Wraps ChromaDB's default embedding function (`DefaultEmbeddingFunction`, all-MiniLM-L6-v2 via onnxruntime) into langchain's `Embeddings` interface. Loads the model lazily on first use.
- `embed_documents(texts) -> list[list[float]]`  — `smart_chroma_rag.py:37`
- `embed_query(text) -> list[float]`  — `smart_chroma_rag.py:40`
- Free, local, ~22 MB model, millisecond queries after first load.

### Small helpers — `smart_chroma_rag.py:44`

- `_sha256_bytes(b) -> str` — SHA-256 hex of bytes.
- `_sha256_file(path) -> str` — SHA-256 of a file, 1 MB chunks.
- `_now() -> float` — `time.time()`.
- `_default_keyword_score(text, keywords) -> int` — counts how many `keywords` appear as substrings in lowercased `text`.

### Collection routing — `smart_chroma_rag.py:62`

- `_CONCEPT_ROUTING: list` — ordered list of `(predicate, collection_name)` pairs:
  - `Skill_*` / `Skillgraph_*` / `Skillspec_*` → `"skillgraphs"`
  - `Flight_*` / `Flightgraph_*` → `"flightgraphs"`
  - `Tool_*` / `Toolgraph_*` / `MCP_*` (but not `Tool_Call_*`) → `"toolgraphs"`
  - `Pattern_*` → `"patterns"`
  - `Conversation_*` / `Iteration_*` → `"conversations"`
  - `*_Observation` / `Observation_*` → `"observations"`
  - default → `"domain_knowledge"`

- `route_concept_to_collection(concept_name: str) -> str`  — `smart_chroma_rag.py:73`
  - Applies `_CONCEPT_ROUTING` predicates in order, returns first match's collection name, or `"domain_knowledge"`. Used by `observation_worker_daemon` when syncing CartON concepts to ChromaDB.

### `SmartChromaRAG` class — `smart_chroma_rag.py:83`

Constructor: `__init__(self, persist_dir, collection_name, embedding_model="local", api_key=None, chunk_size=1200, chunk_overlap=200)`
- Creates a `LocalChromaEmbeddings` instance.
- Connects to the shared ChromaDB HTTP server via `chromadb.HttpClient(host="localhost", port=8101)`.
- Wraps the collection in a LangChain `Chroma` vector store.
- `persist_dir` is used only for the manifest file path (`{persist_dir}/{collection_name}.__manifest__.json`); ChromaDB data is owned by the HTTP server.

**Manifest methods:**

- `_load_manifest(self) -> dict`  — `smart_chroma_rag.py:126`
  - Reads manifest JSON from `_manifest_path`; returns empty manifest skeleton on missing/corrupt file. Tracks `files: {fid: {sha256, chunks, last_ingested}}`, `created_at`, `updated_at`, `embedding_model`.

- `_save_manifest(self) -> None`  — `smart_chroma_rag.py:135`
  - Writes manifest to disk, bumping `updated_at`. Creates parent dirs if needed.

**Ingest / upsert:**

- `ingest_path(self, doc_path, glob="**/*", exts=None, recursive=True, upsert=True) -> dict`  — `smart_chroma_rag.py:142`
  - Incremental ingest: walks `doc_path` for files matching `exts` (default `[".txt", ".md"]`). Two-stage fast skip: (1) mtime check against manifest's `updated_at`; (2) SHA-256 hash check against stored hash. Only changed/new files are chunked and upserted.
  - Recognises CartON path pattern `ConceptName/ConceptName_itself.md` and sets `concept_name` in chunk metadata. Skips single-char, numeric, symbol-only, timestamped observation, `Sync_*`, `Requires_Evolution`, versioned (`*_v\d+`), `Day_*`, `Raw_Conversation_Timeline_*`, and conversation-noise concepts (lines 208–262).
  - Batches chunks to stay under 250k tokens per `add_texts` call; splits single large files into sub-batches.
  - Returns `{status, operation, path, files_added, files_updated, files_skipped, total_chunks}`.

- `upsert_document(self, doc_id, content, metadata=None) -> dict`  — `smart_chroma_rag.py:335`
  - Splits `content` into chunks, upserts via `vs.add_texts` with ids `{doc_id}::c{idx}`. Updates manifest. Returns `{status, operation, doc_id, chunks}`.

- `update_document(self, doc_id, new_content, metadata=None) -> dict`  — `smart_chroma_rag.py:352`
  - Deletes existing chunks by `where={"source": doc_id}`, then calls `upsert_document`.

- `delete(self, ids=None, where=None) -> dict`  — `smart_chroma_rag.py:357`
  - Calls `vs.delete(ids=ids, where=where)`. Updates manifest if deleting by `source` key. Returns `{status, operation, ids, where}`.

- `list(self, limit=None) -> dict`  — `smart_chroma_rag.py:365`
  - Returns all chunks via `vs._collection.get(limit=limit)`. Each result includes `{id, content, metadata, tokens}`.

- `stats(self) -> dict`  — `smart_chroma_rag.py:375`
  - Returns `{collection, total_chunks, files (manifest), embedding_model}`.

**Query:**

- `query(self, query, k=None, max_tokens=20000, search_type="mmr", alpha=0.5, multi_query=0, hyde_cb=None, rerank_cb=None, keyword_boost=True, keywords=None) -> dict`  — `smart_chroma_rag.py:385`
  - Retrieval pipeline:
    1. Builds query set: starts with original query; if `hyde_cb` provided and `multi_query > 0`, appends the HyDE hypothetical answer; appends up to `multi_query` cheap verb-prefix expansions (`explain`/`summarize`/`outline`/`list`).
    2. Retrieves `k` (default 8) docs per query via LangChain retriever (MMR with `lambda_mult=alpha`, or similarity).
    3. Deduplicates by metadata id / source / content hash, keeping first occurrence.
    4. Keyword boost: scores each doc by count of query keywords (words >3 chars) appearing in content; stable-sorts descending.
    5. Token-budget packing: accumulates docs until `max_tokens` reached; skips (does not truncate) over-budget docs.
    6. Optional `rerank_cb(packed, query)` reranker hook.
    7. Deduplicates by `concept_name` metadata for CartON semantic discovery: aggregates chunk count + inverse-rank score per concept, formats as numbered list `"1. Name (score)"`.
  - Returns `{status, operation, query, expansions, documents_retrieved, total_tokens, max_tokens, results:[{content,metadata,tokens}], concepts (formatted list), prioritization_info}`.

**Internals:**

- `_load_and_split_file(self, path) -> List[Document]`  — `smart_chroma_rag.py:524`
  - Loads file via `TextLoader`, splits via `_split_docs`.

- `_split_text(self, text, source, extra_meta) -> List[Document]`  — `smart_chroma_rag.py:529`
  - Wraps raw text in a `Document`, splits via `_split_docs`.

- `_split_docs(self, docs, source) -> List[Document]`  — `smart_chroma_rag.py:533`
  - `RecursiveCharacterTextSplitter` with `chunk_size`/`chunk_overlap`. Ensures `source` and `chunk_idx` in each chunk's metadata.

- `_count_chunks(self) -> int`  — `smart_chroma_rag.py:544`
  - Returns `vs._collection.count()`.

## Dependencies

**stdlib:** `os`, `json`, `hashlib`, `time`, `re`, `pathlib`, `typing`

**third-party:**
- `tiktoken` (optional; falls back to word-count heuristic if unavailable)
- `langchain_core.documents.Document`
- `langchain_core.embeddings.Embeddings`
- `langchain_text_splitters.RecursiveCharacterTextSplitter`
- `langchain_community.document_loaders.TextLoader`, `DirectoryLoader`
- `langchain_chroma.Chroma`
- `chromadb` — `HttpClient` (connects to shared server at `localhost:8101`), `DefaultEmbeddingFunction`

**intra-repo:** none (standalone module)

**consumers (within carton-mcp):**
- `observation_worker_daemon.py` — imports `SmartChromaRAG` and `route_concept_to_collection` for syncing concepts to ChromaDB
- `server_fastmcp.py` — imports for the `chroma_query` MCP tool
- `substrate_projector.py` — references `SmartChromaRAG` indirectly via `enforce_ontology_invariants` path in `carton_utils`

## Notes

- **ChromaDB connection is HTTP-only** (`localhost:8101`): `SmartChromaRAG` never starts ChromaDB; it assumes `observation_worker_daemon` has started the server. If the daemon is down, all `vs.*` calls will raise connection errors.
- **`persist_dir` is manifest-only**: ChromaDB data lives inside the HTTP server's storage, not in `persist_dir`. The `persist_dir` path is only used to locate the manifest JSON file.
- **Concept-name exclusion list in `ingest_path`** (lines 208–262) is extensive and must be kept in sync with the exclusion logic in `scan_carton` (`carton_utils.py:1988`) — they implement the same rules independently.
- **`_CONCEPT_ROUTING` is evaluated in order** (first match wins). `Tool_Call_*` concepts are explicitly excluded from `toolgraphs` to avoid conversation-ingestion noise landing in the tool collection.
- **`DirectoryLoader` is imported but never used** in the current code — `ingest_path` uses manual `rglob` + `TextLoader` per file.
