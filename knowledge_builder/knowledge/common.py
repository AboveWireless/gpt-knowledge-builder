from __future__ import annotations

import re
from collections import OrderedDict

from ..compiler_models import FactCandidate, GlossaryCandidate, KnowledgeChunk, ProcedureCandidate, TopicCandidate
from ..utils import slugify, split_sentences, word_count


HEADING_RE = re.compile(r"^(#{1,6}\s+.+|\d+(\.\d+){0,4}\s+.+|[A-Z][A-Z0-9\s/&,-]{4,})$")
PROCEDURE_HEADING_RE = re.compile(r"\b(procedure|process|installation|method|steps|instructions|checklist)\b", re.IGNORECASE)
NON_PROCEDURAL_HEADING_RE = re.compile(r"\b(general notes?|title block|legend|schedule|index|inspection list|inspection notes?)\b", re.IGNORECASE)
ADMIN_HEADING_RE = re.compile(
    r"\b(title page|tower profile|detail\s+[a-z0-9-]+|sheet\s+[a-z0-9.-]+|vw\s+[a-z0-9.-]+|"
    r"revision|legend|general notes?|cover sheet|site address|site number|job number|project\s*#|"
    r"project number|prepared for|prepared by|description|legal)\b",
    re.IGNORECASE,
)
IMPERATIVE_RE = re.compile(
    r"^(install|remove|verify|check|tighten|inspect|connect|disconnect|measure|set|ensure|confirm|apply|attach|bond|ground)\b",
    re.IGNORECASE,
)
DEFINITION_VERB_RE = re.compile(r"\b(means|refers to|is defined as|defined as)\b", re.IGNORECASE)
FACT_VALUE_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:V|A|W|Hz|mm|cm|m|ft|in|lb|psi|N|Nm|%)\b", re.IGNORECASE)
IDENTIFIER_RE = re.compile(r"\b(?:ANSI|TIA|OSHA|BICSI|IEEE|NEC|NFPA|ISO|IEC|PN|P/N|Part|Model|SKU)[A-Z0-9:/._ -]*\b")
NOISE_TOKEN_RE = re.compile(r"\b(?:ii|iii|iv|v|text|page)\b", re.IGNORECASE)
OCR_GARBAGE_RE = re.compile(r"(?:\b[A-Za-z]\b\s*){4,}")
TOPIC_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9/-]{3,}\b")
NOTE_STYLE_RE = re.compile(
    r"\b(contractor shall|coordinate with|field conditions|diagrammatic only|unless otherwise noted|verify in field|"
    r"do not scale|all work shall|typical unless noted otherwise)\b",
    re.IGNORECASE,
)
ADMIN_LINE_RE = re.compile(
    r"\b("
    r"revision|rev\.?\s*(no|#)?|sheet\s*(no|number|title)?|issued\s*for|drawn\s*by|checked\s*by|approved\s*by|"
    r"engineer'?s?\s*seal|licensed\s+professional\s+engineer|all\s+rights\s+reserved|copyright|"
    r"phone|fax|www\.|http[s]?://|email|project\s*no|project\s*#|job\s*no|drawing\s*no|issue\s*date|plot\s*date|permit|"
    r"state\s+of|consulting\s+engineers|seal|sheet\s+\d+|project\s+name|prepared\s+for|prepared\s+by|site\s+address|"
    r"project\s+address|vicinity\s+map|sheet\s+title|issue|site\s+number|job\s+number|description|legal"
    r")\b",
    re.IGNORECASE,
)
CONTACT_BLOCK_RE = re.compile(r"\b(?:tel|phone|fax|www\.|http[s]?://|@)\b", re.IGNORECASE)
PATH_LIKE_RE = re.compile(r"(?:[A-Za-z]:\\|\\[\w .-]+\\[\w .\\/:-]+|/[\w.-]+/[\w./-]+|www\.|http[s]?://|\.\\[\w .\\/:-]+\.(?:png|jpg|jpeg|pdf|dwg|dxf|tif|tiff))", re.IGNORECASE)
MIXED_METADATA_RE = re.compile(r"\b(?:sheet|rev|issue|date|drawn by|checked by|approved by|project no|drawing no)\b", re.IGNORECASE)
STOPWORDS = {
    "this",
    "that",
    "with",
    "from",
    "have",
    "shall",
    "must",
    "required",
    "using",
    "into",
    "for",
    "when",
    "where",
    "procedure",
    "process",
    "instructions",
}
TECHNICAL_TOPIC_STOPWORDS = STOPWORDS | {
    "title",
    "page",
    "detail",
    "sheet",
    "tower",
    "profile",
    "project",
    "prepared",
    "issued",
    "address",
    "revision",
    "general",
    "notes",
    "copyright",
    "site",
    "number",
    "job",
    "description",
    "legal",
    "option",
    "lat",
}


