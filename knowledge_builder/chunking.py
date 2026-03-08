from __future__ import annotations

import re

from .models import ChunkRecord, Config, DocumentRecord, ExtractedContent
from .utils import slugify, word_count


HEADING_RE = re.compile(r"^(#{1,6}\s+.+|\d+(\.\d+){0,4}\s+.+|[A-Z][A-Z0-9\s/&,-]{5,})$")


def build_chunks(
    doc: DocumentRecord,
    content: ExtractedContent,
    config: Config,
) -> list[ChunkRecord]:
    segments = _segment_document(content)
    target_words = config.chunking.target_words
    overlap_words = min(config.chunking.overlap_words, max(target_words // 2, 0))
    min_words = config.chunking.min_words

    chunks: list[ChunkRecord] = []
    buffer_texts: list[str] = []
    buffer_words = 0
    buffer_pages: list[int] = []
    buffer_sections: list[str] = []

    for segment in segments:
        segment_words = word_count(segment["text"])
        if buffer_texts and buffer_words >= min_words and buffer_words + segment_words > target_words:
            chunks.append(
                _make_chunk(
                    doc=doc,
                    content=content,
                    chunk_index=len(chunks),
                    texts=buffer_texts,
                    pages=buffer_pages,
                    sections=buffer_sections,
                )
            )
            overlap_text = _tail_words(" ".join(buffer_texts), overlap_words)
            buffer_texts = [overlap_text] if overlap_text else []
            buffer_words = word_count(overlap_text)
            buffer_pages = buffer_pages[-2:] if buffer_pages else []
            buffer_sections = buffer_sections[-1:] if buffer_sections else []

        buffer_texts.append(segment["text"])
        buffer_words += segment_words
        buffer_pages.extend(segment["pages"])
        if segment["section"]:
            buffer_sections.append(segment["section"])

    if buffer_texts:
        chunks.append(
            _make_chunk(
                doc=doc,
                content=content,
                chunk_index=len(chunks),
                texts=buffer_texts,
                pages=buffer_pages,
                sections=buffer_sections,
            )
        )
    return chunks


def _segment_document(content: ExtractedContent) -> list[dict]:
    segments: list[dict] = []
    current_section = ""

    pages = content.pages or []
    if not pages and content.text.strip():
        pages = []
        for idx, block in enumerate(content.text.split("\f"), start=1):
            if block.strip():
                pages.append(type("PageTextLike", (), {"page_number": idx, "text": block})())

    for page in pages:
        paragraphs = [p.strip() for p in page.text.split("\n\n") if p.strip()]
        for paragraph in paragraphs:
            first_line = paragraph.splitlines()[0].strip()
            if HEADING_RE.match(first_line):
                current_section = first_line.lstrip("# ").strip()
            segments.append({"text": paragraph, "pages": [page.page_number], "section": current_section})

    if not segments and content.text.strip():
        for paragraph in [p.strip() for p in content.text.split("\n\n") if p.strip()]:
            segments.append({"text": paragraph, "pages": [], "section": current_section})
    return segments


def _make_chunk(
    doc: DocumentRecord,
    content: ExtractedContent,
    chunk_index: int,
    texts: list[str],
    pages: list[int],
    sections: list[str],
) -> ChunkRecord:
    text = "\n\n".join(part for part in texts if part.strip()).strip()
    page_values = sorted(set(page for page in pages if page))
    section_path = [section for section in sections if section]
    return ChunkRecord(
        doc_id=doc.doc_id,
        chunk_id=f"{doc.doc_id}::chunk-{chunk_index:04d}",
        source_path=doc.source_path,
        source_filename=doc.source_filename,
        source_sha256=doc.source_sha256,
        title=doc.title,
        document_type=doc.document_type,
        gpt_purpose=doc.gpt_purpose,
        topic_tags=[doc.topic, doc.probable_domain, doc.document_kind],
        language=doc.language,
        page_start=page_values[0] if page_values else None,
        page_end=page_values[-1] if page_values else None,
        section_path=section_path,
        chunk_index=chunk_index,
        chunk_word_count=word_count(text),
        text=text,
        extraction_method=doc.extraction_method,
        extraction_quality_score=doc.extraction_quality_score,
        ocr_used=doc.ocr_used,
        contains_table=" | " in text or "\t" in text,
        contains_requirements=bool(re.search(r"\b(shall|must|required|shall not|must not)\b", text, re.IGNORECASE)),
        contains_definitions=bool(re.search(r"\bmeans\b|\bdefined as\b", text, re.IGNORECASE)),
        contains_parts_data=bool(re.search(r"\b(?:PN|P/N|Part|Model|SKU)\b", text, re.IGNORECASE)),
    )


def _tail_words(text: str, overlap_words: int) -> str:
    if overlap_words <= 0:
        return ""
    words = text.split()
    if not words:
        return ""
    return " ".join(words[-overlap_words:]).strip()
