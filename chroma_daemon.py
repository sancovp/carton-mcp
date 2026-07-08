#!/usr/bin/env python3
"""
chroma_daemon.py — THE chroma daemon. The SOLE importer of chromadb/langchain/onnxruntime in the system.

DECIDED ARCHITECTURE (Isaac, 2026-06-24; journal Carton_Chroma_Daemon/Chroma_Through_Daemon_Only).
The :8101 chromadb server (started by observation_worker_daemon) is only the vector STORE — it requires
pre-computed `query_embeddings` (it rejects `query_texts`), so every client that wanted to query had to
EMBED its own text, which forced langchain + onnxruntime into every process. THAT is the missing half this
file completes: the EMBEDDER lives HERE, in one daemon. Clients send TEXT over HTTP; this daemon embeds
(onnxruntime, the ONLY place) + queries :8101 + returns results. Every other library calls this daemon via
the thin `chroma_client` (urllib only, ZERO chroma import) so carton / observation_worker / flight-predictor
/ skill-manager / heaven all stay LIGHT.

Endpoints (POST JSON, except /health GET):
  /query   {collection, query, k?, max_tokens?, search_type?}   -> SmartChromaRAG.query(...)
  /index   {collection, path, upsert?}                          -> SmartChromaRAG.ingest_path(...)
  /upsert  {collection, doc_id, content, metadata?}             -> SmartChromaRAG.upsert_document(...)
  /delete  {collection, ids?|where?}                            -> SmartChromaRAG.delete(...)
  /route   {name}                                               -> route_concept_to_collection(name)
  /health  (GET)                                                -> {ok, collections_cached}

Run:  python3 -m carton_mcp.chroma_daemon [--port 8190]
The heavy import is LAZY (first /query etc.) so the process is cheap until actually used.
"""
import json
import os
import sys
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = int(os.environ.get("CHROMA_DAEMON_PORT", "8190"))
_RAG_CACHE: dict = {}


def _get_rag(collection_name: str):
    """Lazy: the ONE place SmartChromaRAG (langchain/chroma/onnxruntime) is constructed."""
    if collection_name not in _RAG_CACHE:
        from carton_mcp.smart_chroma_rag import SmartChromaRAG
        hdd = os.environ.get("HEAVEN_DATA_DIR", "/tmp/heaven_data")
        chroma_dir = os.path.join(hdd, "chroma_db")
        _RAG_CACHE[collection_name] = SmartChromaRAG(persist_dir=chroma_dir, collection_name=collection_name)
    return _RAG_CACHE[collection_name]


_RAW_COLL_CACHE: dict = {}


def _get_raw_collection(name: str, metadata: dict = None):
    """A RAW chromadb collection (NOT SmartChromaRAG) — for low-level skillgraph upsert/get/delete done
    via the same :8101 store. The daemon embeds on upsert (it owns onnxruntime). This is what unifies the
    old split callers (carton_utils via HttpClient:8101 + substrate_projector via a separate PersistentClient
    'skill_chroma' dir) onto ONE store reached through the daemon."""
    if name not in _RAW_COLL_CACHE:
        import chromadb
        host = os.environ.get("CHROMA_HTTP_HOST", "localhost")
        port = int(os.environ.get("CHROMA_HTTP_PORT", "8101"))
        client = chromadb.HttpClient(host=host, port=port)
        _RAW_COLL_CACHE[name] = client.get_or_create_collection(
            name=name, metadata=metadata or {"hnsw:space": "cosine"})
    return _RAW_COLL_CACHE[name]


