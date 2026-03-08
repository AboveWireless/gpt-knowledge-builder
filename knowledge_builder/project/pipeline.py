from __future__ import annotations

import fnmatch
import shutil
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

from ..compiler_models import SourceKnowledge
from ..extractors import extract, get_supported_doc_type
from ..naming import make_safe_corpus_name
from ..scanner.discovery import discover_corpus_files
from ..synthesis import (
    build_entities,
    build_glossary,
    build_knowledge_core_pages,
    build_procedures,
    build_reference_facts,
    build_source_knowledge,
    clean_text_for_knowledge,
)
from ..utils import append_log, chunk_words, ensure_dir, iso_now, json_ready, mtime, sha256_file, slugify, word_count, write_json, write_jsonl
from .enrichment import run_optional_enrichment
from .models import EXPORT_PROFILES, DOCUMENT_PRESETS, ProjectConfig
from .store import (
    load_project_config,
    load_reviews,
    load_state,
    resolve_project_path,
    resolve_provider_api_key,
    save_reviews,
    save_state,
    state_root,
)


MAX_PACKAGE_FILE_BYTES = 8_000_000
EXPORT_WORD_TARGET = 1700
TARGET_PACKAGE_BYTES = 1_200_000
MAX_ARTIFACT_WORDS = 1600


def validate_project(project_root: Path) -> list[str]:
    project_root = project_root.resolve()
    issues: list[str] = []
    project_file = project_root / "project.yaml"
    if not project_file.exists():
        return [f"Missing project file: {project_file}"]

    config = load_project_config(project_root)
    if config.export_profile not in EXPORT_PROFILES:
        issues.append(f"Unknown export profile: {config.export_profile}")
    if config.preset not in DOCUMENT_PRESETS:
        issues.append(f"Unknown document preset: {config.preset}")
    if not config.source_roots:
        issues.append("At least one source root must be configured.")
    for source_root in config.source_roots:
        resolved = resolve_project_path(project_root, source_root)
        if not resolved.exists():
            issues.append(f"Missing source root: {resolved}")
    output_root = resolve_project_path(project_root, config.output_root)
    if output_root.resolve() == project_root.resolve():
        issues.append("output_root should not be the project root itself.")
    if config.optional_model_settings.enabled and not resolve_provider_api_key(project_root, config.optional_model_settings.provider):
        issues.append(f"AI enrichment is enabled but no {config.optional_model_settings.provider} API key is configured.")
    reviews = load_reviews(project_root)
    open_high = [
        item for item in reviews.get("items", [])
        if item.get("status") == "open" and item.get("severity") in {"high", "critical"}
    ]
    if open_high:
        issues.append(f"{len(open_high)} high-severity review item(s) remain unresolved.")
    return issues


