"""Translation adapter for PDF inputs.

The adapter converts the PDF into HTML (PyMuPDF), then plugs into the same
TagPreserver/HtmlChunker pipeline used for EPUB and DOCX. The output is a
minimal EPUB archive built by ``epub_builder.build_epub``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from ..common.translation_orchestrator import TranslationAdapter
from ..epub.container import TranslationContainer
from .converter import PdfHtmlConverter
from .epub_builder import build_epub


class PdfTranslationAdapter(TranslationAdapter[str, bytes]):
    """Adapter that translates a PDF file into an EPUB archive."""

    def __init__(self, target_language: str) -> None:
        self.target_language = target_language
        self.converter = PdfHtmlConverter()
        self.container = TranslationContainer()
        self.tag_preserver = self.container.tag_preserver
        self.html_chunker = self.container.chunker

    def extract_content(
        self,
        source: str,
        log_callback: Optional[Callable],
    ) -> Tuple[str, Dict[str, Any]]:
        html_content, metadata = self.converter.to_html(source)

        if log_callback:
            log_callback(
                "pdf_extract_done",
                f"Extracted {len(html_content)} chars HTML from PDF "
                f"({metadata['page_count']} pages, {len(metadata['toc'])} TOC entries)",
            )
            for warn in metadata.get("warnings", []):
                log_callback("pdf_warning", warn)

        context = {
            "metadata": metadata,
            "preserver": self.tag_preserver,
            "source_path": source,
            "target_language": self.target_language,
        }
        return html_content, context

    def preserve_structure(
        self,
        content: str,
        context: Dict[str, Any],
        log_callback: Optional[Callable],
    ) -> Tuple[str, Dict[str, str], Tuple[str, str]]:
        preserver = context["preserver"]
        text_with_placeholders, tag_map = preserver.preserve_tags(content)
        placeholder_format = (
            preserver.placeholder_format.prefix,
            preserver.placeholder_format.suffix,
        )

        if log_callback:
            log_callback(
                "pdf_tags_preserved",
                f"Preserved {len(tag_map)} tag groups",
            )

        return text_with_placeholders, tag_map, placeholder_format

    def create_chunks(
        self,
        text: str,
        structure_map: Dict[str, str],
        max_tokens: int,
        log_callback: Optional[Callable],
    ) -> List[Dict]:
        chunks = self.html_chunker.chunk_html_with_placeholders(text, structure_map)

        if log_callback:
            log_callback("pdf_chunks_created", f"Created {len(chunks)} chunks")

        return chunks

    def reconstruct_content(
        self,
        translated_chunks: List[str],
        structure_map: Dict[str, str],
        context: Dict[str, Any],
    ) -> str:
        preserver = context["preserver"]
        full_translated = "".join(translated_chunks)
        return preserver.restore_tags(full_translated, structure_map)

    def finalize_output(
        self,
        reconstructed_content: str,
        source: str,
        context: Dict[str, Any],
        log_callback: Optional[Callable],
    ) -> bytes:
        metadata = context.get("metadata") or {}
        target_language = context.get("target_language") or "en"

        epub_bytes = build_epub(
            body_html=reconstructed_content,
            metadata=metadata,
            target_language=target_language,
        )

        if log_callback:
            log_callback(
                "pdf_epub_built",
                f"EPUB package built from PDF ({len(epub_bytes)} bytes)",
            )

        return epub_bytes
