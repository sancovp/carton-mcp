#!/usr/bin/env python3
"""
chroma_client.py — the THIN client for the chroma daemon. Imports ONLY stdlib (urllib) — ZERO chroma.

This is what EVERY library uses instead of importing chromadb/langchain/onnxruntime. carton, observation_
worker, flight-predictor, skill-manager, heaven — none of them import chroma; they import THIS and make an
HTTP call to the chroma_daemon (which is the sole chroma importer). See chroma_daemon.py for the daemon.

  from carton_mcp.chroma_client import chroma_query, chroma_index, chroma_route, chroma_daemon_up
  res = chroma_query("carton_concepts", "what is the read layer", k=8)

If the daemon is down, every call raises ChromaDaemonError (callers decide: skip RAG, or ensure the daemon).
"""
import json
import os
import urllib.request
import urllib.error

_PORT = int(os.environ.get("CHROMA_DAEMON_PORT", "8190"))
_BASE = f"http://127.0.0.1:{_PORT}"
_TIMEOUT = float(os.environ.get("CHROMA_DAEMON_TIMEOUT", "60"))


class ChromaDaemonError(RuntimeError):
    pass


def _post(path: str, payload: dict, timeout: float = None) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(_BASE + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except Exception:
            body = {"error": "HTTPError", "message": str(e)}
        raise ChromaDaemonError(f"{path} -> {body.get('error')}: {body.get('message')}")
    except (urllib.error.URLError, OSError) as e:
        raise ChromaDaemonError(f"chroma daemon unreachable at {_BASE} ({e}); is it running? "
                                f"(python3 -m carton_mcp.chroma_daemon)")


def chroma_daemon_up() -> bool:
    try:
        with urllib.request.urlopen(_BASE + "/health", timeout=3) as r:
            return bool(json.loads(r.read() or b"{}").get("ok"))
    except Exception:
        return False


def chroma_query(collection: str, query: str, k: int = None, max_tokens: int = 20000,
                 search_type: str = "mmr") -> dict:
    return _post("/query", {"collection": collection, "query": query, "k": k,
                            "max_tokens": max_tokens, "search_type": search_type})


def chroma_index(collection: str, path: str, upsert: bool = True, glob: str = None) -> dict:
    return _post("/index", {"collection": collection, "path": path, "upsert": upsert, "glob": glob},
                 timeout=float(os.environ.get("CHROMA_DAEMON_INDEX_TIMEOUT", "900")))


def chroma_upsert(collection: str, doc_id: str, content: str, metadata: dict = None) -> dict:
    return _post("/upsert", {"collection": collection, "doc_id": doc_id, "content": content,
                             "metadata": metadata})


def chroma_add_texts(collection: str, ids: list, docs: list, metadatas: list = None) -> dict:
    """BULK upsert (used by sync_rag): parallel ids/docs/metadatas; the daemon embeds + adds them."""
    return _post("/add_texts", {"collection": collection, "ids": ids, "docs": docs,
                                "metadatas": metadatas},
                 timeout=float(os.environ.get("CHROMA_DAEMON_INDEX_TIMEOUT", "900")))


def chroma_delete(collection: str, ids: list = None, where: dict = None) -> dict:
    return _post("/delete", {"collection": collection, "ids": ids, "where": where})


def chroma_route(name: str) -> str:
    return _post("/route", {"name": name}).get("collection", "domain_knowledge")


# --- RAW collection ops (low-level skillgraph get/upsert/delete on a non-RAG collection) ---
def chroma_coll_get_ids(collection: str, metadata: dict = None) -> list:
    return _post("/coll_get_ids", {"collection": collection, "metadata": metadata}).get("ids", [])


def chroma_coll_upsert(collection: str, ids: list, documents: list = None,
                       metadatas: list = None, metadata: dict = None) -> dict:
    return _post("/coll_upsert", {"collection": collection, "ids": ids, "documents": documents,
                                  "metadatas": metadatas, "metadata": metadata})


def chroma_coll_delete(collection: str, ids: list, metadata: dict = None) -> dict:
    return _post("/coll_delete", {"collection": collection, "ids": ids, "metadata": metadata})


def chroma_coll_query(collection: str, query: str, n_results: int = 10,
                      where: dict = None, metadata: dict = None) -> dict:
    """NATIVE chromadb query — returns {ids, documents, metadatas, distances} (nested per-query).
    The daemon embeds query_texts (it owns onnxruntime). For RAG-style packed results use chroma_query."""
    return _post("/coll_query", {"collection": collection, "query": query, "n_results": n_results,
                                 "where": where, "metadata": metadata})


def chroma_coll_get(collection: str, ids: list = None, where: dict = None, metadata: dict = None) -> dict:
    """NATIVE chromadb get by ids (or where) — returns {ids, documents, metadatas}."""
    return _post("/coll_get", {"collection": collection, "ids": ids, "where": where, "metadata": metadata})


def chroma_coll_count(collection: str, metadata: dict = None) -> int:
    return _post("/coll_count", {"collection": collection, "metadata": metadata}).get("count", 0)


class DaemonCollection:
    """Drop-in proxy for a chromadb Collection (the object returned by
    `client.get_or_create_collection(name)`), routed through the chroma daemon. Mirrors the methods the
    codebase uses — query/get/upsert/add/delete/count — so call-site code works unchanged with ZERO
    chroma import. `add` is an alias of `upsert` (upsert is re-run-safe). The daemon owns the embedder."""

    def __init__(self, name: str, metadata: dict = None):
        self.name = name
        self.metadata = metadata

    def query(self, query_texts=None, n_results: int = 10, where: dict = None, **kw) -> dict:
        return chroma_coll_query(self.name, (query_texts or [""])[0], n_results=n_results,
                                 where=where, metadata=self.metadata)

    def get(self, ids=None, where: dict = None, **kw) -> dict:
        return chroma_coll_get(self.name, ids=ids, where=where, metadata=self.metadata)

    def upsert(self, ids=None, documents=None, metadatas=None, **kw) -> dict:
        return chroma_coll_upsert(self.name, ids=ids, documents=documents, metadatas=metadatas,
                                  metadata=self.metadata)

    def add(self, ids=None, documents=None, metadatas=None, **kw) -> dict:
        return self.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def delete(self, ids=None, where: dict = None, **kw) -> dict:
        return chroma_coll_delete(self.name, ids=ids or [], metadata=self.metadata)

    def count(self, **kw) -> int:
        return chroma_coll_count(self.name, metadata=self.metadata)