def scan_project(project_root: Path, force: bool = False) -> dict:
    project_root = project_root.resolve()
    config = load_project_config(project_root)
    project_state = load_state(project_root)
    review_store = load_reviews(project_root)
    root = state_root(project_root)
    provider_api_key = resolve_provider_api_key(project_root, config.optional_model_settings.provider)
    raw_cache_dir = root / "cache" / "raw"
    clean_cache_dir = root / "cache" / "clean"
    model_cache_dir = root / "cache" / "model"
    ensure_dir(raw_cache_dir)
    ensure_dir(clean_cache_dir)
    ensure_dir(model_cache_dir)

    documents = project_state.get("documents") or {}
    seen_paths: set[str] = set()
    summary = {"scanned": 0, "processed": 0, "skipped": 0, "flagged": 0, "removed": 0}
    duplicate_candidates: list[tuple[str, str, str]] = []

    discovered = _discover_project_files(project_root, config)
    for path in discovered:
        path = path.resolve()
        source_key = str(path)
        seen_paths.add(source_key)
        summary["scanned"] += 1

        checksum = sha256_file(path)
        existing = documents.get(source_key) or {}
        existing_fingerprint = (existing.get("fingerprint") or {})
        raw_cache_path = raw_cache_dir / f"{checksum[:16]}.txt"
        clean_cache_path = clean_cache_dir / f"{checksum[:16]}.txt"

        if (
            not force
            and existing_fingerprint.get("checksum") == checksum
            and raw_cache_path.exists()
            and clean_cache_path.exists()
        ):
            summary["skipped"] += 1
            continue

        doc_type = get_supported_doc_type(path)
        if not doc_type:
            continue

        extracted = extract(path, doc_type, None)
        raw_text = extracted.text or ""
        clean_text = clean_text_for_knowledge(raw_text)
        knowledge = build_source_knowledge(
            source_path=path,
            document_type=doc_type,
            title=extracted.title or path.stem,
            raw_text=raw_text,
            clean_text=clean_text,
            extraction_method=extracted.extraction_method,
            ocr_used=extracted.ocr_used,
            source_folder_name=path.parent.name,
        )

        raw_cache_path.write_text(raw_text, encoding="utf-8")
        clean_cache_path.write_text(clean_text, encoding="utf-8")
        enrichment = run_optional_enrichment(config, path, knowledge, model_cache_dir, api_key=provider_api_key)
        probable_domain = enrichment.get("taxonomy", {}).get("domain") or _infer_probable_domain(path, knowledge)
        doc_id = knowledge.document_id
        ai_hints = _merge_ai_hints(knowledge, enrichment)

        documents[source_key] = {
            "fingerprint": {
                "source_path": source_key,
                "checksum": checksum,
                "size_bytes": path.stat().st_size,
                "modified_at": mtime(path).isoformat(),
            },
            "document": {
                "doc_id": doc_id,
                "source_path": source_key,
                "source_filename": path.name,
                "source_root": _find_source_root(project_root, config, path),
                "document_type": doc_type,
                "checksum": checksum,
                "title": enrichment.get("clean_title") or knowledge.title,
                "clean_text_path": str(clean_cache_path),
                "raw_text_path": str(raw_cache_path),
                "extraction_method": knowledge.extraction_method,
                "ocr_used": knowledge.ocr_used,
                "word_count": word_count(clean_text),
                "chunk_count": len(knowledge.chunks),
                "probable_domain": probable_domain,
                "topic": enrichment.get("taxonomy", {}).get("topic") or _fallback_topic_label(knowledge),
                "review_status": "flagged" if knowledge.empty_reason else "clean",
                "empty_reason": knowledge.empty_reason,
                "duplicate_of": None,
                "knowledge_item_count": len(knowledge.promoted_items),
                "updated_at": iso_now(),
                "enrichment_cache_key": enrichment.get("cache_key", ""),
                "enrichment_mode": enrichment.get("mode", "deterministic"),
                "ai_confidence": enrichment.get("confidence", 0.0),
            },
            "knowledge_summary": {
                "summary_points": knowledge.summary_points,
                "warnings": knowledge.warnings,
                "accepted_candidates": json_ready(knowledge.accepted_candidates),
                "promoted_items": json_ready(knowledge.promoted_items),
                "ai_hints": ai_hints,
                "enrichment": json_ready(enrichment),
            },
        }
        summary["processed"] += 1
        duplicate_candidates.append((source_key, doc_id, clean_text))

    removed_paths = [source_path for source_path in list(documents.keys()) if source_path not in seen_paths]
    for source_path in removed_paths:
        record = documents.pop(source_path)
        summary["removed"] += 1
        for cache_key in ("raw_text_path", "clean_text_path"):
            cache_path = Path(((record.get("document") or {}).get(cache_key)) or "")
            if cache_path.exists():
                cache_path.unlink()

    review_store["items"] = _build_review_queue(project_root, config, documents, duplicate_candidates, review_store.get("items") or [])
    summary["flagged"] = sum(1 for item in review_store["items"] if item.get("status") == "open")

    save_state(project_root, {"version": 1, "documents": documents, "exports": project_state.get("exports") or []})
    save_reviews(project_root, review_store)
    append_log(root / "logs" / "project.log", f"scan scanned={summary['scanned']} processed={summary['processed']} skipped={summary['skipped']} flagged={summary['flagged']}")
    return summary


