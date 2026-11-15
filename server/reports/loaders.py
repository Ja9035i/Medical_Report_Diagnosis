"""File loaders that turn an uploaded file into LangChain Documents (one per page)."""
import re
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List

from langchain_core.documents import Document
from pypdf import PdfReader

OCR_RENDER_SCALE = 2  # render PDF pages at 2x (~144 dpi) for better OCR accuracy
OCR_MIN_CONFIDENCE = 0.5


def clean_text(text: str) -> str:
    """Collapse runs of spaces, trim each line and squeeze blank lines."""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def extract_page_text(page) -> str:
    """
    Layout mode keeps words and lines together (plain mode can emit one word per
    line for some PDFs, which hurts both chunking and lab-value parsing).
    """
    try:
        text = page.extract_text(extraction_mode="layout")
    except Exception:
        text = page.extract_text()
    return clean_text(text or "")


# ---------------- OCR (optional: pip install -r requirements-ocr.txt) ----------------

def ocr_available() -> bool:
    try:
        import pypdfium2  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def _ocr_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def ocr_image(image) -> str:
    """OCR an image (file path or numpy array) into text, one recognised line per row."""
    result, _ = _ocr_engine()(image)
    lines = [text for _, text, score in (result or []) if float(score) >= OCR_MIN_CONFIDENCE]
    return clean_text("\n".join(lines))


def ocr_pdf_page(path: str, page_index: int) -> str:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        image = pdf[page_index].render(scale=OCR_RENDER_SCALE).to_numpy()
    finally:
        pdf.close()
    return ocr_image(image)


# ---------------- loaders ----------------

def load_pdf(path: str) -> List[Document]:
    """
    One Document per PDF page; metadata['page'] is 1-based. Pages with no text
    layer (scanned pages) are OCR'd when OCR is installed, otherwise skipped.
    """
    reader = PdfReader(path)
    use_ocr = None  # decided lazily, only if a page has no text
    docs = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = extract_page_text(page)
        metadata = {"page": page_number}
        if not text:
            if use_ocr is None:
                use_ocr = ocr_available()
            if use_ocr:
                text = ocr_pdf_page(path, page_number - 1)
                metadata["ocr"] = True
        if text:
            docs.append(Document(page_content=text, metadata=metadata))
    return docs


def load_txt(path: str) -> List[Document]:
    """A whole text file as one Document (no page numbers)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    return [Document(page_content=text, metadata={})] if text else []


def load_image(path: str) -> List[Document]:
    """A photo/scan of a report (PNG/JPG) read with OCR."""
    if not ocr_available():
        return []
    text = ocr_image(path)
    return [Document(page_content=text, metadata={"ocr": True})] if text else []


LOADERS: Dict[str, Callable[[str], List[Document]]] = {
    ".pdf": load_pdf,
    ".txt": load_txt,
    ".png": load_image,
    ".jpg": load_image,
    ".jpeg": load_image,
}
