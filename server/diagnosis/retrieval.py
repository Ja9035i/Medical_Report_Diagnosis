"""
Hybrid retrieval for one report:

1. Vector search  (Pinecone, semantic meaning)      -> top VECTOR_K chunk ids
2. Keyword search (BM25 over the report's chunks)   -> top BM25_K chunk ids
3. Reciprocal Rank Fusion merges both rankings
4. Optional cross-encoder reranker reorders the best candidates

Vector search finds paraphrases ("low iron" ~ "ferritin deficiency"); BM25 finds
exact terms, numbers and abbreviations ("CRP", "HbA1c", "11,500") that embeddings
can blur. Fusion gets the strengths of both.
"""
import asyncio
import os
import re
import threading
from functools import lru_cache

from rank_bm25 import BM25Okapi

from ..config import embeddings, vectordb  # embeddings also sets reliable HF download options

VECTOR_K = 10
BM25_K = 10
FINAL_K = 5
RRF_K = 60  # standard RRF constant: dampens the advantage of top ranks
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def tokenize(text: str):
    """Lowercase words and numbers; keeps decimals like '9.1' together."""
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", (text or "").lower())


def bm25_search(question: str, chunks, k: int = BM25_K):
    """Return chunk ids ranked by BM25 keyword relevance (chunks with zero score are dropped)."""
    if not chunks:
        return []
    bm25 = BM25Okapi([tokenize(c["text"]) for c in chunks])
    scores = bm25.get_scores(tokenize(question))
    ranked = sorted(range(len(chunks)), key=lambda i: -scores[i])
    return [chunks[i]["id"] for i in ranked[:k] if scores[i] > 0]


def reciprocal_rank_fusion(rankings, k: int = RRF_K):
    """Merge several ranked id lists: score(id) = sum over lists of 1 / (k + rank)."""
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item: -scores[item])


def reranker_enabled() -> bool:
    return os.getenv("RERANKER_ENABLED", "true").strip().lower() in ("1", "true", "yes")


def reranker_timeout() -> float:
    return float(os.getenv("RERANKER_TIMEOUT", "15"))


@lru_cache(maxsize=1)
def get_reranker():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(RERANKER_MODEL)


# The model is downloaded on first use. A slow or blocked network must never
# freeze a diagnosis, so loading happens in a background thread:
#   not_loaded -> loading -> ready | failed
_reranker = {"status": "not_loaded"}
_reranker_lock = threading.Lock()
_reranker_done = threading.Event()


def reranker_status() -> str:
    return _reranker["status"]


def _reset_reranker_state():
    """Test helper."""
    _reranker["status"] = "not_loaded"
    _reranker_done.clear()


def start_reranker_loading():
    """Begin loading the cross-encoder in the background (once)."""
    def load():
        try:
            get_reranker()
            _reranker["status"] = "ready"
            print("[retrieval] reranker loaded")
        except Exception as exc:
            _reranker["status"] = "failed"
            print(f"[retrieval] reranker failed to load, continuing without it: {exc}")
        finally:
            _reranker_done.set()

    with _reranker_lock:
        if _reranker["status"] == "not_loaded":
            _reranker["status"] = "loading"
            threading.Thread(target=load, daemon=True, name="reranker-loader").start()


def rerank(question: str, chunks):
    """Score each (question, chunk) pair jointly with a cross-encoder and sort by score."""
    scores = get_reranker().predict([(question, c["text"]) for c in chunks])
    ranked = sorted(zip(scores, range(len(chunks))), key=lambda pair: -float(pair[0]))
    return [chunks[i] for _, i in ranked]


async def vector_search(question: str, doc_id: str, k: int = VECTOR_K):
    embed_model = embeddings.get_embed_model()
    vector = await asyncio.to_thread(lambda: embed_model.encode(question).tolist())
    index = vectordb.get_index()
    results = await asyncio.to_thread(
        index.query,
        vector=vector,
        top_k=k,
        include_metadata=True,
        filter={"doc_id": {"$eq": doc_id}},  # only this report's chunks
    )
    hits = []
    for match in results.get("matches", []):
        md = match.get("metadata", {}) or {}
        if md.get("text"):
            hits.append({"id": match.get("id"), "text": md["text"],
                         "source": md.get("source"), "page": md.get("page")})
    return hits


async def hybrid_retrieve(question: str, doc_id: str, chunks=None, final_k: int = FINAL_K):
    """
    Best `final_k` chunks for the question. `chunks` are the report's stored chunks
    (used for BM25); older reports without them fall back to vector search only.
    """
    vector_hits = await vector_search(question, doc_id)
    by_id = {hit["id"]: hit for hit in vector_hits}
    rankings = [[hit["id"] for hit in vector_hits]]

    if chunks:
        for chunk in chunks:
            by_id.setdefault(chunk["id"], chunk)
        rankings.append(bm25_search(question, chunks))

    fused = [by_id[i] for i in reciprocal_rank_fusion(rankings) if i in by_id]
    candidates = fused[: final_k * 2]

    if reranker_enabled() and len(candidates) > 1:
        candidates = await _maybe_rerank(question, candidates)

    return candidates[:final_k]


async def _maybe_rerank(question: str, candidates):
    """Rerank if the model is ready; never wait longer than RERANKER_TIMEOUT."""
    timeout = reranker_timeout()
    if reranker_status() == "not_loaded":
        # First request: start loading and wait a bounded time for it.
        start_reranker_loading()
        await asyncio.to_thread(_reranker_done.wait, timeout)
    if reranker_status() != "ready":
        # Still downloading (or failed): use the fused order instead of blocking.
        return candidates
    try:
        return await asyncio.wait_for(asyncio.to_thread(rerank, question, candidates), timeout)
    except Exception as exc:  # includes timeouts; reranking is an optimisation, not a requirement
        print(f"[retrieval] reranking skipped, using fused order: {exc!r}")
        return candidates
