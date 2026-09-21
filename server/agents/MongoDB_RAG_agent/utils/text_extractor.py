"""Text extraction for the MongoDB Atlas KB Agent.

Supported formats (all handled natively — no dependency on sibling agents):
  - PDF          : digital text via pdfplumber/pypdf; OCR fallback for scanned pages
  - DOCX         : python-docx with table and heading preservation
  - XLSX / XLS   : openpyxl / xlrd; every sheet extracted with headers
  - PPTX         : python-pptx; slide text + speaker notes
  - CSV          : raw CSV with header row preserved
  - TXT / MD     : plain text passthrough
  - HTML         : BeautifulSoup boilerplate removal
  - Images       : pytesseract OCR (PNG, JPG, TIFF, BMP, WEBP)

Falls back to the Document Formatter agent extractor when none of the above
match, so nothing that worked before will regress.
"""

from __future__ import annotations

import base64
import csv
import io
import os
import traceback
from pathlib import Path
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_text_from_file(
    file_content_b64: str,
    file_type: str,
    file_name: str = "",
    ocr_enabled: bool = True,
    ocr_language: str = "eng",
    scanned_page_threshold: int = 100,
) -> str:
    """Decode base-64 content and extract text.

    Returns a plain-text string. Never raises — returns empty string on failure.
    """
    ext = file_type.lower().strip(".")
    if not file_name:
        file_name = f"file.{ext}"
    try:
        raw_bytes = base64.b64decode(file_content_b64)
    except Exception as e:
        print(f"[Extractor] base64 decode failed: {e}")
        return ""

    try:
        handler = _HANDLERS.get(ext) or _HANDLERS.get(_ALIASES.get(ext, ""), None)
        if handler:
            return handler(
                raw_bytes,
                file_name=file_name,
                ocr_enabled=ocr_enabled,
                ocr_language=ocr_language,
                scanned_page_threshold=scanned_page_threshold,
            )
    except Exception as e:
        print(f"[Extractor] native handler for '{ext}' failed: {e}")
        traceback.print_exc()

    # Fallback to Document Formatter agent
    return _fallback_extractor(file_content_b64, ext, file_name)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _extract_pdf(
    data: bytes,
    file_name: str = "",
    ocr_enabled: bool = True,
    ocr_language: str = "eng",
    scanned_page_threshold: int = 100,
    **_,
) -> str:
    parts: list[str] = []

    # Try pdfplumber first (preserves tables better than pypdf)
    pages_text: list[str] = []
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages_text.append(t)
    except ImportError:
        pass
    except Exception as e:
        print(f"[Extractor:PDF] pdfplumber failed: {e}")

    # Fallback: pypdf
    if not pages_text:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            for page in reader.pages:
                pages_text.append(page.extract_text() or "")
        except Exception as e:
            print(f"[Extractor:PDF] pypdf failed: {e}")

    for page_num, text in enumerate(pages_text):
        char_count = len(text.strip())
        if char_count >= scanned_page_threshold:
            parts.append(f"--- Page {page_num + 1} ---\n{text.strip()}")
        elif ocr_enabled:
            ocr_text = _ocr_pdf_page(data, page_num, ocr_language)
            if ocr_text:
                parts.append(f"--- Page {page_num + 1} (OCR) ---\n{ocr_text.strip()}")

    return "\n\n".join(parts)


def _ocr_pdf_page(pdf_bytes: bytes, page_num: int, language: str) -> str:
    try:
        try:
            import fitz
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page = doc[page_num]
            pix = page.get_pixmap(dpi=300)
            img_data = pix.tobytes("png")
            doc.close()
        except ImportError:
            from pdf2image import convert_from_bytes
            images = convert_from_bytes(pdf_bytes, first_page=page_num + 1, last_page=page_num + 1, dpi=300)
            if not images:
                return ""
            buf = io.BytesIO()
            images[0].save(buf, format="PNG")
            img_data = buf.getvalue()
        return _ocr_image_bytes(img_data, language)
    except Exception as e:
        print(f"[Extractor:PDF:OCR] page {page_num}: {e}")
        return ""


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def _extract_docx(data: bytes, **_) -> str:
    import docx  # python-docx
    doc = docx.Document(io.BytesIO(data))
    parts: list[str] = []
    for block in doc.element.body:
        tag = block.tag.split("}")[-1] if "}" in block.tag else block.tag
        if tag == "p":
            text = block.text_content() if hasattr(block, "text_content") else ""
            # Use docx paragraph API for cleaner access
        elif tag == "tbl":
            pass  # handled below via python-docx API

    # Cleaner approach using python-docx API directly
    parts = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            if para.style and para.style.name.startswith("Heading"):
                parts.append(f"\n## {text}\n")
            else:
                parts.append(text)
    for table in doc.tables:
        rows = []
        for row in table.rows:
            rows.append(" | ".join(cell.text.strip() for cell in row.cells))
        if rows:
            parts.append("\n[Table]\n" + "\n".join(rows) + "\n")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# XLSX / XLS
