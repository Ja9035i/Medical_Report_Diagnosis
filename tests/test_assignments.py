"""Tests for doctor-patient assignments: doctors only see their own patients."""
from conftest import PASSWORD

REPORT = ("cbc.txt", b"Hemoglobin: 9.1 g/dL (reference 13.0-17.0)", "text/plain")


def make_doctor(client, admin_auth, name):
    client.post("/auth/users", auth=admin_auth, json={"username": name, "password": PASSWORD, "role": "doctor"})
    return (name, PASSWORD)


def assign(client, admin_auth, doctor, patient):
    return client.post("/assignments", auth=admin_auth, json={"doctor": doctor, "patient": patient})


def test_assigned_doctor_sees_history_and_labs_other_doctor_does_not(client, signup, upload, admin_auth):
    alice = signup("alice")
    doc_id = upload(alice, [REPORT]).json()["doc_id"]
    client.post("/diagnosis/from_report", auth=alice, data={"doc_id": doc_id, "question": "q"})
    dr_a, dr_b = make_doctor(client, admin_auth, "dr_aaa"), make_doctor(client, admin_auth, "dr_bbb")
    assert assign(client, admin_auth, "dr_aaa", "alice").status_code == 200

    assert client.get("/diagnosis/by_patient_name", auth=dr_a, params={"patient_name": "alice"}).status_code == 200
    assert client.get(f"/reports/{doc_id}/labs", auth=dr_a).status_code == 200
    assert client.get("/diagnosis/by_patient_name", auth=dr_b, params={"patient_name": "alice"}).status_code == 403
    assert client.get(f"/reports/{doc_id}/labs", auth=dr_b).status_code == 403


def test_unassign_removes_access(client, signup, upload, admin_auth):
    alice = signup("alice")
    doc_id = upload(alice, [REPORT]).json()["doc_id"]
    dr = make_doctor(client, admin_auth, "dr_aaa")
    assign(client, admin_auth, "dr_aaa", "alice")
    assert client.get(f"/reports/{doc_id}/labs", auth=dr).status_code == 200

    r = client.request("DELETE", "/assignments", auth=admin_auth, json={"doctor": "dr_aaa", "patient": "alice"})
    assert r.status_code == 200
    assert client.get(f"/reports/{doc_id}/labs", auth=dr).status_code == 403
    r = client.request("DELETE", "/assignments", auth=admin_auth, json={"doctor": "dr_aaa", "patient": "alice"})
    assert r.status_code == 404


def test_assignment_validation(client, signup, admin_auth):
    signup("alice")
    make_doctor(client, admin_auth, "dr_aaa")
    assert assign(client, admin_auth, "dr_aaa", "nobody").status_code == 404      # unknown patient
    assert assign(client, admin_auth, "alice", "dr_aaa").status_code == 400       # roles swapped
    assert assign(client, admin_auth, "dr_aaa", "alice").status_code == 200
    assert assign(client, admin_auth, "dr_aaa", "alice").status_code == 400       # duplicate


def test_only_admin_assigns_and_listing_by_role(client, signup, admin_auth):
    alice, _ = signup("alice"), signup("bobby")
    dr = make_doctor(client, admin_auth, "dr_aaa")
    assert assign(client, dr, "dr_aaa", "alice").status_code == 403                # doctor cannot assign
    assert client.post("/assignments", auth=alice, json={"doctor": "dr_aaa", "patient": "alice"}).status_code == 403
    assign(client, admin_auth, "dr_aaa", "alice")
    assign(client, admin_auth, "dr_aaa", "bobby")

    assert client.get("/assignments", auth=dr).json() == {"doctor": "dr_aaa", "patients": ["alice", "bobby"]}
    all_rows = client.get("/assignments", auth=admin_auth).json()
    assert [(a["doctor"], a["patient"]) for a in all_rows] == [("dr_aaa", "alice"), ("dr_aaa", "bobby")]
    assert client.get("/assignments", auth=alice).status_code == 403
