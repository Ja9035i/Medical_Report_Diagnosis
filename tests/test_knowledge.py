"""Tests for the curated medical knowledge base and its use in diagnosis."""
from server.knowledge.conditions import CONDITIONS, CONDITIONS_BY_ID
from server.knowledge.kb import format_knowledge, knowledge_sources, search_kb
from server.labs.reference import REFERENCE_RANGES


def test_knowledge_base_integrity():
    ids = [c["id"] for c in CONDITIONS]
    assert len(ids) == len(set(ids)), "condition ids must be unique"
    for c in CONDITIONS:
        assert c["name"] and c["summary"] and c["confirm_tests"]
        assert c["url"].startswith("https://medlineplus.gov/")
        assert c["patterns"], f"{c['id']} needs at least one lab pattern"
        for lab_key, flag in c["patterns"]:
            assert lab_key in REFERENCE_RANGES, f"{c['id']} refers to unknown lab {lab_key}"
            assert flag in ("HIGH", "LOW")


def test_search_kb_puts_included_ids_first_and_limits_k(client):
    entries = search_kb("tired and pale", k=2, include_ids=["hypothyroidism", "not_a_condition"])
    assert entries[0]["id"] == "hypothyroidism"
    assert len(entries) == 3  # 1 included + 2 semantic
    assert len({e["id"] for e in entries}) == 3


def test_search_kb_with_empty_query_returns_only_included(client):
    assert [e["id"] for e in search_kb("", k=3, include_ids=["dyslipidemia"])] == ["dyslipidemia"]


def test_format_and_sources():
    entry = CONDITIONS_BY_ID["iron_deficiency_anemia"]
    text = format_knowledge([entry])
    assert text.startswith("[KB: Iron-deficiency anemia] (source: MedlinePlus: Anemia)")
    assert "Typically confirmed with:" in text
    assert format_knowledge([]) == "None."
    assert knowledge_sources([entry]) == [
        {"name": "Iron-deficiency anemia", "source": "MedlinePlus: Anemia", "url": "https://medlineplus.gov/anemia.html"}
    ]


def test_diagnosis_prompt_and_response_include_knowledge(client, signup, upload, monkeypatch):
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    from server.config import llm

    captured = {}

    def recording_llm(prompt_value):
        captured["prompt"] = prompt_value.to_string()
        return AIMessage(content="answer")

    monkeypatch.setattr(llm, "get_llm", lambda: RunnableLambda(recording_llm))
    alice = signup("alice")
    doc_id = upload(alice, [("cbc.txt", b"Hemoglobin: 9.1 g/dL (reference 13.0-17.0)", "text/plain")]).json()["doc_id"]
    body = client.post("/diagnosis/from_report", auth=alice, data={"doc_id": doc_id, "question": "q"}).json()

    assert "Reference medical knowledge:" in captured["prompt"]
    # 3 semantic matches plus the top differential conditions (always included)
    assert captured["prompt"].count("] (source: ") == len(body["knowledge_sources"]) >= 3
    assert len({ref["name"] for ref in body["knowledge_sources"]}) == len(body["knowledge_sources"])
    assert all(ref["url"].startswith("https://") for ref in body["knowledge_sources"])
