# PDF input

TBL accepts PDF files as input. The PDF is parsed with **PyMuPDF**, converted
into semantic HTML inside TBL, translated through the standard EPUB/DOCX
pipeline (with tag preservation, intelligent chunking, glossary, and refine
pass), and packaged as an **EPUB** on the output side.

## What you get

- Heading detection from font sizes (`<h1>`, `<h2>`, `<p>`).
- Built-in PDF outline picked up as TOC entries.
- Automatic removal of running headers, footers, and page numbers.
- Removal of recurring watermarks (e.g. Pearson `ptg...` IDs) when they sit
  in the top/bottom margins of every page.
- Hyphenated line breaks (`thou-` + `sand` -> `thousand`) joined.
- Bullet and numbered lists rebuilt as `<ul>` / `<ol>`.

## What is NOT supported in this version

- **Image-only / scanned PDFs.** The upload is rejected with HTTP 400 and a
  clear error message. OCR is intentionally out of scope.
- **PDF on the output side.** Translation always produces an EPUB. The output
  filename is auto-rewritten to `.epub` if you pass `.pdf`.
- **Refine-only mode on PDF.** Refine is applied to the translated EPUB, not
  to the original PDF.
- **Tables, formulas, footnotes** are not preserved structurally. Their text
  may still appear in the body but without the original layout.
- **Multi-column PDFs** with unusual layouts may read out of order in rare
  cases; PyMuPDF's reading-order detection is good but not perfect.

## How it works

```
PDF input
  -> PyMuPDF (fitz.open, get_text("dict"), get_toc())
  -> semantic HTML (src/core/pdf/converter.py)
  -> TagPreserver + HtmlChunker (reused from EPUB/DOCX)
  -> LLM translation (with refine, glossary, checkpointing)
  -> single-chapter EPUB 3 archive (src/core/pdf/epub_builder.py)
```

The architecture mirrors `src/core/docx/`: a converter produces HTML, a
`TranslationAdapter` plugs into `GenericTranslationOrchestrator`, and the
``finalize_output`` step writes the result archive.

## When to prefer PDF input over PDF -> EPUB conversion (Calibre, online tools)

External PDF -> EPUB converters often destroy book structure before TBL
ever sees the file. Real-world example: Petzold's "Code: The Hidden
Language" (Pearson 2nd Edition, 481 PDF pages) converted through Calibre
exposed:

| Artifact | What broke |
|---|---|
| `ptg38990134` watermark x 459 | Pearson tracking ID became 459 stray paragraphs |
| Cover `C O D E` | One title line became four single-letter paragraphs |
| Multi-column TOC | Reading order collapsed across columns |
| Multi-line headings | `Preface to the\nSecond Edition` split in two |
| Running headers/footers | `viii` and chapter titles inlined into body text |
| Bullet lists | `<ul>/<li>` lost, flattened to paragraphs |

With TBL's native PDF input these are fixed at the source, before the LLM
ever touches the content.

## Limitations to expect

- The output EPUB is a single XHTML "chapter" containing the whole book.
  The PDF outline still drives the TOC pane in readers, but every entry
  links back to that one file.
- Cover thumbnail in the web UI is rendered from the first PDF page.
- Translation quality depends on the model and the source. PDFs with weird
  fonts or aggressive ligatures may produce noisier extraction.
