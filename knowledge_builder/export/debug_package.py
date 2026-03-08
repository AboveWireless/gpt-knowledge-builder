from __future__ import annotations

import shutil
from pathlib import Path

from ..compiler_models import SourceKnowledge
from ..naming import make_safe_corpus_name
from ..utils import append_log, ensure_dir


def write_debug_package(
    output_dir: Path,
    corpus_name: str,
    items: list[SourceKnowledge],
    processed_documents: int,
    failed_documents: int,
) -> Path:
    safe_corpus_name = make_safe_corpus_name(corpus_name)
    debug_dir = output_dir / f"{safe_corpus_name}_DEBUG"
    shutil.rmtree(debug_dir, ignore_errors=True)

    extracted_dir = debug_dir / "extracted"
    normalized_dir = debug_dir / "normalized"
    chunks_dir = debug_dir / "chunks"
    accepted_dir = debug_dir / "promotion_candidates"
    rejected_dir = debug_dir / "rejected_candidates"
    evidence_dir = debug_dir / "evidence_maps"
    logs_dir = debug_dir / "logs"

    for path in (extracted_dir, normalized_dir, chunks_dir, accepted_dir, rejected_dir, evidence_dir, logs_dir):
        ensure_dir(path)

    for item in items:
        stem = make_safe_corpus_name(item.source_path.stem)
        (extracted_dir / f"{stem}.txt").write_text(item.raw_text, encoding="utf-8")
        (normalized_dir / f"{stem}.txt").write_text(item.clean_text, encoding="utf-8")
        (chunks_dir / f"{stem}.md").write_text(_render_chunks(item), encoding="utf-8")
        (accepted_dir / f"{stem}.md").write_text(_render_candidates(item.accepted_candidates, title="Accepted Candidates"), encoding="utf-8")
        (rejected_dir / f"{stem}.md").write_text(_render_candidates(item.rejected_candidates, title="Rejected Candidates"), encoding="utf-8")
        (evidence_dir / f"{stem}.md").write_text(_render_evidence_map(item), encoding="utf-8")

    quality_report = debug_dir / "quality_report.txt"
    quality_report.write_text(_render_quality_report(items, processed_documents, failed_documents), encoding="utf-8")
    append_log(logs_dir / "pipeline.log", f"debug package written for {corpus_name}")
    return debug_dir


def _render_chunks(item: SourceKnowledge) -> str:
    lines = [f"# Chunks: {item.source_filename}", ""]
    for chunk in item.chunks:
        lines.append(f"## {chunk.chunk_id}")
        lines.append(f"- heading: {chunk.heading or item.title}")
        lines.append(f"- section_path: {' > '.join(chunk.section_path)}")
        if chunk.page_start is not None:
            lines.append(f"- pages: {chunk.page_start}-{chunk.page_end or chunk.page_start}")
        lines.append("")
        lines.append(chunk.text.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_candidates(candidates, title: str) -> str:
    lines = [f"# {title}", ""]
    if not candidates:
        lines.append("No candidates recorded.")
        return "\n".join(lines) + "\n"
    for candidate in candidates:
        lines.append(f"## {candidate.target_type}: {candidate.title}")
        lines.append(f"- score: {candidate.score}")
        lines.append(f"- reasons: {', '.join(candidate.reasons) if candidate.reasons else 'n/a'}")
        if candidate.rejection_reason:
            lines.append(f"- rejection: {candidate.rejection_reason}")
        lines.append(f"- source_chunk_id: {candidate.source_chunk_id or 'document'}")
        lines.append("")
        lines.append(candidate.body)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_evidence_map(item: SourceKnowledge) -> str:
    lines = [f"# Evidence Map: {item.source_filename}", ""]
    if not item.promoted_items:
        lines.append("No promoted items.")
        return "\n".join(lines) + "\n"
    for promoted in item.promoted_items:
        lines.append(f"## {promoted.target_type}: {promoted.title}")
        lines.append(f"- confidence: {promoted.confidence}")
        lines.append(f"- support: {', '.join(promoted.supporting_sources)}")
        lines.append(f"- provenance: {', '.join(promoted.provenance_summary)}")
        lines.append("")
        lines.append(promoted.body)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_quality_report(items: list[SourceKnowledge], processed_documents: int, failed_documents: int) -> str:
    glossary_kept = sum(len(item.glossary_candidates) for item in items)
    procedures_kept = sum(len(item.procedure_candidates) for item in items)
    facts_kept = sum(len(item.fact_candidates) for item in items)
    topics_kept = sum(len(item.topic_candidates) for item in items)
    accepted = sum(len(item.accepted_candidates) for item in items)
    rejected = sum(len(item.rejected_candidates) for item in items)
    ocr_empty = sum(1 for item in items if item.empty_reason == "ocr_empty")
    chunks = sum(len(item.chunks) for item in items)
    dedupe_ratio = 0.0 if accepted == 0 else round(max(accepted - len({candidate.normalized_key for item in items for candidate in item.accepted_candidates}), 0) / accepted, 3)

    return "\n".join(
        [
            "GPT Knowledge Debug Quality Report",
            "",
            f"documents_processed: {processed_documents}",
            f"documents_failed: {failed_documents}",
            f"ocr_empty_results: {ocr_empty}",
            f"chunks_produced: {chunks}",
            f"glossary_candidates_kept: {glossary_kept}",
            f"procedure_candidates_kept: {procedures_kept}",
            f"fact_candidates_kept: {facts_kept}",
            f"knowledge_core_candidates_kept: {topics_kept}",
            f"accepted_candidates: {accepted}",
            f"rejected_candidates: {rejected}",
            f"dedupe_ratio: {dedupe_ratio}",
            "",
            "low_confidence_warnings:",
            *[
                f"- {item.source_filename}: {item.empty_reason or 'low-signal or OCR-sensitive source'}"
                for item in items
                if item.empty_reason or item.ocr_used
            ],
        ]
    ).strip() + "\n"