def build_chunks(
    text: str,
    source_filename: str,
    title: str,
    *,
    document_id: str = "",
    source_path: str = "",
    file_type: str = "",
    extraction_method: str = "unknown",
) -> list[KnowledgeChunk]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[KnowledgeChunk] = []
    current_heading = title
    section_path = [title]
    for index, paragraph in enumerate(paragraphs):
        first_line = paragraph.splitlines()[0].strip()
        if HEADING_RE.match(first_line):
            current_heading = first_line.lstrip("# ").strip()
            section_path = [title, current_heading]
        chunks.append(
            KnowledgeChunk(
                chunk_id=f"{slugify(source_filename, 40)}-{index:04d}",
                document_id=document_id,
                source_path=source_path,
                source_filename=source_filename,
                file_type=file_type,
                title=title,
                heading=current_heading,
                text=paragraph,
                extraction_method=extraction_method,
                section_path=list(section_path),
            )
        )
    return chunks


def score_glossary_candidate(term: str, definition: str, chunk: KnowledgeChunk) -> float:
    score = 0.0
    if 2 <= len(term.split()) <= 8:
        score += 0.25
    if term[:1].isupper() and not term.isupper():
        score += 0.1
    if DEFINITION_VERB_RE.search(definition):
        score += 0.2
    if 4 <= word_count(definition) <= 40:
        score += 0.25
    if definition.endswith((".", ";")):
        score += 0.1
    if _is_acronym_term(term) and 2 <= word_count(definition) <= 12:
        score += 0.4
    if admin_boilerplate_score(f"{term} {definition}") >= 0.35:
        score -= 0.8
    if OCR_GARBAGE_RE.search(term) or OCR_GARBAGE_RE.search(definition):
        score -= 0.4
    if _looks_fragmentary(definition):
        score -= 0.35
    if not looks_like_clean_term(term):
        score -= 0.45
    if not _looks_definition_body(definition):
        score -= 0.55
    if len(definition) > 320:
        score -= 0.15
    return round(score, 3)


def score_procedure_candidate(title: str, steps: list[str], chunk: KnowledgeChunk) -> float:
    score = 0.0
    if PROCEDURE_HEADING_RE.search(title) or PROCEDURE_HEADING_RE.search(chunk.heading):
        score += 0.25
    if NON_PROCEDURAL_HEADING_RE.search(title) or NON_PROCEDURAL_HEADING_RE.search(chunk.heading):
        score -= 0.35
    if len(steps) >= 2:
        score += 0.3
    imperative_hits = sum(1 for step in steps if IMPERATIVE_RE.search(_strip_step_number(step)))
    score += min(imperative_hits * 0.12, 0.3)
    if imperative_hits == 0 and not PROCEDURE_HEADING_RE.search(title):
        score -= 0.4
    if any(
        _looks_fragmentary(_strip_step_number(step)) and not IMPERATIVE_RE.search(_strip_step_number(step))
        for step in steps
    ):
        score -= 0.3
    if admin_boilerplate_score(" ".join(steps)) >= 0.3:
        score -= 0.7
    if OCR_GARBAGE_RE.search(" ".join(steps)):
        score -= 0.35
    return round(score, 3)


def score_fact_candidate(text: str, chunk: KnowledgeChunk) -> float:
    score = 0.0
    if admin_boilerplate_score(text) >= 0.35:
        score -= 0.75
    if PATH_LIKE_RE.search(text):
        score -= 0.5
    if MIXED_METADATA_RE.search(text) and text.count(",") + text.count("|") + text.count(":") >= 3:
        score -= 0.6
    if NOTE_STYLE_RE.search(text):
        score -= 0.35
    if FACT_VALUE_RE.search(text):
        score += 0.35
    if re.search(r":\s*\d+(?:\.\d+)?\s?(?:V|A|W|Hz|mm|cm|m|ft|in|lb|psi|N|Nm|%)\b", text, re.IGNORECASE):
        score += 0.2
    if re.search(r"\b20\d{2}\b", text):
        score += 0.15
    if re.search(r"\b(shall|must|required|shall not|must not|prohibited|should)\b", text, re.IGNORECASE):
        score += 0.3
    if IDENTIFIER_RE.search(text):
        score += 0.2
    if ":" in text:
        score += 0.1
    if 3 <= word_count(text) <= 35:
        score += 0.2
    if 3 <= word_count(text) <= 12:
        score += 0.1
    if _looks_fragmentary(text):
        score -= 0.3
    if OCR_GARBAGE_RE.search(text):
        score -= 0.35
    return round(score, 3)