def review_project(project_root: Path, approve_all: bool = False, reject_duplicates: bool = False) -> dict:
    project_root = project_root.resolve()
    review_store = load_reviews(project_root)
    state = load_state(project_root)
    items = review_store.get("items") or []
    changed = 0
    for item in items:
        if approve_all and item.get("status") == "open":
            item["status"] = "accepted"
            item["updated_at"] = iso_now()
            changed += 1
        elif reject_duplicates and item.get("status") == "open" and item.get("kind") == "duplicate":
            item["status"] = "rejected"
            item["updated_at"] = iso_now()
            changed += 1
            doc = (state.get("documents") or {}).get(item.get("source_path"))
            if doc:
                doc_document = doc.get("document") or {}
                doc_document["review_status"] = "rejected"
                doc["document"] = doc_document
                state["documents"][item["source_path"]] = doc
    save_reviews(project_root, review_store)
    save_state(project_root, state)
    return {
        "open": sum(1 for item in items if item.get("status") == "open"),
        "accepted": sum(1 for item in items if item.get("status") == "accepted"),
        "rejected": sum(1 for item in items if item.get("status") == "rejected"),
        "changed": changed,
    }


def update_review_item(
    project_root: Path,
    review_id: str,
    status: str | None = None,
    override_title: str | None = None,
    override_domain: str | None = None,
    resolution_note: str | None = None,
) -> dict:
    project_root = project_root.resolve()
    review_store = load_reviews(project_root)
    state = load_state(project_root)
    items = review_store.get("items") or []
    target = next((item for item in items if item.get("review_id") == review_id), None)
    if target is None:
        raise ValueError(f"Review item not found: {review_id}")

    source_path = target.get("source_path")
    document_record = (state.get("documents") or {}).get(source_path) or {}
    document = document_record.get("document") or {}
    knowledge_summary = document_record.get("knowledge_summary") or {}

    if status:
        target["status"] = status
        if status == "rejected":
            document["review_status"] = "rejected"
        elif status in {"accepted", "resolved"} and document.get("review_status") != "rejected":
            document["review_status"] = "clean"
    if override_title is not None:
        cleaned = override_title.strip()
        target["override_title"] = cleaned
        if cleaned:
            document["title"] = cleaned
            enrichment = knowledge_summary.get("enrichment") or {}
            enrichment["clean_title"] = cleaned
            knowledge_summary["enrichment"] = enrichment
    if override_domain is not None:
        cleaned = slugify(override_domain.strip(), max_len=40).replace("-", "_")
        target["override_domain"] = cleaned
        if cleaned:
            document["probable_domain"] = cleaned
            enrichment = knowledge_summary.get("enrichment") or {}
            taxonomy = enrichment.get("taxonomy") or {}
            taxonomy["domain"] = cleaned
            enrichment["taxonomy"] = taxonomy
            knowledge_summary["enrichment"] = enrichment
    if resolution_note is not None:
        target["resolution_note"] = resolution_note.strip()

    target["updated_at"] = iso_now()
    document["updated_at"] = iso_now()
    document_record["document"] = document
    document_record["knowledge_summary"] = knowledge_summary
    state["documents"][source_path] = document_record

    save_reviews(project_root, review_store)
    save_state(project_root, state)
    append_log(state_root(project_root) / "logs" / "project.log", f"review_update review_id={review_id} status={target.get('status')}")
    return target


