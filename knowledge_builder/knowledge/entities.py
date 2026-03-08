from __future__ import annotations

import re
from collections import OrderedDict

from ..compiler_models import KnowledgeCandidate, PromotedKnowledgeItem, SourceKnowledge
from ..utils import slugify
from .common import admin_boilerplate_score, is_admin_or_sheet_heading, is_generic_note_word


STANDARD_RE = re.compile(r"\b(?:ANSI|TIA|OSHA|BICSI|IEEE|NEC|NFPA|ISO|IEC)[A-Z0-9-/.]*\b")
ORG_RE = re.compile(r"\b(?:OpenAI|Microsoft|Google|Amazon|TowerCo|American National Standards Institute)\b")
PART_RE = re.compile(r"\b(?:PN|P/N|Part(?:\s+No\.?)?|Model|SKU)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})\b", re.IGNORECASE)
DOC_TITLE_RE = re.compile(r"^(?:#\s+)?([A-Z][A-Za-z0-9 ,/&()_-]{5,120})$")
ENTITY_STOPWORDS = {
    "NECESSARY",
    "SHALL",
    "QTY",
    "SIZE",
    "NOTE",
    "NOTES",
    "CONSTRUCTION",
    "GENERAL",
    "DETAIL",
    "TITLE",
    "PAGE",
    "NUMBER",
    "NUMBERS",
    "DESCRIPTION",
    "WEIGHT",
    "PROVIDED",
    "WITHOUT",
    "DRAWING",
    "SHEET",
    "PROJECT",
    "DETAIL",
    "REVISION",
    "STANDARD",
    "SYSTEM",
    "ENTITY",
    "ENTITIES",
    "SITE",
    "LEGAL",
    "ISOLATED",
    "TAGS",
    "NUMBERS/TAGS",
    "LAT",
}


def extract_entity_candidates(items: list[SourceKnowledge]) -> list[KnowledgeCandidate]:
    candidates: list[KnowledgeCandidate] = []
    for item in items:
        if admin_boilerplate_score(item.clean_text) >= 0.7:
            continue
        standard_values = {match.group(0).strip() for match in STANDARD_RE.finditer(item.clean_text)}
        for match in STANDARD_RE.finditer(item.clean_text):
            _append_if_valid(candidates, _make_candidate(item, "standard", match.group(0), "Detected standards/code reference."))
        for match in ORG_RE.finditer(item.clean_text):
            org = match.group(0)
            if any(re.search(rf"\b{re.escape(org)}\b", standard_value) for standard_value in standard_values):
                continue
            _append_if_valid(candidates, _make_candidate(item, "organization", org, "Detected organization name."))
        for match in PART_RE.finditer(item.clean_text):
            _append_if_valid(candidates, _make_candidate(item, "product", match.group(1), "Detected part/model identifier."))
        title_match = DOC_TITLE_RE.match(item.title.strip())
        if title_match:
            title_value = title_match.group(1).strip()
            if not _is_generic_document_title(title_value):
                _append_if_valid(candidates, _make_candidate(item, "document", title_value, "Document title promoted as named item."))
    return _dedupe_entities(candidates)


def build_entities_markdown(items: list[SourceKnowledge]) -> str:
    candidates = extract_entity_candidates(items)
    if not candidates:
        return ""

    grouped: OrderedDict[str, list[KnowledgeCandidate]] = OrderedDict()
    for candidate in candidates:
        grouped.setdefault(candidate.target_type.title(), []).append(candidate)

    lines = ["# Entities", ""]
    for group_name, group_candidates in grouped.items():
        lines.append(f"## {group_name}")
        lines.append("")
        for candidate in group_candidates:
            source_names = sorted({candidate.provenance["source_filename"]})
            lines.append(f"- {candidate.title} (sources: {', '.join(source_names)})")
        lines.append("")
    return "\n".join(lines).strip()


def build_promoted_entity_items(items: list[SourceKnowledge]) -> list[PromotedKnowledgeItem]:
    promoted: list[PromotedKnowledgeItem] = []
    for candidate in extract_entity_candidates(items):
        promoted.append(
            PromotedKnowledgeItem(
                target_type="entities",
                title=candidate.title,
                body=candidate.body,
                supporting_sources=[str(candidate.provenance["source_filename"])],
                provenance_summary=[f"{candidate.provenance['source_filename']}::{candidate.source_chunk_id or 'document'}"],
                confidence=candidate.score,
            )
        )
    return promoted


def _make_candidate(item: SourceKnowledge, entity_type: str, value: str, reason: str) -> KnowledgeCandidate:
    cleaned = value.strip()
    return KnowledgeCandidate(
        target_type=entity_type,
        title=cleaned,
        body=cleaned,
        score=0.8,
        reasons=[reason],
        provenance={
            "source_filename": item.source_filename,
            "source_path": str(item.source_path),
            "section_heading": item.title,
        },
        normalized_key=slugify(f"{entity_type}-{cleaned}", 180),
        source_document_id=item.document_id,
        source_chunk_id="",
    )


def _dedupe_entities(candidates: list[KnowledgeCandidate]) -> list[KnowledgeCandidate]:
    best: OrderedDict[str, KnowledgeCandidate] = OrderedDict()
    for candidate in candidates:
        key = candidate.normalized_key
        current = best.get(key)
        if current is None:
            best[key] = candidate
    return list(best.values())


def _append_if_valid(candidates: list[KnowledgeCandidate], candidate: KnowledgeCandidate) -> None:
    if _is_valid_entity(candidate.title):
        candidates.append(candidate)


def _is_valid_entity(value: str) -> bool:
    cleaned = " ".join(value.split()).strip(" -:;,.")
    if not cleaned:
        return False
    if cleaned.upper() in ENTITY_STOPWORDS:
        return False
    if is_generic_note_word(cleaned):
        return False
    if is_admin_or_sheet_heading(cleaned):
        return False
    if len(cleaned) < 3:
        return False
    if len(cleaned.split()) > 6 and cleaned.isupper():
        return False
    if cleaned.isupper() and len(cleaned.split()) > 2:
        return False
    if re.fullmatch(r"[A-Z]{1,4}", cleaned) and cleaned not in {"ANSI", "OSHA", "BICSI", "IEEE", "NFPA", "NEC", "ISO", "IEC", "TIA"}:
        return False
    if re.search(r"(?:\b[A-Z]\b\s*){3,}", cleaned):
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?\s?(?:V|A|W|Hz|mm|cm|m|ft|in|lb|psi|N|Nm|%)", cleaned, re.IGNORECASE):
        return False
    if re.fullmatch(r"[A-Z][a-z]+", cleaned) and cleaned.lower() in {
        "provided",
        "necessary",
        "without",
        "description",
        "weight",
        "number",
        "numbers",
        "isolated",
        "legal",
        "site",
    }:
        return False
    if re.fullmatch(r"(?:numbers/tags|site|number|description|legal|lat)", cleaned, re.IGNORECASE):
        return False
    return True


def _is_generic_document_title(value: str) -> bool:
    cleaned = " ".join(value.split()).strip(" -:;,.")
    lowered = cleaned.lower()
    return lowered in {
        "entities",
        "entity",
        "drawing",
        "topic",
        "notes",
        "general notes",
        "title page",
    } or lowered.startswith("entity ")