def score_topic_candidate(text: str, chunk: KnowledgeChunk) -> float:
    score = 0.0
    if admin_boilerplate_score(text) >= 0.3:
        score -= 0.9
    if chunk.heading and chunk.heading != chunk.title:
        score += 0.25
    words = word_count(text)
    if 20 <= words <= 180:
        score += 0.25
    elif 6 <= words < 20:
        score += 0.15
    if re.search(r"\b(shall|must|required|should|warning|caution|definition|scope|procedure|installation)\b", text, re.IGNORECASE):
        score += 0.2
    if IDENTIFIER_RE.search(text):
        score += 0.15
    if re.search(r"\b(means|refers to|is defined as|defined as)\b", text, re.IGNORECASE):
        score += 0.15
    if _has_technical_topic_signal(text):
        score += 0.15
    if NOTE_STYLE_RE.search(text):
        score -= 0.2
    if _looks_fragmentary(text):
        score -= 0.3
    if OCR_GARBAGE_RE.search(text):
        score -= 0.25
    return round(score, 3)


def dedupe_glossary(candidates: list[GlossaryCandidate]) -> list[GlossaryCandidate]:
    best: dict[str, GlossaryCandidate] = {}
    for candidate in candidates:
        key = slugify(candidate.term, 100)
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate
    return sorted(best.values(), key=lambda item: (-item.score, item.term.lower()))


def dedupe_facts(candidates: list[FactCandidate]) -> list[FactCandidate]:
    best: dict[str, FactCandidate] = {}
    for candidate in candidates:
        key = slugify(candidate.text, 220)
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate
    return sorted(best.values(), key=lambda item: (-item.score, item.text.lower()))


def topic_key_from_chunk(chunk: KnowledgeChunk) -> tuple[str, str]:
    heading = chunk.heading.strip() if chunk.heading else ""
    if heading and heading != chunk.title and not heading.isdigit() and not is_admin_or_sheet_heading(heading):
        label = heading.lstrip("# ").strip()
        return slugify(label, 80), label

    topic_terms = _topic_terms_from_text(normalize_promotion_text(chunk.text))
    if topic_terms:
        label = " ".join(topic_terms).title()
        return slugify(label, 80), label
    return slugify(chunk.title, 80), chunk.title


def normalize_fact_sentence(text: str) -> str:
    sentence = " ".join(text.split())
    sentence = re.sub(r"\s+([,.;:])", r"\1", sentence)
    if sentence and sentence[-1] not in ".:;":
        sentence += "."
    return sentence


