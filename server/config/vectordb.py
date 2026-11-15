import os
import time
from functools import lru_cache

from dotenv import load_dotenv

from .embeddings import EMBED_DIM

load_dotenv()

PINECONE_ENV = os.getenv("PINECONE_ENV", "us-east-1")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "rbac-diagnosis-index")


@lru_cache(maxsize=1)
def get_index():
    """
    Connect to Pinecone on first use (not at import time) and create the index if
    it does not exist. Lazy creation keeps imports fast and lets tests swap in a fake.
    """
    from pinecone import Pinecone, ServerlessSpec

    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    existing = [i["name"] for i in pc.list_indexes()]
    if PINECONE_INDEX_NAME not in existing:
        pc.create_index(
            name=PINECONE_INDEX_NAME,
            dimension=EMBED_DIM,
            metric="dotproduct",  # MiniLM vectors are normalized, so this equals cosine
            spec=ServerlessSpec(cloud="aws", region=PINECONE_ENV),
        )
        while not pc.describe_index(PINECONE_INDEX_NAME).status["ready"]:
            time.sleep(1)
    return pc.Index(PINECONE_INDEX_NAME)
