"""Regression guard for the evaluation set + offline check of the LLM harness."""
import asyncio

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from evaluation import run_eval
from evaluation.cases import CASES, CONDITION_KEYWORDS
from server.knowledge.conditions import CONDITIONS_BY_ID
from server.labs.reference import REFERENCE_RANGES


def test_cases_are_well_formed():
    assert len(CASES) >= 30
    assert len({c["id"] for c in CASES}) == len(CASES)
    for case in CASES:
        assert case["expected_top"] is None or case["expected_top"] in CONDITIONS_BY_ID
        for item in case["expected_abnormal"]:
            key, flag = item.split(":")
            assert key in REFERENCE_RANGES and flag in ("HIGH", "LOW")
    assert set(CONDITION_KEYWORDS) <= set(CONDITIONS_BY_ID)


def test_deterministic_pipeline_meets_targets():
    summary, rows = run_eval.deterministic_metrics()
    assert summary["red_flag_recall"] == 1.0, "every critical value must raise an alert"
    assert summary["red_flag_false_alarms"] == 0
    assert summary["lab_f1"] >= 0.95
    assert summary["differential_top3"] >= 0.9
    assert summary["differential_top1"] >= 0.85


def test_llm_harness_offline(monkeypatch, client):
    from server.config import llm
    from server.diagnosis import retrieval

    def fake_llm(prompt_value):
        text = prompt_value.to_string()
        if "Answer to verify:" in text:
            return AIMessage(content="SUPPORTED")
        return AIMessage(content="This pattern suggests iron deficiency anemia.")

    monkeypatch.setattr(llm, "get_llm", lambda: RunnableLambda(fake_llm))
    monkeypatch.setattr(retrieval, "vector_search", retrieval.vector_search)  # restored after the test
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROUNDING_CHECK", "true")

    cases = [c for c in CASES if c["id"] in ("iron_colon_ranges", "hypothyroid")]
    summary, rows = asyncio.run(run_eval.llm_metrics("groq", cases))
    by_id = {r["id"]: r for r in rows}
    assert by_id["iron_colon_ranges"]["named_condition"] is True
    assert by_id["hypothyroid"]["named_condition"] is False  # answer did not mention thyroid
    assert summary["condition_named_rate"] == 0.5 and summary["grounded_rate"] == 1.0
    assert summary["errors"] == 0


def test_report_is_written(tmp_path):
    summary, rows = run_eval.deterministic_metrics()
    path = run_eval.write_report(summary, rows, [], out_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "| red_flag_recall | 1.0 |" in text
    assert path.with_suffix(".json").exists()
