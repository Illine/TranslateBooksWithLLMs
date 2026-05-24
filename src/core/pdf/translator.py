"""PDF translation entry point.

PDF input is converted to HTML, translated through the generic orchestrator,
and the result is packaged as an EPUB file. The output extension is forced
to ``.epub`` regardless of what the caller requested.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

from ..common.translation_orchestrator import GenericTranslationOrchestrator
from .exceptions import ImageOnlyPdfError
from .pdf_translation_adapter import PdfTranslationAdapter


async def translate_pdf_file(
    input_filepath: str,
    output_filepath: str,
    source_language: str,
    target_language: str,
    model_name: str,
    llm_client: Any,
    max_tokens_per_chunk: int = 450,
    log_callback: Optional[Callable] = None,
    stats_callback: Optional[Callable] = None,
    prompt_options: Optional[Dict] = None,
    max_retries: int = 1,
    context_manager: Optional[Any] = None,
    check_interruption_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Translate a PDF file and write the result as an EPUB.

    Mirrors the signature of ``translate_docx_file`` for symmetry. Output is
    always an EPUB - the ``output_filepath`` extension is rewritten to
    ``.epub`` if needed, with a warning logged.

    Returns:
        Dict with ``success``, ``stats``, ``output_path``.
    """
    if not os.path.exists(input_filepath):
        if log_callback:
            log_callback("pdf_input_not_found", f"PDF '{input_filepath}' not found")
        return {"success": False, "stats": {}, "output_path": None}

    output_filepath = _force_epub_extension(output_filepath, log_callback)

    adapter = PdfTranslationAdapter(target_language=target_language)
    orchestrator = GenericTranslationOrchestrator(adapter)

    try:
        epub_bytes, stats = await orchestrator.translate(
            source=input_filepath,
            source_language=source_language,
            target_language=target_language,
            model_name=model_name,
            llm_client=llm_client,
            max_tokens_per_chunk=max_tokens_per_chunk,
            log_callback=log_callback,
            context_manager=context_manager,
            max_retries=max_retries,
            prompt_options=prompt_options,
            stats_callback=stats_callback,
            check_interruption_callback=check_interruption_callback,
        )
    except ImageOnlyPdfError as e:
        if log_callback:
            log_callback("pdf_image_only", f"❌ {e}")
        return {"success": False, "stats": {}, "output_path": None, "error": str(e)}

    if not epub_bytes:
        if log_callback:
            log_callback("pdf_translation_failed", "PDF translation produced no output")
        return {
            "success": False,
            "stats": stats.to_dict() if hasattr(stats, "to_dict") else {},
            "output_path": None,
        }

    with open(output_filepath, "wb") as f:
        f.write(epub_bytes)

    if log_callback:
        log_callback("file_saved", f"EPUB saved to {output_filepath}")

    return {
        "success": True,
        "stats": stats.to_dict() if hasattr(stats, "to_dict") else {},
        "output_path": output_filepath,
    }


def force_epub_extension(output_filepath: str) -> str:
    """Return ``output_filepath`` with its extension swapped for ``.epub``."""
    base, ext = os.path.splitext(output_filepath)
    if ext.lower() == ".epub":
        return output_filepath
    return base + ".epub"


def _force_epub_extension(
    output_filepath: str,
    log_callback: Optional[Callable],
) -> str:
    new_path = force_epub_extension(output_filepath)
    if log_callback and new_path != output_filepath:
        log_callback(
            "pdf_output_extension_forced",
            f"PDF output is always EPUB; rewriting "
            f"'{output_filepath}' to '{new_path}'.",
        )
    return new_path
