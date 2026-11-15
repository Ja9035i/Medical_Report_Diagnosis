"""
Test setup: every external service is replaced by an in-memory fake, so the suite
runs offline, in seconds, and never touches real MongoDB / Pinecone / LLM accounts.
"""
import os
import sys
import tempfile
from pathlib import Path

import mongomock
import numpy as np
import pymongo
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Must run BEFORE any server module is imported:
# - MongoDB -> mongomock (server/config/db.py does `from pymongo import MongoClient`)
# - env vars are set first, so load_dotenv() in the app does not override them
pymongo.MongoClient = mongomock.MongoClient
os.environ.update({
    "MONGO_URI": "mongodb://fake-host",
    "DB_NAME": "test_db",
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "adminpass123",
    "LLM_PROVIDER": "groq",
    "RERANKER_ENABLED": "false",  # no model download in tests; reranking is tested with a fake
    "UPLOAD_DIR": tempfile.mkdtemp(prefix="test_uploads_"),
})

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.language_models.fake_chat_models import FakeListChatModel  # noqa: E402

from server.config import db, embeddings, llm, vectordb  # noqa: E402
from server.main import app  # noqa: E402

FAKE_ANSWER = "Probable diagnosis: iron-deficiency anemia [cbc.txt]"


class FakeEmbedder:
    """Deterministic stand-in for MiniLM: returns small numpy vectors."""

    def encode(self, texts):
        single = isinstance(texts, str)
        items = [texts] if single else texts
        vectors = np.array([[float(len(t) % 7 + 1), 0.0, 0.0, 0.0] for t in items])
        return vectors[0] if single else vectors


class FakeIndex:
    """In-memory Pinecone index supporting upsert and a doc_id $eq filter."""

    def __init__(self):
        self.vectors = {}

    def upsert(self, vectors):
        for vector_id, values, metadata in vectors:
            self.vectors[vector_id] = (values, metadata)

    def query(self, vector, top_k, include_metadata, filter):
        wanted = filter["doc_id"]["$eq"]
        matches = [
            {"id": vid, "metadata": md}
            for vid, (_, md) in self.vectors.items()
            if md["doc_id"] == wanted
        ]
        return {"matches": matches[:top_k]}


@pytest.fixture
def fake_index():
    return FakeIndex()


@pytest.fixture
def client(monkeypatch, fake_index):
    # Fresh database for every test
    for collection in (db.users_collection, db.reports_collection, db.diagnosis_collection):
        collection.delete_many({})
    try:
        db.users_collection.drop_indexes()
    except Exception:
        pass

    monkeypatch.setattr(embeddings, "get_embed_model", lambda: FakeEmbedder())
    monkeypatch.setattr(vectordb, "get_index", lambda: fake_index)
    monkeypatch.setattr(llm, "get_llm", lambda: FakeListChatModel(responses=[FAKE_ANSWER]))
    monkeypatch.setattr(llm, "get_model_label", lambda: "fake:test-model")

    with TestClient(app) as test_client:  # runs startup -> admin bootstrap
        yield test_client


# ---------- helpers ----------

PASSWORD = "testpass123"


def make_pdf(text: str) -> bytes:
    """Build a minimal one-page PDF containing `text` (no extra libraries needed)."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_at)
    return out


@pytest.fixture
def signup(client):
    def _signup(username):
        response = client.post("/auth/signup", json={"username": username, "password": PASSWORD})
        assert response.status_code == 200, response.text
        return (username, PASSWORD)
    return _signup


@pytest.fixture
def admin_auth():
    return ("admin", "adminpass123")


@pytest.fixture
def upload(client):
    def _upload(auth, files):
        return client.post("/reports/upload", auth=auth, files=[("files", f) for f in files])
    return _upload