def _handle(path: str, body: dict) -> dict:
    if path == "/query":
        rag = _get_rag(body.get("collection") or "carton_concepts")
        # Empty/missing collection -> return empty results, never error (the old client did this by
        # checking rag.vs._collection.count() before querying; fold it into the daemon).
        try:
            if rag._count_chunks() == 0:
                return {"status": "success", "results": [], "documents_retrieved": 0, "empty": True}
        except Exception:
            return {"status": "success", "results": [], "documents_retrieved": 0, "empty": True}
        return rag.query(query=body["query"], k=body.get("k"),
                         max_tokens=body.get("max_tokens", 20000),
                         search_type=body.get("search_type", "mmr"),
                         keyword_boost=body.get("keyword_boost", True))
    if path == "/add_texts":
        # BULK upsert (sync_rag): texts are embedded by the engine here. ids/docs/metadatas are parallel.
        rag = _get_rag(body.get("collection") or "carton_concepts")
        docs = body.get("docs") or []
        ids = body.get("ids") or None
        metas = body.get("metadatas") or [{} for _ in docs]
        rag.vs.add_texts(docs, metadatas=metas, ids=ids)
        return {"status": "success", "added": len(docs)}
    if path == "/index":
        kw = {"doc_path": body["path"], "upsert": body.get("upsert", True)}
        if body.get("glob"):
            kw["glob"] = body["glob"]
        return _get_rag(body.get("collection") or "carton_concepts").ingest_path(**kw)
    if path == "/upsert":
        return _get_rag(body.get("collection") or "carton_concepts").upsert_document(
            doc_id=body["doc_id"], content=body["content"], metadata=body.get("metadata"))
    if path == "/delete":
        return _get_rag(body.get("collection") or "carton_concepts").delete(
            ids=body.get("ids"), where=body.get("where"))
    if path == "/route":
        from carton_mcp.smart_chroma_rag import route_concept_to_collection
        return {"collection": route_concept_to_collection(body["name"])}
    # RAW collection ops (skillgraphs etc.) — low-level get/upsert/delete on a non-RAG collection.
    if path == "/coll_get_ids":
        coll = _get_raw_collection(body["collection"], body.get("metadata"))
        return {"ids": coll.get(include=[]).get("ids", [])}
    if path == "/coll_upsert":
        coll = _get_raw_collection(body["collection"], body.get("metadata"))
        coll.upsert(ids=body["ids"], documents=body.get("documents"), metadatas=body.get("metadatas"))
        return {"status": "success", "upserted": len(body["ids"])}
    if path == "/coll_delete":
        coll = _get_raw_collection(body["collection"], body.get("metadata"))
        ids = body.get("ids") or []
        if ids:
            coll.delete(ids=ids)
        return {"status": "success", "deleted": len(ids)}
    if path == "/coll_query":
        # NATIVE chromadb query (the daemon embeds query_texts via onnxruntime, then queries :8101).
        # Returns chromadb's native nested result: {ids, documents, metadatas, distances}.
        coll = _get_raw_collection(body["collection"], body.get("metadata"))
        kw = {"query_texts": [body["query"]], "n_results": body.get("n_results", 10)}
        if body.get("where"):
            kw["where"] = body["where"]
        return coll.query(**kw)
    if path == "/coll_get":
        # NATIVE chromadb get-by-ids (or where) -> {ids, documents, metadatas}.
        coll = _get_raw_collection(body["collection"], body.get("metadata"))
        kw = {}
        if body.get("ids"):
            kw["ids"] = body["ids"]
        if body.get("where"):
            kw["where"] = body["where"]
        return coll.get(**kw)
    if path == "/coll_count":
        coll = _get_raw_collection(body["collection"], body.get("metadata"))
        return {"count": coll.count()}
    raise ValueError(f"unknown endpoint {path}")


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        data = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True, "collections_cached": list(_RAG_CACHE.keys())})
        else:
            self._send(404, {"error": "GET only on /health"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, _handle(self.path, body))
        except Exception as e:
            import traceback
            self._send(400, {"error": type(e).__name__, "message": str(e),
                             "trace": traceback.format_exc()[-900:]})

    def log_message(self, *a):
        pass  # quiet; launch redirects stdout/stderr to a log


def main(argv):
    p = argparse.ArgumentParser(prog="chroma_daemon")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    a = p.parse_args(argv[1:])
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), _Handler)
    print(f"[chroma_daemon] listening on 127.0.0.1:{a.port} (sole chroma importer; heavy import lazy)",
          file=sys.stderr, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
