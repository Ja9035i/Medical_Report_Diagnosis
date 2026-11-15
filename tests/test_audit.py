"""Tests for the audit log."""
from conftest import PASSWORD
from server.config import db

REPORT = ("cbc.txt", b"Hemoglobin: 9.1 g/dL (reference 13.0-17.0)", "text/plain")


def actions():
    return [e["action"] for e in db.audit_collection.find({}).sort("timestamp", 1)]


def test_full_workflow_is_audited(client, signup, upload, admin_auth):
    alice = signup("alice")
    client.get("/auth/login", auth=alice)
    client.get("/auth/login", auth=("alice", "wrong-password"))
    doc_id = upload(alice, [REPORT]).json()["doc_id"]
    client.get(f"/reports/{doc_id}/labs", auth=alice)
    record_id = client.post("/diagnosis/from_report", auth=alice, data={"doc_id": doc_id, "question": "q"}).json()["record_id"]
    client.post("/auth/users", auth=admin_auth, json={"username": "dr_aaa", "password": PASSWORD, "role": "doctor"})
    client.post("/assignments", auth=admin_auth, json={"doctor": "dr_aaa", "patient": "alice"})
    client.get("/diagnosis/by_patient_name", auth=("dr_aaa", PASSWORD), params={"patient_name": "alice"})
    client.post(f"/diagnosis/{record_id}/review", auth=("dr_aaa", PASSWORD), json={"action": "approve"})

    assert actions() == [
        "signup", "login", "auth_failed", "report_uploaded", "labs_viewed", "diagnosis_created",
        "user_created", "assignment_created", "history_viewed", "diagnosis_reviewed",
    ]
    review = db.audit_collection.find_one({"action": "diagnosis_reviewed"})
    assert review["actor"] == "dr_aaa" and review["target"] == record_id
    assert review["details"] == {"patient": "alice", "decision": "approved"}
    upload_event = db.audit_collection.find_one({"action": "report_uploaded"})
    assert upload_event["details"]["files"] == ["cbc.txt"] and upload_event["target"] == doc_id


def test_admin_can_filter_audit_log(client, signup, admin_auth):
    signup("alice")
    signup("bobby")
    client.get("/auth/login", auth=("bobby", "nope"))
    events = client.get("/audit", auth=admin_auth, params={"action": "signup"}).json()
    assert [e["actor"] for e in events] == ["bobby", "alice"]  # newest first
    failed = client.get("/audit", auth=admin_auth, params={"actor": "bobby", "action": "auth_failed"}).json()
    assert len(failed) == 1
    assert len(client.get("/audit", auth=admin_auth, params={"limit": 1}).json()) == 1


def test_non_admins_cannot_read_audit_log(client, signup, admin_auth):
    alice = signup("alice")
    assert client.get("/audit", auth=alice).status_code == 403
    client.post("/auth/users", auth=admin_auth, json={"username": "dr_aaa", "password": PASSWORD, "role": "doctor"})
    assert client.get("/audit", auth=("dr_aaa", PASSWORD)).status_code == 403


def test_logging_failure_never_breaks_a_request(client, monkeypatch):
    def broken_insert(*args, **kwargs):
        raise RuntimeError("audit database down")

    monkeypatch.setattr(db.audit_collection, "insert_one", broken_insert)
    r = client.post("/auth/signup", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 200
