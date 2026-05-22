"""
Tests for court_mind_web.utils.file_parser

Covers: .txt / .pdf / .docx parsing, error handling,
        unsupported types, and empty-file edge cases.
"""

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from court_mind_web.utils.file_parser import (
    SUPPORTED_EXTENSIONS,
    UnsupportedFileType,
    parse_docx,
    parse_file,
    parse_pdf,
    parse_txt,
)


# ────────────────────────────────────────────
# parse_txt
# ────────────────────────────────────────────
class TestParseTxt:
    def test_basic_bytes(self):
        assert parse_txt(b"Hello World") == "Hello World"

    def test_strips_whitespace(self):
        assert parse_txt(b"  some text  \n") == "some text"

    def test_binary_io(self):
        buf = io.BytesIO(b"case narrative here")
        assert parse_txt(buf) == "case narrative here"

    def test_empty(self):
        assert parse_txt(b"") == ""

    def test_utf8_content(self):
        text = "IPC Section 302 — Murder"
        assert parse_txt(text.encode("utf-8")) == text

    def test_non_utf8_replacement(self):
        raw = b"\xff\xfe Some text"
        result = parse_txt(raw)
        assert "Some text" in result


# ────────────────────────────────────────────
# parse_pdf (mocked — no real PDF needed)
# ────────────────────────────────────────────
class TestParsePdf:
    @patch("pdfminer.high_level.extract_text")
    def test_extracts_text(self, mock_extract):
        mock_extract.return_value = "  Extracted PDF content  "
        result = parse_pdf(b"fake-pdf-bytes")
        assert result == "Extracted PDF content"
        mock_extract.assert_called_once()

    @patch("pdfminer.high_level.extract_text")
    def test_empty_pdf(self, mock_extract):
        mock_extract.return_value = ""
        assert parse_pdf(b"fake") == ""

    @patch("pdfminer.high_level.extract_text")
    def test_binary_io(self, mock_extract):
        mock_extract.return_value = "content"
        buf = io.BytesIO(b"fake")
        result = parse_pdf(buf)
        assert result == "content"


# ────────────────────────────────────────────
# parse_docx (mocked — no real docx needed)
# ────────────────────────────────────────────
class TestParseDocx:
    @patch("docx.Document")
    def test_extracts_paragraphs(self, mock_doc_cls):
        p1 = MagicMock(); p1.text = "Para one"
        p2 = MagicMock(); p2.text = ""
        p3 = MagicMock(); p3.text = "Para three"
        mock_doc = MagicMock()
        mock_doc.paragraphs = [p1, p2, p3]
        mock_doc_cls.return_value = mock_doc

        result = parse_docx(b"fake-docx")
        assert result == "Para one\nPara three"

    @patch("docx.Document")
    def test_empty_docx(self, mock_doc_cls):
        mock_doc = MagicMock()
        mock_doc.paragraphs = []
        mock_doc_cls.return_value = mock_doc
        assert parse_docx(b"fake") == ""


# ────────────────────────────────────────────
# parse_file (dispatcher)
# ────────────────────────────────────────────
class TestParseFile:
    def test_txt_dispatch(self):
        assert parse_file("case.txt", b"hello") == "hello"

    def test_txt_case_insensitive(self):
        assert parse_file("CASE.TXT", b"hello") == "hello"

    @patch("court_mind_web.utils.file_parser.parse_pdf")
    def test_pdf_dispatch(self, mock_pdf):
        mock_pdf.return_value = "pdf text"
        assert parse_file("doc.pdf", b"fake") == "pdf text"

    @patch("court_mind_web.utils.file_parser.parse_docx")
    def test_docx_dispatch(self, mock_docx):
        mock_docx.return_value = "docx text"
        assert parse_file("doc.docx", b"fake") == "docx text"

    def test_unsupported_extension(self):
        with pytest.raises(UnsupportedFileType, match="Unsupported file type '.jpg'"):
            parse_file("image.jpg", b"data")

    def test_no_extension(self):
        with pytest.raises(UnsupportedFileType):
            parse_file("noext", b"data")

    def test_supported_extensions_constant(self):
        assert ".txt" in SUPPORTED_EXTENSIONS
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".docx" in SUPPORTED_EXTENSIONS


# ────────────────────────────────────────────
# FastAPI route integration (lightweight)
# ────────────────────────────────────────────
class TestUploadRouteImport:
    """Verify the main app imports and mounts correctly."""

    def test_app_loads(self):
        from court_mind_web.main import app
        assert app.title == "CourtMind"

    def test_upload_route_exists(self):
        from court_mind_web.main import app
        routes = [r.path for r in app.routes]
        assert "/upload-case" in routes

    def test_simulate_route_exists(self):
        from court_mind_web.main import app
        routes = [r.path for r in app.routes]
        assert "/simulate" in routes
