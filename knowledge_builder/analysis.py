from __future__ import annotations

import re
from statistics import mean

from .models import DocumentProfile, ExtractedContent
from .utils import printable_ratio, split_sentences, word_count


NOISE_RE = re.compile(r"[^\w\s.,;:()\[\]/#%+\-]")
PART_RE = re.compile(r"\b(?:PN|P/N|Part(?:\s+No\.?)?|Model|SKU)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})\b", re.IGNORECASE)
REQUIREMENT_RE = re.compile(r"\b(shall|must|required|shall not|must not|prohibited)\b", re.IGNORECASE)
WARNING_RE = re.compile(r"\b(warning|caution|danger|note)\b", re.IGNORECASE)
TABLE_HINT_RE = re.compile(r"\s\|\s|,{2,}|\t")


def analyze_document(content: ExtractedContent, source_type: str, fallback_language: str = "en") -> DocumentProfile:
    text = content.text or ""
    words = max(word_count(text), 1)
    lines = [line for line in text.splitlines() if line.strip()]
    line_lengths = [len(line.strip()) for line in lines] or [0]
    avg_line_length = mean(line_lengths)
    printable = printable_ratio(text)
    noise_ratio = len(NOISE_RE.findall(text)) / max(len(text), 1)
    empty_ratio = text.count("\n\n") / max(len(lines), 1)
    heading_count = sum(1 for line in lines if _looks_like_heading(line))
    table_density = sum(1 for line in lines if TABLE_HINT_RE.search(line)) / max(len(lines), 1)
    duplicate_density = _duplicate_line_density(lines)
    ocr_confidences = [page.ocr_confidence for page in content.pages if page.ocr_confidence is not None]
    avg_ocr_confidence = mean(ocr_confidences) / 100 if ocr_confidences else None
    scanned_pages = sum(1 for page in content.pages if page.is_scanned)

    score = 1.0
    score -= min(noise_ratio * 2.5, 0.35)
    score -= min((1 - printable) * 0.5, 0.25)
    score -= min(empty_ratio * 0.15, 0.15)
    score -= min(duplicate_density * 0.35, 0.2)
    score -= 0.1 if avg_line_length < 18 else 0
    score += 0.05 if heading_count >= 3 else 0
    if avg_ocr_confidence is not None:
        score = min(score + (avg_ocr_confidence - 0.5) * 0.2, 1.0)
    score = max(0.05, min(score, 0.99))

    quality_flags: list[str] = []
    if printable < 0.95:
        quality_flags.append("low_printable_ratio")
    if noise_ratio > 0.08:
        quality_flags.append("high_symbol_noise")
    if avg_line_length < 18:
        quality_flags.append("short_broken_lines")
    if heading_count == 0:
        quality_flags.append("weak_heading_structure")
    if scanned_pages:
        quality_flags.append("scanned_pages_detected")
    if duplicate_density > 0.2:
        quality_flags.append("duplicate_blocks_detected")

    mostly_tabular = table_density > 0.2 or source_type in {"csv", "xlsx"}
    return DocumentProfile(
        probable_domain=_infer_domain(text),
        document_kind=_infer_document_kind(text, source_type),
        language=fallback_language,
        extraction_method=content.extraction_method,
        extraction_quality_score=round(score, 3),
        ocr_used=content.ocr_used,
        mostly_tabular=mostly_tabular,
        page_count=max(len(content.pages), 1),
        word_count=words,
        quality_flags=quality_flags,
        diagnostics={
            "printable_ratio": round(printable, 3),
            "noise_ratio": round(noise_ratio, 3),
            "empty_ratio": round(empty_ratio, 3),
            "average_line_length": round(avg_line_length, 2),
            "heading_count": heading_count,
            "table_density": round(table_density, 3),
            "duplicate_line_density": round(duplicate_density, 3),
            "avg_ocr_confidence": round(avg_ocr_confidence, 3) if avg_ocr_confidence is not None else None,
            "requirement_hits": len(REQUIREMENT_RE.findall(text)),
            "warning_hits": len(WARNING_RE.findall(text)),
            "parts_hits": len(PART_RE.findall(text)),
        },
    )


def summarize_for_report(text: str, max_sentences: int = 2) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return ""
    return " ".join(sentences[:max_sentences])


def _infer_domain(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("telecommunications", "fiber", "cabling", "tower")):
        return "telecommunications"
    if any(token in lowered for token in ("safety", "osha", "hazard", "warning")):
        return "safety"
    if any(token in lowered for token in ("installation", "maintenance", "manual")):
        return "operations"
    return "general"


def _infer_document_kind(text: str, source_type: str) -> str:
    lowered = text.lower()
    if source_type == "pptx":
        return "presentation"
    if source_type in {"csv", "xlsx"}:
        return "spreadsheet"
    if "table of contents" in lowered and "shall" in lowered:
        return "standard"
    if "manual" in lowered:
        return "manual"
    if "catalog" in lowered or "part number" in lowered:
        return "catalog"
    if "specification" in lowered or "specifications" in lowered:
        return "specification"
    if "warning" in lowered or "caution" in lowered or "danger" in lowered:
        return "safety_document"
    return "document"


def _duplicate_line_density(lines: list[str]) -> float:
    if not lines:
        return 0.0
    unique = len(set(lines))
    return 1 - (unique / len(lines))


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) > 120:
        return False
    if stripped.startswith("#"):
        return True
    if re.match(r"^\d+(\.\d+){0,4}\s+[A-Z]", stripped):
        return True
    if stripped.isupper() and len(stripped.split()) <= 12:
        return True
    return False
