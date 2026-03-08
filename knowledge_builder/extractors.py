from __future__ import annotations

import csv
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree

from .models import Config, ExtractedContent, PageText
from .utils import detect_date_from_text


ExtractorFn = Callable[[Path, Config | None], ExtractedContent]


def get_supported_doc_type(path: Path) -> str | None:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"pdf", "docx", "txt", "md", "html", "htm", "xlsx", "pptx", "csv", "xml", "json", "png", "jpg", "jpeg"}:
        return "html" if suffix == "htm" else suffix
    return None


def extract(path: Path, doc_type: str, config: Config | None = None) -> ExtractedContent:
    extractors: dict[str, ExtractorFn] = {
        "txt": _extract_text,
        "md": _extract_text,
        "csv": _extract_csv,
        "html": _extract_html,
        "pdf": _extract_pdf,
        "docx": _extract_docx,
        "xlsx": _extract_xlsx,
        "pptx": _extract_pptx,
        "xml": _extract_xml,
        "json": _extract_json,
        "png": _extract_image,
        "jpg": _extract_image,
        "jpeg": _extract_image,
    }
    fn = extractors.get(doc_type)
    if not fn:
        return ExtractedContent(text="", title=path.stem, doc_date=None, extraction_method="unsupported")
    content = fn(path, config)
    if not content.title:
        content.title = path.stem
    if not content.doc_date:
        content.doc_date = detect_date_from_text(content.text[:5000]) or None
    if not content.pages and content.text:
        content.pages = [PageText(page_number=1, text=content.text, ocr_used=content.ocr_used)]
    return content


def _extract_text(path: Path, config: Config | None = None) -> ExtractedContent:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return ExtractedContent(
        text=text,
        title=path.stem,
        extraction_method="text",
        pages=[PageText(page_number=1, text=text)],
    )


def _extract_csv(path: Path, config: Config | None = None) -> ExtractedContent:
    rows: list[str] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(" | ".join(cell.strip() for cell in row))
    text = "\n".join(rows)
    return ExtractedContent(
        text=text,
        title=path.stem,
        extraction_method="csv",
        pages=[PageText(page_number=1, text=text)],
    )


def _extract_html(path: Path, config: Config | None = None) -> ExtractedContent:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        return ExtractedContent(
            text=raw,
            title=path.stem,
            extraction_method="html-raw",
            pages=[PageText(page_number=1, text=raw)],
        )
    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else path.stem
    text = soup.get_text("\n", strip=True)
    return ExtractedContent(
        text=text,
        title=title,
        extraction_method="html-bs4",
        pages=[PageText(page_number=1, text=text)],
    )


def _extract_xml(path: Path, config: Config | None = None) -> ExtractedContent:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    try:
        root = ElementTree.fromstring(raw)
        text = "\n".join(" ".join(elem.itertext()).strip() for elem in root.iter() if " ".join(elem.itertext()).strip())
        title = root.tag
        method = "xml-tree"
    except ElementTree.ParseError:
        text = raw
        title = path.stem
        method = "xml-raw"
    return ExtractedContent(
        text=text,
        title=title,
        extraction_method=method,
        pages=[PageText(page_number=1, text=text)],
    )


def _extract_json(path: Path, config: Config | None = None) -> ExtractedContent:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    try:
        obj = json.loads(raw)
        text = json.dumps(obj, indent=2, ensure_ascii=False)
        method = "json"
    except json.JSONDecodeError:
        text = raw
        method = "json-raw"
    return ExtractedContent(
        text=text,
        title=path.stem,
        extraction_method=method,
        pages=[PageText(page_number=1, text=text)],
    )


def _extract_pdf(path: Path, config: Config | None = None) -> ExtractedContent:
    fitz_content = _extract_pdf_with_fitz(path, config)
    if fitz_content is not None:
        return fitz_content

    pdfplumber_content = _extract_pdf_with_pdfplumber(path)
    if pdfplumber_content is not None:
        return pdfplumber_content

    return _extract_pdf_with_pypdf(path)


