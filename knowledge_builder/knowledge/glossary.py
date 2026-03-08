from __future__ import annotations

import re

from ..compiler_models import GlossaryCandidate, KnowledgeCandidate, KnowledgeChunk
from ..utils import slugify
from .common import dedupe_glossary, is_low_value_promotion_chunk, looks_like_clean_term, score_glossary_candidate


TERM_DEF_PATTERNS = [
    re.compile(r"^\s*([A-Z][A-Za-z0-9 /()_-]{1,60})\s*:\s+(.+)$"),
    re.compile(r"^\s*([A-Z][A-Za-z0-9 /()_-]{1,60})\s+-\s+(.+)$"),
    re.compile(r"^\s*([A-Z][A-Za-z0-9 /()_-]{1,60})\s+means\s+(.+)$", re.IGNORECASE),
    re.compile(r"^\s*([A-Z][A-Za-z0-9 /()_-]{1,60})\s+refers to\s+(.+)$", re.IGNORECASE),
    re.compile(r"^\s*([A-Z][A-Za-z0-9 /()_-]{1,60})\s+is defined as\s+(.+)$", re.IGNORECASE),
]
ACRONYM_EXPANSION_RE = re.compile(r"^\s*([A-Z0-9/-]{2,12})\s*[-:]\s*([A-Z][A-Za-z0-9 ,()/_-]{4,120})$")
GENERIC_GLOSSARY_TERM_RE = re.compile(r"^(?:description|legal|option\s+\d+|lat|site|number|job number|site number)$", re.IGNORECASE)


def extract_glossary_candidates(chunks: list[KnowledgeChunk], threshold: float = 0.45) -> list[GlossaryCandidate]:
    accepted, _rejected = inspect_glossary_candidates(chunks, threshold=threshold)
    return accepted


def inspect_glossary_candidates(
    chunks: list[KnowledgeChunk],
    threshold: float = 0.45,
) -> tuple[list[GlossaryCandidate], list[KnowledgeCandidate]]:
    candidates: list[GlossaryCandidate] = []
    rejected: list[KnowledgeCandidate] = []
    for chunk in chunks:
        if is_low_value_promotion_chunk(chunk.text):
            continue
        for line in chunk.text.splitlines():
            stripped = line.strip()
            matched = False
            for pattern in TERM_DEF_PATTERNS:
                match = pattern.match(stripped)
                if not match:
                    continue
                term = match.group(1).strip()
                definition = match.group(2).strip()
                matched = True
                if GENERIC_GLOSSARY_TERM_RE.fullmatch(term) or not looks_like_clean_term(term):
                    rejected.append(
                        KnowledgeCandidate(
                            target_type="glossary",
                            title=term,
                            body=definition,
                            score=0.0,
                            reasons=["Matched glossary pattern but term text was not clean enough to promote."],
                            provenance={
                                "source_filename": chunk.source_filename,
                                "source_path": chunk.source_path,
                                "section_heading": chunk.heading,
                            },
                            normalized_key=slugify(term, 120),
                            source_document_id=chunk.document_id,
                            source_chunk_id=chunk.chunk_id,
                            rejection_reason="unclean_term",
                        )
                    )
                    break
                score = score_glossary_candidate(term, definition, chunk)
                if score >= threshold:
                    candidates.append(
                        GlossaryCandidate(
                            term=term,
                            definition=definition,
                            score=score,
                            source_filename=chunk.source_filename,
                            chunk_id=chunk.chunk_id,
                            heading=chunk.heading,
                        )
                    )
                else:
                    rejected.append(
                        KnowledgeCandidate(
                            target_type="glossary",
                            title=term,
                            body=definition,
                            score=score,
                            reasons=["Matched definitional pattern but failed quality threshold."],
                            provenance={
                                "source_filename": chunk.source_filename,
                                "source_path": chunk.source_path,
                                "section_heading": chunk.heading,
                            },
                            normalized_key=slugify(term, 120),
                            source_document_id=chunk.document_id,
                            source_chunk_id=chunk.chunk_id,
                            rejection_reason="below_threshold",
                        )
                    )
                break
            if matched:
                continue
            acronym_match = ACRONYM_EXPANSION_RE.match(stripped)
            if not acronym_match:
                continue
            term = acronym_match.group(1).strip()
            definition = acronym_match.group(2).strip()
            if GENERIC_GLOSSARY_TERM_RE.fullmatch(term) or not looks_like_clean_term(term):
                continue
            score = score_glossary_candidate(term, definition, chunk)
            if score >= threshold:
                candidates.append(
                    GlossaryCandidate(
                        term=term,
                        definition=definition,
                        score=score,
                        source_filename=chunk.source_filename,
                        chunk_id=chunk.chunk_id,
                        heading=chunk.heading,
                    )
                )
            else:
                rejected.append(
                    KnowledgeCandidate(
                        target_type="glossary",
                        title=term,
                        body=definition,
                        score=score,
                        reasons=["Matched acronym expansion pattern but failed quality threshold."],
                        provenance={
                            "source_filename": chunk.source_filename,
                            "source_path": chunk.source_path,
                            "section_heading": chunk.heading,
                        },
                        normalized_key=slugify(term, 120),
                        source_document_id=chunk.document_id,
                        source_chunk_id=chunk.chunk_id,
                        rejection_reason="below_threshold",
                    )
                )
    return dedupe_glossary(candidates), rejected
