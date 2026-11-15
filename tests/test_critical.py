"""Tests for critical-value (red flag) rules."""
from server.labs.critical import check_critical, value_in_default_unit
from server.labs.extract import extract_lab_values


def run(text):
    labs = extract_lab_values(text)
    return labs, check_critical(labs)


def test_critical_high_potassium():
    labs, alerts = run("Potassium: 6.9 mmol/L")
    assert labs[0]["critical"] is True
    assert alerts == ["Potassium 6.9 mmol/L is above the critical limit (6.5 mmol/L)"]


def test_critical_low_hemoglobin():
    labs, alerts = run("Hemoglobin: 6.2 g/dL (reference 13.0-17.0)")
    assert labs[0]["flag"] == "LOW" and labs[0]["critical"] is True
    assert "below the critical limit" in alerts[0]


def test_abnormal_but_not_critical():
    labs, alerts = run("Potassium: 5.5 mmol/L")
    assert labs[0]["flag"] == "HIGH"
    assert labs[0]["critical"] is False and alerts == []


def test_per_microlitre_counts_are_converted():
    # 11,500/uL = 11.5 x10^3/uL -> high but not critical; 45,000/uL = 45 -> critical
    labs, alerts = run("White Blood Cell Count: 11,500/uL (Reference: 4,000-11,000/uL)")
    assert value_in_default_unit(labs[0]) == 11.5 and alerts == []
    labs, alerts = run("WBC: 45,000/uL")
    assert labs[0]["critical"] is True and len(alerts) == 1


def test_unknown_unit_never_triggers_alert():
    labs, alerts = run("Glucose: 30 mmol/L")  # unit not convertible -> no guess
    assert alerts == [] and labs[0]["critical"] is False


def test_tests_without_critical_rules_are_ignored():
    labs, alerts = run("C-Reactive Protein: 250 mg/L")
    assert labs[0]["flag"] == "HIGH" and alerts == []


def test_multiple_alerts_in_report_order():
    _, alerts = run("Sodium: 115 mmol/L\nGlucose: 450 mg/dL\nCalcium: 9.0 mg/dL")
    assert len(alerts) == 2
    assert alerts[0].startswith("Sodium") and alerts[1].startswith("Fasting glucose")
