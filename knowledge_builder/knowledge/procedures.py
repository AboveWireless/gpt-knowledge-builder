from __future__ import annotations

import re

from ..compiler_models import KnowledgeCandidate, KnowledgeChunk, ProcedureCandidate
from ..utils import slugify
from .common import IMPERATIVE_RE, PROCEDURE_HEADING_RE, is_low_value_promotion_chunk, score_procedure_candidate


STEP_RE = re.compile(r"^\d+[\.)]\s+.+$")


def extract_procedure_candidates(chunks: list[KnowledgeChunk], threshold: float = 0.5) -> list[ProcedureCandidate]:
    accepted, _rejected = inspect_procedure_candidates(chunks, threshold=threshold)
    return accepted


def inspect_procedure_candidates(
    chunks: list[KnowledgeChunk],
    threshold: float = 0.5,
) -> tuple[list[ProcedureCandidate], list[KnowledgeCandidate]]:
    candidates: list[ProcedureCandidate] = []
    rejected: list[KnowledgeCandidate] = []
    for chunk in chunks:
        if is_low_value_promotion_chunk(chunk.text):
            continue
        steps = [line.strip() for line in chunk.text.splitlines() if STEP_RE.match(line.strip())]
        normalized_steps = _normalize_steps(steps)
        if len(normalized_steps) < 2:
            if steps:
                rejected.append(
                    KnowledgeCandidate(
                        target_type="procedures",
                        title=chunk.heading if chunk.heading and chunk.heading != chunk.title else f"{chunk.title} Procedure",
                        body="\n".join(steps),
                        score=0.0,
                        reasons=["Detected step-like lines but not enough usable steps remained after cleanup."],
                        provenance={
                            "source_filename": chunk.source_filename,
                            "source_path": chunk.source_path,
                            "section_heading": chunk.heading,
                        },
                        normalized_key=slugify(chunk.chunk_id, 160),
                        source_document_id=chunk.document_id,
                        source_chunk_id=chunk.chunk_id,
                        rejection_reason="insufficient_usable_steps",
                    )
                )
            continue
        title = chunk.heading if chunk.heading and chunk.heading != chunk.title else f"{chunk.title} Procedure"
        imperative_hits = sum(1 for step in normalized_steps if IMPERATIVE_RE.search(re.sub(r"^\d+[\.)]\s*", "", step).strip()))
        if imperative_hits == 0 and not PROCEDURE_HEADING_RE.search(title):
            rejected.append(
                KnowledgeCandidate(
                    target_type="procedures",
                    title=title,
                    body="\n".join(normalized_steps),
                    score=0.0,
                    reasons=["Step numbering alone was not enough; the content did not show strong procedural/instructional signals."],
                    provenance={
                        "source_filename": chunk.source_filename,
                        "source_path": chunk.source_path,
                        "section_heading": chunk.heading,
                    },
                    normalized_key=slugify(f"{title}-{chunk.chunk_id}", 180),
                    source_document_id=chunk.document_id,
                    source_chunk_id=chunk.chunk_id,
                    rejection_reason="weak_procedural_signal",
                )
            )
            continue
        score = score_procedure_candidate(title, normalized_steps, chunk)
        if score >= threshold:
            candidates.append(
                ProcedureCandidate(
                    title=title,
                    steps=normalized_steps,
                    score=score,
                    source_filename=chunk.source_filename,
                    chunk_id=chunk.chunk_id,
                    heading=chunk.heading,
                )
            )
        else:
            rejected.append(
                KnowledgeCandidate(
                    target_type="procedures",
                    title=title,
                    body="\n".join(normalized_steps),
                    score=score,
                    reasons=["Step sequence detected but failed procedural quality threshold."],
                    provenance={
                        "source_filename": chunk.source_filename,
                        "source_path": chunk.source_path,
                        "section_heading": chunk.heading,
                    },
                    normalized_key=slugify(f"{title}-{chunk.chunk_id}", 180),
                    source_document_id=chunk.document_id,
                    source_chunk_id=chunk.chunk_id,
                    rejection_reason="below_threshold",
                )
            )
    return sorted(candidates, key=lambda item: (-item.score, item.title.lower(), item.source_filename.lower())), rejected


def _normalize_steps(steps: list[str]) -> list[str]:
    normalized = []
    for step in steps:
        text = re.sub(r"^\d+[\.)]\s*", "", step).strip()
        if not _is_usable_step(text):
            continue
        if text and text[-1] not in ".;":
            text += "."
        normalized.append(text)
    return [f"{index}. {text}" for index, text in enumerate(normalized, start=1)]


def _is_usable_step(text: str) -> bool:
    if not text:
        return False
    if len(text.split()) < 2:
        return False
    if len(text.split()) < 3 and text[-1] not in ".;":
        return False
    return True
