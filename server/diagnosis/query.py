import asyncio

from langchain_core.prompts import PromptTemplate

from ..config import embeddings, llm, vectordb
from ..labs.extract import abnormal

TOP_K = 5

prompt = PromptTemplate.from_template(
    """
You are a medical assistant. Using ONLY the provided context (portions of the user's report)
and the rule-checked lab values, produce:
1) A concise probable diagnosis (1-2 lines)
2) Key findings from the report (bullet points), citing the source in brackets, e.g. [report1.pdf, page 2]
3) Recommended next steps (tests/treatments) — label clearly as suggestions, not medical advice.

The lab flags below were computed by deterministic rules from the report's numbers.
Treat them as correct; do not re-judge whether a value is high or low.
If any value is marked CRITICAL, state at the very start that the patient should seek urgent medical care.
If the context does not contain enough information to answer, say so instead of guessing.

Rule-checked abnormal lab values:
{lab_flags}

Context:
{context}

User question:
{question}
""")


def format_lab_flags(labs) -> str:
    """One line per abnormal value, e.g. 'Potassium 6.9 mmol/L — HIGH (ref ≤ 5.1, from report) — CRITICAL'."""
    lines = []
    for lab in abnormal(labs or []):
        low, high = lab.get("ref_low"), lab.get("ref_high")
        if low is not None and high is not None:
            ref = f"{low:g}-{high:g}"
        elif high is not None:
            ref = f"≤ {high:g}"
        else:
            ref = f"≥ {low:g}"
        line = f"- {lab['test']} {lab['value']:g} {lab.get('unit') or ''} — {lab['flag']} (ref {ref}, {lab['range_source']} range)"
        if lab.get("critical"):
            line += " — CRITICAL"
        lines.append(line)
    return "\n".join(lines) if lines else "None detected."

def get_rag_chain():
    """Build prompt | llm on demand (the LLM is created once and cached in config.llm)."""
    return prompt | llm.get_llm()  # Groq or Gemini, chosen by LLM_PROVIDER in .env


def _source_label(md: dict) -> str:
    source = md.get("source", "unknown")
    page = md.get("page")
    return f"{source} (page {page})" if page is not None else source


async def diagnosis_report(user: str, doc_id: str, question: str, labs=None) -> dict:
    # 1) Embed the question with the SAME model used at indexing time
    embed_model = embeddings.get_embed_model()
    embedding = await asyncio.to_thread(lambda: embed_model.encode(question).tolist())
    index = vectordb.get_index()

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

    # 4) Send the retrieved text (with source labels), rule-checked lab flags and question to the LLM
    context_text = "\n\n".join(contexts)
    final = await asyncio.to_thread(
        get_rag_chain().invoke,
        {"context": context_text, "question": question, "lab_flags": format_lab_flags(labs)},
    )

    return {
        "diagnosis": final.content,
        "sources": sources,
        "abnormal_labs": abnormal(labs or []),
        "model": llm.get_model_label(),
        "message": "ok",
    }