def export_project(project_root: Path, zip_pack: bool = False) -> dict:
    project_root = project_root.resolve()
    config = load_project_config(project_root)
    state = load_state(project_root)
    reviews = load_reviews(project_root)
    output_root = resolve_project_path(project_root, config.output_root)
    ensure_dir(output_root)

    corpus_name = make_safe_corpus_name(config.project_name)
    package_dir = output_root / f"{corpus_name}_gpt_package"
    provenance_dir = output_root / f"{corpus_name}_provenance"
    shutil.rmtree(package_dir, ignore_errors=True)
    shutil.rmtree(provenance_dir, ignore_errors=True)
    ensure_dir(package_dir)
    ensure_dir(provenance_dir)

    documents = _load_export_documents(state)
    knowledge_items = _build_export_knowledge(documents)

    knowledge_pages = build_knowledge_core_pages(knowledge_items, target_words=MAX_ARTIFACT_WORDS)
    if not knowledge_pages and knowledge_items:
        knowledge_pages = [_build_fallback_knowledge_core(knowledge_items)]
    optional_outputs = {
        "reference_facts": build_reference_facts(knowledge_items),
        "glossary": build_glossary(knowledge_items),
        "procedures": build_procedures(knowledge_items),
        "entities": build_entities(knowledge_items),
    }
    written_files: list[Path] = []
    _write_split_artifact(package_dir, "knowledge_core", knowledge_pages, written_files)
    for stem, content in optional_outputs.items():
        pages = _split_markdown_pages(content)
        _write_split_artifact(package_dir, stem, pages, written_files)

    package_index_path = package_dir / "package_index.md"
    package_index_path.write_text(_build_package_index(config, written_files), encoding="utf-8")
    written_files.append(package_index_path)

    provenance_manifest_path = provenance_dir / "provenance_manifest.json"
    provenance_items_path = provenance_dir / "knowledge_items.jsonl"
    review_manifest_path = provenance_dir / "review_queue.json"
    validation_messages = _validate_package_outputs(written_files, reviews)
    provenance_items = _build_provenance_items(knowledge_items)
    provenance_payload = {
        "project_name": config.project_name,
        "export_profile": config.export_profile,
        "generated_at": iso_now(),
        "documents": [record for record in documents],
        "knowledge_item_count": len(provenance_items),
        "knowledge_items_file": str(provenance_items_path),
    }
    write_json(provenance_manifest_path, provenance_payload)
    write_jsonl(provenance_items_path, provenance_items)
    write_json(review_manifest_path, reviews)
    (provenance_dir / "validation_report.txt").write_text("\n".join(validation_messages).strip() + ("\n" if validation_messages else ""), encoding="utf-8")

    if config.export_profile in {"custom-gpt-max-traceability", "debug-research"}:
        debug_dir = provenance_dir / "debug"
        ensure_dir(debug_dir)
        for record in documents:
            doc = record.get("document") or {}
            source_name = make_safe_corpus_name(doc.get("source_filename", "document"))
            raw_path = Path(doc.get("raw_text_path") or "")
            clean_path = Path(doc.get("clean_text_path") or "")
            if raw_path.exists():
                shutil.copyfile(raw_path, debug_dir / f"{source_name}__raw.txt")
            if clean_path.exists():
                shutil.copyfile(clean_path, debug_dir / f"{source_name}__clean.txt")

    zip_path = None
    if zip_pack:
        zip_path = output_root / f"{corpus_name}_gpt_package.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in written_files:
                zf.write(file_path, arcname=file_path.name)

    exports = state.get("exports") or []
    exports.append(
        {
            "package_dir": str(package_dir),
            "profile": config.export_profile,
            "written_files": [str(path) for path in written_files],
            "package_index_file": str(package_index_path),
            "provenance_manifest": str(provenance_manifest_path),
            "knowledge_items_file": str(provenance_items_path),
            "validation_messages": validation_messages,
            "zip_path": str(zip_path) if zip_path else "",
            "exported_at": iso_now(),
        }
    )
    state["exports"] = exports
    save_state(project_root, state)
    append_log(state_root(project_root) / "logs" / "project.log", f"export package={package_dir} files={len(written_files)}")
    return {
        "package_dir": str(package_dir),
        "provenance_dir": str(provenance_dir),
        "zip_path": str(zip_path) if zip_path else "",
        "written_files": [str(path) for path in written_files],
        "knowledge_items_file": str(provenance_items_path),
        "validation_messages": validation_messages,
    }


