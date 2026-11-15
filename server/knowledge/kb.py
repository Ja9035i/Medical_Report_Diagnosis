"""
Semantic search over the curated knowledge base.

The knowledge base is small (a few dozen entries), so it is embedded once and
searched in memory with cosine similarity — no network round trip. A large
knowledge base would move to its own Pinecone namespace instead.
"""
import numpy as np

from ..config import embeddings
from .conditions import CONDITIONS, CONDITIONS_BY_ID

_cache = {}  # id(embedding model) -> normalised matrix of entry vectors


def entry_text(condition) -> str:
    return (f"{condition['name']}. {condition['summary']} "
            f"Typically confirmed with: {', '.join(condition['confirm_tests'])}.")


def _normalise(matrix):
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


def _entry_matrix(model):
    key = id(model)
    if key not in _cache:
        vectors = np.asarray(model.encode([entry_text(c) for c in CONDITIONS]), dtype=float)
        _cache.clear()
        _cache[key] = _normalise(vectors)
    return _cache[key]


def search_kb(query: str, k: int = 3, include_ids=()):
    """
    Return up to `k` + len(include_ids) knowledge entries: the ids in
    `include_ids` first (e.g. conditions suggested by the lab pattern), then the
    entries most semantically similar to `query`.
    """
    results = [CONDITIONS_BY_ID[i] for i in include_ids if i in CONDITIONS_BY_ID]
    seen = {c["id"] for c in results}

    if query and query.strip():
        model = embeddings.get_embed_model()
        matrix = _entry_matrix(model)
        q = _normalise(np.asarray(model.encode(query), dtype=float))
        order = np.argsort(-(matrix @ q))
        added = 0
        for i in order:
            condition = CONDITIONS[int(i)]
            if condition["id"] in seen:
                continue
            results.append(condition)
            seen.add(condition["id"])
            added += 1
            if added >= k:
                break
    return results


def format_knowledge(entries) -> str:
    if not entries:
        return "None."
    blocks = []
    for c in entries:
        blocks.append(f"[KB: {c['name']}] (source: {c['source']})\n{c['summary']}\n"
                      f"Typically confirmed with: {', '.join(c['confirm_tests'])}.")
    return "\n\n".join(blocks)


def knowledge_sources(entries):
    return [{"name": c["name"], "source": c["source"], "url": c["url"]} for c in entries]
