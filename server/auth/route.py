import os

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pymongo.errors import DuplicateKeyError

from .models import SignupRequest, CreateUserRequest
from .hash_utilis import hash_password, verify_password
from ..config.db import users_collection

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBasic()


def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    user = users_collection.find_one({"username": credentials.username})
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"username": user["username"], "role": user["role"]}


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
    return {"message": "Patient account created successfully"}


@router.get("/login")
def login(user=Depends(authenticate)):
    return {"username": user["username"], "role": user["role"]}


@router.post("/users")
def create_user(req: CreateUserRequest, admin=Depends(require_admin)):
    """Admin-only: create a user with any role (e.g. onboard a doctor)."""
    if users_collection.find_one({"username": req.username}):
        raise HTTPException(status_code=400, detail="User already exists")
    _create_user(req.username, req.password, req.role)
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