# ---------------------------------------------------------------------------

def _extract_xlsx(data: bytes, **_) -> str:
    parts: list[str] = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = []
            headers: list[str] = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                cells = [str(c) if c is not None else "" for c in row]
                if i == 0:
                    headers = cells
                    rows.append(" | ".join(cells))
                else:
                    # Prepend header context for each row so embedding carries column names
                    row_str = " | ".join(
                        f"{h}: {v}" for h, v in zip(headers, cells) if v.strip()
                    )
                    if row_str.strip():
                        rows.append(row_str)
            if rows:
                parts.append(f"[Sheet: {sheet_name}]\n" + "\n".join(rows))
        wb.close()
    except ImportError:
        # Fallback: xlrd for .xls
        import xlrd
        wb = xlrd.open_workbook(file_contents=data)
        for sheet in wb.sheets():
            rows = []
            headers = [str(sheet.cell_value(0, c)) for c in range(sheet.ncols)] if sheet.nrows > 0 else []
            for r in range(sheet.nrows):
                cells = [str(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
                if r == 0:
                    rows.append(" | ".join(cells))
                else:
                    row_str = " | ".join(f"{h}: {v}" for h, v in zip(headers, cells) if v.strip())
                    if row_str.strip():
                        rows.append(row_str)
            if rows:
                parts.append(f"[Sheet: {sheet.name}]\n" + "\n".join(rows))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------

def _extract_pptx(data: bytes, **_) -> str:
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    parts: list[str] = []
    for slide_num, slide in enumerate(prs.slides, 1):
        slide_parts: list[str] = [f"--- Slide {slide_num} ---"]
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if text:
                        slide_parts.append(text)
        if slide.has_notes_slide:
            notes_text = slide.notes_slide.notes_text_frame.text.strip()
            if notes_text:
                slide_parts.append(f"[Notes]: {notes_text}")
        parts.append("\n".join(slide_parts))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def _extract_csv(data: bytes, **_) -> str:
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return ""
    headers = rows[0]
    lines = [" | ".join(headers)]
    for row in rows[1:]:
        row_str = " | ".join(f"{h}: {v}" for h, v in zip(headers, row) if v.strip())
        if row_str.strip():
            lines.append(row_str)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plain text / Markdown
# ---------------------------------------------------------------------------

def _extract_text(data: bytes, **_) -> str:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _extract_html(data: bytes, **_) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(data, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except ImportError:
        return _extract_text(data)


# ---------------------------------------------------------------------------
# Images (OCR only)
# ---------------------------------------------------------------------------

def _extract_image(
    data: bytes,
    ocr_enabled: bool = True,
    ocr_language: str = "eng",
    **_,
) -> str:
    if not ocr_enabled:
        return ""
    return _ocr_image_bytes(data, ocr_language)


def _ocr_image_bytes(data: bytes, language: str = "eng") -> str:
    try:
        from PIL import Image
        import pytesseract
        img = Image.open(io.BytesIO(data))
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        return pytesseract.image_to_string(img, lang=language).strip()
    except ImportError:
        print("[Extractor:OCR] pytesseract/Pillow not installed; OCR skipped")
        return ""
    except Exception as e:
        print(f"[Extractor:OCR] failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Fallback to Document Formatter agent
# ---------------------------------------------------------------------------

def _fallback_extractor(file_content_b64: str, ext: str, file_name: str) -> str:
    try:
        from agents.Document_formatter_agent.tools.file_extractor import extract_file_content
        text, success, _ = extract_file_content(file_content_b64, ext, file_name)
        return text if success else ""
    except Exception as e:
        print(f"[Extractor:fallback] Document Formatter extractor failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

_HANDLERS = {
    "pdf":  _extract_pdf,
    "docx": _extract_docx,
    "xlsx": _extract_xlsx,
    "xls":  _extract_xlsx,
    "pptx": _extract_pptx,
    "csv":  _extract_csv,
    "txt":  _extract_text,
    "md":   _extract_text,
    "markdown": _extract_text,
    "rst":  _extract_text,
    "html": _extract_html,
    "htm":  _extract_html,
    "png":  _extract_image,
    "jpg":  _extract_image,
    "jpeg": _extract_image,
    "tiff": _extract_image,
    "tif":  _extract_image,
    "bmp":  _extract_image,
    "webp": _extract_image,
}

_ALIASES = {
    "doc": "docx",
    "ppt": "pptx",
    "tsv": "csv",
}