def _discover_project_files(project_root: Path, config: ProjectConfig) -> list[Path]:
    files: list[Path] = []
    for source_root_value in config.source_roots:
        source_root = resolve_project_path(project_root, source_root_value)
        if not source_root.exists():
            continue
        for discovered in discover_corpus_files(source_root):
            rel = discovered.path.relative_to(source_root).as_posix()
            if config.include_globs and not _matches_any(rel, config.include_globs):
                continue
            if config.exclude_globs and _matches_any(rel, config.exclude_globs):
                continue
            files.append(discovered.path)
    return sorted(set(files))


def _matches_any(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        if pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]):
            return True
    return False


def _infer_probable_domain(path: Path, knowledge: SourceKnowledge) -> str:
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


def _fallback_topic_label(knowledge: SourceKnowledge) -> str:
    if knowledge.topic_candidates:
        return knowledge.topic_candidates[0].topic_label
    if knowledge.glossary:
        return knowledge.glossary[0][0]
    return "general"


def _find_source_root(project_root: Path, config: ProjectConfig, path: Path) -> str:
    for source_root_value in config.source_roots:
        source_root = resolve_project_path(project_root, source_root_value)
        try:
            path.relative_to(source_root)
            return str(source_root)
        except ValueError:
            continue
    return str(path.parent)


def _build_review_queue(project_root: Path, config: ProjectConfig, documents: dict, duplicate_candidates: list[tuple[str, str, str]], previous_items: list[dict]) -> list[dict]:
    items: list[dict] = []
    previous_map = {(item.get("doc_id"), item.get("kind")): item for item in previous_items}
    all_duplicate_candidates = _load_duplicate_candidates(documents)
    if duplicate_candidates:
        # Include current-run candidates first so brand new duplicates are evaluated immediately.
        seen_sources = {source_path for source_path, _doc_id, _text in all_duplicate_candidates}
        for candidate in duplicate_candidates:
            if candidate[0] not in seen_sources:
                all_duplicate_candidates.append(candidate)
    duplicate_map = _find_duplicates(all_duplicate_candidates, config.review_thresholds.duplicate_similarity_threshold)

    for source_path, record in sorted(documents.items()):
        document = record.get("document") or {}
        word_total = int(document.get("word_count") or 0)
        doc_id = str(document.get("doc_id") or source_path)
        issues: list[tuple[str, str, str, str, float]] = []
        if document.get("empty_reason"):
            issues.append(("empty", "high", "Document produced no usable knowledge", str(document.get("empty_reason")), 0.2))
        if document.get("ocr_used"):
            issues.append(("ocr", "medium", "OCR-backed extraction used", "Review for text quality and hallucinated tokens.", 0.5))
        if word_total < config.review_thresholds.low_signal_word_count and not document.get("empty_reason"):
            issues.append(("low_signal", "medium", "Low-signal document", f"Only {word_total} words remained after normalization.", 0.45))
        if duplicate_map.get(source_path):
            duplicate_target = duplicate_map[source_path]
            document["duplicate_of"] = duplicate_target
            issues.append(("duplicate", "high", "Possible duplicate document", f"Near-duplicate of {Path(duplicate_target).name}.", 0.3))
        if document.get("probable_domain") == "general" and int(document.get("knowledge_item_count") or 0) <= 1:
            issues.append(("taxonomy", "low", "Weak classification signal", "Review taxonomy/preset if this document belongs to a known domain.", 0.5))
        ai_confidence = float(document.get("ai_confidence") or 0.0)
        if document.get("enrichment_mode") == "openai" and ai_confidence < config.review_thresholds.low_confidence_threshold:
            issues.append(("ai_low_confidence", "medium", "AI enrichment confidence is low", "Review the AI-suggested title and taxonomy.", ai_confidence))

        if issues:
            document["review_status"] = "flagged"
        elif document.get("review_status") != "rejected":
            document["review_status"] = "clean"
        record["document"] = document

        for kind, severity, title, detail, confidence in issues:
            review_id = f"{doc_id}::{kind}"
            previous = previous_map.get((doc_id, kind)) or {}
            items.append(
                {
                    "review_id": review_id,
                    "doc_id": doc_id,
                    "source_path": source_path,
                    "kind": kind,
                    "severity": severity,
                    "status": previous.get("status", "open"),
                    "title": title,
                    "detail": detail,
                    "suggestion": _default_suggestion(kind, document),
                    "confidence": confidence,
                    "created_at": previous.get("created_at", iso_now()),
                    "updated_at": iso_now(),
                    "override_title": previous.get("override_title", ""),
                    "override_domain": previous.get("override_domain", ""),
                    "resolution_note": previous.get("resolution_note", ""),
                }
            )

    return items


