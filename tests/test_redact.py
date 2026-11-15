"""Tests for removing personal identifiers before indexing and LLM calls."""
from server.config import db
from server.privacy.redact import redact_text

HEADER = """Patient Name: Ravi Kumar   Age: 45   Sex: M
UHID: AB-77812
Date of Birth: 05/15/1985
Mobile: +91 98765 43210
Email ravi.k@example.com, Aadhaar 1234 5678 9012
Address: 12 Anna Salai, Chennai
Call 044-24567890 for results"""

LABS = """Test Name: Hemoglobin
Hemoglobin: 9.1 g/dL (reference 13.0-17.0)
WBC Count: 11,500/uL (Reference: 4,000-11,000/uL)
Date of Report: 2023-10-26
Platelet Count 250 10^3/uL 150 - 450"""


def test_identifiers_are_removed_and_counted():
    text, counts = redact_text(HEADER)
    for secret in ("Ravi Kumar", "AB-77812", "05/15/1985", "98765", "ravi.k@example.com",
                   "1234 5678 9012", "Anna Salai", "24567890"):
        assert secret not in text
    assert "Age: 45" in text and "Sex: M" in text  # clinically relevant, kept
    assert counts == {"name": 1, "id": 2, "dob": 1, "phone": 2, "address": 1, "email": 1}


def test_lab_lines_are_untouched():
    text, counts = redact_text(LABS)
    assert text == LABS
    assert sum(counts.values()) == 0


def test_real_report_header_format():
    text, _ = redact_text("Name : Sample Reports\nDate of Birth: 05/15/1985\nPatient ID: 987654321\n")
    assert text.splitlines() == ["Name : [NAME]", "Date of Birth: [DOB]", "Patient ID: [ID]"]


def test_redaction_is_idempotent():
    once, _ = redact_text(HEADER)
    twice, counts = redact_text(once)
    assert twice == once and sum(counts.values()) == 0


def test_upload_redacts_before_indexing_but_keeps_labs(client, signup, upload, fake_index, monkeypatch):
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    from server.config import llm

    prompts = []
    monkeypatch.setattr(llm, "get_llm", lambda: RunnableLambda(
        lambda p: (prompts.append(p.to_string()), AIMessage(content="answer"))[1]))

    alice = signup("alice")
    body = upload(alice, [("r.txt", (HEADER + "\n" + LABS).encode(), "text/plain")]).json()
    assert body["redacted"] == 8
    assert body["labs_found"] == 3  # labs still extracted from the original text

    stored = " ".join(md["text"] for _, md in fake_index.vectors.values())
    assert "Ravi Kumar" not in stored and "[NAME]" in stored and "Hemoglobin: 9.1 g/dL" in stored
    report = db.reports_collection.find_one({"doc_id": body["doc_id"]})
    assert "Ravi Kumar" not in " ".join(c["text"] for c in report["chunks"])
    assert report["redactions"]["name"] == 1

    client.post("/diagnosis/from_report", auth=alice, data={"doc_id": body["doc_id"], "question": "q"})
    assert prompts and all("Ravi Kumar" not in p and "98765" not in p for p in prompts)


def test_redaction_can_be_disabled(client, signup, upload, fake_index, monkeypatch):
    monkeypatch.setenv("PII_REDACTION", "false")
    body = upload(signup("alice"), [("r.txt", HEADER.encode(), "text/plain")]).json()
    assert body["redacted"] == 0
    assert "Ravi Kumar" in " ".join(md["text"] for _, md in fake_index.vectors.values())
