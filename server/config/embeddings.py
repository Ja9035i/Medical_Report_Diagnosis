import os
from functools import lru_cache

# Hugging Face's "Xet" transfer backend can stall at 0 bytes on some networks;
# plain HTTPS downloads are reliable. Must be set before huggingface_hub is imported.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Must be the same model for indexing and querying, otherwise the vectors
# live in different spaces and similarity search is meaningless.
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
EMBED_DIM = 384


@lru_cache(maxsize=1)
def get_embed_model():
    """Load the embedding model once per process, on first use (importing torch is slow)."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBED_MODEL_NAME)
