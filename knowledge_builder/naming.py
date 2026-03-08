from __future__ import annotations

import re
from pathlib import Path

from .models import CanonicalNameParts, KnowledgeMetadata, SourceDocument
from .utils import detect_date_from_filename, slugify


CANONICAL_RE = re.compile(
    r"^[a-z0-9-]+__[a-z0-9-]+__[a-z0-9-]+__[a-z0-9-]+__(\d{8}|nodate)__[a-f0-9]{8}\.md$"
)


def build_canonical_name(source: SourceDocument, metadata: KnowledgeMetadata) -> CanonicalNameParts:
    source_stem = slugify(Path(source.path.name).stem, max_len=50)
    doc_date = _normalize_doc_date(metadata.doc_date)
    return CanonicalNameParts(
        gpt_purpose=slugify(metadata.gpt_purpose, max_len=40),
        doc_type=slugify(source.doc_type, max_len=30),
        topic=slugify(metadata.topic, max_len=40),
        source=source_stem,
        doc_date_or_nodate=doc_date,
        sha8=source.checksum[:8],
    )


def canonical_filename(source: SourceDocument, metadata: KnowledgeMetadata) -> str:
    return build_canonical_name(source, metadata).to_filename()


def make_safe_corpus_name(value: str) -> str:
    return slugify(value, max_len=80).replace("-", "_") or "knowledge_pack"


def is_canonical_filename(name: str) -> bool:
    return bool(CANONICAL_RE.fullmatch(name))


def choose_doc_date(raw_doc_date: str | None, filename: str) -> str:
    if raw_doc_date:
        normalized = _normalize_doc_date(raw_doc_date)
        if normalized != "nodate":
            return normalized
    from_name = detect_date_from_filename(filename)
    return from_name or "nodate"


def _normalize_doc_date(value: str | None) -> str:
    if not value:
        return "nodate"
    only_digits = "".join(ch for ch in value if ch.isdigit())
    if len(only_digits) == 8 and only_digits.startswith("20"):
        return only_digits
    return "nodate"
