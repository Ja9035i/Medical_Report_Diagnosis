"""OCR fallback for scanned PDFs and photos of reports (skipped if OCR is not installed)."""
import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from server.reports import loaders

LINES = ["LAB REPORT", "Hemoglobin: 9.1 g/dL (Reference: 13.0-17.0)", "Potassium: 6.9 mmol/L"]


def report_image():
    image = Image.new("RGB", (1240, 480), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=36)
    for i, line in enumerate(LINES):
        draw.text((60, 60 + i * 110), line, fill="black", font=font)
    return image


def image_bytes(fmt):
    buffer = io.BytesIO()
    report_image().save(buffer, format=fmt)
    return buffer.getvalue()


needs_ocr = pytest.mark.skipif(not loaders.ocr_available(), reason="OCR extras not installed")


@needs_ocr
def test_scanned_pdf_page_is_ocrd(tmp_path):
    path = tmp_path / "scanned.pdf"
    path.write_bytes(image_bytes("PDF"))
    docs = loaders.load_pdf(str(path))
    assert len(docs) == 1
    assert docs[0].metadata == {"page": 1, "ocr": True}
    assert "Hemoglobin: 9.1 g/dL" in docs[0].page_content


@needs_ocr
def test_scanned_pdf_upload_extracts_labs_and_alerts(client, signup, upload):
    body = upload(signup("alice"), [("scan.pdf", image_bytes("PDF"), "application/pdf")]).json()
    assert body["labs_found"] == 2
    assert body["critical_alerts"] == ["Potassium 6.9 mmol/L is above the critical limit (6.5 mmol/L)"]


@needs_ocr
def test_photo_upload_png(client, signup, upload):
    body = upload(signup("alice"), [("photo.png", image_bytes("PNG"), "image/png")]).json()
    assert body["labs_found"] == 2 and body["abnormal_count"] == 2


def test_scanned_pdf_without_ocr_is_rejected_with_hint(client, signup, upload, monkeypatch):
    monkeypatch.setattr(loaders, "ocr_available", lambda: False)
    r = upload(signup("alice"), [("scan.pdf", image_bytes("PDF"), "application/pdf")])
    assert r.status_code == 400
    assert "requirements-ocr.txt" in r.json()["detail"]
