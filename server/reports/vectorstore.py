import os
import time
import asyncio
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import UploadFile, HTTPException
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import embeddings, vectordb
from ..config.db import reports_collection
from ..labs.critical import check_critical
from ..labs.extract import extract_lab_values
from .loaders import LOADERS

load_dotenv()

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploaded_dir")
os.makedirs(UPLOAD_DIR, exist_ok=True)

UPSERT_BATCH_SIZE = 100  # stay well under Pinecone's per-request size limit

splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)


async def load_vectorstore(uploaded_files: List[UploadFile], uploaded: str, doc_id: str) -> dict:
    """
    Save every uploaded file, chunk its text, embed the chunks, upsert them into
    Pinecone (vector + original text as metadata), extract structured lab values
    with rule-based flags, and record the report in MongoDB.
    Returns {"num_chunks", "labs", "critical_alerts"}.
    """
    # Validate all file types first so we never save half of a bad upload.
    for file in uploaded_files:
        ext = Path(file.filename).suffix.lower()
        if ext not in LOADERS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext}' for {file.filename}. Allowed: PDF, TXT, PNG, JPG.",
            )

    all_chunks = []
    filenames = []
    all_labs = []

    for file in uploaded_files:
        filename = Path(file.filename).name
        ext = Path(filename).suffix.lower()

        # 1) Save the raw file to disk
        save_path = Path(UPLOAD_DIR) / f"{doc_id}_{filename}"
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)

        # 2) Load -> 3) split, for EVERY file (previously only the last file was indexed)
        documents = await asyncio.to_thread(LOADERS[ext], str(save_path))
        chunks = splitter.split_documents(documents)
        for chunk in chunks:
            chunk.metadata["source"] = filename
        all_chunks.extend(chunks)
        filenames.append(filename)

        # Structured lab values with deterministic HIGH/LOW flags (no LLM)
        file_labs = extract_lab_values("\n".join(doc.page_content for doc in documents))
        for lab in file_labs:
            lab["source"] = filename
        all_labs.extend(file_labs)

    if not all_chunks:
        raise HTTPException(
            status_code=400,
            detail="No readable text found in the uploaded files (for scanned reports, install OCR: pip install -r requirements-ocr.txt).",
        )

    texts = [chunk.page_content for chunk in all_chunks]
    ids = [f"{doc_id}-{i}" for i in range(len(all_chunks))]

    metadatas = []
    for chunk in all_chunks:
        md = {
            "source": chunk.metadata["source"],
            "doc_id": doc_id,
            "uploader": uploaded,
            "text": chunk.page_content[:2000],  # original text, read back at query time
        }
        page = chunk.metadata.get("page")
        if page is not None:  # Pinecone rejects null metadata; TXT files have no pages
            md["page"] = int(page)  # loaders already use 1-based page numbers
        metadatas.append(md)

    # 4) Embed with the shared model (loaded once per process)
    embed_model = embeddings.get_embed_model()
    vectors_values = await asyncio.to_thread(lambda: embed_model.encode(texts).tolist())

    # 5) Upsert in batches
    vectors = list(zip(ids, vectors_values, metadatas))
    index = vectordb.get_index()

    def upsert():
        for start in range(0, len(vectors), UPSERT_BATCH_SIZE):
            index.upsert(vectors=vectors[start:start + UPSERT_BATCH_SIZE])

    await asyncio.to_thread(upsert)

    # 6) Critical-value rules (red flags) on the extracted labs
    critical_alerts = check_critical(all_labs)

    # 7) Report metadata in MongoDB (ownership is checked against "uploader")
    reports_collection.insert_one({
        "doc_id": doc_id,
        "filename": ", ".join(filenames),
        "filenames": filenames,
        "uploader": uploaded,
        "num_chunks": len(all_chunks),
        # Chunk text kept here too, so BM25 keyword search can run over the whole report
        "chunks": [
            {"id": ids[i], "text": md["text"], "source": md["source"], "page": md.get("page")}
            for i, md in enumerate(metadatas)
        ],
        "labs": all_labs,
        "critical_alerts": critical_alerts,
        "uploaded_at": time.time(),
    })

    return {"num_chunks": len(all_chunks), "labs": all_labs, "critical_alerts": critical_alerts}