def _extract_pdf_with_fitz(path: Path, config: Config | None) -> ExtractedContent | None:
    try:
        import fitz  # type: ignore
    except ImportError:
        return None

    try:
        with _mupdf_messages_disabled(fitz):
            doc = fitz.open(path)
            pages: list[PageText] = []
            used_ocr = False
            method = "pymupdf"

            for index, page in enumerate(doc, start=1):
                text = page.get_text("text") or ""
                image_heavy = bool(page.get_images(full=True))
                ocr_confidence = None
                ocr_used = False
                is_scanned = False

                if _looks_like_low_quality_page(text, image_heavy):
                    is_scanned = image_heavy
                    ocr_text, ocr_confidence = _ocr_page_with_tesseract(page, config)
                    if ocr_text:
                        text = ocr_text
                        ocr_used = True
                        used_ocr = True
                        method = "pymupdf+tesseract"

                pages.append(
                    PageText(
                        page_number=index,
                        text=text,
                        ocr_used=ocr_used,
                        ocr_confidence=ocr_confidence,
                        is_scanned=is_scanned,
                    )
                )
    except Exception:
        return None

    body = "\n\n".join(page.text for page in pages if page.text.strip())
    return ExtractedContent(
        text=body,
        title=path.stem,
        extraction_method=method,
        pages=pages,
        ocr_used=used_ocr,
    )


@contextmanager
def _mupdf_messages_disabled(fitz_module):
    tools = getattr(fitz_module, "TOOLS", None)
    if tools is None:
        yield
        return

    previous_errors = _call_mupdf_toggle(tools.mupdf_display_errors)
    previous_warnings = _call_mupdf_toggle(tools.mupdf_display_warnings)
    try:
        tools.mupdf_display_errors(False)
        tools.mupdf_display_warnings(False)
        yield
    finally:
        tools.mupdf_display_errors(previous_errors)
        tools.mupdf_display_warnings(previous_warnings)
        reset = getattr(tools, "reset_mupdf_warnings", None)
        if callable(reset):
            reset()


def _call_mupdf_toggle(toggle) -> bool:
    try:
        return bool(toggle())
    except TypeError:
        return True


def _extract_pdf_with_pdfplumber(path: Path) -> ExtractedContent | None:
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return None

    pages: list[PageText] = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append(PageText(page_number=index, text=text))
    body = "\n\n".join(page.text for page in pages if page.text.strip())
    return ExtractedContent(
        text=body,
        title=path.stem,
        extraction_method="pdfplumber",
        pages=pages,
    )


def _extract_pdf_with_pypdf(path: Path) -> ExtractedContent:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        text = "[Extractor missing] Install pypdf or PyMuPDF to parse PDF."
        return ExtractedContent(
            text=text,
            title=path.stem,
            extraction_method="pdf-missing",
            pages=[PageText(page_number=1, text=text)],
        )

    reader = PdfReader(str(path))
    pages: list[PageText] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append(PageText(page_number=index, text=page.extract_text() or ""))
    body = "\n\n".join(page.text for page in pages if page.text.strip())
    return ExtractedContent(
        text=body,
        title=path.stem,
        extraction_method="pypdf",
        pages=pages,
    )


def _extract_docx(path: Path, config: Config | None = None) -> ExtractedContent:
    try:
        from docx import Document  # type: ignore
    except ImportError:
        text = "[Extractor missing] Install python-docx to parse DOCX."
        return ExtractedContent(
            text=text,
            title=path.stem,
            extraction_method="docx-missing",
            pages=[PageText(page_number=1, text=text)],
        )
    doc = Document(str(path))
    title = doc.core_properties.title or path.stem
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return ExtractedContent(
        text=text,
        title=title,
        extraction_method="docx",
        pages=[PageText(page_number=1, text=text)],
    )


