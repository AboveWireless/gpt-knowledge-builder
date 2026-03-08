from __future__ import annotations

import re

from ..compiler_models import FactCandidate, KnowledgeCandidate, KnowledgeChunk
from ..utils import slugify
from .common import dedupe_facts, normalize_fact_sentence, score_fact_candidate, split_candidate_sentences


FACT_SIGNAL_RE = re.compile(
    r"\b(shall|must|required|shall not|must not|prohibited|warning|caution|danger|[A-Z]{2,}[A-Z0-9-/.]*|20\d{2}|\d+(?:\.\d+)?\s?(?:V|A|W|Hz|mm|cm|m|ft|in|lb|psi|N|Nm|%))\b",
    re.IGNORECASE,
)
ATOMIC_FACT_RE = re.compile(r"^[^|]{0,240}$")


def extract_fact_candidates(chunks: list[KnowledgeChunk], threshold: float = 0.45) -> list[FactCandidate]:
    accepted, _rejected = inspect_fact_candidates(chunks, threshold=threshold)
    return accepted


def inspect_fact_candidates(
    chunks: list[KnowledgeChunk],
    threshold: float = 0.45,
) -> tuple[list[FactCandidate], list[KnowledgeCandidate]]:
    candidates: list[FactCandidate] = []
    rejected: list[KnowledgeCandidate] = []
    for chunk in chunks:
        for sentence in split_candidate_sentences(chunk):
            if not FACT_SIGNAL_RE.search(sentence):
                continue
            normalized = normalize_fact_sentence(sentence)
            if not _looks_atomic_fact(normalized):
                rejected.append(
                    KnowledgeCandidate(
                        target_type="reference_facts",
                        title="facts",
                        body=normalized,
                        score=0.0,
                        reasons=["Fact-like text was rejected because it was too long, too mixed, or too metadata-heavy to be an atomic fact."],
                        provenance={
                            "source_filename": chunk.source_filename,
                            "source_path": chunk.source_path,
                            "section_heading": chunk.heading,
                        },
                        normalized_key=slugify(normalized, 200),
                        source_document_id=chunk.document_id,
                        source_chunk_id=chunk.chunk_id,
                        rejection_reason="non_atomic_fact",
                    )
                )
                continue
            score = score_fact_candidate(normalized, chunk)
            if score >= threshold:
                candidates.append(
                    FactCandidate(
                        text=normalized,
                        score=score,
                        source_filename=chunk.source_filename,
                        chunk_id=chunk.chunk_id,
                        heading=chunk.heading,
                        category=_classify_fact(normalized),
                    )
                )
            else:
                rejected.append(
                    KnowledgeCandidate(
                        target_type="reference_facts",
                        title=_classify_fact(normalized),
                        body=normalized,
                        score=score,
                        reasons=["Fact signal detected but statement failed fact quality threshold."],
                        provenance={
                            "source_filename": chunk.source_filename,
                            "source_path": chunk.source_path,
                            "section_heading": chunk.heading,
                        },
                        normalized_key=slugify(normalized, 200),
                        source_document_id=chunk.document_id,
                        source_chunk_id=chunk.chunk_id,
                        rejection_reason="below_threshold",
                    )
                )
    return dedupe_facts(candidates), rejected


def _classify_fact(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("shall", "must", "required", "prohibited")):
        return "requirements"
    if re.search(r"\b20\d{2}\b", text):
        return "dates"
    if re.search(r"\b(?:ansi|tia|osha|bicsi|ieee|iso|iec)\b", lowered):
        return "standards"
    if re.search(r"\b\d+(?:\.\d+)?\s?(?:v|a|w|hz|mm|cm|m|ft|in|lb|psi|n|nm|%)\b", lowered):
        return "values"
    return "facts"


def _looks_atomic_fact(text: str) -> bool:
    if not ATOMIC_FACT_RE.fullmatch(text):
        return False
    if len(text) > 220:
        return False
    if text.count("|") >= 1:
        return False
    if text.count(",") >= 4 and ":" in text:
        return False
    if re.search(r"(?:https?://|www\.|[A-Za-z]:\\)", text):
        return False
    if re.search(r"(?:\.\\|\\{2,}|//|/\w+/)", text):
        return False
    if re.search(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", text):
        return False
    if re.search(r"\b(?:site number|job number|project #|description|legal)\b", text, re.IGNORECASE):
        return False
    if re.search(r"\b(?:contractor shall coordinate|drawings are diagrammatic only|verify field conditions|unless otherwise noted)\b", text, re.IGNORECASE):
        return False
    return True
