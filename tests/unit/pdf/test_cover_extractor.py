"""Tests for the PDF pre-upload validator and cover extractor."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from src.core.pdf.cover_extractor import PdfCoverExtractor, validate_pdf_is_translatable
from src.core.pdf.exceptions import ImageOnlyPdfError


def _pdf_with_text(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((50, 100), "Hello", fontsize=14.0)
    doc.save(str(path))
    doc.close()
    return path


def _pdf_without_text(path: Path) -> Path:
    doc = pymupdf.open()
    doc.new_page(width=400, height=600)
    doc.save(str(path))
    doc.close()
    return path


class TestValidate:
    def test_text_pdf_passes(self, tmp_path: Path) -> None:
        path = _pdf_with_text(tmp_path / "ok.pdf")
        validate_pdf_is_translatable(str(path))  # no exception

    def test_image_only_pdf_rejected(self, tmp_path: Path) -> None:
        path = _pdf_without_text(tmp_path / "empty.pdf")
        with pytest.raises(ImageOnlyPdfError):
            validate_pdf_is_translatable(str(path))


class TestThumbnail:
    def test_extract_cover_writes_jpeg(self, tmp_path: Path) -> None:
        pdf = _pdf_with_text(tmp_path / "doc.pdf")
        out_dir = tmp_path / "thumbs"

        filename = PdfCoverExtractor.extract_cover(str(pdf), out_dir)

        assert filename and filename.endswith(".jpg")
        thumbnail = out_dir / filename
        assert thumbnail.exists()
        assert thumbnail.stat().st_size > 0
