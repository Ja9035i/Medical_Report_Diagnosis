"""Tests for the LangGraph diagnosis pipeline and its grounding check."""
import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from server.config import llm
from server.diagnosis import graph

REPORT = ("cbc.txt", b"Hemoglobin: 9.1 g/dL (reference 13.0-17.0)\nPatient reports fatigue.", "text/plain")


class ScriptedLLM:
    """Answers generation calls with 'draft N' and verification calls from a script."""

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.generations = 0
        self.prompts = []

    def __call__(self, prompt_value):
        text = prompt_value.to_string()
        self.prompts.append(text)
        if "Answer to verify:" in text:
            return AIMessage(content=self.verdicts.pop(0))
        self.generations += 1
        return AIMessage(content=f"draft {self.generations}")


@pytest.fixture
def scripted(monkeypatch):
    def install(verdicts):
        fake = ScriptedLLM(verdicts)
        monkeypatch.setattr(llm, "get_llm", lambda: RunnableLambda(fake))
        monkeypatch.setenv("GROUNDING_CHECK", "true")
        return fake
    return install


def diagnose(client, signup, upload):
    alice = signup("alice")
    doc_id = upload(alice, [REPORT]).json()["doc_id"]
    return client.post("/diagnosis/from_report", auth=alice, data={"doc_id": doc_id, "question": "q"}).json()


def test_graph_has_expected_nodes():
    nodes = set(graph.get_graph().get_graph().nodes)
    assert {"retrieve", "analyze", "generate", "check_grounding", "finalize"} <= nodes


@pytest.mark.parametrize("text,expected", [
    ("SUPPORTED", (True, None)),
    ("supported.", (True, None)),
    ("UNSUPPORTED: patient is 45 years old", (False, "patient is 45 years old")),
    ("The answer invents a fever", (False, "The answer invents a fever")),
])
def test_parse_verdict(text, expected):
    assert graph.parse_verdict(text) == expected


def test_supported_first_time(client, signup, upload, scripted):
    fake = scripted(["SUPPORTED"])
    body = diagnose(client, signup, upload)
    assert body["diagnosis"] == "draft 1"
    assert body["grounded"] is True and body["attempts"] == 1
    assert fake.generations == 1


def test_unsupported_draft_is_regenerated_with_feedback(client, signup, upload, scripted):
    fake = scripted(["UNSUPPORTED: invents a fever", "SUPPORTED"])
    body = diagnose(client, signup, upload)
    assert body["diagnosis"] == "draft 2"
    assert body["grounded"] is True and body["attempts"] == 2
    retry_prompt = [p for p in fake.prompts if "Answer to verify:" not in p][1]
    assert "invents a fever" in retry_prompt and "Rewrite the answer" in retry_prompt


def test_still_unsupported_after_retry_warns(client, signup, upload, scripted):
    scripted(["UNSUPPORTED: a", "UNSUPPORTED: invents age"])
    body = diagnose(client, signup, upload)
    assert body["diagnosis"] == "draft 2"  # warn mode keeps the answer...
    assert body["grounded"] is False and body["grounding_note"] == "invents age"  # ...but flags it
    assert body["attempts"] == 2  # only one retry


def test_refuse_mode_replaces_unsupported_answer(client, signup, upload, scripted, monkeypatch):
    monkeypatch.setenv("GROUNDING_MODE", "refuse")
    scripted(["UNSUPPORTED: a", "UNSUPPORTED: b"])
    body = diagnose(client, signup, upload)
    assert body["diagnosis"] == graph.REFUSAL and body["grounded"] is False


def test_grounding_check_disabled_makes_one_llm_call(client, signup, upload, scripted, monkeypatch):
    fake = scripted([])
    monkeypatch.setenv("GROUNDING_CHECK", "false")
    body = diagnose(client, signup, upload)
    assert body["grounded"] is None and body["attempts"] == 1
    assert len(fake.prompts) == 1


def test_grounding_verdict_saved_in_history(client, signup, upload, scripted):
    scripted(["SUPPORTED"])
    diagnose(client, signup, upload)
    from server.config.db import diagnosis_collection
    assert diagnosis_collection.find_one({})["grounded"] is True