def _extract_xlsx(path: Path, config: Config | None = None) -> ExtractedContent:
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError:
        text = "[Extractor missing] Install openpyxl to parse XLSX."
        return ExtractedContent(
            text=text,
            title=path.stem,
            extraction_method="xlsx-missing",
            pages=[PageText(page_number=1, text=text)],
        )

    wb = load_workbook(str(path), read_only=True, data_only=True)
    rows: list[str] = []
    pages: list[PageText] = []
    for index, ws in enumerate(wb.worksheets, start=1):
        sheet_rows = [f"# Sheet: {ws.title}"]
        for row in ws.iter_rows(values_only=True):
            values = ["" if v is None else str(v).strip() for v in row]
            line = " | ".join(v for v in values if v)
            if line:
                sheet_rows.append(line)
        sheet_text = "\n".join(sheet_rows)
        rows.append(sheet_text)
        pages.append(PageText(page_number=index, text=sheet_text))
    text = "\n\n".join(rows)
    return ExtractedContent(
        text=text,
        title=path.stem,
        extraction_method="xlsx",
        pages=pages,
    )


def _extract_pptx(path: Path, config: Config | None = None) -> ExtractedContent:
    try:
        from pptx import Presentation  # type: ignore
    except ImportError:
        text = "[Extractor missing] Install python-pptx to parse PPTX."
        return ExtractedContent(
            text=text,
            title=path.stem,
            extraction_method="pptx-missing",
            pages=[PageText(page_number=1, text=text)],
        )
    prs = Presentation(str(path))
    slides: list[str] = []
    pages: list[PageText] = []
    for index, slide in enumerate(prs.slides, start=1):
        chunks = [f"# Slide {index}"]
        for shape in slide.shapes:
            text = getattr(shape, "text", "")
            if text and text.strip():
                chunks.append(text.strip())
        slide_text = "\n".join(chunks)
        slides.append(slide_text)
        pages.append(PageText(page_number=index, text=slide_text))
    text = "\n\n".join(slides)
    return ExtractedContent(
        text=text,
        title=path.stem,
        extraction_method="pptx",
        pages=pages,
    )


def _extract_image(path: Path, config: Config | None = None) -> ExtractedContent:
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        text = "[OCR extractor missing] Install pytesseract and Pillow to parse image documents."
        return ExtractedContent(
            text=text,
            title=path.stem,
            extraction_method="image-ocr-missing",
            pages=[PageText(page_number=1, text=text, is_scanned=True)],
        )

    image = Image.open(path)
    text = pytesseract.image_to_string(image).strip()
    return ExtractedContent(
        text=text,
        title=path.stem,
        extraction_method="image-tesseract",
        pages=[PageText(page_number=1, text=text, ocr_used=True, is_scanned=True)],
        ocr_used=True,
    )


def _looks_like_low_quality_page(text: str, image_heavy: bool) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) < 40 and image_heavy:
        return True
    alpha = sum(1 for ch in stripped if ch.isalpha())
    return alpha < max(10, len(stripped) * 0.2) and image_heavy


def _ocr_page_with_tesseract(page, config: Config | None) -> tuple[str | None, float | None]:
    if not config or not config.ocr.enabled or config.ocr.engine.lower() != "tesseract":
        return None, None

    try:
        import fitz  # type: ignore
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return None, None

    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    mode = "RGB" if pix.n >= 3 else "L"
    image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)

    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        words = [word.strip() for word in data.get("text", []) if word.strip()]
        confidences = []
        for conf in data.get("conf", []):
            try:
                value = float(conf)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                confidences.append(value)
        text = " ".join(words).strip()
        confidence = sum(confidences) / len(confidences) if confidences else None
        if not text:
            text = pytesseract.image_to_string(image).strip()
        if confidence is not None and (confidence / 100) < config.ocr.threshold:
            return None, confidence
        return text or None, confidence
    except Exception:
        return None, None
