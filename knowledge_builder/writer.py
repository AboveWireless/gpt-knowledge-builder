from __future__ import annotations

from pathlib import Path

from .models import DocumentProfile, KnowledgeMetadata
from .utils import normalize_unicode


def render_markdown(
    metadata: KnowledgeMetadata,
    text: str,
    profile: DocumentProfile | None = None,
    extraction_notes: list[str] | None = None,
) -> str:
    title = _display_title(metadata.title)
    body = _normalize_text(text)

    lines = [f"# {title}", ""]
    lines.extend(
        [
            "## Metadata",
            "",
            f"- Source file: {Path(metadata.source_path).name}",
            f"- Source path: {metadata.source_path}",
            f"- Document type: {metadata.source_type}",
            f"- GPT knowledge set: {metadata.gpt_purpose}",
            f"- Topic: {metadata.topic}",
        ]
    )
    if metadata.doc_date != "nodate":
        lines.append(f"- Document date: {metadata.doc_date}")
    if profile:
        lines.extend(
            [
                f"- Extraction method: {profile.extraction_method}",
                f"- Extraction quality score: {profile.extraction_quality_score}",
                f"- OCR used: {'yes' if profile.ocr_used else 'no'}",
                f"- Document kind: {profile.document_kind}",
                f"- Probable domain: {profile.probable_domain}",
                f"- Mostly tabular: {'yes' if profile.mostly_tabular else 'no'}",
            ]
        )
    if extraction_notes:
        lines.extend(["", "## Extraction Notes", ""])
        lines.extend(f"- {note}" for note in extraction_notes if note.strip())
    lines.extend(["", "## Content", "", body])
    return "\n".join(lines).strip() + "\n"


def write_markdown(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _display_title(title: str) -> str:
    raw = normalize_unicode(title).replace("-", " ").replace("_", " ").strip()
    return " ".join(raw.split()) or "Knowledge File"


def _normalize_text(text: str) -> str:
    cleaned = normalize_unicode(text).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    return cleaned.strip()
