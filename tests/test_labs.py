"""Tests for deterministic lab-value extraction and flagging."""
import pytest

from conftest import make_pdf
from server.labs.extract import abnormal, extract_lab_values, flag_value
from server.labs.reference import normalize_unit
from server.reports.loaders import clean_text, load_pdf

SAMPLE_REPORT = (
    "BLOOD TEST RESULTS :\n"
    " C-Reactive Protein (CRP): 12 mg/L (Reference: < 5 mg/L) - White Blood Cell (WBC) Count: 11,500/uL\n"
    "(Reference: 4,000-11,000/uL) - Other markers are within normal limits.\n"
    "CONCLUSION: The patient's elevated CRP and WBC count suggest an infection."
)


def by_key(results):
    return {r["key"]: r for r in results}


def test_real_report_format_uses_report_ranges():
    labs = by_key(extract_lab_values(SAMPLE_REPORT))
    assert set(labs) == {"crp", "wbc"}
    assert labs["crp"]["value"] == 12 and labs["crp"]["ref_high"] == 5 and labs["crp"]["flag"] == "HIGH"
    assert labs["wbc"]["value"] == 11500 and (labs["wbc"]["ref_low"], labs["wbc"]["ref_high"]) == (4000, 11000)
    assert labs["wbc"]["flag"] == "HIGH" and labs["wbc"]["range_source"] == "report"


def test_colon_format_with_reference_word():
    lab = extract_lab_values("Hemoglobin: 9.1 g/dL (reference 13.0-17.0) LOW")[0]
    assert (lab["key"], lab["value"], lab["unit"], lab["flag"]) == ("hemoglobin", 9.1, "g/dL", "LOW")


def test_table_rows_with_bare_ranges():
    labs = by_key(extract_lab_values(
        "Hemoglobin 14.2 g/dL 13.0 - 17.0\nMCV 70 fL 80 - 100\nPlatelet Count 250 10^3/uL 150 - 450"))
    assert labs["hemoglobin"]["flag"] == "NORMAL"
    assert labs["mcv"]["flag"] == "LOW"
    assert labs["platelets"]["flag"] == "NORMAL" and labs["platelets"]["unit"] == "10^3/uL"


def test_default_range_used_when_report_has_none_and_units_match():
    lab = extract_lab_values("Fasting Blood Sugar: 130 mg/dL")[0]
    assert lab["range_source"] == "default" and lab["flag"] == "HIGH"


def test_no_default_range_when_units_differ():
    lab = extract_lab_values("Glucose: 7.2 mmol/L")[0]
    assert lab["range_source"] is None and lab["flag"] == "UNKNOWN"


def test_hba1c_is_not_confused_with_hemoglobin():
    labs = extract_lab_values("HbA1c: 6.8 %")
    assert [r["key"] for r in labs] == ["hba1c"]
    assert labs[0]["flag"] == "HIGH"


def test_short_alias_requires_unit():
    labs = extract_lab_values("K 4 and K: 4.0 mmol/L")
    assert len(labs) == 1 and labs[0]["key"] == "potassium" and labs[0]["value"] == 4.0


def test_longer_alias_wins_over_shorter():
    labs = by_key(extract_lab_values("HDL Cholesterol: 35 mg/dL\nTotal Cholesterol: 240 mg/dL"))
    assert labs["hdl"]["flag"] == "LOW"
    assert labs["cholesterol_total"]["flag"] == "HIGH"


def test_mentions_without_values_are_ignored():
    assert extract_lab_values("The elevated CRP and WBC count suggest infection.") == []


def test_results_are_in_report_order_and_abnormal_filter():
    labs = extract_lab_values("Sodium: 140 mmol/L\nPotassium: 6.0 mmol/L\nCalcium: 9.0 mg/dL")
    assert [r["key"] for r in labs] == ["sodium", "potassium", "calcium"]
    assert [r["key"] for r in abnormal(labs)] == ["potassium"]


@pytest.mark.parametrize("value,low,high,expected", [
    (5, 1, 10, "NORMAL"), (0.5, 1, 10, "LOW"), (11, 1, 10, "HIGH"),
    (5, None, 5, "NORMAL"), (6, None, 5, "HIGH"), (30, 40, None, "LOW"), (5, None, None, "UNKNOWN"),
])
def test_flag_value(value, low, high, expected):
    assert flag_value(value, low, high) == expected


def test_unit_normalization():
    assert normalize_unit("µIU/mL") == normalize_unit("mIU/L")
    assert normalize_unit("x10^9/L") == normalize_unit("10^3/uL")
    assert normalize_unit("mEq/L") == normalize_unit("mmol/L")


def test_clean_text_collapses_spaces_and_blank_lines():
    assert clean_text("a    b\n\n\n\n  c  ") == "a b\n\nc"


def test_pdf_loader_keeps_words_together(tmp_path):
    path = tmp_path / "r.pdf"
    path.write_bytes(make_pdf("Hemoglobin 9.1 g/dL 13.0 - 17.0"))
    text = load_pdf(str(path))[0].page_content
    assert "Hemoglobin 9.1 g/dL" in text
    assert extract_lab_values(text)[0]["flag"] == "LOW"
