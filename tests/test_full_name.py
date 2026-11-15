"""Tests for the optional full name on accounts."""
from conftest import PASSWORD


def test_signup_with_full_name_is_tidied_and_returned(client):
    r = client.post("/auth/signup", json={"username": "ravi01", "password": PASSWORD, "full_name": "  Ravi   Kumar "})
    assert r.status_code == 200
    me = client.get("/auth/me", auth=("ravi01", PASSWORD)).json()
    assert me == {"username": "ravi01", "role": "patient", "full_name": "Ravi Kumar"}
    token = client.post("/auth/token", data={"username": "ravi01", "password": PASSWORD}).json()
    assert token["full_name"] == "Ravi Kumar"


def test_full_name_is_optional_and_blank_means_none(client):
    client.post("/auth/signup", json={"username": "asha_m", "password": PASSWORD, "full_name": "   "})
    assert client.get("/auth/me", auth=("asha_m", PASSWORD)).json()["full_name"] is None


def test_full_name_length_limit(client):
    r = client.post("/auth/signup", json={"username": "longname", "password": PASSWORD, "full_name": "x" * 101})
    assert r.status_code == 422


def test_admin_creates_doctor_with_full_name_and_lists_it(client, admin_auth):
    client.post("/auth/users", auth=admin_auth,
                json={"username": "dr_mehta", "password": PASSWORD, "role": "doctor", "full_name": "Dr. Anil Mehta"})
    users = client.get("/auth/users", auth=admin_auth).json()
    assert {"username": "dr_mehta", "role": "doctor", "full_name": "Dr. Anil Mehta"} in users
    assert all("password" not in u for u in users)


def test_full_name_never_reaches_the_llm_or_vector_store(client, upload, fake_index, monkeypatch):
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    from server.config import llm

    prompts = []
    monkeypatch.setattr(llm, "get_llm", lambda: RunnableLambda(
        lambda p: (prompts.append(p.to_string()), AIMessage(content="answer"))[1]))
    client.post("/auth/signup", json={"username": "ravi01", "password": PASSWORD, "full_name": "Ravi Kumar"})
    auth = ("ravi01", PASSWORD)
    doc_id = upload(auth, [("r.txt", b"Hemoglobin: 9.1 g/dL (reference 13.0-17.0)", "text/plain")]).json()["doc_id"]
    client.post("/diagnosis/from_report", auth=auth, data={"doc_id": doc_id, "question": "What is wrong?"})

    assert prompts and all("Ravi Kumar" not in p for p in prompts)
    assert all("Ravi Kumar" not in md["text"] for _, md in fake_index.vectors.values())