def _load_duplicate_candidates(documents: dict) -> list[tuple[str, str, str]]:
    candidates: list[tuple[str, str, str]] = []
    for source_path, record in sorted(documents.items()):
        document = record.get("document") or {}
        clean_path = Path(document.get("clean_text_path") or "")
        if not clean_path.exists():
            continue
        clean_text = clean_path.read_text(encoding="utf-8", errors="ignore")
        candidates.append((source_path, str(document.get("doc_id") or source_path), clean_text))
    return candidates


def _find_duplicates(duplicate_candidates: list[tuple[str, str, str]], threshold: float) -> dict[str, str]:
    duplicates: dict[str, str] = {}
    for index, (source_path, _doc_id, clean_text) in enumerate(duplicate_candidates):
        sample = clean_text[:3000]
        for prior_source_path, _prior_doc_id, prior_clean_text in duplicate_candidates[:index]:
            prior_sample = prior_clean_text[:3000]
            if not sample.strip() or not prior_sample.strip():
                continue
            similarity = SequenceMatcher(None, sample, prior_sample).ratio()
            if similarity >= threshold:
                duplicates[source_path] = prior_source_path
                break
    return duplicates


def _load_export_documents(state: dict) -> list[dict]:
    documents = []
    for record in (state.get("documents") or {}).values():
        document = record.get("document") or {}
        if document.get("empty_reason"):
            continue
        if document.get("review_status") == "rejected":
            continue
        documents.append(record)
    return documents


def _build_export_knowledge(records: list[dict]) -> list[SourceKnowledge]:
    items: list[SourceKnowledge] = []
    for record in records:
        document = record.get("document") or {}
        source_path = Path(document.get("source_path") or "")
        raw_text_path = Path(document.get("raw_text_path") or "")
        clean_text_path = Path(document.get("clean_text_path") or "")
        if not source_path.exists() or not raw_text_path.exists() or not clean_text_path.exists():
            continue
        raw_text = raw_text_path.read_text(encoding="utf-8", errors="ignore")
        clean_text = clean_text_path.read_text(encoding="utf-8", errors="ignore")
        item = build_source_knowledge(
            source_path=source_path,
            document_type=str(document.get("document_type") or "txt"),
            title=str(document.get("title") or source_path.stem),
            raw_text=raw_text,
            clean_text=clean_text,
            extraction_method=str(document.get("extraction_method") or "unknown"),
            ocr_used=bool(document.get("ocr_used")),
            source_folder_name=source_path.parent.name,
        )
        enrichment = (record.get("knowledge_summary") or {}).get("enrichment") or {}
        if enrichment.get("clean_title"):
            item.title = str(enrichment["clean_title"]).strip() or item.title
        items.append(item)
    return items


