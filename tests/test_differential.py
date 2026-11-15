"""Tests for the rule-based ranked differential diagnosis."""
from server.knowledge.differential import format_differential, likelihood_label, rank_differential
from server.labs.extract import extract_lab_values


def ranked(text):
    return rank_differential(extract_lab_values(text))


def test_iron_deficiency_pattern_ranks_first_and_high():
    diff = ranked("Hemoglobin: 9.1 g/dL (reference 13.0-17.0)\nMCV: 70 fL\nFerritin: 8 ng/mL")
    top = diff[0]
    assert top["id"] == "iron_deficiency_anemia" and top["likelihood"] == "High"
    assert top["supporting"] == ["Hemoglobin 9.1 g/dL (LOW)", "MCV 70 fL (LOW)", "Ferritin 8 ng/mL (LOW)"]
    assert top["not_measured"] == ["MCH"]


def test_contradicting_value_lowers_alternative():
    diff = {d["id"]: d for d in ranked("Hemoglobin: 9.1 g/dL (reference 13.0-17.0)\nMCV: 70 fL\nFerritin: 8 ng/mL")}
    b12 = diff["b12_deficiency_anemia"]
    assert b12["against"] == ["MCV 70 fL (LOW)"]  # B12 deficiency expects HIGH MCV
    assert b12["likelihood"] == "Low"


def test_real_sample_report_suggests_infection():
    text = ("C-Reactive Protein (CRP): 12 mg/L (Reference: < 5 mg/L) - "
            "White Blood Cell (WBC) Count: 11,500/uL (Reference: 4,000-11,000/uL)")
    top = ranked(text)[0]
    assert top["id"] == "infection_inflammation" and top["likelihood"] == "High"
    assert top["not_measured"] == ["ESR"]


def test_normal_results_give_no_differential():
    assert ranked("Hemoglobin: 14.5 g/dL\nPotassium: 4.2 mmol/L") == []
    assert format_differential([]) == "No condition patterns matched the abnormal lab values."


def test_single_marker_condition_and_measured_normal_counts_against():
    diff = {d["id"]: d for d in ranked("Potassium: 6.0 mmol/L\nCreatinine: 1.0 mg/dL")}
    assert diff["hyperkalemia"]["likelihood"] == "High"          # defined by the one marker
    assert diff["kidney_impairment"]["against"] == ["Creatinine 1 mg/dL (NORMAL)"]
    assert diff["kidney_impairment"]["likelihood"] == "Low"


def test_results_limited_and_sorted_by_score():
    diff = ranked("TSH: 8.0 mIU/L\nLDL: 190 mg/dL\nHDL: 30 mg/dL\nPotassium: 6.0 mmol/L\n"
                  "Sodium: 125 mmol/L\nPlatelet count: 90 10^3/uL\nVitamin D: 12 ng/mL")
    assert len(diff) == 5
    scores = [d["score"] for d in diff]
    assert scores == sorted(scores, reverse=True)


def test_likelihood_label_thresholds():
    assert likelihood_label(0.75, 3, 4) == "High"
    assert likelihood_label(1.0, 1, 1) == "High"
    assert likelihood_label(0.5, 1, 2) == "Medium"
    assert likelihood_label(0.17, 1, 3) == "Low"


def test_format_differential_lists_evidence():
    text = format_differential(ranked("Hemoglobin: 9.1 g/dL (reference 13.0-17.0)\nMCV: 70 fL\nFerritin: 8 ng/mL"))
    first = text.splitlines()[0]
    assert first.startswith("1. Iron-deficiency anemia — High (supporting: Hemoglobin 9.1 g/dL (LOW)")
    assert "not measured: MCH" in first


def test_diagnosis_response_and_prompt_include_differential(client, signup, upload, monkeypatch):
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    from server.config import llm

    captured = {}

    def recording_llm(prompt_value):
        captured["prompt"] = prompt_value.to_string()
        return AIMessage(content="answer")

    monkeypatch.setattr(llm, "get_llm", lambda: RunnableLambda(recording_llm))
    alice = signup("alice")
    report = b"Hemoglobin: 9.1 g/dL (reference 13.0-17.0)\nMCV: 70 fL\nFerritin: 8 ng/mL"
    doc_id = upload(alice, [("cbc.txt", report, "text/plain")]).json()["doc_id"]
    body = client.post("/diagnosis/from_report", auth=alice, data={"doc_id": doc_id, "question": "q"}).json()

    assert body["differential"][0]["id"] == "iron_deficiency_anemia"
    assert "1. Iron-deficiency anemia — High" in captured["prompt"]
    # The top differential condition is always included in the knowledge section
    assert "[KB: Iron-deficiency anemia]" in captured["prompt"]
    assert body["knowledge_sources"][0]["name"] == "Iron-deficiency anemia"
