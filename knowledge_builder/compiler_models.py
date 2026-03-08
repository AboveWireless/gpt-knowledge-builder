from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class BuildOptions:
    input_dir: Path
    output_dir: Path
    pack_name: str = ""
    zip_pack: bool = False
    debug_outputs: bool = False
    source_folder_name: str | None = None
    event_callback: Callable[[str, str], None] | None = None


@dataclass(slots=True)
class SourceKnowledge:
    document_id: str
    source_path: Path
    source_filename: str
    source_folder_name: str
    document_type: str
    title: str
    raw_text: str
    clean_text: str
    extraction_method: str = "unknown"
    ocr_used: bool = False
    chunks: list["KnowledgeChunk"] = field(default_factory=list)
    summary_points: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    glossary: list[tuple[str, str]] = field(default_factory=list)
    procedures: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    glossary_candidates: list["GlossaryCandidate"] = field(default_factory=list)
    procedure_candidates: list["ProcedureCandidate"] = field(default_factory=list)
    fact_candidates: list["FactCandidate"] = field(default_factory=list)
    topic_candidates: list["TopicCandidate"] = field(default_factory=list)
    accepted_candidates: list["KnowledgeCandidate"] = field(default_factory=list)
    rejected_candidates: list["KnowledgeCandidate"] = field(default_factory=list)
    promoted_items: list["PromotedKnowledgeItem"] = field(default_factory=list)
    empty_reason: str | None = None


@dataclass(slots=True)
class BuildResult:
    package_dir: Path
    zip_path: Path | None
    written_files: list[Path]
    corpus_name: str = ""
    source_folder_name: str = ""
    debug_dir: Path | None = None
    processed_documents: int = 0
    contributed_documents: int = 0
    failed_documents: int = 0


@dataclass(slots=True)
class BatchFolderResult:
    folder_name: str
    input_dir: Path
    success: bool
    corpus_name: str = ""
    package_dir: Path | None = None
    zip_path: Path | None = None
    debug_dir: Path | None = None
    processed_documents: int = 0
    contributed_documents: int = 0
    failed_documents: int = 0
    error: str | None = None


@dataclass(slots=True)
class BatchBuildResult:
    output_dir: Path
    summary_path: Path
    folder_results: list[BatchFolderResult]
    selected_folder_names: list[str] = field(default_factory=list)
    skipped_folder_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class KnowledgeChunk:
    chunk_id: str
    document_id: str
    source_path: str
    source_filename: str
    file_type: str
    title: str
    heading: str
    text: str
    extraction_method: str = "unknown"
    page_start: int | None = None
    page_end: int | None = None
    sheet_name: str | None = None
    row_range: str | None = None
    section_path: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GlossaryCandidate:
    term: str
    definition: str
    score: float
    source_filename: str
    chunk_id: str
    heading: str = ""


@dataclass(slots=True)
class ProcedureCandidate:
    title: str
    steps: list[str]
    score: float
    source_filename: str
    chunk_id: str
    heading: str = ""


@dataclass(slots=True)
class FactCandidate:
    text: str
    score: float
    source_filename: str
    chunk_id: str
    heading: str = ""
    category: str = "fact"


@dataclass(slots=True)
class TopicCandidate:
    topic_key: str
    topic_label: str
    text: str
    score: float
    source_filename: str
    chunk_id: str
    heading: str = ""


@dataclass(slots=True)
class KnowledgeCandidate:
    target_type: str
    title: str
    body: str
    score: float
    reasons: list[str]
    provenance: dict[str, str | int | None]
    normalized_key: str
    source_document_id: str
    source_chunk_id: str
    rejection_reason: str | None = None


@dataclass(slots=True)
class PromotedKnowledgeItem:
    target_type: str
    title: str
    body: str
    supporting_sources: list[str]
    provenance_summary: list[str]
    confidence: float