def normalize_promotion_text(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if HEADING_RE.match(stripped):
            continue
        if _is_admin_line(stripped):
            continue
        cleaned_lines.append(stripped)
    cleaned = " ".join(cleaned_lines)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    return cleaned.strip()


def split_candidate_sentences(chunk: KnowledgeChunk) -> list[str]:
    sentences: list[str] = []
    for line in chunk.text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        line_sentences = split_sentences(stripped)
        if line_sentences:
            sentences.extend(sentence.strip() for sentence in line_sentences if sentence.strip())
        else:
            sentences.append(stripped)
    return sentences


def _looks_fragmentary(text: str) -> bool:
    stripped = " ".join(text.split()).strip()
    if not stripped:
        return True
    if len(stripped) < 12:
        return True
    if NOISE_TOKEN_RE.search(stripped) and word_count(stripped) <= 4:
        return True
    if stripped[-1] not in ".:;" and word_count(stripped) < 8:
        return True
    if word_count(stripped) <= 2:
        return True
    if len(stripped.split()) == 3 and stripped[-1] not in ".:;" and stripped[0].isupper():
        return True
    if re.fullmatch(r"[A-Za-z0-9 /._-]+", stripped) and word_count(stripped) <= 3 and stripped[-1] not in ".:;":
        return True
    return False


def _strip_step_number(step: str) -> str:
    return re.sub(r"^\d+[\.)]\s*", "", step).strip()


def dedupe_text_blocks(values: list[str]) -> list[str]:
    seen = OrderedDict()
    for value in values:
        key = slugify(value, 220)
        if key not in seen:
            seen[key] = value
    return list(seen.values())


def admin_boilerplate_score(text: str) -> float:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 0.0
    admin_hits = sum(1 for line in lines if _is_admin_line(line))
    line_ratio = admin_hits / len(lines)
    contact_bonus = 0.2 if CONTACT_BLOCK_RE.search(text) else 0.0
    return round(min(line_ratio + contact_bonus, 1.0), 3)


def is_low_value_promotion_chunk(text: str) -> bool:
    cleaned = normalize_promotion_text(text)
    if not cleaned:
        return True
    if admin_boilerplate_score(text) >= 0.5:
        return True
    if is_admin_or_sheet_heading(cleaned):
        return True
    return False


def looks_like_clean_term(term: str) -> bool:
    stripped = " ".join(term.split()).strip(" -:;,.")
    if not stripped:
        return False
    if len(stripped) > 60:
        return False
    words = stripped.split()
    if len(words) > 5 and stripped.isupper():
        return False
    if stripped.isupper() and len(words) > 2:
        return False
    if is_generic_note_word(stripped):
        return False
    if re.fullmatch(r"option\s+\d+", stripped, re.IGNORECASE):
        return False
    if re.fullmatch(r"(?:lat|long|lon|description|legal|site|number)", stripped, re.IGNORECASE):
        return False
    if words[-1].lower() in {"as", "the", "a", "an", "of", "to", "mi", "po"}:
        return False
    if OCR_GARBAGE_RE.search(stripped):
        return False
    return True


def _is_acronym_term(term: str) -> bool:
    stripped = term.strip()
    return bool(re.fullmatch(r"[A-Z0-9/-]{2,12}", stripped))


def _is_admin_line(text: str) -> bool:
    stripped = " ".join(text.split())
    if not stripped:
        return False
    if ADMIN_LINE_RE.search(stripped):
        return True
    if stripped.isupper() and CONTACT_BLOCK_RE.search(stripped):
        return True
    if re.search(r"\b(sheet|rev|issue|drawing)\b", stripped, re.IGNORECASE) and re.search(r"\b\d+\b", stripped):
        return True
    if stripped.count(":") >= 2 and word_count(stripped) <= 14:
        return True
    if stripped.count("|") >= 1:
        return True
    return False


def is_admin_or_sheet_heading(text: str) -> bool:
    stripped = " ".join(text.split()).strip(" -:;,.")
    if not stripped:
        return False
    if ADMIN_HEADING_RE.search(stripped):
        return True
    if re.fullmatch(r"[A-Z]{1,2}\d(?:[A-Z0-9.-]{0,6})", stripped):
        return True
    if re.fullmatch(r"(?:detail|sheet|vw)\s+[A-Z0-9.-]+", stripped, re.IGNORECASE):
        return True
    return False


def is_generic_note_word(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered in {
        "note",
        "notes",
        "all construction",
        "general notes",
        "necessary",
        "shall",
        "qty",
        "size",
        "detail",
        "title page",
        "tower profile",
        "description",
        "legal",
        "site",
        "number",
        "job number",
        "site number",
        "isolated",
        "lat",
    }


def _topic_terms_from_text(text: str) -> list[str]:
    counts: OrderedDict[str, int] = OrderedDict()
    for token in TOPIC_WORD_RE.findall(text):
        lowered = token.lower()
        if lowered in TECHNICAL_TOPIC_STOPWORDS:
            continue
        if re.fullmatch(r"[A-Z0-9.-]+", token) and len(token) <= 4:
            continue
        if is_admin_or_sheet_heading(token):
            continue
        counts.setdefault(lowered, 0)
        counts[lowered] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))
    return [token for token, _count in ranked[:3]]


def _has_technical_topic_signal(text: str) -> bool:
    return len(_topic_terms_from_text(text)) >= 2


def _looks_definition_body(text: str) -> bool:
    stripped = " ".join(text.split()).strip()
    if not stripped:
        return False
    if NOTE_STYLE_RE.search(stripped):
        return False
    if re.fullmatch(r"[A-Z0-9 /._-]{2,40}", stripped):
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?(?:,\s*\d+(?:\.\d+)?)*", stripped):
        return False
    return word_count(stripped) >= 3
