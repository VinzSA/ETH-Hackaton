"""
PDF text extraction.
- Digital PDFs: PyMuPDF (fitz) — preserves page/char offsets for SourceRef.
- Scanned/photo PDFs: falls back to pytesseract when a page has <50 chars.
"""
import io
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class PageText:
    page: int          # 1-indexed
    text: str
    char_start: int    # cumulative offset within the document
    char_end: int
    is_ocr: bool = False


def extract_pages(source: str | Path | bytes) -> list[PageText]:
    """
    Extract text from a PDF.
    `source` can be a file path or raw bytes (for in-memory uploads).
    Returns one PageText per page, with cumulative char offsets.
    """
    if isinstance(source, (str, Path)):
        doc = fitz.open(str(source))
    else:
        doc = fitz.open(stream=source, filetype="pdf")

    pages: list[PageText] = []
    cursor = 0

    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")

        if len(text.strip()) < 50:
            text = _ocr_page(page)
            is_ocr = True
        else:
            is_ocr = False

        start = cursor
        end = cursor + len(text)
        cursor = end

        pages.append(PageText(page=i, text=text, char_start=start, char_end=end, is_ocr=is_ocr))

    doc.close()
    return pages


def full_text(pages: list[PageText]) -> str:
    return "".join(p.text for p in pages)


def _ocr_page(page: fitz.Page) -> str:
    """Render the page to an image and run Tesseract PSM 6."""
    try:
        import pytesseract
        from PIL import Image

        mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better OCR quality
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return pytesseract.image_to_string(img, config="--psm 6")
    except Exception:
        return ""
