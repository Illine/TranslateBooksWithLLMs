"""Unit tests for PdfHtmlConverter and PDF helpers.

Synthetic PDFs are generated on the fly via PyMuPDF (no binary fixtures
checked into the repo). Each test crafts exactly the page layout needed to
exercise one converter behavior so failures point at one concept.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from src.core.pdf.converter import PdfHtmlConverter
from src.core.pdf.exceptions import ImageOnlyPdfError


def _new_pdf(tmp_path: Path, name: str = "doc.pdf") -> Path:
    return tmp_path / name


def _save(doc: "pymupdf.Document", path: Path) -> Path:
    doc.save(str(path))
    doc.close()
    return path


def _insert(doc: "pymupdf.Document", text: str, *, fontsize: float = 10.0, x: float = 50, y: float = 100) -> None:
    page = doc.new_page(width=400, height=600)
    page.insert_text((x, y), text, fontsize=fontsize)


class TestImageOnlyDetection:
    def test_pdf_without_text_raises(self, tmp_path: Path) -> None:
        path = _new_pdf(tmp_path, "image_only.pdf")
        doc = pymupdf.open()
        doc.new_page(width=400, height=600)  # blank page, no text
        _save(doc, path)

        with pytest.raises(ImageOnlyPdfError):
            PdfHtmlConverter().to_html(str(path))


class TestBodyParagraph:
    def test_single_paragraph_renders_as_p(self, tmp_path: Path) -> None:
        path = _new_pdf(tmp_path)
        doc = pymupdf.open()
        _insert(doc, "Hello world.", fontsize=10.0)
        _save(doc, path)

        html, meta = PdfHtmlConverter().to_html(str(path))

        assert "<p>Hello world.</p>" in html
        assert meta["page_count"] == 1
        assert meta["toc"] == []


class TestHeadingDetection:
    def test_large_font_promoted_to_h1(self, tmp_path: Path) -> None:
        # Body block at 10pt, heading block at 28pt (>10 * 1.6 = 16).
        path = _new_pdf(tmp_path)
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=600)
        page.insert_text((50, 80), "Chapter One", fontsize=28.0)
        # Multiple body lines so the mode font size is 10pt.
        for offset, line in enumerate(("Body paragraph line.", "Another body line.", "Third body line.")):
            page.insert_text((50, 150 + offset * 30), line, fontsize=10.0)
        _save(doc, path)

        html, _ = PdfHtmlConverter().to_html(str(path))

        assert "<h1>Chapter One</h1>" in html
        assert "<p>Body paragraph line.</p>" in html

    def test_medium_font_promoted_to_h2(self, tmp_path: Path) -> None:
        # Heading at 14pt (>10 * 1.3 = 13, but <10 * 1.6 = 16).
        path = _new_pdf(tmp_path)
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=600)
        page.insert_text((50, 80), "Subsection", fontsize=14.0)
        for offset, line in enumerate(("Body.", "Body line two.", "Body line three.")):
            page.insert_text((50, 150 + offset * 30), line, fontsize=10.0)
        _save(doc, path)

        html, _ = PdfHtmlConverter().to_html(str(path))

        assert "<h2>Subsection</h2>" in html


class TestHeaderFooterDedup:
    def test_repeating_top_zone_text_is_dropped(self, tmp_path: Path) -> None:
        path = _new_pdf(tmp_path)
        doc = pymupdf.open()
        for page_num in range(4):
            page = doc.new_page(width=400, height=600)
            # Top-zone running header (y at 5% of 600 = 30, well above 8% = 48).
            page.insert_text((50, 20), "Code", fontsize=10.0)
            # Body content - different per page so mode font is 10pt and
            # the body is not deduped.
            page.insert_text((50, 200), f"This is body paragraph number {page_num} with content.", fontsize=10.0)
        _save(doc, path)

        html, _ = PdfHtmlConverter().to_html(str(path))

        assert "<p>Code</p>" not in html
        assert "This is body paragraph number 0" in html


class TestBulletListDetection:
    def test_bullet_lines_become_ul(self, tmp_path: Path) -> None:
        path = _new_pdf(tmp_path)
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=600)
        # PyMuPDF requires fonts that include bullet glyphs; use ASCII dash
        # which the regex also accepts.
        page.insert_text((50, 100), "- First item in the list", fontsize=10.0)
        page.insert_text((50, 130), "- Second item in the list", fontsize=10.0)
        page.insert_text((50, 160), "- Third item in the list", fontsize=10.0)
        _save(doc, path)

        html, _ = PdfHtmlConverter().to_html(str(path))

        assert "<ul>" in html
        assert "<li>First item in the list</li>" in html
        assert "<li>Second item in the list</li>" in html
        assert "<li>Third item in the list</li>" in html

    def test_bullets_in_one_block_split_per_line(self, tmp_path: Path) -> None:
        # When PyMuPDF groups consecutive bullet lines into ONE text block
        # (close vertical spacing), the converter must still emit one <li>
        # per line rather than swallowing them into a single item.
        path = _new_pdf(tmp_path)
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=600)
        # Tight 12pt line spacing groups all four bullets into a single
        # PyMuPDF block; the per-line split kicks in here.
        for offset, item in enumerate(("Apples", "Oranges", "Bananas", "Pears")):
            page.insert_text((50, 100 + offset * 12), f"- {item}", fontsize=10.0)
        _save(doc, path)

        html, _ = PdfHtmlConverter().to_html(str(path))

        assert html.count("<li>") == 4
        for fruit in ("Apples", "Oranges", "Bananas", "Pears"):
            assert f"<li>{fruit}</li>" in html


class TestFontSizeSplit:
    def test_heading_glued_to_paragraph_is_split_back(self, tmp_path: Path) -> None:
        # PyMuPDF groups vertically close lines into one block even when
        # their font sizes differ. The converter must split such blocks so
        # the heading lands in <h1> instead of being swallowed by the body.
        path = _new_pdf(tmp_path)
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=600)
        # Body lines first at 10pt, then a 24pt heading directly underneath.
        page.insert_text((50, 100), "First body line.", fontsize=10.0)
        page.insert_text((50, 115), "Second body line.", fontsize=10.0)
        page.insert_text((50, 130), "Third body line.", fontsize=10.0)
        page.insert_text((50, 150), "Inline Heading", fontsize=24.0)
        _save(doc, path)

        html, _ = PdfHtmlConverter().to_html(str(path))

        assert "<h1>Inline Heading</h1>" in html
        assert "<p>First body line. Second body line. Third body line.</p>" in html


class TestCrossPageHyphenJoin:
    def test_word_broken_across_pages_is_reassembled(self, tmp_path: Path) -> None:
        path = _new_pdf(tmp_path)
        doc = pymupdf.open()

        # Page 1 - body paragraph ending with hyphenated word.
        page1 = doc.new_page(width=400, height=600)
        for offset, line in enumerate((
            "Body paragraph filler line.",
            "Another filler line.",
            "Yet a third filler line.",
            "And the word breaks: revolu-",
        )):
            page1.insert_text((50, 100 + offset * 20), line, fontsize=10.0)

        # Page 2 - continuation starts lowercase.
        page2 = doc.new_page(width=400, height=600)
        for offset, line in enumerate((
            "tionary developments changed everything.",
            "More body text on the second page.",
            "Closing line of the section.",
        )):
            page2.insert_text((50, 100 + offset * 20), line, fontsize=10.0)
        _save(doc, path)

        html, _ = PdfHtmlConverter().to_html(str(path))

        assert "revolu-" not in html
        assert "revolutionary developments" in html


class TestHtmlEscaping:
    def test_special_characters_are_escaped(self, tmp_path: Path) -> None:
        path = _new_pdf(tmp_path)
        doc = pymupdf.open()
        _insert(doc, "2 < 3 and 5 > 4 with & sign")
        _save(doc, path)

        html, _ = PdfHtmlConverter().to_html(str(path))

        assert "&lt;" in html
        assert "&gt;" in html
        assert "&amp;" in html
