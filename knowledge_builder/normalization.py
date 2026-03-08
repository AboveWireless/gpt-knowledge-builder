from __future__ import annotations

import re
from collections import Counter

from .models import Config, PageText
from .utils import normalize_unicode


TOC_LINE_RE = re.compile(r"\.{3,}\s*\d+\s*$")
PAGE_ONLY_RE = re.compile(r"^\s*(page\s+)?\d+\s*$", re.IGNORECASE)
HEADING_RE = re.compile(r"^(\d+(\.\d+){0,4}|[A-Z][A-Z0-9\s/&,-]{4,}|#{1,6}\s+.+)$")


def normalize_pages(pages: list[PageText], config: Config) -> tuple[list[PageText], dict]:
    normalized_pages: list[PageText] = []
    header_footer_lines = _detect_repeated_edge_lines(pages) if config.extraction.remove_repeated_headers else set()
    duplicate_counter: Counter[str] = Counter()

    for page in pages:
        lines = normalize_unicode(page.text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
        cleaned = _clean_lines(lines, header_footer_lines, config)
        merged = _merge_wrapped_lines(cleaned)
        merged = _remove_duplicate_blocks(merged, duplicate_counter)
        text = "\n".join(merged).strip()
        normalized_pages.append(
            PageText(
                page_number=page.page_number,
                text=text,
                ocr_used=page.ocr_used,
                ocr_confidence=page.ocr_confidence,
                is_scanned=page.is_scanned,
            )
        )

    metrics = {
        "repeated_edge_line_count": len(header_footer_lines),
        "duplicate_block_count": sum(1 for count in duplicate_counter.values() if count > 1),
    }
    return normalized_pages, metrics


def normalize_text(text: str) -> str:
    text = normalize_unicode(text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _detect_repeated_edge_lines(pages: list[PageText]) -> set[str]:
    candidates: Counter[str] = Counter()
    for page in pages:
        lines = [line.strip() for line in page.text.splitlines() if line.strip()]
        edge_lines = lines[:2] + lines[-2:]
        for line in edge_lines:
            if 3 <= len(line) <= 120:
                candidates[line] += 1
    threshold = max(2, len(pages) // 3) if pages else 2
    return {line for line, count in candidates.items() if count >= threshold}


def _clean_lines(lines: list[str], repeated_edge_lines: set[str], config: Config) -> list[str]:
    cleaned: list[str] = []
    blank_run = 0
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
            continue
        blank_run = 0
        if repeated_edge_lines and line in repeated_edge_lines:
            continue
        if not config.extraction.preserve_page_numbers and PAGE_ONLY_RE.fullmatch(line):
            continue
        if TOC_LINE_RE.search(line):
            continue
        if _is_noise_line(line):
            continue
        cleaned.append(line)
    return cleaned


def _merge_wrapped_lines(lines: list[str]) -> list[str]:
    if not lines:
        return []
    merged: list[str] = []
    for line in lines:
        if not merged or not line:
            merged.append(line)
            continue
        prev = merged[-1]
        if not prev or _looks_like_heading(prev) or _looks_like_heading(line):
            merged.append(line)
            continue
        if _should_merge(prev, line):
            merged[-1] = f"{prev} {line}".strip()
        else:
            merged.append(line)
    return merged


def _remove_duplicate_blocks(lines: list[str], duplicate_counter: Counter[str]) -> list[str]:
    output: list[str] = []
    window: list[str] = []
    for line in lines:
        if line:
            window.append(line)
            if len(window) > 3:
                window.pop(0)
        block = "\n".join(window[-3:])
        if len(window) == 3 and duplicate_counter[block] >= 1:
            continue
        if len(window) == 3:
            duplicate_counter[block] += 1
        output.append(line)
    return output


def _should_merge(prev: str, line: str) -> bool:
    if prev.endswith((".", ":", ";", "?", "!")):
        return False
    if line.startswith(("-", "*", "#")):
        return False
    if re.match(r"^\d+[\.)]\s", line):
        return False
    if _looks_like_heading(line):
        return False
    return True


def _looks_like_heading(line: str) -> bool:
    return bool(HEADING_RE.match(line.strip()))


def _is_noise_line(line: str) -> bool:
    if len(line) <= 1 and line not in {"-", "*"}:
        return True
    if re.fullmatch(r"[_\-]{3,}", line):
        return True
    return False
