from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class TaxonomyRule:
    pattern: str
    gpt_purpose: str
    topic: str


@dataclass(slots=True)
class Defaults:
    gpt_purpose: str
    topic: str
    language: str = "en"


@dataclass(slots=True)
class OCRConfig:
    enabled: bool = False
    engine: str = "tesseract"
    threshold: float = 0.45


@dataclass(slots=True)
class ChunkingConfig:
    target_words: int = 800
    overlap_words: int = 120
    min_words: int = 250


@dataclass(slots=True)
class OutputsConfig:
    write_chunks: bool = True
    write_structured_data: bool = True
    write_manifests: bool = True
    write_raw_text: bool = True
    write_clean_docs: bool = True
    write_root_markdown: bool = True


@dataclass(slots=True)
class ExtractionConfig:
    preserve_page_numbers: bool = False
    detect_tables: bool = True
    detect_parts: bool = True
    detect_requirements: bool = True
    remove_repeated_headers: bool = True


@dataclass(slots=True)
class PerformanceConfig:
    max_workers: int = 4
    skip_large_files_mb: int = 0


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"


@dataclass(slots=True)
class Config:
    input_roots: list[Path]
    output_root: Path
    include_globs: list[str]
    exclude_globs: list[str]
    taxonomy_rules: list[TaxonomyRule]
    defaults: Defaults
    ocr: OCRConfig = field(default_factory=OCRConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    outputs: OutputsConfig = field(default_factory=OutputsConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


@dataclass(slots=True)
class SourceDocument:
    path: Path
    root: Path
    doc_type: str
    checksum: str
    modified_at: datetime
    size_bytes: int = 0


@dataclass(slots=True)
class PageText:
    page_number: int
    text: str
    ocr_used: bool = False
    ocr_confidence: float | None = None
    is_scanned: bool = False


@dataclass(slots=True)
class ExtractedContent:
    text: str
    title: str | None = None
    doc_date: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    pages: list[PageText] = field(default_factory=list)
    extraction_method: str = "unknown"
    ocr_used: bool = False
    extraction_status: str = "success"
    fallback_chain: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failure_reason: str | None = None
    quality_score: float = 1.0
    preview_excerpt: str = ""


@dataclass(slots=True)
class KnowledgeMetadata:
    source_path: str
    source_type: str
    checksum: str
    extracted_at: str
    doc_date: str
    gpt_purpose: str
    topic: str
    title: str
    language: str
    source_root: str


@dataclass(slots=True)
class CanonicalNameParts:
    gpt_purpose: str
    doc_type: str
    topic: str
    source: str
    doc_date_or_nodate: str
    sha8: str

    def to_filename(self) -> str:
        return (
            f"{self.gpt_purpose}__{self.doc_type}__{self.topic}__"
            f"{self.source}__{self.doc_date_or_nodate}__{self.sha8}.md"
        )


@dataclass(slots=True)
class ManifestRecord:
    source_path: str
    checksum: str
    output_file: str
    canonical_name: str
    last_updated: str


@dataclass(slots=True)
class DocumentProfile:
    probable_domain: str
    document_kind: str
    language: str
    extraction_method: str
    extraction_quality_score: float
    ocr_used: bool
    mostly_tabular: bool
    page_count: int
    word_count: int
    quality_flags: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentRecord:
    doc_id: str
    source_path: str
    source_filename: str
    source_sha256: str
    document_type: str
    title: str
    doc_date: str
    topic: str
    gpt_purpose: str
    extraction_method: str
    extraction_quality_score: float
    ocr_used: bool
    output_markdown_file: str
    chunk_count: int
    processing_status: str
    probable_domain: str = "general"
    document_kind: str = "document"
    language: str = "en"
    mostly_tabular: bool = False
    quality_flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ChunkRecord:
    doc_id: str
    chunk_id: str
    source_path: str
    source_filename: str
    source_sha256: str
    title: str
    document_type: str
    gpt_purpose: str
    topic_tags: list[str]
    language: str
    page_start: int | None
    page_end: int | None
    section_path: list[str]
    chunk_index: int
    chunk_word_count: int
    text: str
    extraction_method: str
    extraction_quality_score: float
    ocr_used: bool
    contains_table: bool
    contains_requirements: bool
    contains_definitions: bool
    contains_parts_data: bool


@dataclass(slots=True)
class ProcessingFailure:
    source_path: str
    error: str
    document_type: str
    checksum: str | None = None
