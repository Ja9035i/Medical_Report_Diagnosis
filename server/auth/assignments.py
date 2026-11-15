"""
Doctor–patient assignments.

A doctor may only see the records of patients assigned to them by an admin.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from ..audit import log_event
from ..config.db import assignments_collection, diagnosis_collection, reports_collection, users_collection
from .route import authenticate, require_admin

router = APIRouter(prefix="/assignments", tags=["assignments"])


class AssignmentRequest(BaseModel):
    doctor: str = Field(min_length=3, max_length=50)
    patient: str = Field(min_length=3, max_length=50)


def is_assigned(doctor: str, patient: str) -> bool:
    return assignments_collection.find_one({"doctor": doctor, "patient": patient}) is not None


def assigned_patients(doctor: str):
    return sorted(a["patient"] for a in assignments_collection.find({"doctor": doctor}))


def require_assigned(user, patient: str):
    """Raise 403 unless `user` is a doctor assigned to `patient`."""
    if user["role"] != "doctor" or not is_assigned(user["username"], patient):
        raise HTTPException(status_code=403, detail="This patient is not assigned to you")


def _require_role(username: str, role: str):
    user = users_collection.find_one({"username": username})
    if not user:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    if user["role"] != role:
        raise HTTPException(status_code=400, detail=f"User '{username}' is not a {role}")


@router.post("")
def assign(req: AssignmentRequest, admin=Depends(require_admin)):
    _require_role(req.doctor, "doctor")
    _require_role(req.patient, "patient")
    if is_assigned(req.doctor, req.patient):
        raise HTTPException(status_code=400, detail="Already assigned")
    try:
        assignments_collection.insert_one(
            {"doctor": req.doctor, "patient": req.patient, "assigned_at": time.time()})
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="Already assigned")
    log_event(admin["username"], "admin", "assignment_created", req.patient, doctor=req.doctor)
    return {"message": f"Patient '{req.patient}' assigned to doctor '{req.doctor}'"}


@router.delete("")
def unassign(req: AssignmentRequest, admin=Depends(require_admin)):
    result = assignments_collection.delete_one({"doctor": req.doctor, "patient": req.patient})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Assignment not found")
    log_event(admin["username"], "admin", "assignment_removed", req.patient, doctor=req.doctor)
    return {"message": f"Patient '{req.patient}' unassigned from doctor '{req.doctor}'"}


@router.get("")
def list_assignments(user=Depends(authenticate)):
    """Admin: every assignment. Doctor: their own patients."""
    if user["role"] == "admin":
        return list(assignments_collection.find({}, {"_id": 0}).sort([("doctor", 1), ("patient", 1)]))
    if user["role"] == "doctor":
        return {"doctor": user["username"], "patients": assigned_patients(user["username"])}
    raise HTTPException(status_code=403, detail="Only admins and doctors can view assignments")


@router.get("/my-patients")
def my_patients(user=Depends(authenticate)):
    """
    A doctor's assigned patients with a summary per patient, most urgent first:
    patients with critical lab alerts, then pending reviews, then latest activity.
    """
    if user["role"] != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors have a patient list")

    rows = []
    for username in assigned_patients(user["username"]):
        account = users_collection.find_one({"username": username}, {"full_name": 1}) or {}
        reports = list(reports_collection.find({"uploader": username},
                                               {"uploaded_at": 1, "critical_alerts": 1}))
        pending = diagnosis_collection.count_documents({
            "requester": username,
            "$or": [{"review_status": "pending_review"}, {"review_status": {"$exists": False}}],
        })
        last_diagnosis = diagnosis_collection.find_one({"requester": username}, {"timestamp": 1},
                                                       sort=[("timestamp", -1)])
        rows.append({
            "username": username,
            "full_name": account.get("full_name"),
            "reports": len(reports),
            "critical_reports": sum(1 for r in reports if r.get("critical_alerts")),
            "pending_reviews": pending,
            "latest_upload": max((r["uploaded_at"] for r in reports), default=None),
            "latest_diagnosis": last_diagnosis["timestamp"] if last_diagnosis else None,
        })

    def urgency(row):
        latest = max(row["latest_upload"] or 0, row["latest_diagnosis"] or 0)
        return (-row["critical_reports"], -row["pending_reviews"], -latest, row["username"])

    return sorted(rows, key=urgency)


def ensure_assignment_index():
    try:
        assignments_collection.create_index([("doctor", 1), ("patient", 1)], unique=True)
    except Exception as exc:
        print(f"[startup] Could not create assignments index: {exc}")
