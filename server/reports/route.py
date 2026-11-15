import uuid
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException

from ..audit import log_event
from ..auth.assignments import require_assigned
from ..auth.route import authenticate
from ..config.db import reports_collection
from ..labs.extract import abnormal
from .vectorstore import load_vectorstore

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/upload")
async def upload_reports(user=Depends(authenticate), files: List[UploadFile] = File(...)):
    if user["role"] != "patient":
        raise HTTPException(status_code=403, detail="Only patients can upload reports for diagnosis")

    doc_id = str(uuid.uuid4())
    result = await load_vectorstore(files, uploaded=user["username"], doc_id=doc_id)
    log_event(user["username"], "patient", "report_uploaded", doc_id,
              files=[f.filename for f in files], labs_found=len(result["labs"]),
              critical_alerts=len(result["critical_alerts"]))
    return {
        "message": "Uploaded and indexed",
        "doc_id": doc_id,
        "num_chunks": result["num_chunks"],
        "labs_found": len(result["labs"]),
        "abnormal_count": len(abnormal(result["labs"])),
        "critical_alerts": result["critical_alerts"],
    }


@router.get("/{doc_id}/labs")
def report_labs(doc_id: str, user=Depends(authenticate)):
    """Structured lab values: the owning patient, or a doctor assigned to that patient."""
    report = reports_collection.find_one({"doc_id": doc_id}, {"_id": 0})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if user["role"] == "patient":
        if report["uploader"] != user["username"]:
            raise HTTPException(status_code=403, detail="You cannot access another user's report")
    elif user["role"] == "doctor":
        require_assigned(user, report["uploader"])
    else:
        raise HTTPException(status_code=403, detail="Only the patient or their doctor can view lab results")

    log_event(user["username"], user["role"], "labs_viewed", doc_id, patient=report["uploader"])
    labs = report.get("labs", [])
    return {
        "doc_id": doc_id,
        "uploader": report["uploader"],
        "labs": labs,
        "abnormal": abnormal(labs),
        "critical_alerts": report.get("critical_alerts", []),
        "extracted": "labs" in report,  # False for reports uploaded before lab extraction existed
    }


@router.get("/mine")
def my_reports(user=Depends(authenticate)):
    """A patient's own reports, newest first, so they can come back to earlier uploads."""
    if user["role"] != "patient":
        raise HTTPException(status_code=403, detail="Only patients have uploaded reports")

    cursor = reports_collection.find(
        {"uploader": user["username"]},
        {"_id": 0, "doc_id": 1, "filename": 1, "filenames": 1, "num_chunks": 1, "uploaded_at": 1},
    ).sort("uploaded_at", -1)

    reports = []
    for r in cursor:
        # Older records only have the comma-joined "filename" field
        r["filenames"] = r.get("filenames") or [f.strip() for f in r.pop("filename", "").split(",") if f.strip()]
        r.pop("filename", None)
        reports.append(r)
    return reports