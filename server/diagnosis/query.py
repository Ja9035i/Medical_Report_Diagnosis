
from langchain_core.prompts import PromptTemplate

from ..config import llm
from ..labs.extract import abnormal

TOP_K = 5
KB_K = 3

prompt = PromptTemplate.from_template(
    """
You are a medical assistant. Using ONLY the patient's report context, the rule-checked lab values
and the reference medical knowledge below, produce:
1) A concise probable diagnosis (1-2 lines)
2) Differential diagnosis: briefly explain the ranked list below — why the top condition fits best and
   what would distinguish it from the others. If the report text clearly contradicts the ranking, say so.
3) Key findings from the report (bullet points), citing the source label exactly as it appears in the context, e.g. [report1.pdf (page 2)] or [notes.txt]
4) Recommended next steps (tests/treatments) — label clearly as suggestions, not medical advice.

The lab flags below were computed by deterministic rules from the report's numbers.
Treat them as correct; do not re-judge whether a value is high or low.
If any value is marked CRITICAL, state at the very start that the patient should seek urgent medical care.
The reference medical knowledge is general background, NOT facts about this patient: use it to explain
patterns and suggest confirmatory tests, and cite it as [KB: name]. Only state patient facts found in the report.
If the context does not contain enough information to answer, say so instead of guessing.

Rule-checked abnormal lab values:
{lab_flags}

Ranked differential diagnosis (computed by rules from the lab pattern):
{differential}

Reference medical knowledge:
{knowledge}

Patient report context:
{context}
{feedback}
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
    """Run the LangGraph pipeline: retrieve -> analyze -> generate -> check_grounding -> finalize."""
    from .graph import run_diagnosis_graph
    return await run_diagnosis_graph(question, doc_id, labs=labs, chunks=chunks)
