"""Smoke tests for the PdfTranslationAdapter pipeline.

The adapter wires PdfHtmlConverter into the standard TagPreserver +
HtmlChunker + finalize-as-EPUB flow. These tests skip the LLM by feeding
the chunks back as the "translated" output and verify the resulting EPUB
is a well-formed package.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pymupdf
import pytest

from src.core.pdf.pdf_translation_adapter import PdfTranslationAdapter


def _build_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((50, 80), "Chapter Title", fontsize=24.0)
    for offset, line in enumerate(("Body paragraph one.", "Body paragraph two.", "Body paragraph three.")):
        page.insert_text((50, 150 + offset * 30), line, fontsize=10.0)
    doc.save(str(path))
    doc.close()
    return path


def _collect_chunk_text(chunk: object) -> str:
    """HtmlChunker returns dicts with shape varying by version - read defensively."""
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, dict):
        for key in ("translatable_text", "content", "text"):
            if chunk.get(key):
                return chunk[key]
    return ""


class TestAdapterPipeline:
    def test_end_to_end_without_llm(self, tmp_path: Path) -> None:
        pdf_path = _build_pdf(tmp_path)
        adapter = PdfTranslationAdapter(target_language="ru")

        html, ctx = adapter.extract_content(str(pdf_path), log_callback=None)
        assert "Chapter Title" in html
        assert ctx["target_language"] == "ru"

        text_p, tag_map, fmt = adapter.preserve_structure(html, ctx, log_callback=None)
        assert fmt == ("[id", "]")

        chunks = adapter.create_chunks(text_p, tag_map, max_tokens=450, log_callback=None)
        assert chunks, "chunker produced no chunks"

        # Echo the original chunk text back as the translation.
        translated = [_collect_chunk_text(c) for c in chunks]
        reconstructed = adapter.reconstruct_content(translated, tag_map, ctx)
        assert reconstructed  # non-empty

        epub_bytes = adapter.finalize_output(reconstructed, str(pdf_path), ctx, log_callback=None)
        assert epub_bytes.startswith(b"PK")

        with zipfile.ZipFile(io.BytesIO(epub_bytes)) as zf:
            names = zf.namelist()
            assert "mimetype" in names
            assert "META-INF/container.xml" in names
            assert "OEBPS/content.opf" in names
            assert "OEBPS/chapter.xhtml" in names
            # mimetype must be the very first entry and stored uncompressed.
            assert names[0] == "mimetype"
            info = zf.getinfo("mimetype")
            assert info.compress_type == zipfile.ZIP_STORED
