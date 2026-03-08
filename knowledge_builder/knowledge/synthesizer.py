from __future__ import annotations

from collections import defaultdict

from ..compiler_models import KnowledgeCandidate, SourceKnowledge, TopicCandidate
from ..utils import slugify, word_count
from .common import (
    dedupe_text_blocks,
    is_admin_or_sheet_heading,
    is_low_value_promotion_chunk,
    normalize_promotion_text,
    score_topic_candidate,
    topic_key_from_chunk,
)


def extract_topic_candidates(items: list[SourceKnowledge], threshold: float = 0.4) -> list[TopicCandidate]:
    accepted, _rejected = inspect_topic_candidates(items, threshold=threshold)
    return accepted


def inspect_topic_candidates(
    items: list[SourceKnowledge],
    threshold: float = 0.4,
) -> tuple[list[TopicCandidate], list[KnowledgeCandidate]]:
    candidates: list[TopicCandidate] = []
    rejected: list[KnowledgeCandidate] = []
    for item in items:
        for chunk in item.chunks:
            if is_low_value_promotion_chunk(chunk.text):
                rejected.append(
                    KnowledgeCandidate(
                        target_type="knowledge_core",
                        title=chunk.heading or item.title,
                        body=normalize_promotion_text(chunk.text),
                        score=0.0,
                        reasons=["Chunk was dominated by drawing/title-block/administrative boilerplate and was excluded from topic synthesis."],
                        provenance={
                            "source_filename": chunk.source_filename,
                            "source_path": chunk.source_path,
                            "section_heading": chunk.heading,
                        },
                        normalized_key=slugify(f"boilerplate-{chunk.chunk_id}", 180),
                        source_document_id=chunk.document_id,
                        source_chunk_id=chunk.chunk_id,
                        rejection_reason="admin_boilerplate",
                    )
                )
                continue
            topic_key, topic_label = topic_key_from_chunk(chunk)
            normalized_text = normalize_promotion_text(chunk.text)
            if not normalized_text:
                continue
            if word_count(normalized_text) < 8:
                continue
            if is_admin_or_sheet_heading(topic_label) and word_count(normalized_text) < 12:
                rejected.append(
                    KnowledgeCandidate(
                        target_type="knowledge_core",
                        title=topic_label,
                        body=normalized_text,
                        score=0.0,
                        reasons=["Drawing/sheet label was not used as a topic anchor because the body lacked substantive technical explanation."],
                        provenance={
                            "source_filename": chunk.source_filename,
                            "source_path": chunk.source_path,
                            "section_heading": chunk.heading,
                        },
                        normalized_key=slugify(f"admin-heading-{chunk.chunk_id}", 180),
                        source_document_id=chunk.document_id,
                        source_chunk_id=chunk.chunk_id,
                        rejection_reason="weak_sheet_anchor",
                    )
                )
                continue
            score = score_topic_candidate(normalized_text, chunk)
            if score >= threshold:
                candidates.append(
                    TopicCandidate(
                        topic_key=topic_key,
                        topic_label=topic_label,
                        text=normalized_text,
                        score=score,
                        source_filename=chunk.source_filename,
                        chunk_id=chunk.chunk_id,
                        heading=chunk.heading,
                    )
                )
            else:
                rejected.append(
                    KnowledgeCandidate(
                        target_type="knowledge_core",
                        title=topic_label,
                        body=normalized_text,
                        score=score,
                        reasons=["Topic-like chunk detected but failed topic synthesis threshold."],
                        provenance={
                            "source_filename": chunk.source_filename,
                            "source_path": chunk.source_path,
                            "section_heading": chunk.heading,
                        },
                        normalized_key=slugify(f"{topic_key}-{chunk.chunk_id}", 180),
                        source_document_id=chunk.document_id,
                        source_chunk_id=chunk.chunk_id,
                        rejection_reason="below_threshold",
                    )
                )
    return candidates, rejected


