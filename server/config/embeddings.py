from functools import lru_cache

# Must be the same model for indexing and querying, otherwise the vectors
# live in different spaces and similarity search is meaningless.
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
EMBED_DIM = 384


@lru_cache(maxsize=1)
def get_embed_model():
    """Load the embedding model once per process, on first use (importing torch is slow)."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBED_MODEL_NAME)
