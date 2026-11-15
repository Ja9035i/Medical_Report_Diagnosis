import asyncio
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException

from ..audit import log_event
from ..auth.assignments import require_assigned
from ..auth.route import authenticate
from ..config import vectordb
from ..config.db import diagnosis_collection, reports_collection
from ..labs.extract import abnormal
from .vectorstore import UPLOAD_DIR, load_vectorstore

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
        "redacted": result["redacted"],  # personal identifiers removed before indexing
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


@router.get("/patient/{username}")
def patient_reports(username: str, user=Depends(authenticate)):
    """An assigned doctor's view of one patient's reports, newest first, with lab summaries."""
    require_assigned(user, username)
    cursor = reports_collection.find(
        {"uploader": username},
        {"_id": 0, "doc_id": 1, "filename": 1, "filenames": 1, "uploaded_at": 1, "labs": 1, "critical_alerts": 1},
    ).sort("uploaded_at", -1)
    reports = []
    for r in cursor:
        labs = r.get("labs", [])
        reports.append({
            "doc_id": r["doc_id"],
            "filenames": r.get("filenames") or [f.strip() for f in r.get("filename", "").split(",") if f.strip()],
            "uploaded_at": r["uploaded_at"],
            "labs_found": len(labs),
            "abnormal_count": len(abnormal(labs)),
            "critical_alerts": r.get("critical_alerts", []),
            "labs": labs,
        })
    log_event(user["username"], "doctor", "patient_reports_viewed", username, reports=len(reports))
    return reports


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

DELETE_BATCH_SIZE = 1000  # Pinecone accepts up to 1000 ids per delete call


@router.delete("/{doc_id}")
async def delete_report(doc_id: str, user=Depends(authenticate)):
    """
    Permanently delete a report everywhere: Pinecone vectors, raw files on disk,
    the report record and its diagnosis history. Owning patient or admin only.
    """
    report = reports_collection.find_one({"doc_id": doc_id})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if user["role"] == "patient":
        if report["uploader"] != user["username"]:
            raise HTTPException(status_code=403, detail="You cannot delete another user's report")
    elif user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only the patient or an admin can delete a report")

    # 1) Vectors first: if this fails, nothing else is deleted and the request can be retried
    ids = [c["id"] for c in report.get("chunks") or []] or           [f"{doc_id}-{i}" for i in range(report.get("num_chunks", 0))]
    try:
        index = vectordb.get_index()

        def delete_vectors():
            for start in range(0, len(ids), DELETE_BATCH_SIZE):
                index.delete(ids=ids[start:start + DELETE_BATCH_SIZE])

        if ids:
            await asyncio.to_thread(delete_vectors)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not delete vectors; nothing was removed: {exc}")

    # 2) Raw files on disk (saved as "<doc_id>_<filename>")
    files_deleted = 0
    for path in Path(UPLOAD_DIR).glob(f"{doc_id}_*"):
        try:
            path.unlink()
            files_deleted += 1
        except OSError as exc:
            print(f"[delete] could not remove {path}: {exc}")

    # 3) Database records
    diagnoses_deleted = diagnosis_collection.delete_many({"doc_id": doc_id}).deleted_count
    reports_collection.delete_one({"doc_id": doc_id})

    log_event(user["username"], user["role"], "report_deleted", doc_id, patient=report["uploader"],
              vectors=len(ids), files=files_deleted, diagnoses=diagnoses_deleted)
    return {"doc_id": doc_id, "vectors_deleted": len(ids), "files_deleted": files_deleted,
            "diagnoses_deleted": diagnoses_deleted}
