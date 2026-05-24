"""Build a minimal EPUB 3 archive from translated HTML.

A PDF input is translated through the HTML pipeline and then repackaged as
a single-chapter EPUB. The structure is intentionally minimal: one XHTML
file in OEBPS/, a small OPF manifest, and a navigation document. This is
enough for e-readers to open the file and is symmetric with how mammoth +
python-docx produce DOCX in `src/core/docx/converter.py`.
"""

from __future__ import annotations

import html
import io
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


_CONTAINER_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
    '</container>'
)


def build_epub(
    body_html: str,
    metadata: Optional[Dict[str, Any]] = None,
    target_language: str = "en",
) -> bytes:
    """Package the translated HTML body into a minimal EPUB 3 archive.

    Args:
        body_html: Inner HTML (without ``<html>``/``<body>`` wrappers, or with
            them - both are handled).
        metadata: Optional dict with ``title``, ``author``, ``toc`` (list of
            ``[level, title, page]`` tuples as returned by PyMuPDF).
        target_language: BCP 47 language tag for the EPUB ``dc:language``.

    Returns:
        EPUB file bytes.
    """
    metadata = metadata or {}
    title = metadata.get("title") or "Translated PDF"
    author = metadata.get("author") or "Unknown"
    toc = metadata.get("toc") or []

    inner_body = _strip_outer_html(body_html)
    chapter_xhtml = _wrap_chapter(inner_body, title=title, lang=target_language)
    nav_xhtml = _build_nav(toc, lang=target_language)
    opf = _build_opf(
        title=title,
        author=author,
        language=target_language,
        has_nav=True,
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        # The mimetype entry must be the first file and stored uncompressed
        # per the EPUB specification.
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr("META-INF/container.xml", _CONTAINER_XML)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
        zf.writestr("OEBPS/chapter.xhtml", chapter_xhtml)

    return buffer.getvalue()


def _strip_outer_html(content: str) -> str:
    """Return the inner body content if the input is a full HTML document."""
    if "<body" in content:
        start = content.find("<body")
        body_open_end = content.find(">", start)
        body_close = content.rfind("</body>")
        if body_open_end != -1 and body_close > body_open_end:
            return content[body_open_end + 1 : body_close].strip()
    return content.strip()


def _wrap_chapter(inner_body: str, title: str, lang: str) -> str:
    safe_title = html.escape(title)
    safe_lang = html.escape(lang)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{safe_lang}" lang="{safe_lang}">\n'
        f'<head><title>{safe_title}</title><meta charset="utf-8"/></head>\n'
        f'<body>{inner_body}</body>\n'
        '</html>'
    )


def _build_nav(toc: List[List[Any]], lang: str) -> str:
    safe_lang = html.escape(lang)
    items = _render_nav_items(toc) if toc else (
        '<li><a href="chapter.xhtml">Chapter</a></li>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{safe_lang}" lang="{safe_lang}">\n'
        '<head><title>Table of Contents</title><meta charset="utf-8"/></head>\n'
        '<body><nav epub:type="toc" id="toc">\n'
        f'<h1>Table of Contents</h1>\n<ol>{items}</ol>\n'
        '</nav></body></html>'
    )


def _render_nav_items(toc: List[List[Any]]) -> str:
    """Flatten the TOC to a single-level list pointing at the chapter file.

    The output EPUB has only one XHTML file (the whole translated body), so we
    cannot anchor TOC entries to per-chapter files. We keep titles as a flat
    list so e-readers still expose them in the TOC pane.
    """
    parts: List[str] = []
    for entry in toc:
        if not entry or len(entry) < 2:
            continue
        raw_title = str(entry[1]).strip()
        if not raw_title:
            continue
        parts.append(f'<li><a href="chapter.xhtml">{html.escape(raw_title)}</a></li>')
    return "".join(parts) or '<li><a href="chapter.xhtml">Chapter</a></li>'


def _build_opf(title: str, author: str, language: str, has_nav: bool) -> str:
    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_title = html.escape(title)
    safe_author = html.escape(author)
    safe_lang = html.escape(language)
    nav_item = (
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        if has_nav else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookID">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'<dc:identifier id="BookID">{book_id}</dc:identifier>\n'
        f'<dc:title>{safe_title}</dc:title>\n'
        f'<dc:creator>{safe_author}</dc:creator>\n'
        f'<dc:language>{safe_lang}</dc:language>\n'
        f'<meta property="dcterms:modified">{modified}</meta>\n'
        '</metadata>\n'
        '<manifest>\n'
        f'{nav_item}\n'
        '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>\n'
        '</manifest>\n'
        '<spine>\n'
        '<itemref idref="chapter"/>\n'
        '</spine>\n'
        '</package>'
    )
