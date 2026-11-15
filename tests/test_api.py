"""API tests: auth/RBAC, upload, retrieval isolation, diagnosis, doctor history, my reports."""
from conftest import FAKE_ANSWER, PASSWORD, make_pdf

TXT = ("cbc.txt", b"Hemoglobin: 9.1 g/dL (reference 13.0-17.0) LOW", "text/plain")


def pdf(name="report.pdf", text="Ferritin 8 ng/mL LOW"):
    return (name, make_pdf(text), "application/pdf")


# ---------------- health & auth ----------------

def test_health(client):
    assert client.get("/health").json() == {"status": "healthy"}


def test_signup_ignores_role_and_creates_patient(client):
    r = client.post("/auth/signup", json={"username": "alice", "password": PASSWORD, "role": "admin"})
    assert r.status_code == 200
    assert client.get("/auth/login", auth=("alice", PASSWORD)).json()["role"] == "patient"


def test_weak_signup_rejected(client):
    r = client.post("/auth/signup", json={"username": "ab", "password": "1"})
    assert r.status_code == 422


def test_duplicate_signup_rejected(client, signup):
    signup("alice")
    r = client.post("/auth/signup", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 400


def test_wrong_password_rejected(client, signup):
    signup("alice")
    assert client.get("/auth/login", auth=("alice", "wrongpass")).status_code == 401


def test_admin_bootstrapped_and_creates_doctor(client, admin_auth):
    assert client.get("/auth/login", auth=admin_auth).json()["role"] == "admin"
    r = client.post("/auth/users", auth=admin_auth,
                    json={"username": "drkumar", "password": PASSWORD, "role": "doctor"})
    assert r.status_code == 200
    assert client.get("/auth/login", auth=("drkumar", PASSWORD)).json()["role"] == "doctor"


def test_admin_list_users_hides_passwords(client, admin_auth, signup):
    signup("alice")
    users = client.get("/auth/users", auth=admin_auth).json()
    assert {"username": "alice", "role": "patient"} in users
    assert all("password" not in u for u in users)


def test_patient_cannot_create_or_list_users(client, signup):
    auth = signup("alice")
    r = client.post("/auth/users", auth=auth, json={"username": "x" * 3, "password": PASSWORD, "role": "doctor"})
    assert r.status_code == 403
    assert client.get("/auth/users", auth=auth).status_code == 403


# ---------------- upload ----------------

def test_upload_pdf_and_txt_indexes_both(client, signup, upload, fake_index):
    auth = signup("alice")
    r = upload(auth, [pdf(), TXT])
    assert r.status_code == 200
    body = r.json()
    assert body["num_chunks"] == 2

    stored = [md for _, md in fake_index.vectors.values()]
    assert {md["source"] for md in stored} == {"report.pdf", "cbc.txt"}
    assert all(md["doc_id"] == body["doc_id"] and md["uploader"] == "alice" for md in stored)
    pdf_md = next(md for md in stored if md["source"] == "report.pdf")
    assert pdf_md["page"] == 1 and "Ferritin" in pdf_md["text"]
    assert "page" not in next(md for md in stored if md["source"] == "cbc.txt")


def test_unsupported_file_rejected(client, signup, upload):
    auth = signup("alice")
    r = upload(auth, [("notes.docx", b"abc", "application/octet-stream")])
    assert r.status_code == 400


def test_empty_file_rejected(client, signup, upload):
    auth = signup("alice")
    r = upload(auth, [("empty.txt", b"   ", "text/plain")])
    assert r.status_code == 400


def test_only_patients_upload(client, admin_auth, upload):
    assert upload(admin_auth, [TXT]).status_code == 403


# ---------------- diagnosis ----------------

def test_diagnosis_returns_answer_sources_and_model(client, signup, upload):
    auth = signup("alice")
    doc_id = upload(auth, [pdf(), TXT]).json()["doc_id"]
    r = client.post("/diagnosis/from_report", auth=auth, data={"doc_id": doc_id, "question": "What is wrong?"})
    assert r.status_code == 200
    body = r.json()
    assert body["diagnosis"] == FAKE_ANSWER
    assert set(body["sources"]) == {"report.pdf (page 1)", "cbc.txt"}
    assert body["model"] == "fake:test-model"


def test_retrieval_only_uses_own_report(client, signup, upload):
    alice, bob = signup("alice"), signup("bobby")
    alice_doc = upload(alice, [("alice.txt", b"Alice glucose 300 HIGH", "text/plain")]).json()["doc_id"]
    upload(bob, [("bob.txt", b"Bob cholesterol 280 HIGH", "text/plain")])
    r = client.post("/diagnosis/from_report", auth=alice, data={"doc_id": alice_doc, "question": "q"})
    assert r.json()["sources"] == ["alice.txt"]


def test_other_patient_blocked(client, signup, upload):
    alice, bob = signup("alice"), signup("bobby")
    doc_id = upload(alice, [TXT]).json()["doc_id"]
    r = client.post("/diagnosis/from_report", auth=bob, data={"doc_id": doc_id, "question": "q"})
    assert r.status_code == 403


def test_unknown_report_404(client, signup):
    auth = signup("alice")
    r = client.post("/diagnosis/from_report", auth=auth, data={"doc_id": "does-not-exist", "question": "q"})
    assert r.status_code == 404


def test_report_with_no_vectors_404_and_not_saved(client, signup, upload, fake_index):
    auth = signup("alice")
    doc_id = upload(auth, [TXT]).json()["doc_id"]
    fake_index.vectors.clear()  # simulate an index that lost the chunks
    r = client.post("/diagnosis/from_report", auth=auth, data={"doc_id": doc_id, "question": "q"})
    assert r.status_code == 404
    from server.config.db import diagnosis_collection
    assert diagnosis_collection.count_documents({}) == 0


# ---------------- doctor history ----------------

def test_doctor_sees_history_newest_first(client, signup, upload, admin_auth):
    alice = signup("alice")
    doc_id = upload(alice, [TXT]).json()["doc_id"]
    for q in ("first question", "second question"):
        client.post("/diagnosis/from_report", auth=alice, data={"doc_id": doc_id, "question": q})
    client.post("/auth/users", auth=admin_auth, json={"username": "drkumar", "password": PASSWORD, "role": "doctor"})
    client.post("/assignments", auth=admin_auth, json={"doctor": "drkumar", "patient": "alice"})

    r = client.get("/diagnosis/by_patient_name", auth=("drkumar", PASSWORD), params={"patient_name": "alice"})
    assert r.status_code == 200
    records = r.json()
    assert [rec["question"] for rec in records] == ["second question", "first question"]
    assert records[0]["model"] == "fake:test-model"


def test_doctor_unassigned_or_unknown_patient_403(client, admin_auth):
    client.post("/auth/users", auth=admin_auth, json={"username": "drkumar", "password": PASSWORD, "role": "doctor"})
    r = client.get("/diagnosis/by_patient_name", auth=("drkumar", PASSWORD), params={"patient_name": "nobody"})
    assert r.status_code == 403


def test_patient_cannot_read_history(client, signup):
    alice = signup("alice")
    r = client.get("/diagnosis/by_patient_name", auth=alice, params={"patient_name": "alice"})
    assert r.status_code == 403


def test_doctor_cannot_request_diagnosis(client, signup, upload, admin_auth):
    doc_id = upload(signup("alice"), [TXT]).json()["doc_id"]
    client.post("/auth/users", auth=admin_auth, json={"username": "drkumar", "password": PASSWORD, "role": "doctor"})
    r = client.post("/diagnosis/from_report", auth=("drkumar", PASSWORD), data={"doc_id": doc_id, "question": "q"})
    assert r.status_code == 403


# ---------------- my reports ----------------

def test_my_reports_newest_first_and_isolated(client, signup, upload):
    alice, bob = signup("alice"), signup("bobby")
    first = upload(alice, [("a1.txt", b"one", "text/plain")]).json()["doc_id"]
    second = upload(alice, [("a2.txt", b"two", "text/plain")]).json()["doc_id"]
    upload(bob, [("b1.txt", b"bob", "text/plain")])

    mine = client.get("/reports/mine", auth=alice).json()
    assert [r["doc_id"] for r in mine] == [second, first]
    assert mine[0]["filenames"] == ["a2.txt"]
    assert client.get("/reports/mine", auth=bob).json()[0]["filenames"] == ["b1.txt"]


def test_my_reports_patients_only(client, admin_auth):
    assert client.get("/reports/mine", auth=admin_auth).status_code == 403


# ---------------- lab extraction, red flags, labs endpoint ----------------

LABS_TXT = ("labs.txt", b"Potassium: 6.9 mmol/L\nHemoglobin: 9.1 g/dL (reference 13.0-17.0)\nSodium: 140 mmol/L",
            "text/plain")


def test_upload_returns_lab_summary_and_critical_alerts(client, signup, upload):
    body = upload(signup("alice"), [LABS_TXT]).json()
    assert body["labs_found"] == 3
    assert body["abnormal_count"] == 2
    assert body["critical_alerts"] == ["Potassium 6.9 mmol/L is above the critical limit (6.5 mmol/L)"]


def test_labs_endpoint_access_rules(client, signup, upload, admin_auth):
    alice, bob = signup("alice"), signup("bobby")
    doc_id = upload(alice, [LABS_TXT]).json()["doc_id"]
    client.post("/auth/users", auth=admin_auth, json={"username": "drkumar", "password": PASSWORD, "role": "doctor"})
    client.post("/assignments", auth=admin_auth, json={"doctor": "drkumar", "patient": "alice"})

    r = client.get(f"/reports/{doc_id}/labs", auth=alice)
    assert r.status_code == 200
    body = r.json()
    assert [lab["key"] for lab in body["abnormal"]] == ["potassium", "hemoglobin"]
    assert body["extracted"] is True and body["uploader"] == "alice"

    assert client.get(f"/reports/{doc_id}/labs", auth=("drkumar", PASSWORD)).status_code == 200
    assert client.get(f"/reports/{doc_id}/labs", auth=bob).status_code == 403
    assert client.get(f"/reports/{doc_id}/labs", auth=admin_auth).status_code == 403
    assert client.get("/reports/missing/labs", auth=alice).status_code == 404


def test_diagnosis_includes_rule_flags_in_prompt_and_response(client, signup, upload, monkeypatch):
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    from server.config import llm

    captured = {}

    def recording_llm(prompt_value):
        captured["prompt"] = prompt_value.to_string()
        return AIMessage(content="answer")

    monkeypatch.setattr(llm, "get_llm", lambda: RunnableLambda(recording_llm))

    alice = signup("alice")
    doc_id = upload(alice, [LABS_TXT]).json()["doc_id"]
    body = client.post("/diagnosis/from_report", auth=alice, data={"doc_id": doc_id, "question": "q"}).json()

    assert "Potassium 6.9 mmol/L — HIGH" in captured["prompt"] and "CRITICAL" in captured["prompt"]
    assert "Hemoglobin 9.1 g/dL — LOW (ref 13-17, report range)" in captured["prompt"]
    flags_section = captured["prompt"].split("Rule-checked abnormal lab values:")[1].split("Reference medical knowledge:")[0]
    assert "Sodium" not in flags_section  # normal values are not listed as flags
    assert [lab["key"] for lab in body["abnormal_labs"]] == ["potassium", "hemoglobin"]
    assert len(body["critical_alerts"]) == 1
