"""Unit tests for small pure functions (no HTTP)."""
import pytest

from conftest import make_pdf
from server.auth.hash_utils import hash_password, verify_password
from server.config import llm
from server.diagnosis.query import _source_label
from server.reports.loaders import load_pdf, load_txt


def test_suite_uses_fake_database_not_real_mongodb():
    import mongomock
    from server.config import db
    assert isinstance(db.client, mongomock.MongoClient)
    assert db.DB_NAME == "test_db"


def test_password_hash_roundtrip():
    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed)
    assert not verify_password("wrong", hashed)


def test_source_label_with_and_without_page():
    assert _source_label({"source": "r.pdf", "page": 2}) == "r.pdf (page 2)"
    assert _source_label({"source": "notes.txt"}) == "notes.txt"


def test_load_pdf_uses_one_based_pages(tmp_path):
    path = tmp_path / "r.pdf"
    path.write_bytes(make_pdf("Hemoglobin 9.1 LOW"))
    docs = load_pdf(str(path))
    assert len(docs) == 1
    assert docs[0].metadata == {"page": 1}
    assert "Hemoglobin" in docs[0].page_content


def test_load_txt_and_empty_txt(tmp_path):
    full, empty = tmp_path / "a.txt", tmp_path / "b.txt"
    full.write_text("MCV 70 fL LOW", encoding="utf-8")
    empty.write_text("   ", encoding="utf-8")
    assert load_txt(str(full))[0].page_content == "MCV 70 fL LOW"
    assert load_txt(str(empty)) == []


def test_llm_provider_validation(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ValueError):
        llm.get_model_label()


def test_llm_model_label_override(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    assert llm.get_model_label() == "gemini:gemini-test"


def test_format_lab_flags():
    from server.diagnosis.query import format_lab_flags
    labs = [
        {"test": "Potassium", "value": 6.9, "unit": "mmol/L", "ref_low": 3.5, "ref_high": 5.1,
         "range_source": "default", "flag": "HIGH", "critical": True},
        {"test": "CRP", "value": 12.0, "unit": "mg/L", "ref_low": None, "ref_high": 5.0,
         "range_source": "report", "flag": "HIGH", "critical": False},
        {"test": "Sodium", "value": 140.0, "unit": "mmol/L", "ref_low": 135, "ref_high": 145,
         "range_source": "default", "flag": "NORMAL", "critical": False},
    ]
    text = format_lab_flags(labs)
    assert text.splitlines() == [
        "- Potassium 6.9 mmol/L — HIGH (ref 3.5-5.1, default range) — CRITICAL",
        "- CRP 12 mg/L — HIGH (ref ≤ 5, report range)",
    ]
    assert format_lab_flags([]) == "None detected."
