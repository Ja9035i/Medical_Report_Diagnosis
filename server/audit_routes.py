"""Admin-only access to the audit log."""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from .auth.route import require_admin
from .config.db import audit_collection

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_events(
    admin=Depends(require_admin),
    actor: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Newest events first, optionally filtered by actor and/or action."""
    query = {}
    if actor:
        query["actor"] = actor
    if action:
        query["action"] = action
    return list(audit_collection.find(query, {"_id": 0}).sort("timestamp", -1).limit(limit))
