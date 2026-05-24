"""PDF cover extraction and pre-upload validation.

The web upload flow renders the first PDF page as a small JPEG thumbnail
(matching the EPUB thumbnail size) and rejects image-only PDFs before the
job is queued, so users get immediate feedback instead of a job that fails
mid-pipeline.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pymupdf
from PIL import Image

from .exceptions import ImageOnlyPdfError

__all__ = [
    "ImageOnlyPdfError",
    "PdfCoverExtractor",
    "PdfUploadSummary",
    "prepare_pdf_for_upload",
    "validate_pdf_is_translatable",
]


THUMBNAIL_SIZE = (48, 64)  # Match EPUBCoverExtractor for visual consistency.
JPEG_QUALITY = 85
# Render the first page at 2x for a crisp Lanczos downscale.
RENDER_ZOOM = 2.0
# Number of pages sampled for language detection at upload time.
LANG_SAMPLE_PAGES = 10


@dataclass
class PdfUploadSummary:
    """Bundle of artefacts produced by a single PyMuPDF open at upload time."""

    page_count: int
    sample_text: str
    thumbnail_filename: Optional[str]


def prepare_pdf_for_upload(
    pdf_path: str,
    thumbnails_dir: Path,
) -> PdfUploadSummary:
    """Open the PDF once and produce everything the upload route needs.

    Raises ``ImageOnlyPdfError`` when no page contains extractable text.
    The thumbnail field is ``None`` on rendering failure (graceful
    degradation - upload still succeeds, just without a preview).
    """
    doc = pymupdf.open(pdf_path)
    try:
        if doc.page_count == 0:
            raise ImageOnlyPdfError(f"PDF '{pdf_path}' has no pages.")

        sample_parts: List[str] = []
        has_text = False
        sample_limit = min(doc.page_count, LANG_SAMPLE_PAGES)
        for index, page in enumerate(doc):
            text = page.get_text("text")
            if text:
                if index < sample_limit:
                    sample_parts.append(text)
                if text.strip():
                    has_text = True
                    if index >= sample_limit - 1:
                        # We have what we need for language detection AND
                        # confirmed the doc is translatable. Stop walking.
                        break

        if not has_text:
            raise ImageOnlyPdfError(
                f"PDF '{pdf_path}' contains no extractable text on any of its "
                f"{doc.page_count} pages. The file appears to be a scan or "
                f"image-only PDF; OCR is not supported."
            )

        thumbnail_filename = _render_thumbnail(doc, pdf_path, thumbnails_dir)

        return PdfUploadSummary(
            page_count=doc.page_count,
            sample_text="\n".join(sample_parts),
            thumbnail_filename=thumbnail_filename,
        )
    finally:
        doc.close()


def _render_thumbnail(
    doc: "pymupdf.Document",
    pdf_path: str,
    output_dir: Path,
) -> Optional[str]:
    try:
        page = doc[0]
        matrix = pymupdf.Matrix(RENDER_ZOOM, RENDER_ZOOM)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        image_data = pixmap.tobytes("png")
    except Exception:
        return None
    return _save_thumbnail(image_data, pdf_path, output_dir)


def _save_thumbnail(
    image_data: bytes,
    pdf_path: str,
    output_dir: Path,
) -> Optional[str]:
    try:
        image = Image.open(io.BytesIO(image_data))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

        thumb = Image.new("RGB", THUMBNAIL_SIZE, (255, 255, 255))
        offset_x = (THUMBNAIL_SIZE[0] - image.width) // 2
        offset_y = (THUMBNAIL_SIZE[1] - image.height) // 2
        thumb.paste(image, (offset_x, offset_y))

        thumbnail_filename = f"{Path(pdf_path).stem}_cover.jpg"
        output_dir.mkdir(parents=True, exist_ok=True)
        thumb.save(
            output_dir / thumbnail_filename,
            "JPEG",
            quality=JPEG_QUALITY,
            optimize=True,
        )
        return thumbnail_filename
    except Exception:
        return None


# Backwards-compatible facade for callers that want to extract just the cover
# (e.g. tests). The upload path should prefer ``prepare_pdf_for_upload``.
class PdfCoverExtractor:
    """Render the first PDF page as a small JPEG thumbnail."""

    THUMBNAIL_SIZE = THUMBNAIL_SIZE
    JPEG_QUALITY = JPEG_QUALITY
    RENDER_ZOOM = RENDER_ZOOM

    @classmethod
    def extract_cover(cls, pdf_path: str, output_dir: Path) -> Optional[str]:
        try:
            doc = pymupdf.open(pdf_path)
        except Exception:
            return None
        try:
            if doc.page_count == 0:
                return None
            return _render_thumbnail(doc, pdf_path, output_dir)
        finally:
            doc.close()


def validate_pdf_is_translatable(pdf_path: str) -> None:
    """Reject image-only PDFs without producing thumbnails or samples.

    Kept for callers that only want the validation step (e.g. unit tests).
    The upload route uses ``prepare_pdf_for_upload`` instead so the single
    open also yields the cover and language sample.
    """
    doc = pymupdf.open(pdf_path)
    try:
        if doc.page_count == 0:
            raise ImageOnlyPdfError(f"PDF '{pdf_path}' has no pages.")
        for page in doc:
            if page.get_text("text").strip():
                return
        raise ImageOnlyPdfError(
            f"PDF '{pdf_path}' contains no extractable text on any of its "
            f"{doc.page_count} pages. The file appears to be a scan or "
            f"image-only PDF; OCR is not supported."
        )
    finally:
        doc.close()
