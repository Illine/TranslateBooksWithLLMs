"""PDF to HTML conversion for translation.

Uses PyMuPDF (fitz) to extract semantic structure (headings via font size,
TOC via document outline, lists via leading markers) and emit HTML that can
be fed into the existing EPUB/DOCX translation pipeline.

Image-only PDFs (scans) raise ImageOnlyPdfError - OCR is intentionally out
of scope for v1.
"""

from __future__ import annotations

import html
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pymupdf

from .exceptions import ImageOnlyPdfError


# Top/bottom margin treated as a candidate header/footer zone (fraction of
# page height). Empirically 8% works for most book layouts including Petzold.
_HEADER_FOOTER_ZONE = 0.08

# A text snippet recurring in the header/footer zone on at least this fraction
# of pages is considered a running header/footer (or watermark) and dropped.
_HEADER_FOOTER_FREQUENCY = 0.5

# Font-size multipliers above the median body size that promote a block to a
# heading. Tuned on Petzold (body 10pt, h2 18.6pt, h1 38.1pt) - generous
# enough not to false-positive bolded inline text.
_H1_RATIO = 1.6
_H2_RATIO = 1.3

# Bullet/numbered list leading markers. Single character bullets or short
# numeric/letter prefixes followed by a separator.
_LIST_MARKER_RE = re.compile(
    r"^\s*(?:[•‣◦⁃∙·‧▪▫●■○►☆★☞→]"
    r"|[\-–—−\*]"
    r"|\d+[\.\)]"
    r"|[a-zA-Zа-яА-Я][\.\)])\s+(.*)"
)


@dataclass
class _Block:
    """One logical block of text on a page (paragraph, heading, list item)."""

    text: str
    lines: List[str]
    font_size: float
    y0: float
    y1: float
    page_height: float

    @property
    def in_margin_zone(self) -> bool:
        margin = self.page_height * _HEADER_FOOTER_ZONE
        return self.y1 < margin or self.y0 > self.page_height - margin


@dataclass
class _ConversionState:
    """Working state accumulated while walking the document."""

    blocks_by_page: List[List[_Block]] = field(default_factory=list)
    all_font_sizes: List[float] = field(default_factory=list)
    page_count: int = 0


