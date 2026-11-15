import os
from typing import Optional

import jwt
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import (HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials, HTTPBearer,
                              OAuth2PasswordRequestForm)
from pymongo.errors import DuplicateKeyError

from .models import SignupRequest, CreateUserRequest
from .hash_utils import hash_password, verify_password
from .tokens import create_access_token, decode_token, expire_minutes
from ..audit import log_event
from ..config.db import users_collection

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer(auto_error=False)
basic_scheme = HTTPBasic(auto_error=False)


def basic_auth_allowed() -> bool:
    """HTTP Basic sends the password on every request; it is off unless explicitly enabled."""
    return os.getenv("ALLOW_BASIC_AUTH", "false").strip().lower() in ("1", "true", "yes")


def _unauthorized(detail: str):
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _check_password(username: str, password: str):
    user = users_collection.find_one({"username": username})
    if not user or not verify_password(password, user["password"]):
        log_event(username, None, "auth_failed")
        raise _unauthorized("Invalid credentials")
    return user


def authenticate(
    bearer: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    basic: Optional[HTTPBasicCredentials] = Depends(basic_scheme),
):
    """
    Accepts `Authorization: Bearer <JWT>` (normal use), or HTTP Basic only when
    ALLOW_BASIC_AUTH=true. The user is re-read from the database on every request,
    so deleted accounts and role changes take effect immediately.
    """
    if bearer is not None:
        try:
            payload = decode_token(bearer.credentials)
        except jwt.ExpiredSignatureError:
            raise _unauthorized("Session expired, please log in again")
        except jwt.InvalidTokenError:
            raise _unauthorized("Invalid token")
        user = users_collection.find_one({"username": payload["sub"]})
        if not user:
            raise _unauthorized("Account no longer exists")
        return {"username": user["username"], "role": user["role"]}

    if basic is not None and basic_auth_allowed():
        user = _check_password(basic.username, basic.password)
        return {"username": user["username"], "role": user["role"]}

    raise _unauthorized("Not authenticated")


@router.post("/token")
def issue_token(form: OAuth2PasswordRequestForm = Depends()):
    """Exchange username + password (sent once) for a signed access token."""
    user = _check_password(form.username, form.password)
    log_event(user["username"], user["role"], "login", method="token")
    return {
        "access_token": create_access_token(user["username"], user["role"]),
        "token_type": "bearer",
        "expires_in": expire_minutes() * 60,
        "username": user["username"],
        "role": user["role"],
    }


@router.get("/me")
def me(user=Depends(authenticate)):
    return user


def require_admin(user=Depends(authenticate)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _create_user(username: str, password: str, role: str):
    try:
        users_collection.insert_one({
            "username": username,
            "password": hash_password(password),
            "role": role,
        })
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="User already exists")


@router.post("/signup")
def signup(req: SignupRequest):
    """Public signup always creates a PATIENT. Doctors/admins are created by an admin."""
    if users_collection.find_one({"username": req.username}):
        raise HTTPException(status_code=400, detail="User already exists")
    _create_user(req.username, req.password, "patient")
    log_event(req.username, "patient", "signup")
    return {"message": "Patient account created successfully"}


@router.get("/login")
def login(user=Depends(authenticate)):
    log_event(user["username"], user["role"], "login")
    return {"username": user["username"], "role": user["role"]}


@router.post("/users")
def create_user(req: CreateUserRequest, admin=Depends(require_admin)):
    """Admin-only: create a user with any role (e.g. onboard a doctor)."""
    if users_collection.find_one({"username": req.username}):
        raise HTTPException(status_code=400, detail="User already exists")
    _create_user(req.username, req.password, req.role)
    log_event(admin["username"], "admin", "user_created", req.username, new_role=req.role)
    return {"message": f"{req.role.capitalize()} '{req.username}' created successfully"}


@router.get("/users")
def list_users(admin=Depends(require_admin)):
    """Admin-only: list users (never returns password hashes)."""
    return list(users_collection.find({}, {"_id": 0, "username": 1, "role": 1}).sort("username", 1))


def ensure_admin():
    """
    Called at startup. Makes usernames unique and creates the first admin from
    ADMIN_USERNAME / ADMIN_PASSWORD in .env if that admin does not exist yet.
    """
    try:
        users_collection.create_index("username", unique=True)
    except Exception as exc:  # e.g. existing duplicate usernames
        print(f"[startup] Could not create unique index on users.username: {exc}")

    username = os.getenv("ADMIN_USERNAME")
    password = os.getenv("ADMIN_PASSWORD")
    if not username or not password:
        print("[startup] ADMIN_USERNAME/ADMIN_PASSWORD not set; no admin account bootstrapped.")
        return
    if not users_collection.find_one({"username": username}):
        users_collection.insert_one({
            "username": username,
            "password": hash_password(password),
            "role": "admin",
        })
        print(f"[startup] Admin account '{username}' created.")
