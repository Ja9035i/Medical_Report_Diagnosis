"""File loaders that turn an uploaded file into LangChain Documents (one per page)."""
import re
from pathlib import Path
from typing import Callable, Dict, List

from langchain_core.documents import Document
from pypdf import PdfReader


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


def load_pdf(path: str) -> List[Document]:
    """One Document per PDF page; metadata['page'] is 1-based. Pages without text are skipped."""
    reader = PdfReader(path)
    docs = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = extract_page_text(page)
        if text:
            docs.append(Document(page_content=text, metadata={"page": page_number}))
    return docs


def load_txt(path: str) -> List[Document]:
    """A whole text file as one Document (no page numbers)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    return [Document(page_content=text, metadata={})] if text else []


LOADERS: Dict[str, Callable[[str], List[Document]]] = {
    ".pdf": load_pdf,
    ".txt": load_txt,
}
