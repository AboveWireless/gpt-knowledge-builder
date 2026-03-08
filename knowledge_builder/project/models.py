from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EXPORT_PROFILES = {
    "custom-gpt-balanced",
    "custom-gpt-max-traceability",
    "debug-research",
}

DOCUMENT_PRESETS = {
    "business-sops",
    "product-docs",
    "policies-contracts",
    "course-training",
    "mixed-office-documents",
}


@dataclass(slots=True)
class ModelSettings:
    enabled: bool = False
    provider: str = "openai"
    model: str = "gpt-5.4"
    prompt_version: str = "v1"


@dataclass(slots=True)
class ReviewThresholds:
    low_signal_word_count: int = 60
    duplicate_similarity_threshold: float = 0.96
    low_confidence_threshold: float = 0.55


@dataclass(slots=True)
class ProjectConfig:
    version: int
    project_name: str
    source_roots: list[str]
    output_root: str
    preset: str = "mixed-office-documents"
    export_profile: str = "custom-gpt-balanced"
    include_globs: list[str] = field(
        default_factory=lambda: ["**/*.pdf", "**/*.docx", "**/*.txt", "**/*.md", "**/*.html", "**/*.htm", "**/*.xlsx", "**/*.pptx", "**/*.csv"]
    )
    exclude_globs: list[str] = field(default_factory=lambda: ["**/~$*", "**/.~*"])
    optional_model_settings: ModelSettings = field(default_factory=ModelSettings)
    review_thresholds: ReviewThresholds = field(default_factory=ReviewThresholds)
    taxonomy_presets: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentFingerprint:
    source_path: str
    checksum: str
    size_bytes: int
    modified_at: str


@dataclass(slots=True)
class ExtractionResult:
    doc_id: str
    source_path: str
    document_type: str
    title: str
    raw_text_path: str
    clean_text_path: str
    extraction_method: str
    ocr_used: bool
    word_count: int
    chunk_count: int
    empty_reason: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CorpusDocument:
    doc_id: str
    source_path: str
    source_filename: str
    source_root: str
    document_type: str
    checksum: str
    title: str
    clean_text_path: str
    raw_text_path: str
    extraction_method: str
    ocr_used: bool
    word_count: int
    chunk_count: int
    probable_domain: str
    review_status: str = "clean"
    empty_reason: str | None = None
    duplicate_of: str | None = None
    knowledge_item_count: int = 0
    updated_at: str = ""
    enrichment_cache_key: str = ""


@dataclass(slots=True)
class ReviewItem:
    review_id: str
    doc_id: str
    kind: str
    severity: str
    status: str
    title: str
    detail: str
    suggestion: str
    confidence: float
    created_at: str
    updated_at: str
    override_title: str = ""
    override_domain: str = ""
    resolution_note: str = ""


@dataclass(slots=True)
class KnowledgeArtifact:
    artifact_id: str
    artifact_type: str
    title: str
    body: str
    confidence: float
    supporting_sources: list[str] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ExportPackage:
    package_dir: str
    profile: str
    written_files: list[str]
    package_index_file: str
    provenance_manifest: str
    validation_messages: list[str] = field(default_factory=list)
