"""
CourtMind — Case File Parser

Extracts plain text from uploaded case files (.txt, .pdf, .docx).
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO, Union


SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}


class UnsupportedFileType(ValueError):
    """Raised when the file extension is not supported."""


def parse_file(filename: str, file_obj: Union[BinaryIO, bytes]) -> str:
    """
    Dispatch to the correct parser based on file extension.

    Parameters
    ----------
    filename : str
        Original filename (used to detect extension).
    file_obj : BinaryIO | bytes
        File-like object or raw bytes.

    Returns
    -------
    str  Extracted text.
    """
    ext = Path(filename).suffix.lower()
    if ext == ".txt":
        return parse_txt(file_obj)
    elif ext == ".pdf":
        return parse_pdf(file_obj)
    elif ext == ".docx":
        return parse_docx(file_obj)
    else:
        raise UnsupportedFileType(
            f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )


def parse_txt(file_obj: Union[BinaryIO, bytes]) -> str:
    """Extract text from a .txt file."""
    raw = file_obj if isinstance(file_obj, bytes) else file_obj.read()
    return raw.decode("utf-8", errors="replace").strip()


def parse_pdf(file_obj: Union[BinaryIO, bytes]) -> str:
    """Extract text from a .pdf file using pdfminer.six."""
    from pdfminer.high_level import extract_text as _extract_text

    raw = file_obj if isinstance(file_obj, bytes) else file_obj.read()
    return _extract_text(io.BytesIO(raw)).strip()


def parse_docx(file_obj: Union[BinaryIO, bytes]) -> str:
    """Extract text from a .docx file using python-docx."""
    from docx import Document

    raw = file_obj if isinstance(file_obj, bytes) else file_obj.read()
    doc = Document(io.BytesIO(raw))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs).strip()