def _split_markdown_pages(content: str, target_words: int = EXPORT_WORD_TARGET) -> list[str]:
    content = content.strip()
    if not content:
        return []
    if word_count(content) <= target_words:
        return [content]
    sections = [section.strip() for section in content.split("\n## ") if section.strip()]
    if len(sections) == 1:
        return chunk_words(content, target_words)

    pages: list[str] = []
    current = ""
    for index, section in enumerate(sections):
        section_text = section if index == 0 and section.startswith("# ") else f"## {section}" if not section.startswith("# ") else section
        candidate = f"{current}\n\n{section_text}".strip() if current else section_text
        if current and word_count(candidate) > target_words:
            pages.append(current.strip())
            current = section_text
        else:
            current = candidate
    if current.strip():
        pages.append(current.strip())
    return [page for page in pages if page.strip()]


def _write_split_artifact(package_dir: Path, stem: str, pages: list[str], written_files: list[Path]) -> None:
    normalized_pages: list[str] = []
    for page in pages:
        normalized_pages.extend(_split_page_by_size(page))
    if not normalized_pages:
        return
    single = len(normalized_pages) == 1 and stem != "knowledge_core"
    for index, page in enumerate(normalized_pages, start=1):
        file_name = f"{stem}.md" if single else f"{stem}_{index:02d}.md"
        path = package_dir / file_name
        path.write_text(page.strip() + "\n", encoding="utf-8")
        written_files.append(path)


def _split_page_by_size(content: str) -> list[str]:
    page = content.strip()
    if not page:
        return []
    encoded_size = len(page.encode("utf-8"))
    if encoded_size <= TARGET_PACKAGE_BYTES:
        return [page]
    sections = [section.strip() for section in page.split("\n## ") if section.strip()]
    if len(sections) <= 1:
        return _split_by_paragraphs(page)
    pages: list[str] = []
    current = ""
    for index, section in enumerate(sections):
        chunk = section if index == 0 and section.startswith("# ") else f"## {section}" if not section.startswith("# ") else section
        candidate = f"{current}\n\n{chunk}".strip() if current else chunk
        if current and len(candidate.encode("utf-8")) > TARGET_PACKAGE_BYTES:
            pages.append(current.strip())
            current = chunk
        else:
            current = candidate
    if current.strip():
        pages.append(current.strip())
    return pages or [page]


def _split_by_paragraphs(content: str) -> list[str]:
    paragraphs = [part.strip() for part in content.split("\n\n") if part.strip()]
    pages: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if current and len(candidate.encode("utf-8")) > TARGET_PACKAGE_BYTES:
            pages.append(current.strip())
            current = paragraph
        else:
            current = candidate
    if current.strip():
        pages.append(current.strip())
    return pages or [content.strip()]


def _build_provenance_items(knowledge_items: list[SourceKnowledge]) -> list[dict]:
    rows: list[dict] = []
    for item in knowledge_items:
        accepted_index = {candidate.normalized_key: candidate for candidate in item.accepted_candidates}
        for promoted in item.promoted_items:
            matching_candidates = [
                candidate
                for candidate in item.accepted_candidates
                if candidate.target_type == promoted.target_type and candidate.body.strip() == promoted.body.strip()
            ]
            if not matching_candidates and promoted.target_type == "glossary":
                key = f"glossary::{promoted.title.lower()}"
                candidate = accepted_index.get(key)
                if candidate:
                    matching_candidates = [candidate]
            rows.append(
                {
                    "document_id": item.document_id,
                    "source_filename": item.source_filename,
                    "target_type": promoted.target_type,
                    "title": promoted.title,
                    "body": promoted.body,
                    "confidence": promoted.confidence,
                    "supporting_sources": promoted.supporting_sources,
                    "provenance": [
                        {
                            "source_document_id": candidate.source_document_id,
                            "source_chunk_id": candidate.source_chunk_id,
                            "source_filename": candidate.provenance.get("source_filename"),
                            "source_path": candidate.provenance.get("source_path"),
                            "section_heading": candidate.provenance.get("section_heading"),
                            "confidence": candidate.score,
                            "reasons": candidate.reasons,
                        }
                        for candidate in matching_candidates
                    ],
                }
            )
    return rows


