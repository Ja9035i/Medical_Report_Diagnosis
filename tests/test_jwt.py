"""Tests for JWT login: tokens replace sending the password on every request."""
import time

import jwt

from conftest import PASSWORD
from server.auth import tokens


def get_token(client, username, password=PASSWORD):
    return client.post("/auth/token", data={"username": username, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_returns_token_and_token_works(client, signup, upload):
    signup("alice")
    r = get_token(client, "alice")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["role"] == "patient" and body["expires_in"] == 3600
    payload = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert payload["sub"] == "alice" and "password" not in str(payload)

    h = bearer(body["access_token"])
    assert client.get("/auth/me", headers=h).json() == {"username": "alice", "role": "patient", "full_name": None}
    files = [("files", ("cbc.txt", b"Hemoglobin: 9.1 g/dL (reference 13.0-17.0)", "text/plain"))]
    assert client.post("/reports/upload", headers=h, files=files).status_code == 200
    assert len(client.get("/reports/mine", headers=h).json()) == 1


def test_wrong_password_gets_no_token_and_is_audited(client, signup):
    from server.config import db
    signup("alice")
    assert get_token(client, "alice", "wrong-password").status_code == 401
    assert get_token(client, "nobody").status_code == 401
    assert db.audit_collection.count_documents({"action": "auth_failed"}) == 2


def test_expired_tampered_and_garbage_tokens_rejected(client, signup):
    signup("alice")
    expired = tokens.create_access_token("alice", "patient", minutes=-1)
    r = client.get("/auth/me", headers=bearer(expired))
    assert r.status_code == 401 and "expired" in r.json()["detail"].lower()

    forged = jwt.encode({"sub": "alice", "role": "admin", "exp": int(time.time()) + 600}, "wrong-secret",
                        algorithm="HS256")
    assert client.get("/auth/me", headers=bearer(forged)).status_code == 401
    assert client.get("/auth/me", headers=bearer("not-a-jwt")).status_code == 401
    assert client.get("/auth/me").status_code == 401  # no credentials at all


def test_role_comes_from_database_not_token(client, signup):
    """A token minted with role=admin cannot escalate a patient's privileges."""
    signup("alice")
    sneaky = tokens.create_access_token("alice", "admin")  # validly signed, but wrong role claim
    assert client.get("/auth/me", headers=bearer(sneaky)).json()["role"] == "patient"
    assert client.get("/auth/users", headers=bearer(sneaky)).status_code == 403


def test_deleted_user_token_stops_working(client, signup):
    from server.config import db
    signup("alice")
    token = get_token(client, "alice").json()["access_token"]
    db.users_collection.delete_one({"username": "alice"})
    r = client.get("/auth/me", headers=bearer(token))
    assert r.status_code == 401 and "no longer exists" in r.json()["detail"]


def test_basic_auth_disabled_by_default(client, signup, monkeypatch):
    signup("alice")
    monkeypatch.setenv("ALLOW_BASIC_AUTH", "false")
    assert client.get("/auth/me", auth=("alice", PASSWORD)).status_code == 401
    assert get_token(client, "alice").status_code == 200  # token login still works


def test_admin_token_can_manage_users(client, admin_auth):
    token = get_token(client, *admin_auth).json()["access_token"]
    r = client.post("/auth/users", headers=bearer(token),
                    json={"username": "dr_aaa", "password": PASSWORD, "role": "doctor"})
    assert r.status_code == 200
