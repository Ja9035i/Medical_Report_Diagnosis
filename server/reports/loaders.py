"""File loaders that turn an uploaded file into LangChain Documents (one per page)."""
from pathlib import Path
from typing import Callable, Dict, List

from langchain_core.documents import Document
from pypdf import PdfReader


def load_pdf(path: str) -> List[Document]:
    """One Document per PDF page; metadata['page'] is 1-based. Pages without text are skipped."""
    reader = PdfReader(path)
    docs = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
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
