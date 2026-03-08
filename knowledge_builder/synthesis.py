from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

from .compiler_models import KnowledgeCandidate, PromotedKnowledgeItem, SourceKnowledge
from .knowledge.common import build_chunks, dedupe_text_blocks
from .knowledge.entities import build_entities_markdown, build_promoted_entity_items, extract_entity_candidates
from .knowledge.facts import inspect_fact_candidates
from .knowledge.file_guide import build_file_guide as _build_file_guide
from .knowledge.glossary import inspect_glossary_candidates
from .knowledge.instructions import build_instructions as _build_instructions
from .knowledge.procedures import inspect_procedure_candidates
from .knowledge.synthesizer import build_topic_pages, inspect_topic_candidates
from .utils import normalize_unicode, sha256_file, split_sentences, word_count


ENTITY_RE = re.compile(r"\b(?:ANSI|TIA|OSHA|BICSI|IEEE|NEC|NFPA|ISO|IEC)[A-Z0-9-/.]*\b")
PART_RE = re.compile(r"\b(?:PN|P/N|Part(?:\s+No\.?)?|Model|SKU|Standard)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,})\b")
WARNING_RE = re.compile(r"\b(warning|caution|danger|note)\b", re.IGNORECASE)


def clean_text_for_knowledge(text: str) -> str:
    text = normalize_unicode(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    lines = _drop_obvious_noise(lines)
    lines = _merge_wrapped_lines(lines)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_source_knowledge(
    source_path,
    document_type: str,
    title: str,
    raw_text: str,
    clean_text: str,
    extraction_method: str = "unknown",
    ocr_used: bool = False,
    source_folder_name: str | None = None,
) -> SourceKnowledge:
    source_path = Path(source_path)
    document_id = sha256_file(source_path)[:16] if source_path.exists() else f"doc-{source_path.stem}"
    knowledge = SourceKnowledge(
        document_id=document_id,
        source_path=source_path,
        source_filename=source_path.name,
        source_folder_name=source_folder_name or source_path.parent.name,
        document_type=document_type,
        title=title.strip() or source_path.stem,
        raw_text=raw_text,
        clean_text=clean_text,
        extraction_method=extraction_method,
        ocr_used=ocr_used,
    )
    if not clean_text.strip():
        knowledge.empty_reason = "empty_after_extraction"
        return knowledge

    knowledge.chunks = build_chunks(
        clean_text,
        knowledge.source_filename,
        knowledge.title,
        document_id=knowledge.document_id,
        source_path=str(knowledge.source_path),
        file_type=knowledge.document_type,
        extraction_method=knowledge.extraction_method,
    )
    knowledge.glossary_candidates, glossary_rejected = inspect_glossary_candidates(knowledge.chunks)
    knowledge.procedure_candidates, procedure_rejected = inspect_procedure_candidates(knowledge.chunks)
    knowledge.fact_candidates, fact_rejected = inspect_fact_candidates(knowledge.chunks)
    knowledge.topic_candidates, topic_rejected = inspect_topic_candidates([knowledge])

    knowledge.glossary = [(candidate.term, candidate.definition) for candidate in knowledge.glossary_candidates]
    knowledge.procedures = [candidate.title for candidate in knowledge.procedure_candidates]
    knowledge.facts = [candidate.text for candidate in knowledge.fact_candidates]
    knowledge.summary_points = summarize_document(knowledge.chunks)
    entity_candidates = extract_entity_candidates([knowledge])
    knowledge.entities = [candidate.title for candidate in entity_candidates]
    knowledge.warnings = extract_warnings(clean_text)
    knowledge.accepted_candidates = (
        [_candidate_from_glossary(candidate, knowledge) for candidate in knowledge.glossary_candidates]
        + [_candidate_from_procedure(candidate, knowledge) for candidate in knowledge.procedure_candidates]
        + [_candidate_from_fact(candidate, knowledge) for candidate in knowledge.fact_candidates]
        + [_candidate_from_topic(candidate, knowledge) for candidate in knowledge.topic_candidates]
        + entity_candidates
    )
    knowledge.rejected_candidates = glossary_rejected + procedure_rejected + fact_rejected + topic_rejected
    knowledge.promoted_items = (
        [_promoted_from_glossary(candidate) for candidate in knowledge.glossary_candidates]
        + [_promoted_from_procedure(candidate) for candidate in knowledge.procedure_candidates]
        + [_promoted_from_fact(candidate) for candidate in knowledge.fact_candidates]
        + [_promoted_from_topic(candidate) for candidate in knowledge.topic_candidates]
        + build_promoted_entity_items([knowledge])
    )
    return knowledge


def summarize_document(chunks, max_points: int = 6) -> list[str]:
    points: list[str] = []
    for chunk in chunks:
        if chunk.heading and chunk.heading != chunk.title:
            points.append(chunk.heading)
        sentence = split_sentences(chunk.text.replace("\n", " ").strip())
        if sentence:
            lead = sentence[0].strip()
            if 8 <= word_count(lead) <= 35:
                points.append(lead)
        if len(points) >= max_points:
            break
    return dedupe_text_blocks(points)[:max_points]


def build_reference_facts(items: list[SourceKnowledge]) -> str:
    candidates = []
    for item in items:
        candidates.extend(item.fact_candidates)
    if not candidates:
        return ""

    grouped: dict[str, list[tuple[str, list[str]]]] = OrderedDict()
    clustered: dict[str, OrderedDict[str, dict[str, object]]] = OrderedDict()
    for candidate in candidates:
        category = candidate.category.title()
        grouped.setdefault(category, [])
        clustered.setdefault(category, OrderedDict())
        key = re.sub(r"\s+", " ", candidate.text.strip().lower())
        existing = clustered[category].get(key)
        if existing is None:
            clustered[category][key] = {
                "text": candidate.text,
                "score": candidate.score,
                "sources": {candidate.source_filename},
            }
            continue
        existing["sources"].add(candidate.source_filename)
        if candidate.score > existing["score"]:
            existing["text"] = candidate.text
            existing["score"] = candidate.score

    lines = ["# Reference Facts", ""]
    for category, _facts in grouped.items():
        fact_records = sorted(
            clustered[category].values(),
            key=lambda item: (-len(item["sources"]), -item["score"], str(item["text"]).lower()),
        )[:120]
        if not fact_records:
            continue
        lines.append(f"## {category}")
        lines.append("")
        for record in fact_records:
            sources = sorted(record["sources"])
            lines.append(f"- {record['text']} [sources: {', '.join(sources)}]")
        lines.append("")
    return "\n".join(lines).strip()


def build_glossary(items: list[SourceKnowledge]) -> str:
    entries = OrderedDict()
    for item in items:
        for candidate in item.glossary_candidates:
            entries.setdefault(candidate.term, candidate.definition)
    if not entries:
        return ""
    lines = ["# Glossary", ""]
    for term, definition in entries.items():
        lines.append(f"## {term}")
        lines.append(definition)
        lines.append("")
    return "\n".join(lines).strip()


def build_procedures(items: list[SourceKnowledge]) -> str:
    groups = []
    seen_titles = set()
    for item in items:
        for candidate in item.procedure_candidates:
            key = (candidate.title.lower(), tuple(candidate.steps))
            if key in seen_titles:
                continue
            seen_titles.add(key)
            lines = [f"## {candidate.title}", "", f"Source: {candidate.source_filename}", ""]
            lines.extend(candidate.steps)
            groups.append("\n".join(lines).strip())
    return "\n\n".join(groups).strip()


def build_entities(items: list[SourceKnowledge]) -> str:
    return build_entities_markdown(items)


def build_knowledge_core_pages(items: list[SourceKnowledge], target_words: int = 1600) -> list[str]:
    return build_topic_pages(items, target_words=target_words)


def build_instructions(pack_name: str, included_files: list[str]) -> str:
    return _build_instructions(pack_name, included_files)


def build_file_guide(files: list[str]) -> str:
    return _build_file_guide(files)


def extract_entities(text: str) -> list[str]:
    entities = set(ENTITY_RE.findall(text))
    entities.update(match.group(1) for match in PART_RE.finditer(text))
    return sorted(entities)[:300]


def extract_warnings(text: str) -> list[str]:
    warnings: list[str] = []
    for sentence in split_sentences(text):
        if WARNING_RE.search(sentence):
            warnings.append(sentence.strip())
    return dedupe_text_blocks(warnings)[:200]


def _drop_obvious_noise(lines: list[str]) -> list[str]:
    cleaned = []
    blank_run = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
            continue
        blank_run = 0
        if re.fullmatch(r"(page\s+)?\d+", stripped, re.IGNORECASE):
            continue
        if re.search(r"\.{3,}\s*\d+$", stripped):
            continue
        if re.fullmatch(r"(?:[A-Za-z]\s+){4,}[A-Za-z]?", stripped):
            continue
        cleaned.append(stripped)
    return cleaned


def _merge_wrapped_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for line in lines:
        if not merged or not line:
            merged.append(line)
            continue
        prev = merged[-1]
        if _should_preserve_line_boundary(prev, line):
            merged.append(line)
            continue
        merged[-1] = f"{prev} {line}".strip()
    return merged


def _should_preserve_line_boundary(prev: str, line: str) -> bool:
    if prev.endswith((".", ":", ";", "?", "!")):
        return True
    if re.match(r"^#{1,6}\s+", prev) or re.match(r"^#{1,6}\s+", line):
        return True
    if re.match(r"^\d+[\.)]\s+", line):
        return True
    if _looks_definition_line(prev) or _looks_definition_line(line):
        return True
    if _looks_short_term_line(prev) or _looks_short_term_line(line):
        return True
    return False


def _looks_definition_line(text: str) -> bool:
    return bool(
        re.match(r"^\s*[A-Z][A-Za-z0-9 /()_-]{1,60}\s*(?::|-)\s+.+$", text)
        or re.match(
            r"^\s*[A-Z][A-Za-z0-9 /()_-]{1,60}\s+(means|refers to|is defined as|defined as|is)\s+.+$",
            text,
            re.IGNORECASE,
        )
    )


def _looks_short_term_line(text: str) -> bool:
    stripped = text.strip()
    return bool(re.fullmatch(r"[A-Z][A-Z0-9 /()_-]{1,30}", stripped) and len(stripped.split()) <= 4)


def _candidate_from_glossary(candidate, item: SourceKnowledge) -> KnowledgeCandidate:
    return KnowledgeCandidate(
        target_type="glossary",
        title=candidate.term,
        body=candidate.definition,
        score=candidate.score,
        reasons=["Promoted glossary definition."],
        provenance={"source_filename": item.source_filename, "source_path": str(item.source_path), "section_heading": candidate.heading},
        normalized_key=f"glossary::{candidate.term.lower()}",
        source_document_id=item.document_id,
        source_chunk_id=candidate.chunk_id,
    )


def _candidate_from_procedure(candidate, item: SourceKnowledge) -> KnowledgeCandidate:
    return KnowledgeCandidate(
        target_type="procedures",
        title=candidate.title,
        body="\n".join(candidate.steps),
        score=candidate.score,
        reasons=["Promoted procedure with validated step sequence."],
        provenance={"source_filename": item.source_filename, "source_path": str(item.source_path), "section_heading": candidate.heading},
        normalized_key=f"procedure::{candidate.title.lower()}",
        source_document_id=item.document_id,
        source_chunk_id=candidate.chunk_id,
    )


def _candidate_from_fact(candidate, item: SourceKnowledge) -> KnowledgeCandidate:
    return KnowledgeCandidate(
        target_type="reference_facts",
        title=candidate.category,
        body=candidate.text,
        score=candidate.score,
        reasons=["Promoted high-precision fact."],
        provenance={"source_filename": item.source_filename, "source_path": str(item.source_path), "section_heading": candidate.heading},
        normalized_key=f"fact::{candidate.text.lower()}",
        source_document_id=item.document_id,
        source_chunk_id=candidate.chunk_id,
    )


def _candidate_from_topic(candidate, item: SourceKnowledge) -> KnowledgeCandidate:
    return KnowledgeCandidate(
        target_type="knowledge_core",
        title=candidate.topic_label,
        body=candidate.text,
        score=candidate.score,
        reasons=["Promoted topic evidence for synthesized knowledge core."],
        provenance={"source_filename": item.source_filename, "source_path": str(item.source_path), "section_heading": candidate.heading},
        normalized_key=f"topic::{candidate.topic_key}::{candidate.chunk_id}",
        source_document_id=item.document_id,
        source_chunk_id=candidate.chunk_id,
    )


def _promoted_from_glossary(candidate) -> PromotedKnowledgeItem:
    return PromotedKnowledgeItem(
        target_type="glossary",
        title=candidate.term,
        body=candidate.definition,
        supporting_sources=[candidate.source_filename],
        provenance_summary=[f"{candidate.source_filename}::{candidate.chunk_id}"],
        confidence=candidate.score,
    )


def _promoted_from_procedure(candidate) -> PromotedKnowledgeItem:
    return PromotedKnowledgeItem(
        target_type="procedures",
        title=candidate.title,
        body="\n".join(candidate.steps),
        supporting_sources=[candidate.source_filename],
        provenance_summary=[f"{candidate.source_filename}::{candidate.chunk_id}"],
        confidence=candidate.score,
    )


def _promoted_from_fact(candidate) -> PromotedKnowledgeItem:
    return PromotedKnowledgeItem(
        target_type="reference_facts",
        title=candidate.category,
        body=candidate.text,
        supporting_sources=[candidate.source_filename],
        provenance_summary=[f"{candidate.source_filename}::{candidate.chunk_id}"],
        confidence=candidate.score,
    )


def _promoted_from_topic(candidate) -> PromotedKnowledgeItem:
    return PromotedKnowledgeItem(
        target_type="knowledge_core",
        title=candidate.topic_label,
        body=candidate.text,
        supporting_sources=[candidate.source_filename],
        provenance_summary=[f"{candidate.source_filename}::{candidate.chunk_id}"],
        confidence=candidate.score,
    )
