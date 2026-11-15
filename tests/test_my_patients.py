"""Tests for the doctor's 'My Patients' summary and patient report view."""
from conftest import PASSWORD
from server.config import db

NORMAL = ("n.txt", b"Hemoglobin: 14.5 g/dL (reference 13.0-17.0)", "text/plain")
CRITICAL = ("k.txt", b"Potassium: 6.9 mmol/L", "text/plain")


def patient(client, username, full_name=None):
    client.post("/auth/signup", json={"username": username, "password": PASSWORD, "full_name": full_name})
    return (username, PASSWORD)


def setup_doctor(client, admin_auth, patients, name="dr_aaa"):
    client.post("/auth/users", auth=admin_auth, json={"username": name, "password": PASSWORD, "role": "doctor"})
    for p in patients:
        client.post("/assignments", auth=admin_auth, json={"doctor": name, "patient": p})
    return (name, PASSWORD)


def test_summary_counts_and_urgency_order(client, upload, admin_auth):
    calm = patient(client, "calm_pt", "Calm Patient")
    waiting = patient(client, "wait_pt", "Waiting Patient")
    urgent = patient(client, "urgent_pt", "Urgent Patient")
    upload(calm, [NORMAL])
    doc = upload(waiting, [NORMAL]).json()["doc_id"]
    client.post("/diagnosis/from_report", auth=waiting, data={"doc_id": doc, "question": "q"})
    upload(urgent, [CRITICAL])
    upload(urgent, [NORMAL])
    dr = setup_doctor(client, admin_auth, ["calm_pt", "wait_pt", "urgent_pt"])

    rows = client.get("/assignments/my-patients", auth=dr).json()
    assert [r["username"] for r in rows] == ["urgent_pt", "wait_pt", "calm_pt"]  # critical, pending, calm
    urgent_row = rows[0]
    assert urgent_row["full_name"] == "Urgent Patient"
    assert urgent_row["reports"] == 2 and urgent_row["critical_reports"] == 1
    assert rows[1]["pending_reviews"] == 1 and rows[1]["latest_diagnosis"] is not None
    assert rows[2]["reports"] == 1 and rows[2]["pending_reviews"] == 0 and rows[2]["latest_upload"]


def test_doctor_only_sees_assigned_patients(client, upload, admin_auth):
    patient(client, "mine_pt")
    patient(client, "other_pt")
    dr = setup_doctor(client, admin_auth, ["mine_pt"])
    assert [r["username"] for r in client.get("/assignments/my-patients", auth=dr).json()] == ["mine_pt"]


def test_my_patients_is_doctor_only(client, admin_auth):
    pt = patient(client, "alice")
    assert client.get("/assignments/my-patients", auth=pt).status_code == 403
    assert client.get("/assignments/my-patients", auth=admin_auth).status_code == 403


def test_patient_reports_for_assigned_doctor(client, upload, admin_auth):
    pt = patient(client, "alice", "Alice A")
    upload(pt, [NORMAL])
    upload(pt, [CRITICAL])
    dr = setup_doctor(client, admin_auth, ["alice"])
    other = setup_doctor(client, admin_auth, [], name="dr_bbb")

    reports = client.get("/reports/patient/alice", auth=dr).json()
    assert len(reports) == 2
    assert reports[0]["filenames"] == ["k.txt"]  # newest first
    assert reports[0]["critical_alerts"] and reports[0]["abnormal_count"] == 1
    assert reports[1]["labs_found"] == 1 and reports[1]["abnormal_count"] == 0

    assert client.get("/reports/patient/alice", auth=other).status_code == 403
    assert client.get("/reports/patient/alice", auth=pt).status_code == 403
    event = db.audit_collection.find_one({"action": "patient_reports_viewed"})
    assert event["actor"] == "dr_aaa" and event["target"] == "alice"
