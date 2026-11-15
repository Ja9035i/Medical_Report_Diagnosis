"""
JWT access tokens.

The client sends its password once to POST /auth/token and receives a signed,
short-lived token. Later requests carry `Authorization: Bearer <token>`, so the
password is not sent with every request.
"""
import os
import secrets
import time

import jwt
from dotenv import load_dotenv

load_dotenv()

ALGORITHM = "HS256"


def _load_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if secret:
        return secret
    # Without a configured secret, tokens still work but become invalid on restart.
    print("[auth] JWT_SECRET is not set; using a temporary random secret (tokens reset on restart).")
    return secrets.token_urlsafe(48)


SECRET = _load_secret()


def expire_minutes() -> int:
    return int(os.getenv("JWT_EXPIRE_MINUTES", "60"))


def create_access_token(username: str, role: str, minutes: int = None) -> str:
    now = int(time.time())
    lifetime = expire_minutes() if minutes is None else minutes
    payload = {"sub": username, "role": role, "iat": now, "exp": now + lifetime * 60}
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Return the payload, or raise jwt.InvalidTokenError (expired, tampered, malformed)."""
    return jwt.decode(token, SECRET, algorithms=[ALGORITHM], options={"require": ["sub", "exp"]})
