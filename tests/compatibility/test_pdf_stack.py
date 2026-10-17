"""Frozen documents exercise installed parsers, rendering and Portuguese OCR."""

import shutil
from pathlib import Path

import fitz
import pytest

from apps.ingestion import fulltext

FIXTURES = Path(__file__).parents[1] / "fixtures" / "compatibility"


def test_real_pdf_preserves_accents_and_page_order_without_ocr(monkeypatch):
    def unexpected_ocr(*args):
        pytest.fail("A complete text layer should not require OCR")

    monkeypatch.setattr(fulltext, "_ocr_page", unexpected_ocr)
    expected = (FIXTURES / "legislative-text.txt").read_text().strip()
    assert fulltext._extract((FIXTURES / "legislative-text.pdf").read_bytes()) == expected


def test_real_pdf_still_extracts_when_optional_renderer_is_unavailable(monkeypatch):
    monkeypatch.setattr(fulltext, "_open_fitz", lambda content: None)
    expected = (FIXTURES / "legislative-text.txt").read_text().strip()
    assert fulltext._extract((FIXTURES / "legislative-text.pdf").read_bytes()) == expected


def test_encrypted_pdf_without_password_is_an_extraction_failure():
    assert fulltext._extract((FIXTURES / "encrypted.pdf").read_bytes()) is None


def test_truncated_document_is_an_extraction_failure():
    assert fulltext._extract((FIXTURES / "legislative-text.pdf").read_bytes()[:80]) is None


def test_scanned_pdf_degrades_cleanly_without_ocr(monkeypatch):
    monkeypatch.setattr(fulltext, "_ocr_page", lambda doc, index: None)
    assert fulltext._extract((FIXTURES / "legislative-scan.pdf").read_bytes()) is None


def test_real_portuguese_ocr_recovers_image_only_document():
    if not shutil.which("tesseract"):
        pytest.fail("Install Tesseract with Portuguese data to run compatibility tests")
    content = (FIXTURES / "legislative-scan.pdf").read_bytes()
    with fitz.open(stream=content, filetype="pdf") as document:
        assert document[0].get_text().strip() == ""
    text = fulltext._extract(content)
    assert text is not None
    normalized = " ".join(text.casefold().split())
    for phrase in (
        "direitos das mulheres",
        "igualdade de acesso",
        "justificação",
        "sociedade civil",
    ):
        assert phrase in normalized
    # Minor whitespace/punctuation changes across Tesseract builds are harmless;
    # losing most of the document or returning only a header is not.
    assert len(text.split()) >= 85