def build_topic_pages(items: list[SourceKnowledge], target_words: int = 1600) -> list[str]:
    candidates = extract_topic_candidates(items)
    grouped: dict[str, list[TopicCandidate]] = defaultdict(list)
    labels: dict[str, str] = {}
    for candidate in candidates:
        grouped[candidate.topic_key].append(candidate)
        labels.setdefault(candidate.topic_key, candidate.topic_label)

    ordered_topics = sorted(
        grouped.keys(),
        key=lambda key: (-_topic_group_score(grouped[key]), -len(grouped[key]), labels[key].lower()),
    )

    topic_sections: list[str] = []
    for topic_key in ordered_topics:
        candidates_for_topic = sorted(grouped[topic_key], key=lambda item: (-item.score, item.source_filename.lower()))
        selected = _select_topic_candidates(candidates_for_topic)
        bullets = dedupe_text_blocks([_condense_topic_text(candidate.text) for candidate in selected])[:5]
        if not bullets:
            continue
        lines = [f"## {labels[topic_key]}", ""]
        for bullet in bullets:
            lines.append(f"- {bullet}")
        sources = sorted({candidate.source_filename for candidate in selected})
        lines.extend(["", f"Sources: {', '.join(sources)}"])
        topic_sections.append("\n".join(lines).strip())

    if not topic_sections:
        fallback = _fallback_topic_sections(items)
        topic_sections = fallback if fallback else ["## Knowledge\n\n- No high-signal knowledge candidates were promoted."]

    return _paginate_sections(topic_sections, target_words)


def _topic_group_score(candidates: list[TopicCandidate]) -> float:
    return sum(candidate.score for candidate in candidates) + (len({candidate.source_filename for candidate in candidates}) * 0.25)


def _condense_topic_text(text: str) -> str:
    cleaned = normalize_promotion_text(text)
    if not cleaned:
        return ""
    text = cleaned
    if word_count(text) < 6:
        return ""
    if len(text) > 320:
        text = text[:317].rstrip() + "..."
    return text


def _fallback_topic_sections(items: list[SourceKnowledge]) -> list[str]:
    sections = []
    for item in items:
        if item.empty_reason:
            continue
        bullet_pool: list[str] = []
        for value in item.summary_points + item.facts[:3] + item.warnings[:2]:
            cleaned = normalize_promotion_text(value)
            if not cleaned:
                continue
            if is_low_value_promotion_chunk(value):
                continue
            if word_count(cleaned) < 4:
                continue
            bullet_pool.append(cleaned)
        bullets = dedupe_text_blocks(bullet_pool)[:5]
        if not bullets:
            continue
        lines = [f"## {item.title}", ""]
        for bullet in bullets:
            lines.append(f"- {bullet}")
        lines.extend(["", f"Sources: {item.source_filename}"])
        sections.append("\n".join(lines).strip())
    return sections


def _select_topic_candidates(candidates: list[TopicCandidate], limit: int = 5) -> list[TopicCandidate]:
    selected: list[TopicCandidate] = []
    seen_sources: set[str] = set()
    for candidate in candidates:
        if candidate.source_filename in seen_sources:
            continue
        selected.append(candidate)
        seen_sources.add(candidate.source_filename)
        if len(selected) >= limit:
            return selected
    for candidate in candidates:
        if candidate in selected:
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def _paginate_sections(sections: list[str], target_words: int) -> list[str]:
    pages: list[str] = []
    current = ""
    for section in sections:
        candidate = f"{current}\n\n{section}".strip() if current else section
        if current and word_count(candidate) > target_words:
            pages.append(current.strip())
            current = section
        else:
            current = candidate
    if current.strip():
        pages.append(current.strip())
    if len(pages) >= 2 and word_count(pages[-1]) < 120:
        merged = f"{pages[-2]}\n\n{pages[-1]}".strip()
        if word_count(merged) <= int(target_words * 1.25):
            pages[-2] = merged
            pages.pop()
    filtered: list[str] = []
    for index, page in enumerate(pages):
        if word_count(page) >= 40:
            filtered.append(page)
            continue
        if len(pages) == 1 and word_count(page) >= 8:
            filtered.append(page)
            continue
        if index == 0 and page.count("\n- ") >= 1 and word_count(page) >= 8:
            filtered.append(page)
    return filtered
