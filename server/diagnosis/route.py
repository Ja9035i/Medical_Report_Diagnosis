import time

from fastapi import APIRouter, Depends, Form, HTTPException

from ..auth.route import authenticate
from ..config.db import reports_collection, diagnosis_collection
from .query import diagnosis_report

router = APIRouter(prefix="/diagnosis", tags=["diagnosis"])


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

    diagnosis_collection.insert_one({
        "doc_id": doc_id,
        "requester": user["username"],
        "question": question,
        "answer": res["diagnosis"],
        "sources": res["sources"],
        "model": res.get("model"),  # which LLM produced this answer (for comparison/audit)
        "timestamp": time.time(),
    })
    return res


@router.get("/by_patient_name")
async def get_patient_diagnosis(patient_name: str, user=Depends(authenticate)):
    if user["role"] != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors can access this endpoint")

    # find() returns a cursor, which is always truthy, so materialize it before checking
    records = list(diagnosis_collection.find({"requester": patient_name}).sort("timestamp", -1))
    if not records:
        raise HTTPException(status_code=404, detail="No diagnosis found for this patient")

    for record in records:
        record["_id"] = str(record["_id"])
    return records
