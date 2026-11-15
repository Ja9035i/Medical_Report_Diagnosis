import time
from typing import Literal, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, Form, HTTPException
from pydantic import BaseModel, Field

from ..auth.assignments import assigned_patients, require_assigned
from ..auth.route import authenticate
from ..config.db import reports_collection, diagnosis_collection
from .query import diagnosis_report

router = APIRouter(prefix="/diagnosis", tags=["diagnosis"])

PENDING = "pending_review"


def _serialize(record):
    record["_id"] = str(record["_id"])
    return record


@router.post("/from_report")
async def diagnos(
    user=Depends(authenticate),
    doc_id: str = Form(...),
    question: str = Form(default="Please provide a diagnosis based on my report"),
):
    if user["role"] != "patient":
        raise HTTPException(status_code=403, detail="Only patients can request a diagnosis from a report")

    report = reports_collection.find_one({"doc_id": doc_id})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if report["uploader"] != user["username"]:
        raise HTTPException(status_code=403, detail="You cannot access another user's report")

    res = await diagnosis_report(
        user["username"], doc_id, question,
        labs=report.get("labs", []), chunks=report.get("chunks"),
    )
    res["critical_alerts"] = report.get("critical_alerts", [])

    if res["diagnosis"] is None:
        # Nothing retrieved: don't store an empty answer in the history
        raise HTTPException(status_code=404, detail=res["message"])

    result = diagnosis_collection.insert_one({
        "doc_id": doc_id,
        "requester": user["username"],
        "question": question,
        "answer": res["diagnosis"],
        "sources": res["sources"],
        "model": res.get("model"),  # which LLM produced this answer (for comparison/audit)
        "grounded": res.get("grounded"),  # verdict of the grounding check (None if disabled)
        "abnormal_labs": res.get("abnormal_labs", []),
        "differential": res.get("differential", []),
        "critical_alerts": res["critical_alerts"],
        # Doctor-in-the-loop: every AI answer starts as a draft awaiting review
        "review_status": PENDING,
        "final_answer": None,
        "doctor_note": None,
        "reviewed_by": None,
        "reviewed_at": None,
        "timestamp": time.time(),
    })
    res["record_id"] = str(result.inserted_id)
    res["review_status"] = PENDING
    return res


@router.get("/mine")
async def my_diagnoses(user=Depends(authenticate)):
    """A patient's own diagnosis history with review status, newest first."""
    if user["role"] != "patient":
        raise HTTPException(status_code=403, detail="Only patients have a diagnosis history")
    records = diagnosis_collection.find({"requester": user["username"]}).sort("timestamp", -1)
    return [_serialize(r) for r in records]


@router.get("/pending")
async def pending_reviews(user=Depends(authenticate)):
    """AI answers awaiting review for the doctor's assigned patients, oldest first."""
    if user["role"] != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors review diagnoses")
    patients = assigned_patients(user["username"])
    records = diagnosis_collection.find(
        {"requester": {"$in": patients}, "review_status": PENDING}).sort("timestamp", 1)
    return [_serialize(r) for r in records]


class ReviewRequest(BaseModel):
    action: Literal["approve", "edit", "reject"]
    note: Optional[str] = Field(default=None, max_length=2000)
    edited_answer: Optional[str] = Field(default=None, max_length=20000)


REVIEW_STATUS = {"approve": "approved", "edit": "edited", "reject": "rejected"}


@router.post("/{record_id}/review")
async def review_diagnosis(record_id: str, req: ReviewRequest, user=Depends(authenticate)):
    """The patient's assigned doctor approves, edits or rejects an AI answer (once)."""
    if user["role"] != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors review diagnoses")
    try:
        oid = ObjectId(record_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=404, detail="Diagnosis record not found")
    record = diagnosis_collection.find_one({"_id": oid})
    if not record:
        raise HTTPException(status_code=404, detail="Diagnosis record not found")
    require_assigned(user, record["requester"])
    if record.get("review_status", PENDING) != PENDING:
        raise HTTPException(status_code=409, detail=f"Already reviewed ({record['review_status']})")
    if req.action == "edit" and not (req.edited_answer and req.edited_answer.strip()):
        raise HTTPException(status_code=400, detail="An edited answer is required for 'edit'")

    final_answer = {"approve": record["answer"], "edit": req.edited_answer, "reject": None}[req.action]
    update = {
        "review_status": REVIEW_STATUS[req.action],
        "final_answer": final_answer,
        "doctor_note": req.note,
        "reviewed_by": user["username"],
        "reviewed_at": time.time(),
    }
    diagnosis_collection.update_one({"_id": oid}, {"$set": update})
    return {"record_id": record_id, **update}


@router.get("/by_patient_name")
async def get_patient_diagnosis(patient_name: str, user=Depends(authenticate)):
    if user["role"] != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors can access this endpoint")
    require_assigned(user, patient_name)  # doctors only see their own patients

    # find() returns a cursor, which is always truthy, so materialize it before checking
    records = list(diagnosis_collection.find({"requester": patient_name}).sort("timestamp", -1))
    if not records:
        raise HTTPException(status_code=404, detail="No diagnosis found for this patient")
    return [_serialize(r) for r in records]
