import asyncio

from langchain_core.prompts import PromptTemplate

from ..config import llm
from ..knowledge.kb import format_knowledge, knowledge_sources, search_kb
from ..labs.extract import abnormal
from .retrieval import hybrid_retrieve

TOP_K = 5
KB_K = 3

prompt = PromptTemplate.from_template(
    """
You are a medical assistant. Using ONLY the patient's report context, the rule-checked lab values
and the reference medical knowledge below, produce:
1) A concise probable diagnosis (1-2 lines)
2) Key findings from the report (bullet points), citing the source in brackets, e.g. [report1.pdf, page 2]
3) Recommended next steps (tests/treatments) — label clearly as suggestions, not medical advice.

The lab flags below were computed by deterministic rules from the report's numbers.
Treat them as correct; do not re-judge whether a value is high or low.
If any value is marked CRITICAL, state at the very start that the patient should seek urgent medical care.
The reference medical knowledge is general background, NOT facts about this patient: use it to explain
patterns and suggest confirmatory tests, and cite it as [KB: name]. Only state patient facts found in the report.
If the context does not contain enough information to answer, say so instead of guessing.

Rule-checked abnormal lab values:
{lab_flags}

Reference medical knowledge:
{knowledge}

Patient report context:
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


async def diagnosis_report(user: str, doc_id: str, question: str, labs=None, chunks=None) -> dict:
    # 1-3) Hybrid retrieval over ONLY this report: vector + BM25, fused, reranked.
    #      Results carry the ORIGINAL chunk text (vectors are never decoded).
    retrieved = await hybrid_retrieve(question, doc_id, chunks=chunks, final_k=TOP_K)

    contexts = []
    sources = []
    for chunk in retrieved:
        label = _source_label(chunk)
        contexts.append(f"[{label}]\n{chunk['text']}")
        if label not in sources:
            sources.append(label)

    if not contexts:
        return {
            "diagnosis": None,
            "sources": [],
            "message": "No indexed content was found for this report. Please re-upload it.",
        }

    # 4) Second knowledge source: general medical knowledge relevant to the
    #    question and the abnormal labs (dual-source RAG)
    abnormal_labs = abnormal(labs or [])
    kb_query = " ".join([question] + [f"{lab['test']} {lab['flag'].lower()}" for lab in abnormal_labs])
    kb_entries = await asyncio.to_thread(search_kb, kb_query, KB_K)

    # 5) Send report context, rule-checked lab flags, knowledge and question to the LLM
    context_text = "\n\n".join(contexts)
    final = await asyncio.to_thread(
        get_rag_chain().invoke,
        {
            "context": context_text,
            "question": question,
            "lab_flags": format_lab_flags(labs),
            "knowledge": format_knowledge(kb_entries),
        },
    )

    return {
        "diagnosis": final.content,
        "sources": sources,
        "knowledge_sources": knowledge_sources(kb_entries),
        "abnormal_labs": abnormal_labs,
        "model": llm.get_model_label(),
        "message": "ok",
    }
