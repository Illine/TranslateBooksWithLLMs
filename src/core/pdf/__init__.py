"""PDF input support for TBL.

PDF documents are converted to HTML via PyMuPDF (fitz), translated through
the generic EPUB/DOCX pipeline (TagPreserver + HtmlChunker), and the result
is packaged as an EPUB file. PDF-on-PDF translation is out of scope.
"""

from .exceptions import ImageOnlyPdfError, PdfRefineNotSupportedError

__all__ = ["ImageOnlyPdfError", "PdfRefineNotSupportedError"]