class PdfHtmlConverter:
    """Convert a PDF to a single semantic HTML string.

    The output mirrors what mammoth produces for DOCX so the same
    TagPreserver/HtmlChunker pipeline handles it without changes.
    """

    def to_html(self, pdf_path: str) -> Tuple[str, Dict[str, Any]]:
        """Extract HTML + metadata from a PDF file.

        Args:
            pdf_path: Path to the input PDF.

        Returns:
            ``(html_content, metadata)`` where ``html_content`` is a single
            ``<html>...</html>`` document and ``metadata`` contains
            ``page_count``, ``toc`` (list of ``[level, title, page]``) and
            ``warnings`` (list of human-readable strings).

        Raises:
            ImageOnlyPdfError: when no page contains extractable text.
        """
        doc = pymupdf.open(pdf_path)
        try:
            state = self._collect_blocks(doc)
            if not any(state.blocks_by_page):
                raise ImageOnlyPdfError(
                    f"PDF '{pdf_path}' contains no extractable text on any of "
                    f"its {doc.page_count} pages. The file appears to be a scan "
                    f"or image-only PDF; OCR is not supported."
                )

            body_threshold = self._compute_body_font_size(state.all_font_sizes)
            running_texts = self._detect_running_headers_footers(state.blocks_by_page)
            warnings = self._collect_warnings(doc, state)

            html_content = self._render_html(
                state.blocks_by_page,
                body_threshold,
                running_texts,
            )

            toc = doc.get_toc() or []
            metadata = {
                "page_count": doc.page_count,
                "toc": toc,
                "warnings": warnings,
                "title": doc.metadata.get("title") if doc.metadata else None,
                "author": doc.metadata.get("author") if doc.metadata else None,
            }
            return html_content, metadata
        finally:
            doc.close()

    def _collect_blocks(self, doc: "pymupdf.Document") -> _ConversionState:
        state = _ConversionState(page_count=doc.page_count)
        for page in doc:
            page_height = page.rect.height
            page_blocks: List[_Block] = []
            page_dict = page.get_text("dict")
            for raw_block in page_dict.get("blocks", []):
                if raw_block.get("type") != 0:
                    continue
                lines = raw_block.get("lines", [])
                if not lines:
                    continue

                bbox = raw_block.get("bbox") or (0.0, 0.0, 0.0, 0.0)
                line_records = self._extract_line_records(lines)
                if not line_records:
                    continue

                for sub_lines, sub_sizes in self._split_by_font_size(line_records):
                    state.all_font_sizes.extend(sub_sizes)
                    block_text = self._join_lines_with_hyphens(sub_lines).strip()
                    if not block_text:
                        continue
                    page_blocks.append(
                        _Block(
                            text=block_text,
                            lines=sub_lines,
                            font_size=statistics.median(sub_sizes) if sub_sizes else 0.0,
                            y0=float(bbox[1]),
                            y1=float(bbox[3]),
                            page_height=page_height,
                        )
                    )
            state.blocks_by_page.append(page_blocks)
        return state

    @staticmethod
    def _extract_line_records(lines: List[Dict[str, Any]]) -> List[Tuple[str, float, List[float]]]:
        """Flatten raw PyMuPDF lines into ``(text, median_size, span_sizes)``."""
        records: List[Tuple[str, float, List[float]]] = []
        for line in lines:
            parts: List[str] = []
            sizes: List[float] = []
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text:
                    continue
                parts.append(text)
                sizes.append(span.get("size", 0.0))
            if not parts:
                continue
            line_text = "".join(parts)
            line_size = statistics.median(sizes) if sizes else 0.0
            records.append((line_text, line_size, sizes))
        return records

    @staticmethod
    def _split_by_font_size(
        line_records: List[Tuple[str, float, List[float]]],
    ) -> List[Tuple[List[str], List[float]]]:
        """Split a PyMuPDF block when font size jumps significantly between lines.

        Wraps a small style change (italic emphasis, footnote subscript) into
        the surrounding paragraph, but breaks out a true heading that PyMuPDF
        glued to a body paragraph because the lines were vertically close.
        """
        if not line_records:
            return []
        groups: List[Tuple[List[str], List[float]]] = []
        current_lines: List[str] = []
        current_sizes: List[float] = []
        current_anchor: float = line_records[0][1]
        for text, size, span_sizes in line_records:
            if current_lines and current_anchor > 0 and size > 0:
                ratio = max(size, current_anchor) / min(size, current_anchor)
                if ratio >= _H2_RATIO:
                    groups.append((current_lines, current_sizes))
                    current_lines = []
                    current_sizes = []
                    current_anchor = size
            current_lines.append(text)
            current_sizes.extend(span_sizes)
            if not current_anchor:
                current_anchor = size
        if current_lines:
            groups.append((current_lines, current_sizes))
        return groups

    @staticmethod
    def _join_lines_with_hyphens(lines: List[str]) -> str:
        """Concatenate lines, joining trailing hyphens with the next word."""
        result: List[str] = []
        for raw in lines:
            line = raw.rstrip()
            if result and result[-1].endswith("-") and line and line[0].islower():
                # Join "thou-" + "sand" -> "thousand". Use lowercase as a
                # cheap signal that this is a real word break, not a real
                # hyphen (compound words usually do not break on uppercase).
                result[-1] = result[-1][:-1] + line
            else:
                if result:
                    result.append(" " + line)
                else:
                    result.append(line)
        return "".join(result)

    @staticmethod
    def _compute_body_font_size(sizes: List[float]) -> float:
        if not sizes:
            return 0.0
        # Use the most common rounded size as body. Median can be skewed by
        # long stretches of large-font front matter; mode is more robust.
        rounded = Counter(round(s, 1) for s in sizes)
        mode_size, _ = rounded.most_common(1)[0]
        return mode_size

    @staticmethod
    def _detect_running_headers_footers(
        blocks_by_page: List[List[_Block]],
    ) -> set[str]:
        """Identify text that recurs in top/bottom zones across many pages."""
        zone_counts: Counter[str] = Counter()
        page_total = max(len(blocks_by_page), 1)
        for page_blocks in blocks_by_page:
            seen_on_page: set[str] = set()
            for block in page_blocks:
                if not block.in_margin_zone:
                    continue
                normalised = PdfHtmlConverter._normalise_for_dedup(block.text)
                if not normalised:
                    continue
                if normalised in seen_on_page:
                    continue
                seen_on_page.add(normalised)
                zone_counts[normalised] += 1
        threshold = max(2, int(page_total * _HEADER_FOOTER_FREQUENCY))
        return {text for text, count in zone_counts.items() if count >= threshold}

    @staticmethod
    def _normalise_for_dedup(text: str) -> str:
        """Strip digits and whitespace so paginated headers collapse together."""
        # "Page 1" and "Page 2" must compare equal, while distinct chapter
        # headers (different words) stay distinct after the digit substitution.
        return re.sub(r"\d+", "#", text).strip().casefold()

    @staticmethod
    def _collect_warnings(
        doc: "pymupdf.Document",
        state: _ConversionState,
    ) -> List[str]:
        warnings: List[str] = []
        empty_pages = sum(1 for blocks in state.blocks_by_page if not blocks)
        if empty_pages:
            warnings.append(
                f"{empty_pages} of {doc.page_count} pages had no extractable text "
                f"(likely images, covers, or scans). Their content was skipped."
            )
        return warnings

    def _render_html(
        self,
        blocks_by_page: List[List[_Block]],
        body_threshold: float,
        running_texts: set[str],
    ) -> str:
        survived = self._filter_running_texts(blocks_by_page, running_texts)
        survived = self._join_cross_block_hyphens(survived)

        body_parts: List[str] = []
        pending_list_items: List[str] = []
        list_kind: Optional[str] = None  # 'ul' or 'ol'

        def flush_list() -> None:
            nonlocal pending_list_items, list_kind
            if not pending_list_items:
                return
            tag = list_kind or "ul"
            items_html = "".join(f"<li>{item}</li>" for item in pending_list_items)
            body_parts.append(f"<{tag}>{items_html}</{tag}>")
            pending_list_items = []
            list_kind = None

        for block in survived:
            list_items = self._extract_list_items(block)
            if list_items is not None:
                items, kind = list_items
                if list_kind and list_kind != kind:
                    flush_list()
                list_kind = kind
                pending_list_items.extend(html.escape(item) for item in items)
                continue

            flush_list()

            tag = self._block_tag(block.font_size, body_threshold)
            body_parts.append(f"<{tag}>{html.escape(block.text)}</{tag}>")

        flush_list()

        body = "\n".join(body_parts)
        return f"<!DOCTYPE html><html><head><meta charset=\"utf-8\"/></head><body>{body}</body></html>"

    def _filter_running_texts(
        self,
        blocks_by_page: List[List[_Block]],
        running_texts: set[str],
    ) -> List[_Block]:
        """Drop running headers/footers and flatten pages into one stream."""
        result: List[_Block] = []
        for page_blocks in blocks_by_page:
            for block in page_blocks:
                if running_texts and self._normalise_for_dedup(block.text) in running_texts:
                    continue
                result.append(block)
        return result

    @staticmethod
    def _join_cross_block_hyphens(blocks: List[_Block]) -> List[_Block]:
        """Merge `word-` at end of block N with continuation in block N+1.

        Intra-block joining is handled in ``_join_lines_with_hyphens``; this
        pass catches the case where the break falls on a page boundary so
        ``_collect_blocks`` never saw the two halves side by side.
        """
        if not blocks:
            return blocks
        merged: List[_Block] = [blocks[0]]
        for nxt in blocks[1:]:
            prev = merged[-1]
            if (
                prev.text.endswith("-")
                and len(prev.text) >= 2
                and prev.text[-2].isalpha()
                and nxt.text
                and nxt.text[0].islower()
            ):
                # Drop the trailing hyphen and glue the words together.
                glued_text = prev.text[:-1] + nxt.text
                glued_lines = list(prev.lines)
                if glued_lines and nxt.lines:
                    glued_lines[-1] = glued_lines[-1].rstrip()
                    if glued_lines[-1].endswith("-"):
                        glued_lines[-1] = glued_lines[-1][:-1] + nxt.lines[0]
                    else:
                        glued_lines[-1] = glued_lines[-1] + nxt.lines[0]
                    glued_lines.extend(nxt.lines[1:])
                merged[-1] = _Block(
                    text=glued_text,
                    lines=glued_lines or prev.lines,
                    # Keep the head block's font / bbox so heading detection
                    # and zone checks on the next block do not get confused.
                    font_size=prev.font_size,
                    y0=prev.y0,
                    y1=prev.y1,
                    page_height=prev.page_height,
                )
            else:
                merged.append(nxt)
        return merged

    @staticmethod
    def _extract_list_items(block: _Block) -> Optional[Tuple[List[str], str]]:
        """If every line in ``block`` is a list item, return its items and kind.

        Each line is checked against ``_LIST_MARKER_RE`` separately so a
        multi-line bullet block becomes one ``<li>`` per line instead of
        collapsing into a single item.
        """
        lines = [line.strip() for line in block.lines if line.strip()]
        if not lines:
            return None
        items: List[str] = []
        kind: Optional[str] = None
        for line in lines:
            match = _LIST_MARKER_RE.match(line)
            if not match:
                return None
            bullet = line[:1]
            current_kind = "ol" if bullet.isdigit() or bullet.isalpha() else "ul"
            if kind is None:
                kind = current_kind
            elif kind != current_kind:
                return None
            items.append(match.group(1).strip())
        return items, (kind or "ul")

    @staticmethod
    def _block_tag(font_size: float, body_threshold: float) -> str:
        if body_threshold <= 0 or font_size <= 0:
            return "p"
        if font_size >= body_threshold * _H1_RATIO:
            return "h1"
        if font_size >= body_threshold * _H2_RATIO:
            return "h2"
        return "p"
