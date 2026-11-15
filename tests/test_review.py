"""Tests for doctor-in-the-loop review of AI diagnoses."""
from conftest import FAKE_ANSWER, PASSWORD

REPORT = ("cbc.txt", b"Hemoglobin: 9.1 g/dL (reference 13.0-17.0)", "text/plain")


def setup_case(client, signup, upload, admin_auth, assign=True):
    alice = signup("alice")
    doc_id = upload(alice, [REPORT]).json()["doc_id"]
    body = client.post("/diagnosis/from_report", auth=alice, data={"doc_id": doc_id, "question": "q"}).json()
    client.post("/auth/users", auth=admin_auth, json={"username": "dr_aaa", "password": PASSWORD, "role": "doctor"})
    if assign:
        client.post("/assignments", auth=admin_auth, json={"doctor": "dr_aaa", "patient": "alice"})
    return alice, ("dr_aaa", PASSWORD), body


def test_new_diagnosis_is_pending_review(client, signup, upload, admin_auth):
    alice, _, body = setup_case(client, signup, upload, admin_auth)
    assert body["review_status"] == "pending_review" and body["record_id"]
    mine = client.get("/diagnosis/mine", auth=alice).json()
    assert mine[0]["review_status"] == "pending_review" and mine[0]["final_answer"] is None
    assert mine[0]["abnormal_labs"][0]["key"] == "hemoglobin"  # context stored for the reviewing doctor


def test_doctor_sees_pending_and_approves(client, signup, upload, admin_auth):
    alice, dr, body = setup_case(client, signup, upload, admin_auth)
    pending = client.get("/diagnosis/pending", auth=dr).json()
    assert [p["_id"] for p in pending] == [body["record_id"]]

    r = client.post(f"/diagnosis/{body['record_id']}/review", auth=dr, json={"action": "approve", "note": "Agree."})
    assert r.status_code == 200 and r.json()["review_status"] == "approved"
    record = client.get("/diagnosis/mine", auth=alice).json()[0]
    assert record["review_status"] == "approved" and record["final_answer"] == FAKE_ANSWER
    assert record["doctor_note"] == "Agree." and record["reviewed_by"] == "dr_aaa"
    assert client.get("/diagnosis/pending", auth=dr).json() == []


def test_doctor_edits_answer(client, signup, upload, admin_auth):
    alice, dr, body = setup_case(client, signup, upload, admin_auth)
    r = client.post(f"/diagnosis/{body['record_id']}/review", auth=dr,
                    json={"action": "edit", "edited_answer": "Likely iron deficiency; check ferritin."})
    assert r.json()["review_status"] == "edited"
    record = client.get("/diagnosis/mine", auth=alice).json()[0]
    assert record["final_answer"] == "Likely iron deficiency; check ferritin."
    assert record["answer"] == FAKE_ANSWER  # original AI draft is kept for audit


def test_doctor_rejects_answer(client, signup, upload, admin_auth):
    alice, dr, body = setup_case(client, signup, upload, admin_auth)
    r = client.post(f"/diagnosis/{body['record_id']}/review", auth=dr, json={"action": "reject", "note": "Needs repeat test."})
    assert r.json()["review_status"] == "rejected" and r.json()["final_answer"] is None


def test_review_rules(client, signup, upload, admin_auth):
    alice, dr, body = setup_case(client, signup, upload, admin_auth)
    url = f"/diagnosis/{body['record_id']}/review"
    assert client.post(url, auth=dr, json={"action": "edit"}).status_code == 400           # edit needs text
    assert client.post(url, auth=dr, json={"action": "maybe"}).status_code == 422          # unknown action
    assert client.post(url, auth=alice, json={"action": "approve"}).status_code == 403     # patients can't review
    assert client.post("/diagnosis/not-an-id/review", auth=dr, json={"action": "approve"}).status_code == 404
    assert client.post(url, auth=dr, json={"action": "approve"}).status_code == 200
    assert client.post(url, auth=dr, json={"action": "reject"}).status_code == 409         # only once


def test_unassigned_doctor_cannot_review_or_see_pending(client, signup, upload, admin_auth):
    _, dr, body = setup_case(client, signup, upload, admin_auth, assign=False)
    assert client.get("/diagnosis/pending", auth=dr).json() == []
    r = client.post(f"/diagnosis/{body['record_id']}/review", auth=dr, json={"action": "approve"})
    assert r.status_code == 403


def test_role_restrictions_on_lists(client, signup, upload, admin_auth):
    alice, dr, _ = setup_case(client, signup, upload, admin_auth)
    assert client.get("/diagnosis/mine", auth=dr).status_code == 403
    assert client.get("/diagnosis/pending", auth=alice).status_code == 403


def test_legacy_records_without_status_appear_as_pending(client, signup, upload, admin_auth):
    from server.config import db
    alice, dr, body = setup_case(client, signup, upload, admin_auth)
    db.diagnosis_collection.insert_one({"doc_id": "old", "requester": "alice", "question": "old question",
                                        "answer": "old answer", "sources": [], "timestamp": 1.0})
    pending = client.get("/diagnosis/pending", auth=dr).json()
    assert [p["question"] for p in pending] == ["old question", "q"]  # oldest first
    legacy_id = pending[0]["_id"]
    assert client.post(f"/diagnosis/{legacy_id}/review", auth=dr, json={"action": "approve"}).status_code == 200
