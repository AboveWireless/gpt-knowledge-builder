from __future__ import annotations

import re

from .models import ChunkRecord, Config, DocumentRecord
from .utils import split_sentences


DEFINITION_RE = re.compile(r"^\s*([A-Z][A-Za-z0-9 /()-]{2,60})\s+(?:means|is defined as)\s+(.+)$", re.IGNORECASE)
REQUIREMENT_RE = re.compile(r"\b(shall|must|required|shall not|must not|prohibited)\b", re.IGNORECASE)
WARNING_RE = re.compile(r"^\s*(warning|caution|danger|note)\s*[:\-]?\s*(.+)$", re.IGNORECASE)
PART_RE = re.compile(r"\b(?:PN|P/N|Part(?:\s+No\.?)?|Model|SKU)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})\b", re.IGNORECASE)
SPEC_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9 /()-]{2,40})\s*[:=]\s*([-+]?\d+(?:\.\d+)?)\s*([A-Za-z%/.-]{0,12})\b"
)


def extract_structured_records(doc: DocumentRecord, chunks: list[ChunkRecord], config: Config) -> dict[str, list[dict]]:
    definitions: list[dict] = []
    requirements: list[dict] = []
    warnings: list[dict] = []
    parts: list[dict] = []
    specs: list[dict] = []
    procedures: list[dict] = []
    tables: list[dict] = []

    for chunk in chunks:
        definitions.extend(_extract_definitions(doc, chunk))
        if config.extraction.detect_requirements:
            requirements.extend(_extract_requirements(doc, chunk))
        warnings.extend(_extract_warnings(doc, chunk))
        if config.extraction.detect_parts:
            parts.extend(_extract_parts(doc, chunk))
        specs.extend(_extract_specs(doc, chunk))
        procedures.extend(_extract_procedures(doc, chunk))
        if config.extraction.detect_tables:
            tables.extend(_extract_tables(doc, chunk))

    return {
        "definitions": definitions,
        "requirements": requirements,
        "warnings": warnings,
        "parts": parts,
        "specs": specs,
        "procedures": procedures,
        "tables": tables,
    }


def _extract_definitions(doc: DocumentRecord, chunk: ChunkRecord) -> list[dict]:
    records: list[dict] = []
    for idx, line in enumerate(chunk.text.splitlines()):
        match = DEFINITION_RE.match(line.strip())
        if not match:
            continue
        records.append(
            _base_item(doc, chunk, "definitions", idx)
            | {
                "term": match.group(1).strip(),
                "definition": match.group(2).strip(),
            }
        )
    return records


def _extract_requirements(doc: DocumentRecord, chunk: ChunkRecord) -> list[dict]:
    records: list[dict] = []
    for idx, sentence in enumerate(split_sentences(chunk.text)):
        match = REQUIREMENT_RE.search(sentence)
        if not match:
            continue
        records.append(
            _base_item(doc, chunk, "requirements", idx)
            | {
                "requirement_text": sentence.strip(),
                "requirement_type": match.group(1).lower(),
            }
        )
    return records


def _extract_warnings(doc: DocumentRecord, chunk: ChunkRecord) -> list[dict]:
    records: list[dict] = []
    for idx, line in enumerate(chunk.text.splitlines()):
        match = WARNING_RE.match(line.strip())
        if not match:
            continue
        records.append(
            _base_item(doc, chunk, "warnings", idx)
            | {
                "warning_type": match.group(1).lower(),
                "warning_text": match.group(2).strip(),
            }
        )
    return records


def _extract_parts(doc: DocumentRecord, chunk: ChunkRecord) -> list[dict]:
    records: list[dict] = []
    seen: set[str] = set()
    for idx, match in enumerate(PART_RE.finditer(chunk.text)):
        part_number = match.group(1).strip()
        if part_number in seen:
            continue
        seen.add(part_number)
        context = _context_window(chunk.text, match.start())
        records.append(
            _base_item(doc, chunk, "parts", idx)
            | {
                "part_number": part_number,
                "part_name": "",
                "description": context,
                "compatible_models": [],
            }
        )
    return records


def _extract_specs(doc: DocumentRecord, chunk: ChunkRecord) -> list[dict]:
    records: list[dict] = []
    for idx, match in enumerate(SPEC_RE.finditer(chunk.text)):
        records.append(
            _base_item(doc, chunk, "specs", idx)
            | {
                "parameter": match.group(1).strip(),
                "value": match.group(2).strip(),
                "unit": match.group(3).strip(),
                "context": _context_window(chunk.text, match.start()),
            }
        )
    return records


def _extract_procedures(doc: DocumentRecord, chunk: ChunkRecord) -> list[dict]:
    records: list[dict] = []
    for idx, line in enumerate(chunk.text.splitlines()):
        stripped = line.strip()
        if re.match(r"^\d+[\.)]\s+", stripped):
            records.append(
                _base_item(doc, chunk, "procedures", idx)
                | {
                    "step_text": stripped,
                }
            )
    return records


def _extract_tables(doc: DocumentRecord, chunk: ChunkRecord) -> list[dict]:
    records: list[dict] = []
    lines = [line.strip() for line in chunk.text.splitlines() if line.strip()]
    table_lines = [line for line in lines if " | " in line]
    if table_lines:
        records.append(
            _base_item(doc, chunk, "tables", 0)
            | {
                "table_text": "\n".join(table_lines),
            }
        )
    return records


def _base_item(doc: DocumentRecord, chunk: ChunkRecord, kind: str, index: int) -> dict:
    return {
        "doc_id": doc.doc_id,
        "item_id": f"{doc.doc_id}::{kind}-{index:04d}",
        "section_path": chunk.section_path,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "source_filename": doc.source_filename,
    }


def _context_window(text: str, start: int, radius: int = 120) -> str:
    left = max(0, start - radius)
    right = min(len(text), start + radius)
    return text[left:right].strip()
