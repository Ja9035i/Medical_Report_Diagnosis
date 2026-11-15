"""Tests for permanent report deletion (vectors, files, records, history)."""
from pathlib import Path

from conftest import PASSWORD
from server.config import db
from server.reports.vectorstore import UPLOAD_DIR

REPORT = ("cbc.txt", b"Hemoglobin: 9.1 g/dL (reference 13.0-17.0)", "text/plain")


def uploaded_files(doc_id):
    return list(Path(UPLOAD_DIR).glob(f"{doc_id}_*"))


def test_patient_deletes_own_report_everywhere(client, signup, upload, fake_index):
    alice = signup("alice")
    doc_id = upload(alice, [REPORT, ("b.txt", b"MCV 70 fL", "text/plain")]).json()["doc_id"]
    client.post("/diagnosis/from_report", auth=alice, data={"doc_id": doc_id, "question": "q"})
    assert len(uploaded_files(doc_id)) == 2 and len(fake_index.vectors) == 2

    r = client.delete(f"/reports/{doc_id}", auth=alice)
    assert r.status_code == 200
    assert r.json() == {"doc_id": doc_id, "vectors_deleted": 2, "files_deleted": 2, "diagnoses_deleted": 1}
    assert fake_index.vectors == {}
    assert uploaded_files(doc_id) == []
    assert db.reports_collection.find_one({"doc_id": doc_id}) is None
    assert db.diagnosis_collection.count_documents({"doc_id": doc_id}) == 0
    assert client.get("/reports/mine", auth=alice).json() == []
    event = db.audit_collection.find_one({"action": "report_deleted"})
    assert event["actor"] == "alice" and event["target"] == doc_id


def test_delete_access_rules(client, signup, upload, admin_auth):
    alice, bob = signup("alice"), signup("bobby")
    doc_id = upload(alice, [REPORT]).json()["doc_id"]
    client.post("/auth/users", auth=admin_auth, json={"username": "dr_aaa", "password": PASSWORD, "role": "doctor"})
    client.post("/assignments", auth=admin_auth, json={"doctor": "dr_aaa", "patient": "alice"})

    assert client.delete(f"/reports/{doc_id}", auth=bob).status_code == 403
    assert client.delete(f"/reports/{doc_id}", auth=("dr_aaa", PASSWORD)).status_code == 403  # even assigned
    assert client.delete(f"/reports/{doc_id}", auth=admin_auth).status_code == 200
    assert client.delete(f"/reports/{doc_id}", auth=admin_auth).status_code == 404


def test_vector_failure_deletes_nothing(client, signup, upload, fake_index, monkeypatch):
    alice = signup("alice")
    doc_id = upload(alice, [REPORT]).json()["doc_id"]

    def broken_delete(ids):
        raise RuntimeError("pinecone unavailable")

    monkeypatch.setattr(fake_index, "delete", broken_delete)
    r = client.delete(f"/reports/{doc_id}", auth=alice)
    assert r.status_code == 502
    assert db.reports_collection.find_one({"doc_id": doc_id}) is not None
    assert len(uploaded_files(doc_id)) == 1


def test_other_reports_are_untouched(client, signup, upload, fake_index):
    alice = signup("alice")
    keep = upload(alice, [("keep.txt", b"Ferritin 8 ng/mL", "text/plain")]).json()["doc_id"]
    drop = upload(alice, [REPORT]).json()["doc_id"]
    client.delete(f"/reports/{drop}", auth=alice)
    assert [r["doc_id"] for r in client.get("/reports/mine", auth=alice).json()] == [keep]
    assert all(md["doc_id"] == keep for _, md in fake_index.vectors.values())
    assert len(uploaded_files(keep)) == 1
