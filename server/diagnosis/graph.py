"""
Diagnosis pipeline as a LangGraph state graph.

    START -> retrieve --(no context)--> END
                |
                v
             analyze -> generate -> check_grounding --(unsupported, retry left)--> generate
                                           |
                                           v
                                       finalize -> END

- retrieve:        hybrid retrieval over this report only
- analyze:         abnormal labs, ranked differential, knowledge-base entries
- generate:        LLM answer (with feedback on a retry)
- check_grounding: second LLM call verifies every patient-specific claim is supported
                   by the report text or the rule-checked lab values
- finalize:        attach the verdict; in GROUNDING_MODE=refuse an answer that is still
                   unsupported after the retry is replaced by a safe refusal
"""
import asyncio
import os
from typing import Optional, TypedDict

from langchain_core.prompts import PromptTemplate
from langgraph.graph import END, START, StateGraph

from ..config import llm
from ..knowledge.differential import format_differential, rank_differential
from ..knowledge.kb import format_knowledge, knowledge_sources, search_kb
from ..labs.extract import abnormal
from .retrieval import hybrid_retrieve

MAX_RETRIES = 1
REFUSAL = ("I could not produce an answer that is fully supported by your report. "
           "Please review your results with a doctor.")

GROUNDING_PROMPT = PromptTemplate.from_template(
    """You are verifying a medical answer against the patient's report.

Patient report context:
{context}

Rule-checked abnormal lab values (these count as supported facts):
{lab_flags}

Answer to verify:
{answer}

Check ONLY statements about THIS patient (their values, symptoms, history and findings).
General medical explanations, differential reasoning, [KB: ...] references and suggested
next steps do not need support from the report.
If every patient-specific statement is supported by the report context or the lab values,
reply with exactly: SUPPORTED
Otherwise reply: UNSUPPORTED: <short list of the unsupported statements>"""
)


class DiagnosisState(TypedDict, total=False):
    question: str
    doc_id: str
    labs: list
    chunks: Optional[list]
    contexts: list
    sources: list
    abnormal_labs: list
    differential: list
    kb_entries: list
    answer: Optional[str]
    attempts: int
    grounded: Optional[bool]
    grounding_note: Optional[str]


def grounding_enabled() -> bool:
    return os.getenv("GROUNDING_CHECK", "true").strip().lower() in ("1", "true", "yes")


def grounding_mode() -> str:
    return os.getenv("GROUNDING_MODE", "warn").strip().lower()


def parse_verdict(text: str):
    """'SUPPORTED' -> (True, None); 'UNSUPPORTED: x, y' -> (False, 'x, y')."""
    cleaned = (text or "").strip()
    if cleaned.upper().startswith("SUPPORTED"):
        return True, None
    note = cleaned.split(":", 1)[1].strip() if ":" in cleaned else cleaned
    return False, note or "The verifier could not confirm the answer against the report."


# ---------------- nodes ----------------

async def retrieve_node(state: DiagnosisState):
    from .query import TOP_K, _source_label

    retrieved = await hybrid_retrieve(state["question"], state["doc_id"],
                                      chunks=state.get("chunks"), final_k=TOP_K)
    contexts, sources = [], []
    for chunk in retrieved:
        label = _source_label(chunk)
        contexts.append(f"[{label}]\n{chunk['text']}")
        if label not in sources:
            sources.append(label)
    return {"contexts": contexts, "sources": sources}


def route_after_retrieve(state: DiagnosisState):
    return "analyze" if state.get("contexts") else END


async def analyze_node(state: DiagnosisState):
    from .query import KB_K

    labs = state.get("labs") or []
    abnormal_labs = abnormal(labs)
    differential = rank_differential(labs)
    kb_query = " ".join([state["question"]] + [f"{lab['test']} {lab['flag'].lower()}" for lab in abnormal_labs])
    kb_entries = await asyncio.to_thread(search_kb, kb_query, KB_K, [d["id"] for d in differential[:3]])
    return {"abnormal_labs": abnormal_labs, "differential": differential, "kb_entries": kb_entries}


async def generate_node(state: DiagnosisState):
    from .query import format_lab_flags, get_rag_chain

    feedback = ""
    if state.get("grounded") is False:
        feedback = ("IMPORTANT: a previous draft contained statements not supported by the report: "
                    f"{state.get('grounding_note')}. Rewrite the answer using only patient facts that "
                    "appear in the report context or the rule-checked lab values.")
    result = await asyncio.to_thread(get_rag_chain().invoke, {
        "context": "\n\n".join(state["contexts"]),
        "question": state["question"],
        "lab_flags": format_lab_flags(state.get("labs")),
        "differential": format_differential(state.get("differential")),
        "knowledge": format_knowledge(state.get("kb_entries")),
        "feedback": feedback,
    })
    return {"answer": llm.message_text(result), "attempts": state.get("attempts", 0) + 1}


async def check_grounding_node(state: DiagnosisState):
    from .query import format_lab_flags

    if not grounding_enabled():
        return {"grounded": None, "grounding_note": "Grounding check disabled."}
    chain = GROUNDING_PROMPT | llm.get_llm()
    verdict = await asyncio.to_thread(chain.invoke, {
        "context": "\n\n".join(state["contexts"]),
        "lab_flags": format_lab_flags(state.get("labs")),
        "answer": state["answer"],
    })
    grounded, note = parse_verdict(llm.message_text(verdict))
    return {"grounded": grounded, "grounding_note": note}


def route_after_check(state: DiagnosisState):
    if state.get("grounded") is False and state.get("attempts", 0) <= MAX_RETRIES:
        return "generate"
    return "finalize"


def finalize_node(state: DiagnosisState):
    if state.get("grounded") is False and grounding_mode() == "refuse":
        return {"answer": REFUSAL}
    return {}


def build_graph():
    graph = StateGraph(DiagnosisState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("generate", generate_node)
    graph.add_node("check_grounding", check_grounding_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges("retrieve", route_after_retrieve, ["analyze", END])
    graph.add_edge("analyze", "generate")
    graph.add_edge("generate", "check_grounding")
    graph.add_conditional_edges("check_grounding", route_after_check, ["generate", "finalize"])
    graph.add_edge("finalize", END)
    return graph.compile()


_compiled = None


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


async def run_diagnosis_graph(question: str, doc_id: str, labs=None, chunks=None) -> dict:
    state = await get_graph().ainvoke({
        "question": question, "doc_id": doc_id, "labs": labs or [], "chunks": chunks, "attempts": 0,
    })
    if not state.get("contexts"):
        return {"diagnosis": None, "sources": [],
                "message": "No indexed content was found for this report. Please re-upload it."}
    return {
        "diagnosis": state["answer"],
        "sources": state["sources"],
        "differential": state["differential"],
        "knowledge_sources": knowledge_sources(state["kb_entries"]),
        "abnormal_labs": state["abnormal_labs"],
        "grounded": state.get("grounded"),
        "grounding_note": state.get("grounding_note"),
        "attempts": state.get("attempts", 0),
        "model": llm.get_model_label(),
        "message": "ok",
    }