def _merge_ai_hints(knowledge: SourceKnowledge, enrichment: dict) -> dict:
    hints = {
        "synopsis": str(enrichment.get("synopsis") or "").strip(),
        "glossary_hints": list(enrichment.get("glossary_hints") or []),
        "review_notes": list(enrichment.get("review_notes") or []),
    }
    if not hints["synopsis"] and knowledge.summary_points:
        hints["synopsis"] = " ".join(knowledge.summary_points[:3]).strip()
    return hints


def _default_suggestion(kind: str, document: dict) -> str:
    if kind == "duplicate":
        return "Reject this duplicate or keep it as an independent source."
    if kind == "taxonomy":
        return f"Override the domain if {document.get('source_filename')} belongs to a specific knowledge area."
    if kind == "ai_low_confidence":
        return "Review the AI-suggested title/domain before exporting."
    return "Approve, reject, or edit the document metadata."


def _build_package_index(config: ProjectConfig, written_files: list[Path]) -> str:
    lines = [
        "# Package Index",
        "",
        f"Project: {config.project_name}",
        f"Profile: {config.export_profile}",
        "",
        "Use this file to understand what each upload file contains.",
        "",
    ]
    for path in sorted(written_files, key=lambda item: item.name):
        purpose = _describe_package_file(path.name)
        lines.append(f"- `{path.name}`: {purpose}")
    lines.append("")
    return "\n".join(lines)


def _build_fallback_knowledge_core(knowledge_items: list[SourceKnowledge]) -> str:
    lines = ["# Knowledge Core", ""]
    for item in knowledge_items:
        lines.append(f"## {item.title}")
        if item.summary_points:
            for point in item.summary_points[:4]:
                lines.append(f"- {point}")
        elif item.clean_text.strip():
            excerpt = item.clean_text.strip().splitlines()[0][:300]
            lines.append(excerpt)
        lines.append(f"Source: {item.source_filename}")
        lines.append("")
    return "\n".join(lines).strip()


def _describe_package_file(file_name: str) -> str:
    if file_name.startswith("knowledge_core_"):
        return "Synthesized high-value knowledge for broad GPT answers."
    if file_name.startswith("reference_facts"):
        return "Short precise facts and constraints extracted from source documents."
    if file_name.startswith("procedures"):
        return "Step-based instructions and workflows."
    if file_name.startswith("glossary"):
        return "Terms and definitions."
    if file_name.startswith("entities"):
        return "Named entities, systems, parts, or standards."
    if file_name == "package_index.md":
        return "Guide to the package contents."
    return "Package artifact."


def _validate_package_outputs(written_files: list[Path], reviews: dict) -> list[str]:
    messages: list[str] = []
    seen_hashes: dict[str, Path] = {}
    for path in written_files:
        if path.suffix.lower() != ".md":
            messages.append(f"Non-markdown package file detected: {path.name}")
        if path.stat().st_size > MAX_PACKAGE_FILE_BYTES:
            messages.append(f"Oversized package file: {path.name}")
        digest = sha256_file(path)
        if digest in seen_hashes:
            messages.append(f"Duplicate package content: {path.name} matches {seen_hashes[digest].name}")
        else:
            seen_hashes[digest] = path
    open_reviews = [item for item in (reviews.get("items") or []) if item.get("status") == "open"]
    if open_reviews:
        messages.append(f"{len(open_reviews)} unresolved review item(s) remain.")
    return messages
