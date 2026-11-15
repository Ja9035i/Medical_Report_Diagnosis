"""Tests for hybrid retrieval: BM25, reciprocal rank fusion, reranker hook, end-to-end merge."""
import asyncio

from server.diagnosis import retrieval

CHUNKS = [
    {"id": "d-0", "text": "Patient reports fatigue and shortness of breath.", "source": "r.pdf", "page": 1},
    {"id": "d-1", "text": "Serum ferritin 8 ng/mL, markedly low.", "source": "r.pdf", "page": 2},
    {"id": "d-2", "text": "Chest X-ray shows no consolidation.", "source": "r.pdf", "page": 3},
]


def test_tokenize_keeps_decimals_and_lowercases():
    assert retrieval.tokenize("Hb 9.1 g/dL, CRP") == ["hb", "9.1", "g", "dl", "crp"]


def test_bm25_finds_exact_term_and_drops_zero_scores():
    assert retrieval.bm25_search("ferritin level?", CHUNKS) == ["d-1"]
    assert retrieval.bm25_search("anything", []) == []


def test_reciprocal_rank_fusion_rewards_agreement():
    fused = retrieval.reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "a"]])
    assert fused[0] == "b"  # ranked high by both lists
    assert set(fused) == {"a", "b", "c"}


def test_hybrid_merges_vector_and_keyword_results(monkeypatch):
    async def fake_vector_search(question, doc_id, k=10):
        return [CHUNKS[0], CHUNKS[2]]  # semantic search misses the ferritin chunk

    monkeypatch.setattr(retrieval, "vector_search", fake_vector_search)
    result = asyncio.run(retrieval.hybrid_retrieve("ferritin", "d", chunks=CHUNKS, final_k=3))
    assert "d-1" in [c["id"] for c in result]  # recovered by BM25


def test_hybrid_without_stored_chunks_uses_vector_only(monkeypatch):
    async def fake_vector_search(question, doc_id, k=10):
        return [CHUNKS[2], CHUNKS[0]]

    monkeypatch.setattr(retrieval, "vector_search", fake_vector_search)
    result = asyncio.run(retrieval.hybrid_retrieve("ferritin", "d", chunks=None, final_k=2))
    assert [c["id"] for c in result] == ["d-2", "d-0"]


def test_reranker_reorders_when_enabled(monkeypatch):
    async def fake_vector_search(question, doc_id, k=10):
        return list(CHUNKS)

    monkeypatch.setattr(retrieval, "vector_search", fake_vector_search)
    monkeypatch.setenv("RERANKER_ENABLED", "true")
    monkeypatch.setattr(retrieval, "reranker_status", lambda: "ready")
    monkeypatch.setattr(retrieval, "rerank", lambda q, chunks: list(reversed(chunks)))
    result = asyncio.run(retrieval.hybrid_retrieve("q", "d", chunks=None, final_k=3))
    assert [c["id"] for c in result] == ["d-2", "d-1", "d-0"]


def test_reranker_failure_falls_back_to_fused_order(monkeypatch):
    async def fake_vector_search(question, doc_id, k=10):
        return list(CHUNKS)

    def broken_rerank(q, chunks):
        raise RuntimeError("model download failed")

    monkeypatch.setattr(retrieval, "vector_search", fake_vector_search)
    monkeypatch.setenv("RERANKER_ENABLED", "true")
    monkeypatch.setattr(retrieval, "reranker_status", lambda: "ready")
    monkeypatch.setattr(retrieval, "rerank", broken_rerank)
    result = asyncio.run(retrieval.hybrid_retrieve("q", "d", chunks=None, final_k=3))
    assert [c["id"] for c in result] == ["d-0", "d-1", "d-2"]


def test_hanging_reranker_download_does_not_block(monkeypatch):
    """A stuck model download must not freeze diagnosis: wait at most RERANKER_TIMEOUT once."""
    import time

    async def fake_vector_search(question, doc_id, k=10):
        return list(CHUNKS)

    def slow_load():
        time.sleep(3)  # simulates a download that hangs
        raise RuntimeError("network stalled")

    retrieval._reset_reranker_state()
    monkeypatch.setattr(retrieval, "vector_search", fake_vector_search)
    monkeypatch.setattr(retrieval, "get_reranker", slow_load)
    monkeypatch.setenv("RERANKER_ENABLED", "true")
    monkeypatch.setenv("RERANKER_TIMEOUT", "0.2")

    start = time.time()
    first = asyncio.run(retrieval.hybrid_retrieve("q", "d", chunks=None, final_k=3))
    assert time.time() - start < 2
    assert [c["id"] for c in first] == ["d-0", "d-1", "d-2"]  # fused order, no reranking
    assert retrieval.reranker_status() == "loading"

    start = time.time()
    asyncio.run(retrieval.hybrid_retrieve("q", "d", chunks=None, final_k=3))
    assert time.time() - start < 0.5  # later requests skip immediately while loading
    retrieval._reset_reranker_state()


def test_upload_stores_chunks_for_keyword_search(client, signup, upload):
    from server.config.db import reports_collection
    doc_id = upload(signup("alice"), [("a.txt", b"Ferritin 8 ng/mL LOW", "text/plain")]).json()["doc_id"]
    chunks = reports_collection.find_one({"doc_id": doc_id})["chunks"]
    assert chunks == [{"id": f"{doc_id}-0", "text": "Ferritin 8 ng/mL LOW", "source": "a.txt", "page": None}]
