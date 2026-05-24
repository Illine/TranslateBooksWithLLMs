"""Exceptions raised by the PDF input adapter."""


class ImageOnlyPdfError(ValueError):
    """Raised when a PDF has no extractable text on any page.

    Such PDFs are scans or screenshots and need OCR, which is not implemented.
    Callers should map this to a 400 Bad Request in the web upload flow and
    to an exit error in the CLI.
    """


class PdfRefineNotSupportedError(NotImplementedError):
    """Raised when refine-only mode is requested for a PDF input.

    PDF translation produces an EPUB output, so refine should be applied to
    the resulting EPUB, not the original PDF.
    """
