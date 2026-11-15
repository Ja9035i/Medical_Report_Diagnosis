from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from ..auth.route import authenticate
from .vectorstore import load_vectorstore
import uuid
from typing import List
from ..config.db import reports_collection


router=APIRouter(prefix="/reports",tags=["reports"])

@router.post("/upload")
async def upload_reports(user=Depends(authenticate),files:List[UploadFile]=File(...)):
    if user["role"] !="patient":
        raise HTTPException(status_code=403,detail="Only patients can upload reports for diagnosis")
    
    doc_id=str(uuid.uuid4())
    num_chunks = await load_vectorstore(files, uploaded=user["username"], doc_id=doc_id)
    return {"message": "Uploaded and indexed", "doc_id": doc_id, "num_chunks": num_chunks}


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