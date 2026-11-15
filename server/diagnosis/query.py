import asyncio

from langchain_core.prompts import PromptTemplate

from ..config.embeddings import get_embed_model
from ..config.llm import get_llm, get_model_label
from ..config.vectordb import index

TOP_K = 5

llm = get_llm()  # Groq or Gemini, chosen by LLM_PROVIDER in .env

prompt = PromptTemplate.from_template(
    """
You are a medical assistant. Using ONLY the provided context (portions of the user's report), produce:
1) A concise probable diagnosis (1-2 lines)
2) Key findings from the report (bullet points), citing the source in brackets, e.g. [report1.pdf, page 2]
3) Recommended next steps (tests/treatments) — label clearly as suggestions, not medical advice.

If the context does not contain enough information to answer, say so instead of guessing.

Context:
{context}

User question:
{question}
""")

rag_chain = prompt | llm


def _source_label(md: dict) -> str:
    source = md.get("source", "unknown")
    page = md.get("page")
    return f"{source} (page {page})" if page is not None else source


async def diagnosis_report(user: str, doc_id: str, question: str) -> dict:
    # 1) Embed the question with the SAME model used at indexing time
    embed_model = get_embed_model()
    embedding = await asyncio.to_thread(lambda: embed_model.encode(question).tolist())

    # 2) Search ONLY this report's chunks. The filter runs inside Pinecone, so the
    #    top-k is chosen from this doc_id (previously top-k was taken from the whole
    #    index and filtered afterwards, which often left nothing).
    results = await asyncio.to_thread(
        index.query,
        vector=embedding,
        top_k=TOP_K,
        include_metadata=True,
        filter={"doc_id": {"$eq": doc_id}},
    )

    # 3) Read back the ORIGINAL TEXT stored as metadata (vectors are never decoded)
    contexts = []
    sources = []
    for match in results.get("matches", []):
        md = match.get("metadata", {}) or {}
        text = md.get("text") or ""
        if not text:
            continue
        label = _source_label(md)
        contexts.append(f"[{label}]\n{text}")
        if label not in sources:
            sources.append(label)

    if not contexts:
        return {
            "diagnosis": None,
            "sources": [],
            "message": "No indexed content was found for this report. Please re-upload it.",
        }

    # 4) Send the retrieved text (with source labels) + question to the LLM
    context_text = "\n\n".join(contexts)
    final = await asyncio.to_thread(rag_chain.invoke, {"context": context_text, "question": question})

    return {"diagnosis": final.content, "sources": sources, "model": get_model_label(), "message": "ok"}
