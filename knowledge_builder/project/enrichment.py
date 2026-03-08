from __future__ import annotations

import json
from pathlib import Path

from ..compiler_models import SourceKnowledge
from ..utils import iso_now, word_count, write_json
from .models import ProjectConfig


ENRICHMENT_SCHEMA_VERSION = "v2"
MAX_INPUT_CHARS = 12000


def run_optional_enrichment(
    config: ProjectConfig,
    path: Path,
    knowledge: SourceKnowledge,
    model_cache_dir: Path,
    api_key: str = "",
) -> dict:
    checksum_prefix = knowledge.document_id[:16]
    cache_key = (
        f"{checksum_prefix}__{config.optional_model_settings.provider}__"
        f"{config.optional_model_settings.model}__{config.optional_model_settings.prompt_version}__{ENRICHMENT_SCHEMA_VERSION}"
    )
    cache_path = model_cache_dir / f"{cache_key}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    fallback = _fallback_payload(config, path, knowledge, cache_key)
    if not _can_call_openai(config, api_key):
        write_json(cache_path, fallback)
        return fallback

    try:
        from openai import OpenAI
    except ImportError:
        write_json(cache_path, fallback)
        return fallback

    client = OpenAI(api_key=api_key)
    prompt = _build_prompt(path, knowledge)
    try:
        response = client.responses.create(
            model=config.optional_model_settings.model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You analyze extracted enterprise documents for a local GPT knowledge builder. "
                                "Return strict JSON only with keys: clean_title, taxonomy, synopsis, glossary_hints, "
                                "review_notes, confidence. taxonomy must contain domain and topic. "
                                "glossary_hints and review_notes must be arrays of strings."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                },
            ],
        )
        raw_text = getattr(response, "output_text", "") or ""
        parsed = json.loads(raw_text)
        payload = {
            "cache_key": cache_key,
            "model_enabled": True,
            "provider": config.optional_model_settings.provider,
            "model": config.optional_model_settings.model,
            "prompt_version": config.optional_model_settings.prompt_version,
            "generated_at": iso_now(),
            "clean_title": str(parsed.get("clean_title") or fallback["clean_title"]).strip(),
            "taxonomy": {
                "domain": str(((parsed.get("taxonomy") or {}).get("domain")) or fallback["taxonomy"]["domain"]).strip() or fallback["taxonomy"]["domain"],
                "topic": str(((parsed.get("taxonomy") or {}).get("topic")) or fallback["taxonomy"]["topic"]).strip() or fallback["taxonomy"]["topic"],
            },
            "synopsis": str(parsed.get("synopsis") or fallback["synopsis"]).strip(),
            "glossary_hints": _clean_string_list(parsed.get("glossary_hints"), limit=12),
            "review_notes": _clean_string_list(parsed.get("review_notes"), limit=8),
            "confidence": _safe_confidence(parsed.get("confidence"), fallback["confidence"]),
            "mode": "openai",
        }
    except Exception as exc:
        payload = fallback | {
            "mode": "fallback",
            "error": str(exc),
        }

    write_json(cache_path, payload)
    return payload


def _can_call_openai(config: ProjectConfig, api_key: str) -> bool:
    return bool(
        config.optional_model_settings.enabled
        and config.optional_model_settings.provider == "openai"
        and api_key
    )


def _fallback_payload(config: ProjectConfig, path: Path, knowledge: SourceKnowledge, cache_key: str) -> dict:
    return {
        "cache_key": cache_key,
        "model_enabled": False,
        "provider": config.optional_model_settings.provider,
        "model": config.optional_model_settings.model,
        "prompt_version": config.optional_model_settings.prompt_version,
        "generated_at": iso_now(),
        "clean_title": _fallback_title(knowledge),
        "taxonomy": {
            "domain": _fallback_domain(path, knowledge),
            "topic": _fallback_topic(knowledge),
        },
        "synopsis": " ".join(knowledge.summary_points[:3]).strip(),
        "glossary_hints": [term for term, _definition in knowledge.glossary[:8]],
        "review_notes": list(knowledge.warnings[:4]),
        "confidence": 0.55,
        "mode": "deterministic",
    }


def _build_prompt(path: Path, knowledge: SourceKnowledge) -> str:
    summary_points = "\n".join(f"- {point}" for point in knowledge.summary_points[:6]) or "- none"
    glossary_terms = "\n".join(f"- {term}" for term, _definition in knowledge.glossary[:10]) or "- none"
    warnings = "\n".join(f"- {warning}" for warning in knowledge.warnings[:6]) or "- none"
    excerpt = knowledge.clean_text[:MAX_INPUT_CHARS].strip()
    return (
        f"Source file: {path.name}\n"
        f"Document type: {knowledge.document_type}\n"
        f"Current title: {knowledge.title}\n"
        f"Word count: {word_count(knowledge.clean_text)}\n\n"
        f"Extracted summary points:\n{summary_points}\n\n"
        f"Glossary terms already found:\n{glossary_terms}\n\n"
        f"Warnings/notices:\n{warnings}\n\n"
        "Document excerpt:\n"
        f"{excerpt}\n"
    )


def _fallback_title(knowledge: SourceKnowledge) -> str:
    if knowledge.summary_points:
        return knowledge.summary_points[0][:80].rstrip(".")
    return knowledge.title.strip()


def _fallback_domain(path: Path, knowledge: SourceKnowledge) -> str:
    lowered = f"{path.as_posix()} {knowledge.title.lower()} {knowledge.clean_text[:600].lower()}"
    heuristics = (
        ("policy", ("policy", "compliance", "contract", "legal", "agreement")),
        ("training", ("training", "course", "lesson", "quiz", "exercise")),
        ("product", ("product", "release", "feature", "roadmap", "requirements")),
        ("operations", ("procedure", "installer", "sop", "workflow", "maintenance")),
    )
    for label, terms in heuristics:
        if any(term in lowered for term in terms):
            return label
    return "general"


def _fallback_topic(knowledge: SourceKnowledge) -> str:
    if knowledge.topic_candidates:
        return knowledge.topic_candidates[0].topic_label[:60]
    if knowledge.glossary:
        return knowledge.glossary[0][0][:60]
    return "general"


def _clean_string_list(value, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _safe_confidence(value, fallback: float) -> float:
    try:
        numeric = float(value)
    except Exception:
        return fallback
    return max(0.0, min(1.0, numeric))
