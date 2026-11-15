"""
Audit log: an append-only record of who did what, and when.

Writing to the log must never break the request it describes, so failures are
printed and swallowed.
"""
import time
from typing import Optional

from .config.db import audit_collection


def log_event(actor: str, role: Optional[str], action: str, target: Optional[str] = None, **details):
    try:
        audit_collection.insert_one({
            "timestamp": time.time(),
            "actor": actor,
            "role": role,
            "action": action,
            "target": target,
            "details": details,
        })
    except Exception as exc:  # never fail the real request because of logging
        print(f"[audit] could not record {action}: {exc}")
