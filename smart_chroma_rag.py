# smart_chroma_rag.py
import os, json, hashlib, time, re
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def _count_tokens(text: str) -> int:
        return len(_ENC.encode(text or ""))
except Exception:
    def _count_tokens(text: str) -> int:
        # fallback; not accurate but monotone
        return max(1, len((text or "").split()) // 0.75)

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_chroma import Chroma


class LocalChromaEmbeddings(Embeddings):
    """Adapter: wraps chromadb's default embedding function (all-MiniLM-L6-v2)
    into langchain's Embeddings interface. Loads onnxruntime ONCE on first use.
    Free, local, ~22MB model, millisecond queries after first load."""

    def __init__(self):
        self._fn = None

    def _get_fn(self):
        if self._fn is None:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            self._fn = DefaultEmbeddingFunction()
        return self._fn

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._get_fn()(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._get_fn()([text])[0]

# --------- small helpers ---------

def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()

def _now() -> float:
    return time.time()

def _default_keyword_score(text: str, keywords: List[str]) -> int:
    L = (text or "").lower()
    return sum(1 for kw in keywords if kw in L)

# --------- Collection Routing ---------

_CONCEPT_ROUTING = [
    (lambda n: n.startswith("Skill_") or n.startswith("Skillgraph_") or n.startswith("Skillspec_"), "skillgraphs"),
    (lambda n: n.startswith("Flight_") or n.startswith("Flightgraph_"), "flightgraphs"),
    (lambda n: (n.startswith("Tool_") or n.startswith("Toolgraph_") or n.startswith("MCP_"))
               and not n.startswith("Tool_Call_"), "toolgraphs"),
    (lambda n: n.startswith("Pattern_"), "patterns"),
    (lambda n: n.startswith("Conversation_") or n.startswith("Iteration_"), "conversations"),
    (lambda n: "_Observation" in n or n.startswith("Observation_"), "observations"),
]

def route_concept_to_collection(concept_name: str) -> str:
    """Route a concept to its ChromaDB collection based on name prefix."""
    for pred, collection in _CONCEPT_ROUTING:
        if pred(concept_name):
            return collection
    return "domain_knowledge"


# --------- SmartChromaRAG ---------

class SmartChromaRAG:
    """
    A thin, pragmatic RAG engine around Chroma with:
      - incremental ingest (manifest w/ file hashes)
      - upsert/update/delete by id
      - MMR / hybrid keyword+dense retrieval
      - optional multi-query / HyDE expansions
      - optional reranker callback
      - token-budget packing
    """

    def __init__(
        self,
        persist_dir: str = "./chroma_db",
        collection_name: str = "default",
        embedding_model: str = "local",
        api_key: Optional[str] = None,
        chunk_size: int = 1200,
        chunk_overlap: int = 200,
    ):
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.embeddings = LocalChromaEmbeddings()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Manifest lives on filesystem (tracks file hashes for incremental ingest).
        # persist_dir kept for manifest path only — chroma data owned by HTTP server.
        self._manifest_path = Path(persist_dir) / f"{collection_name}.__manifest__.json"
        self._manifest = self._load_manifest()

        # Connect to the shared ChromaDB HTTP server started by observation_worker_daemon.
        import chromadb as _chromadb
        _client = _chromadb.HttpClient(host="localhost", port=8101)
        self.vs = Chroma(
            client=_client,
            collection_name=collection_name,
            embedding_function=self.embeddings,
        )

    # --------- MANIFEST (for incremental ingest) ---------

    def _load_manifest(self) -> Dict[str, Any]:
        p = self._manifest_path
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                pass
        return {"files": {}, "created_at": _now(), "updated_at": _now(), "embedding_model": self.embedding_model}

    def _save_manifest(self) -> None:
        self._manifest["updated_at"] = _now()
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self._manifest_path.write_text(json.dumps(self._manifest, indent=2))

    # --------- INGEST / UPSERT ---------

    def ingest_path(
        self,
        doc_path: str,
        glob: str = "**/*",
        exts: Optional[List[str]] = None,
        recursive: bool = True,
        upsert: bool = True,
    ) -> Dict[str, Any]:
        """
        Incremental ingest: walks path, chunks text files, upserts only changed files.
        """
        base = Path(doc_path)
        if not base.exists():
            return {"status": "error", "message": f"path not found: {doc_path}"}

        if exts is None:
            exts = [".txt", ".md"]  # you can add ".pdf" if your stack supports it

        files = []
        if base.is_dir():
            for p in base.rglob(glob if recursive else "*"):
                if p.is_file() and p.suffix.lower() in exts:
                    files.append(p)
        else:
            if base.suffix.lower() in exts:
                files.append(base)

        added, updated, skipped = 0, 0, 0

        # Batching to stay under OpenAI 300k token limit
        batch_texts, batch_metas, batch_ids = [], [], []
        batch_tokens = 0
        MAX_BATCH_TOKENS = 250000  # Safety margin below 300k

        def flush_batch():
            nonlocal batch_texts, batch_metas, batch_ids, batch_tokens
            if batch_texts:
                print(f"[BATCH] Flushing {len(batch_texts)} chunks, ~{batch_tokens} tokens")
                self.vs.add_texts(batch_texts, metadatas=batch_metas, ids=batch_ids)
                batch_texts, batch_metas, batch_ids = [], [], []
                batch_tokens = 0

        # Timestamp-based fast skip: only hash files modified since last sync
        last_sync_time = self._manifest.get("updated_at", 0)

        for p in files:
            fid = str(p.resolve())

            # Fast path: skip files not modified since last sync (mtime check, no I/O)
            try:
                file_mtime = p.stat().st_mtime
            except OSError:
                skipped += 1
                continue
            prior = self._manifest["files"].get(fid)
            if prior and file_mtime <= last_sync_time and upsert:
                skipped += 1
                continue

            # Only hash files that are new or modified (slow path)
            fhash = _sha256_file(p)
            if prior and prior.get("sha256") == fhash and upsert:
                skipped += 1
                continue

            # Extract concept_name from CartON path pattern: .../ConceptName/ConceptName_itself.md
            concept_name = None
            if "_itself.md" in p.name:
                concept_name = p.name.replace("_itself.md", "")

                # Exclude meta-concepts (observations, syncs, etc.)
                if concept_name:
                    # Skip single-character index concepts: A, B, C, 0, 1, 2, etc.
                    if re.match(r'^[A-Za-z0-9]$', concept_name):
                        skipped += 1
                        continue
                    # Skip purely numeric concepts: 123, 456, etc.
                    if re.match(r'^\d+$', concept_name):
                        skipped += 1
                        continue
                    # Skip symbol/punctuation only concepts
                    if re.match(r'^[^\w]+$', concept_name):
                        skipped += 1
                        continue
                    # Skip timestamped observations: 2025_10_20_00_15_07_Observation
                    if re.match(r'^\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}_Observation$', concept_name):
                        skipped += 1
                        continue
                    # Skip sync concepts: Sync_20250910_040525
                    if re.match(r'^Sync_\d+$', concept_name):
                        skipped += 1
                        continue
                    # Skip Requires_Evolution marker
                    if concept_name == 'Requires_Evolution':
                        skipped += 1
                        continue
                    # Skip sunk concepts from CartON sinking protocol: Concept_Name_v1, Concept_Name_v2, etc.
                    if re.match(r'.*_v\d+$', concept_name):
                        skipped += 1
                        continue
                    # Skip transcript concepts from precompact hook
                    # Day_YYYY_MM_DD
                    if re.match(r'^Day_\d{4}_\d{2}_\d{2}$', concept_name):
                        skipped += 1
                        continue
                    # Raw_Conversation_Timeline_YYYY_MM_DD
                    if re.match(r'^Raw_Conversation_Timeline_\d{4}_\d{2}_\d{2}$', concept_name):
                        skipped += 1
                        continue
                    # Conversation transcript noise — case-insensitive prefix check
                    cn_lower = concept_name.lower()
                    if any(cn_lower.startswith(p) for p in [
                        'conversation_', 'userthought_', 'user_thought_',
                        'agentmessage_', 'agent_message_',
                        'toolcall_', 'tool_call_',
                        'coglog_', 'iteration_', 'user_message_',
                        'phase_summary_', 'executive_summary_',
                        'subphase_', 'iteration_summary_',
                    ]):
                        skipped += 1
                        continue

            docs = self._load_and_split_file(p)
            # stable ids per chunk: file_id::chunk_idx::<sha>
            ids = [f"{fid}::c{idx}" for idx, _ in enumerate(docs)]
            metadatas = [dict(doc.metadata, source=fid, file_sha256=fhash, chunk_idx=i, concept_name=concept_name) for i, doc in enumerate(docs)]

            # Count tokens for this file's chunks
            file_tokens = sum(_count_tokens(d.page_content) for d in docs)

            # If adding this file would exceed limit, flush current batch first
            if batch_tokens + file_tokens > MAX_BATCH_TOKENS and batch_texts:
                print(f"[BATCH] Would exceed limit: current={batch_tokens}, file={file_tokens}, flushing...")
                flush_batch()

            # If this single file exceeds batch limit, split it into sub-batches
            if file_tokens > MAX_BATCH_TOKENS:
                print(f"[BATCH] Large file {fid} ({file_tokens} tokens), splitting into sub-batches...")
                sub_batch_texts = []
                sub_batch_metas = []
                sub_batch_ids = []
                sub_batch_tokens = 0

                for i, doc in enumerate(docs):
                    chunk_tokens = _count_tokens(doc.page_content)
                    if sub_batch_tokens + chunk_tokens > MAX_BATCH_TOKENS and sub_batch_texts:
                        print(f"[BATCH] Sub-batch flush: {len(sub_batch_texts)} chunks, ~{sub_batch_tokens} tokens")
                        self.vs.add_texts(sub_batch_texts, metadatas=sub_batch_metas, ids=sub_batch_ids)
                        sub_batch_texts = []
                        sub_batch_metas = []
                        sub_batch_ids = []
                        sub_batch_tokens = 0

                    sub_batch_texts.append(doc.page_content)
                    sub_batch_metas.append(metadatas[i])
                    sub_batch_ids.append(ids[i])
                    sub_batch_tokens += chunk_tokens

                # Flush remaining sub-batch
                if sub_batch_texts:
                    print(f"[BATCH] Final sub-batch flush: {len(sub_batch_texts)} chunks, ~{sub_batch_tokens} tokens")
                    self.vs.add_texts(sub_batch_texts, metadatas=sub_batch_metas, ids=sub_batch_ids)
            else:
                # Add this file's chunks to batch
                batch_texts.extend([d.page_content for d in docs])
                batch_metas.extend(metadatas)
                batch_ids.extend(ids)
                batch_tokens += file_tokens

                if len(batch_texts) % 100 == 0:
                    print(f"[BATCH] Accumulated {len(batch_texts)} chunks, ~{batch_tokens} tokens")

            if prior:
                updated += 1
            else:
                added += 1
            self._manifest["files"][fid] = {"sha256": fhash, "chunks": len(docs), "last_ingested": _now()}

        # Flush any remaining batch
        flush_batch()

        self._save_manifest()
        total_chunks = self._count_chunks()
        return {
            "status": "success",
            "operation": "ingest",
            "path": str(base),
            "files_added": added,
            "files_updated": updated,
            "files_skipped": skipped,
            "total_chunks": total_chunks,
        }

    def upsert_document(
        self,
        doc_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Upsert a single logical document (split into chunks).
        """
        docs = self._split_text(content, source=doc_id, extra_meta=metadata or {})
        ids = [f"{doc_id}::c{idx}" for idx, _ in enumerate(docs)]
        metadatas = [d.metadata for d in docs]
        self.vs.add_texts([d.page_content for d in docs], metadatas=metadatas, ids=ids)
        self._manifest["files"][doc_id] = {"sha256": _sha256_bytes(content.encode()), "chunks": len(docs), "last_ingested": _now()}
        self._save_manifest()
        return {"status": "success", "operation": "upsert", "doc_id": doc_id, "chunks": len(docs)}

    def update_document(self, doc_id: str, new_content: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Delete existing chunks by id prefix, then upsert."""
        self.delete(where={"source": doc_id})  # delete by metadata key
        return self.upsert_document(doc_id=doc_id, content=new_content, metadata=metadata)

    def delete(self, ids: Optional[List[str]] = None, where: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self.vs.delete(ids=ids, where=where)
        # update manifest best-effort if deleting by doc_id
        if where and "source" in where:
            self._manifest["files"].pop(where["source"], None)
            self._save_manifest()
        return {"status": "success", "operation": "delete", "ids": ids, "where": where}

    def list(self, limit: Optional[int] = None) -> Dict[str, Any]:
        coll = self.vs._collection
        raw = coll.get(limit=limit)
        out = []
        for i, _id in enumerate(raw["ids"]):
            doc = raw["documents"][i] if i < len(raw["documents"]) else ""
            meta = raw["metadatas"][i] if i < len(raw["metadatas"]) else {}
            out.append({"id": _id, "content": doc, "metadata": meta, "tokens": _count_tokens(doc)})
        return {"status": "success", "count": len(out), "results": out}

    def stats(self) -> Dict[str, Any]:
        return {
            "collection": self.collection_name,
            "total_chunks": self._count_chunks(),
            "files": self._manifest.get("files", {}),
            "embedding_model": self.embedding_model,
        }

    # --------- QUERY ---------

    def query(
        self,
        query: str,
        k: Optional[int] = None,
        max_tokens: int = 20000,
        search_type: str = "mmr",           # "similarity" | "mmr"
        alpha: float = 0.5,                 # MMR diversity
        multi_query: int = 0,               # 0 = disabled; else number of expansions
        hyde_cb: Optional[Callable[[str], str]] = None,  # optional HyDE generator(query)->hypothetical answer
        rerank_cb: Optional[Callable[[List[Dict[str, Any]], str], List[Dict[str, Any]]]] = None,  # optional cross-encoder etc.
        keyword_boost: bool = True,
        keywords: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Retrieval with budget-aware packing, optional multi-query & HyDE, optional reranker.
        """
        if not k:
            k = 8

        # Build query set
        queries = [query]
        if multi_query and multi_query > 0:
            # naive expansions: split into bigrams/variations; if hyde_cb present, also add HyDE
            if hyde_cb:
                try:
                    hyp = hyde_cb(query)
                    if isinstance(hyp, str) and hyp.strip():
                        queries.append(hyp.strip())
                except Exception:
                    pass
            # cheap variations: prepend/append key verbs
            extras = []
            for verb in ["explain", "summarize", "outline", "list"]:
                extras.append(f"{verb} {query}")
            queries += extras[:max(0, multi_query - (len(queries)-1))]

        # retrieve per query
        hits: List[Document] = []
        for q in queries:
            retriever = self.vs.as_retriever(
                search_type=search_type,
                search_kwargs={"k": k, "lambda_mult": alpha} if search_type == "mmr" else {"k": k},
            )
            docs = retriever.invoke(q)
            hits.extend(docs)

        # de-dup by id, keep first occurrence (order ~ similarity)
        seen, uniq = set(), []
        for d in hits:
            if d.metadata is None:
                d.metadata = {}
            _id = d.metadata.get("id") or d.metadata.get("source") or d.metadata.get("uuid") or d.metadata.get("chunk_id")
            # fallback: hash content
            _id = _id or _sha256_bytes(d.page_content.encode())
            if _id in seen: 
                continue
            seen.add(_id)
            d.metadata["__uid__"] = _id
            uniq.append(d)

        # keyword boost (BM25-ish)
        if keyword_boost:
            if keywords is None:
                # crude keywordization
                toks = [t.lower() for t in query.split() if len(t) > 3]
                keywords = sorted(set(toks))
            scored = []
            for d in uniq:
                kw = _default_keyword_score(d.page_content, keywords)
                scored.append((kw, d))
            # stable sort by kw desc then keep original order
            uniq = [d for _, d in sorted(scored, key=lambda x: x[0], reverse=True)]

        # pack to budget
        packed: List[Dict[str, Any]] = []
        used = 0
        for d in uniq:
            tok = _count_tokens(d.page_content)
            if used + tok > max_tokens:
                continue
            packed.append({"content": d.page_content, "metadata": d.metadata, "tokens": tok})
            used += tok

        # reranker hook (optional)
        if rerank_cb:
            try:
                packed = rerank_cb(packed, query)
            except Exception:
                pass

        # Deduplicate by concept_name for CartON semantic discovery
        concept_scores = {}
        for idx, doc in enumerate(packed):
            concept_name = doc["metadata"].get("concept_name")
            if concept_name:
                if concept_name not in concept_scores:
                    concept_scores[concept_name] = {
                        "concept_name": concept_name,
                        "chunk_count": 0,
                        "total_score": 0.0,
                        "first_rank": idx  # Track original rank for sorting
                    }
                concept_scores[concept_name]["chunk_count"] += 1
                # Score based on inverse rank (earlier = higher score)
                concept_scores[concept_name]["total_score"] += 1.0 / (idx + 1)

        # Sort by total_score descending and format as numbered list
        sorted_concepts = sorted(
            concept_scores.items(),
            key=lambda x: x[1]["total_score"],
            reverse=True
        )

        # Format as simple numbered list: "1. Name (score)"
        concepts_formatted = "\n".join([
            f"{i}. {concept_name} ({data['total_score']:.2f})"
            for i, (concept_name, data) in enumerate(sorted_concepts, 1)
        ])

        return {
            "status": "success",
            "operation": "query",
            "query": query,
            "expansions": len(queries)-1,
            "documents_retrieved": len(packed),
            "total_tokens": used,
            "max_tokens": max_tokens,
            "results": packed,
            "concepts": concepts_formatted,  # Formatted numbered list
            "prioritization_info": {
                "method": "keyword_boost+MMR" if keyword_boost else "MMR",
                "keywords_used": keywords or [],
                "search_type": search_type,
                "alpha": alpha,
            },
        }

    # --------- internals ---------

    def _load_and_split_file(self, path: Path) -> List[Document]:
        loader = TextLoader(str(path))
        docs = loader.load()
        return self._split_docs(docs, source=str(path))

    def _split_text(self, text: str, source: str, extra_meta: Dict[str, Any]) -> List[Document]:
        docs = [Document(page_content=text, metadata={"source": source, **extra_meta})]
        return self._split_docs(docs, source=source)

    def _split_docs(self, docs: List[Document], source: str) -> List[Document]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        splits = splitter.split_documents(docs)
        # ensure source present
        for i, d in enumerate(splits):
            d.metadata = dict(d.metadata or {}, source=source, chunk_idx=i)
        return splits

    def _count_chunks(self) -> int:
        return self.vs._collection.count()