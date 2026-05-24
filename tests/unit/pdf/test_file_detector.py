"""File detection regression tests for PDF inputs."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from src.utils.file_detector import detect_file_type, detect_file_type_by_content


def _make_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((50, 100), "Test", fontsize=10.0)
    doc.save(str(path))
    doc.close()
    return path


class TestPdfDetection:
    def test_pdf_extension(self, tmp_path: Path) -> None:
        path = _make_pdf(tmp_path / "doc.pdf")
        assert detect_file_type(str(path)) == "pdf"

    def test_pdf_magic_bytes_without_extension(self, tmp_path: Path) -> None:
        # Synthesise a file with PDF magic bytes but a misleading extension.
        path = _make_pdf(tmp_path / "doc.bin")
        assert detect_file_type_by_content(str(path)) == "pdf"
