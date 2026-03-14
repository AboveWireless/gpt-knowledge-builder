from __future__ import annotations

import fnmatch
import json
import shutil
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

from ..compiler_models import SourceKnowledge
from ..extractors import extract, get_supported_doc_type
from ..naming import make_safe_corpus_name
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
MAX_SOURCE_FILE_BYTES = 32 * 1024 * 1024
PREVIEW_UNIT_WORDS = 220
RECENT_ISSUE_LIMIT = 12


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


def diagnostics_paths(project_root: Path) -> dict[str, Path]:
    diagnostics_dir = state_root(project_root.resolve()) / "exports" / "diagnostics"
    return {
        "diagnostics_dir": diagnostics_dir,
        "json_path": diagnostics_dir / "corpus_diagnostics.json",
        "markdown_path": diagnostics_dir / "corpus_diagnostics.md",
    }


def scan_project(project_root: Path, force: bool = False) -> dict:
    return _scan_project_paths(project_root.resolve(), force=force)


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


def retry_document_extraction(project_root: Path, review_id: str, strategy: str = "default") -> dict:
    project_root = project_root.resolve()
    review_store = load_reviews(project_root)
    target = next((item for item in (review_store.get("items") or []) if item.get("review_id") == review_id), None)
    if target is None:
        raise ValueError(f"Review item not found: {review_id}")
    source_path = Path(str(target.get("source_path") or "")).resolve()
    summary = _scan_project_paths(
        project_root,
        force=True,
        target_paths={str(source_path)},
        strategy_overrides={str(source_path): strategy or "default"},
    )
    return {
        "review_id": review_id,
        "source_path": str(source_path),
        "strategy": strategy or "default",
        "summary": summary,
    }


def retry_review_items(
    project_root: Path,
    *,
    kind: str = "all",
    document_type: str = "all",
    extraction_status: str = "all",
    strategy: str | None = None,
    status: str = "open",
) -> dict:
    project_root = project_root.resolve()
    state = load_state(project_root)
    reviews = load_reviews(project_root)
    documents = state.get("documents") or {}
    matched_sources: list[str] = []
    seen: set[str] = set()

    for item in reviews.get("items") or []:
        if status != "all" and str(item.get("status") or "") != status:
            continue
        if kind != "all" and str(item.get("kind") or "") != kind:
            continue
        source_path = str(item.get("source_path") or "")
        if not source_path or source_path in seen:
            continue
        document = (documents.get(source_path) or {}).get("document") or {}
        if document_type != "all" and str(document.get("document_type") or "") != document_type:
            continue
        if extraction_status != "all" and str(document.get("extraction_status") or "") != extraction_status:
            continue
        seen.add(source_path)
        matched_sources.append(source_path)

    summary = {
        "scanned": 0,
        "processed": 0,
        "skipped": 0,
        "removed": 0,
        "partial": 0,
        "failed": 0,
        "unsupported": 0,
        "metadata_only": 0,
        "duplicates": 0,
        "review_required": 0,
    }
    if matched_sources:
        summary = _scan_project_paths(
            project_root,
            force=True,
            target_paths=set(matched_sources),
            strategy_overrides={source_path: strategy or "default" for source_path in matched_sources},
        )

    return {
        "matched_sources": matched_sources,
        "kind": kind,
        "document_type": document_type,
        "extraction_status": extraction_status,
        "strategy": strategy or "default",
        "summary": summary,
    }


def promote_duplicate_as_canonical(project_root: Path, review_id: str) -> dict:
    project_root = project_root.resolve()
    state = load_state(project_root)
    reviews = load_reviews(project_root)
    target = next((item for item in (reviews.get("items") or []) if item.get("review_id") == review_id), None)
    if target is None:
        raise ValueError(f"Review item not found: {review_id}")
    if str(target.get("kind") or "") != "duplicate":
        raise ValueError("Selected review item is not a duplicate.")

    documents = state.get("documents") or {}
    canonical_source = str(target.get("source_path") or "")
    canonical_document = ((documents.get(canonical_source) or {}).get("document") or {})
    duplicate_source = str(canonical_document.get("duplicate_of") or "")
    if not duplicate_source:
        raise ValueError("Selected document is not currently marked as a duplicate.")

    for source_path, record in documents.items():
        document = record.get("document") or {}
        if source_path in {canonical_source, duplicate_source} or str(document.get("duplicate_canonical_source") or "") in {canonical_source, duplicate_source}:
            document["duplicate_canonical_source"] = canonical_source
            document["duplicate_of"] = None if source_path == canonical_source else canonical_source
            document["updated_at"] = iso_now()
            record["document"] = document
            documents[source_path] = record

    review_items = _build_review_queue(project_root, load_project_config(project_root), documents, reviews.get("items") or [])
    reviews["items"] = review_items
    state["documents"] = documents
    save_state(project_root, state)
    save_reviews(project_root, reviews)
    append_log(state_root(project_root) / "logs" / "project.log", f"duplicate_promote canonical={canonical_source} duplicate={duplicate_source}")
    return {
        "review_id": review_id,
        "canonical_source": canonical_source,
        "duplicate_source": duplicate_source,
    }


def export_diagnostics_report(project_root: Path) -> dict:
    project_root = project_root.resolve()
    state = load_state(project_root)
    reviews = load_reviews(project_root)
    config = load_project_config(project_root)
    paths = diagnostics_paths(project_root)
    ensure_dir(paths["diagnostics_dir"])

    documents = state.get("documents") or {}
    degraded_documents: list[dict] = []
    for source_path, record in sorted(documents.items()):
        document = record.get("document") or {}
        status = str(document.get("extraction_status") or "unknown")
        if status == "success" and not document.get("duplicate_of"):
            continue
        degraded_documents.append(
            {
                "source_path": source_path,
                "status": status,
                "reason": _document_issue_reason(document),
                "document_type": document.get("document_type", ""),
                "duplicate_of": document.get("duplicate_of", ""),
            }
        )

    open_reviews = [item for item in (reviews.get("items") or []) if item.get("status") == "open"]
    payload = {
        "generated_at": iso_now(),
        "project_name": config.project_name,
        "corpus_metrics": {
            "documents": len(documents),
            "partial": sum(1 for record in documents.values() if (record.get("document") or {}).get("extraction_status") == "partial"),
            "failed": sum(1 for record in documents.values() if (record.get("document") or {}).get("extraction_status") == "failed"),
            "unsupported": sum(1 for record in documents.values() if (record.get("document") or {}).get("extraction_status") == "unsupported"),
            "metadata_only": sum(1 for record in documents.values() if (record.get("document") or {}).get("extraction_status") == "metadata_only"),
            "duplicates": sum(1 for record in documents.values() if (record.get("document") or {}).get("duplicate_of")),
            "open_reviews": len(open_reviews),
        },
        "degraded_documents": degraded_documents,
        "open_reviews": open_reviews,
    }
    write_json(paths["json_path"], payload)

    markdown_lines = [
        "# Corpus Diagnostics",
        "",
        f"Project: {config.project_name}",
        f"Generated: {payload['generated_at']}",
        "",
        "## Corpus Metrics",
        "",
        f"- Documents: {payload['corpus_metrics']['documents']}",
        f"- Partial: {payload['corpus_metrics']['partial']}",
        f"- Failed: {payload['corpus_metrics']['failed']}",
        f"- Unsupported: {payload['corpus_metrics']['unsupported']}",
        f"- Metadata Only: {payload['corpus_metrics']['metadata_only']}",
        f"- Duplicates: {payload['corpus_metrics']['duplicates']}",
        f"- Open Reviews: {payload['corpus_metrics']['open_reviews']}",
        "",
        "## Degraded Documents",
        "",
    ]
    if degraded_documents:
        for item in degraded_documents:
            markdown_lines.append(
                f"- `{Path(str(item['source_path'])).name}` [{item['status']}] {item['reason']}"
            )
    else:
        markdown_lines.append("- None")
    markdown_lines.extend(["", "## Open Reviews", ""])
    if open_reviews:
        for item in open_reviews:
            markdown_lines.append(
                f"- `{Path(str(item.get('source_path') or '')).name}` [{item.get('severity', 'unknown')}] "
                f"{item.get('kind', 'review')} :: {item.get('title', '')}"
            )
    else:
        markdown_lines.append("- None")
    paths["markdown_path"].write_text("\n".join(markdown_lines).strip() + "\n", encoding="utf-8")

    append_log(state_root(project_root) / "logs" / "project.log", f"diagnostics json={paths['json_path']} markdown={paths['markdown_path']}")
    return {
        "diagnostics_dir": str(paths["diagnostics_dir"]),
        "json_path": str(paths["json_path"]),
        "markdown_path": str(paths["markdown_path"]),
    }


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
            raw_path = _safe_record_path(doc.get("raw_text_path"))
            clean_path = _safe_record_path(doc.get("clean_text_path"))
            if raw_path and raw_path.exists():
                shutil.copyfile(raw_path, debug_dir / f"{source_name}__raw.txt")
            if clean_path and clean_path.exists():
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
        "package_index_file": str(package_index_path),
        "provenance_manifest": str(provenance_manifest_path),
        "knowledge_items_file": str(provenance_items_path),
        "validation_messages": validation_messages,
    }


def _scan_project_paths(
    project_root: Path,
    *,
    force: bool,
    target_paths: set[str] | None = None,
    strategy_overrides: dict[str, str] | None = None,
) -> dict:
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
    strategy_overrides = strategy_overrides or {}
    run_summary = {
        "scanned": 0,
        "processed": 0,
        "skipped": 0,
        "removed": 0,
        "partial": 0,
        "failed": 0,
        "unsupported": 0,
        "metadata_only": 0,
        "duplicates": 0,
        "review_required": 0,
    }

    discovered = _discover_project_files(project_root, config)
    if target_paths is not None:
        target_paths = {str(Path(path).resolve()) for path in target_paths}
        discovered = [path for path in discovered if str(path.resolve()) in target_paths]

    for path in discovered:
        path = path.resolve()
        source_key = str(path)
        seen_paths.add(source_key)
        run_summary["scanned"] += 1

        checksum = sha256_file(path)
        existing = documents.get(source_key) or {}
        if _should_skip_existing(existing, checksum, force):
            run_summary["skipped"] += 1
            continue

        retry_strategy = strategy_overrides.get(source_key, "default")
        record = _build_document_record(
            project_root=project_root,
            config=config,
            path=path,
            doc_type=get_supported_doc_type(path),
            checksum=checksum,
            existing=existing,
            raw_cache_dir=raw_cache_dir,
            clean_cache_dir=clean_cache_dir,
            model_cache_dir=model_cache_dir,
            provider_api_key=provider_api_key,
            retry_strategy=retry_strategy,
        )
        documents[source_key] = record
        status = str((record.get("document") or {}).get("extraction_status") or "")
        run_summary["processed"] += 1
        if status in {"partial", "failed", "unsupported", "metadata_only"}:
            run_summary[status] += 1

    if target_paths is None:
        removed_paths = [source_path for source_path in list(documents.keys()) if source_path not in seen_paths]
        for source_path in removed_paths:
            record = documents.pop(source_path)
            run_summary["removed"] += 1
            doc = record.get("document") or {}
            for cache_key in ("raw_text_path", "clean_text_path"):
                cache_path = _safe_record_path(doc.get(cache_key))
                if cache_path and cache_path.exists():
                    cache_path.unlink()

    review_items = _build_review_queue(project_root, config, documents, review_store.get("items") or [])
    review_store["items"] = review_items
    report = _build_scan_report(documents, review_items, run_summary)

    project_state["documents"] = documents
    project_state["exports"] = project_state.get("exports") or []
    project_state["last_scan_report"] = report
    save_state(project_root, project_state)
    save_reviews(project_root, review_store)
    append_log(
        root / "logs" / "project.log",
        (
            "scan "
            f"scanned={report['scanned']} processed={report['processed']} skipped={report['skipped']} removed={report['removed']} "
            f"partial={report['partial']} failed={report['failed']} unsupported={report['unsupported']} "
            f"metadata_only={report['metadata_only']} review_required={report['review_required']} duplicates={report['duplicates']}"
        ),
    )
    return report


def _build_document_record(
    *,
    project_root: Path,
    config: ProjectConfig,
    path: Path,
    doc_type: str | None,
    checksum: str,
    existing: dict,
    raw_cache_dir: Path,
    clean_cache_dir: Path,
    model_cache_dir: Path,
    provider_api_key: str,
    retry_strategy: str,
) -> dict:
    existing_doc = existing.get("document") or {}
    raw_cache_path = raw_cache_dir / f"{checksum[:16]}.txt"
    clean_cache_path = clean_cache_dir / f"{checksum[:16]}.txt"
    strategy_name = retry_strategy or "default"

    if doc_type is None:
        return _degraded_document_record(
            project_root=project_root,
            config=config,
            path=path,
            checksum=checksum,
            existing_doc=existing_doc,
            doc_type="unknown",
            extraction_status="unsupported",
            extraction_method="unsupported",
            warnings=[f"Unsupported document type: {path.suffix.lower() or 'unknown'}"],
            failure_reason=f"Unsupported document type: {path.suffix.lower() or 'unknown'}",
            retry_strategy=strategy_name,
        )
    if MAX_SOURCE_FILE_BYTES and path.stat().st_size > MAX_SOURCE_FILE_BYTES:
        return _degraded_document_record(
            project_root=project_root,
            config=config,
            path=path,
            checksum=checksum,
            existing_doc=existing_doc,
            doc_type=doc_type,
            extraction_status="metadata_only",
            extraction_method=f"{doc_type}-metadata-only",
            warnings=[f"Source file exceeds MAX_SOURCE_FILE_BYTES ({MAX_SOURCE_FILE_BYTES} bytes)."],
            failure_reason="File skipped because it exceeded the source size limit.",
            retry_strategy=strategy_name,
        )

    extracted = extract(path, doc_type, None, None if strategy_name == "default" else strategy_name)
    raw_text = extracted.text or ""
    clean_text = clean_text_for_knowledge(raw_text)
    raw_cache_path.write_text(raw_text, encoding="utf-8")
    clean_cache_path.write_text(clean_text, encoding="utf-8")
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
    enrichment = run_optional_enrichment(config, path, knowledge, model_cache_dir, api_key=provider_api_key)
    preview_mode, preview_units, preview_excerpt = _build_preview_data(path, doc_type, extracted.pages, clean_text, extracted.preview_excerpt)
    warnings = _unique_texts(list(extracted.warnings) + list(knowledge.warnings))
    return {
        "fingerprint": {
            "source_path": str(path),
            "checksum": checksum,
            "size_bytes": path.stat().st_size,
            "modified_at": mtime(path).isoformat(),
        },
        "document": {
            "doc_id": knowledge.document_id,
            "source_path": str(path),
            "source_filename": path.name,
            "source_root": _find_source_root(project_root, config, path),
            "document_type": doc_type,
            "checksum": checksum,
            "title": enrichment.get("clean_title") or knowledge.title,
            "clean_text_path": str(clean_cache_path),
            "raw_text_path": str(raw_cache_path),
            "extraction_method": extracted.extraction_method,
            "extraction_status": extracted.extraction_status,
            "failure_reason": extracted.failure_reason or "",
            "ocr_used": extracted.ocr_used,
            "quality_score": float(extracted.quality_score),
            "warnings": warnings,
            "word_count": word_count(clean_text),
            "chunk_count": len(knowledge.chunks),
            "probable_domain": enrichment.get("taxonomy", {}).get("domain") or _infer_probable_domain(path, knowledge),
            "topic": enrichment.get("taxonomy", {}).get("topic") or _fallback_topic_label(knowledge),
            "review_status": "flagged" if extracted.extraction_status != "success" or knowledge.empty_reason else "clean",
            "empty_reason": knowledge.empty_reason,
            "duplicate_of": existing_doc.get("duplicate_of"),
            "duplicate_canonical_source": existing_doc.get("duplicate_canonical_source", str(path)),
            "knowledge_item_count": len(knowledge.promoted_items),
            "updated_at": iso_now(),
            "enrichment_cache_key": enrichment.get("cache_key", ""),
            "enrichment_mode": enrichment.get("mode", "deterministic"),
            "ai_confidence": enrichment.get("confidence", 0.0),
            "preview_mode": preview_mode,
            "preview_units": preview_units,
            "preview_cache": existing_doc.get("preview_cache") or {},
            "last_preview_error": existing_doc.get("last_preview_error", ""),
            "preview_excerpt": preview_excerpt,
            "last_retry_strategy": strategy_name,
            "retry_strategies": _merge_retry_strategies(existing_doc.get("retry_strategies"), strategy_name),
        },
        "knowledge_summary": {
            "summary_points": knowledge.summary_points,
            "warnings": knowledge.warnings,
            "accepted_candidates": json_ready(knowledge.accepted_candidates),
            "promoted_items": json_ready(knowledge.promoted_items),
            "ai_hints": _merge_ai_hints(knowledge, enrichment),
            "enrichment": json_ready(enrichment),
        },
    }


def _degraded_document_record(
    *,
    project_root: Path,
    config: ProjectConfig,
    path: Path,
    checksum: str,
    existing_doc: dict,
    doc_type: str,
    extraction_status: str,
    extraction_method: str,
    warnings: list[str],
    failure_reason: str,
    retry_strategy: str,
) -> dict:
    preview_excerpt = failure_reason or (warnings[0] if warnings else "No preview available.")
    return {
        "fingerprint": {
            "source_path": str(path),
            "checksum": checksum,
            "size_bytes": path.stat().st_size,
            "modified_at": mtime(path).isoformat(),
        },
        "document": {
            "doc_id": existing_doc.get("doc_id") or checksum[:16],
            "source_path": str(path),
            "source_filename": path.name,
            "source_root": _find_source_root(project_root, config, path),
            "document_type": doc_type,
            "checksum": checksum,
            "title": existing_doc.get("title") or path.stem,
            "clean_text_path": "",
            "raw_text_path": "",
            "extraction_method": extraction_method,
            "extraction_status": extraction_status,
            "failure_reason": failure_reason,
            "ocr_used": False,
            "quality_score": 0.0 if extraction_status == "unsupported" else 0.2,
            "warnings": warnings,
            "word_count": 0,
            "chunk_count": 0,
            "probable_domain": "general",
            "topic": "general",
            "review_status": "flagged",
            "empty_reason": extraction_status,
            "duplicate_of": existing_doc.get("duplicate_of"),
            "duplicate_canonical_source": existing_doc.get("duplicate_canonical_source", str(path)),
            "knowledge_item_count": 0,
            "updated_at": iso_now(),
            "enrichment_cache_key": "",
            "enrichment_mode": "deterministic",
            "ai_confidence": 0.0,
            "preview_mode": "text",
            "preview_units": [{"label": "Preview", "text": preview_excerpt, "page_number": 1, "ocr_used": False}],
            "preview_cache": existing_doc.get("preview_cache") or {},
            "last_preview_error": existing_doc.get("last_preview_error", ""),
            "preview_excerpt": preview_excerpt,
            "last_retry_strategy": retry_strategy,
            "retry_strategies": _merge_retry_strategies(existing_doc.get("retry_strategies"), retry_strategy),
        },
        "knowledge_summary": {
            "summary_points": [],
            "warnings": warnings,
            "accepted_candidates": [],
            "promoted_items": [],
            "ai_hints": {"synopsis": "", "glossary_hints": [], "review_notes": warnings[:4]},
            "enrichment": {"mode": "deterministic", "taxonomy": {"domain": "general", "topic": "general"}, "confidence": 0.0},
        },
    }


def _should_skip_existing(existing: dict, checksum: str, force: bool) -> bool:
    if force or not existing:
        return False
    return str((existing.get("fingerprint") or {}).get("checksum") or "") == checksum


def _discover_project_files(project_root: Path, config: ProjectConfig) -> list[Path]:
    files: list[Path] = []
    output_root = resolve_project_path(project_root, config.output_root).resolve()
    for source_root_value in config.source_roots:
        source_root = resolve_project_path(project_root, source_root_value)
        if not source_root.exists():
            continue
        for discovered in source_root.rglob("*"):
            if not discovered.is_file():
                continue
            discovered = discovered.resolve()
            if _should_skip_project_path(output_root, discovered):
                continue
            rel = discovered.relative_to(source_root).as_posix()
            if config.include_globs and not _matches_any(rel, config.include_globs):
                continue
            if config.exclude_globs and _matches_any(rel, config.exclude_globs):
                continue
            files.append(discovered)
    return sorted(set(files))


def _should_skip_project_path(output_root: Path, path: Path) -> bool:
    hidden_markers = {".git", ".svn", ".hg", "__pycache__", ".knowledge_builder"}
    generated_suffixes = ("_GPT_KNOWLEDGE", "_DEBUG")
    if any(part in hidden_markers for part in path.parts):
        return True
    if any(part.endswith(generated_suffixes) for part in path.parts if part):
        return True
    try:
        path.relative_to(output_root)
        return True
    except ValueError:
        return False


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


def _build_review_queue(project_root: Path, config: ProjectConfig, documents: dict, previous_items: list[dict]) -> list[dict]:
    items: list[dict] = []
    previous_map = {str(item.get("review_id") or ""): item for item in previous_items}
    duplicate_map = _find_duplicates(
        _load_duplicate_candidates(documents),
        config.review_thresholds.duplicate_similarity_threshold,
        {
            source_path: str((record.get("document") or {}).get("duplicate_canonical_source") or "")
            for source_path, record in documents.items()
        },
    )
    canonical_sources = set(duplicate_map.values())

    for source_path, record in sorted(documents.items()):
        document = record.get("document") or {}
        word_total = int(document.get("word_count") or 0)
        doc_id = str(document.get("doc_id") or source_path)
        issues: list[tuple[str, str, str, str, float]] = []
        extraction_status = str(document.get("extraction_status") or "unknown")

        if source_path in duplicate_map:
            duplicate_target = duplicate_map[source_path]
            document["duplicate_of"] = duplicate_target
            document["duplicate_canonical_source"] = duplicate_target
            issues.append(("duplicate", "high", "Possible duplicate document", f"Near-duplicate of {Path(duplicate_target).name}.", 0.3))
        elif source_path in canonical_sources:
            document["duplicate_of"] = None
            document["duplicate_canonical_source"] = str(document.get("duplicate_canonical_source") or source_path)
        else:
            document["duplicate_of"] = None
            document["duplicate_canonical_source"] = str(document.get("duplicate_canonical_source") or source_path)

        if extraction_status in {"failed", "unsupported", "metadata_only", "partial"}:
            severity = "high" if extraction_status in {"failed", "unsupported"} else "medium"
            issues.append(("extraction_issue", severity, "Extraction requires review", _document_issue_reason(document), 0.35 if extraction_status == "partial" else 0.2))
        if not word_total and extraction_status not in {"unsupported", "metadata_only"}:
            issues.append(("empty", "high", "Document produced no usable knowledge", _document_issue_reason(document), 0.15))
        if document.get("ocr_used"):
            issues.append(("ocr", "medium", "OCR-backed extraction used", "Review for text quality and hallucinated tokens.", 0.5))
        if word_total < config.review_thresholds.low_signal_word_count and word_total > 0 and extraction_status not in {"unsupported", "metadata_only", "failed"}:
            issues.append(("low_signal", "medium", "Low-signal document", f"Only {word_total} words remained after normalization.", 0.45))
        if document.get("probable_domain") == "general" and int(document.get("knowledge_item_count") or 0) <= 1 and word_total > 0:
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
            previous = previous_map.get(review_id) or {}
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


def _load_duplicate_candidates(documents: dict) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for source_path, record in sorted(documents.items()):
        document = record.get("document") or {}
        clean_path = _safe_record_path(document.get("clean_text_path"))
        if not clean_path or not clean_path.exists():
            continue
        clean_text = clean_path.read_text(encoding="utf-8", errors="ignore")
        if clean_text.strip():
            candidates.append((source_path, clean_text))
    return candidates


def _find_duplicates(duplicate_candidates: list[tuple[str, str]], threshold: float, preferred_canonicals: dict[str, str]) -> dict[str, str]:
    if len(duplicate_candidates) < 2:
        return {}
    duplicates: dict[str, str] = {}
    parents = list(range(len(duplicate_candidates)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for index, (source_path, clean_text) in enumerate(duplicate_candidates):
        sample = clean_text[:3000]
        for prior_index, (prior_source_path, prior_clean_text) in enumerate(duplicate_candidates[:index]):
            prior_sample = prior_clean_text[:3000]
            if not sample.strip() or not prior_sample.strip():
                continue
            similarity = SequenceMatcher(None, sample, prior_sample).ratio()
            if similarity >= threshold:
                union(index, prior_index)

    groups: dict[int, list[str]] = {}
    for index, (source_path, _clean_text) in enumerate(duplicate_candidates):
        groups.setdefault(find(index), []).append(source_path)

    for group in groups.values():
        if len(group) < 2:
            continue
        votes: dict[str, int] = {}
        for source_path in group:
            preferred = preferred_canonicals.get(source_path, "")
            if preferred in group:
                votes[preferred] = votes.get(preferred, 0) + 1
        canonical = sorted(group)[0]
        if votes:
            canonical = sorted(votes.items(), key=lambda item: (-item[1], item[0]))[0][0]
        for source_path in group:
            if source_path != canonical:
                duplicates[source_path] = canonical
    return duplicates


def _load_export_documents(state: dict) -> list[dict]:
    documents = []
    for record in (state.get("documents") or {}).values():
        document = record.get("document") or {}
        if document.get("review_status") == "rejected":
            continue
        if str(document.get("extraction_status") or "") in {"failed", "unsupported", "metadata_only"}:
            continue
        clean_path = _safe_record_path(document.get("clean_text_path"))
        raw_path = _safe_record_path(document.get("raw_text_path"))
        if not clean_path or not raw_path or not clean_path.exists() or not raw_path.exists():
            continue
        documents.append(record)
    return documents


def _build_export_knowledge(records: list[dict]) -> list[SourceKnowledge]:
    items: list[SourceKnowledge] = []
    for record in records:
        document = record.get("document") or {}
        source_path = _safe_record_path(document.get("source_path"))
        raw_text_path = _safe_record_path(document.get("raw_text_path"))
        clean_text_path = _safe_record_path(document.get("clean_text_path"))
        if not source_path or not raw_text_path or not clean_text_path:
            continue
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
    if kind in {"extraction_issue", "empty"}:
        return "Retry extraction or accept the degraded output after inspecting the preview."
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


def _build_scan_report(documents: dict, review_items: list[dict], run_summary: dict) -> dict:
    report = dict(run_summary)
    report["documents"] = len(documents)
    report["document_types"] = {}
    report["partial_docs"] = 0
    report["failed_docs"] = 0
    report["metadata_only_docs"] = 0
    report["unsupported_docs"] = 0
    open_reviews = [item for item in review_items if item.get("status") == "open"]
    recent_issues: list[dict] = []

    for source_path, record in sorted(documents.items()):
        document = record.get("document") or {}
        doc_type = str(document.get("document_type") or "unknown")
        report["document_types"][doc_type] = report["document_types"].get(doc_type, 0) + 1
        status = str(document.get("extraction_status") or "unknown")
        if status == "partial":
            report["partial_docs"] += 1
        elif status == "failed":
            report["failed_docs"] += 1
        elif status == "metadata_only":
            report["metadata_only_docs"] += 1
        elif status == "unsupported":
            report["unsupported_docs"] += 1

        if status in {"partial", "failed", "metadata_only", "unsupported"}:
            recent_issues.append({"source_path": source_path, "status": status, "reason": _document_issue_reason(document)})
        elif document.get("duplicate_of"):
            recent_issues.append(
                {
                    "source_path": source_path,
                    "status": "duplicate",
                    "reason": f"Near-duplicate of {Path(str(document.get('duplicate_of') or '')).name}.",
                }
            )

    report["partial"] = report["partial_docs"]
    report["failed"] = report["failed_docs"]
    report["metadata_only"] = report["metadata_only_docs"]
    report["unsupported"] = report["unsupported_docs"]
    report["duplicates"] = sum(1 for record in documents.values() if (record.get("document") or {}).get("duplicate_of"))
    report["open_reviews"] = len(open_reviews)
    report["flagged"] = len(open_reviews)
    report["review_required"] = len(open_reviews)

    for item in open_reviews:
        if len(recent_issues) >= RECENT_ISSUE_LIMIT:
            break
        recent_issues.append(
            {
                "source_path": str(item.get("source_path") or ""),
                "status": str(item.get("kind") or "review"),
                "reason": str(item.get("title") or item.get("detail") or "Review required."),
            }
        )
    report["recent_issues"] = recent_issues[:RECENT_ISSUE_LIMIT]
    return report


def _document_issue_reason(document: dict) -> str:
    warnings = document.get("warnings") or []
    if warnings:
        return str(warnings[0])
    failure_reason = str(document.get("failure_reason") or "").strip()
    if failure_reason:
        return failure_reason
    return f"Extraction finished with status {document.get('extraction_status', 'unknown')}."


def _build_preview_data(path: Path, doc_type: str, pages: list, clean_text: str, fallback_excerpt: str) -> tuple[str, list[dict], str]:
    excerpt = clean_text.strip() or fallback_excerpt.strip() or path.stem
    if doc_type == "pdf":
        units = []
        for page in pages or []:
            text = str(getattr(page, "text", "") or "").strip() or excerpt
            units.append(
                {
                    "label": f"Page {getattr(page, 'page_number', len(units) + 1)}",
                    "text": text,
                    "page_number": getattr(page, "page_number", len(units) + 1),
                    "ocr_used": bool(getattr(page, "ocr_used", False)),
                }
            )
        if not units:
            units = [{"label": "Preview", "text": excerpt, "page_number": 1, "ocr_used": False}]
        return "pdf_image", units, excerpt[:900]

    if pages and len(pages) > 1:
        units = [
            {
                "label": f"Page {getattr(page, 'page_number', index + 1)}",
                "text": str(getattr(page, "text", "") or "").strip() or excerpt,
                "page_number": getattr(page, "page_number", index + 1),
                "ocr_used": bool(getattr(page, "ocr_used", False)),
            }
            for index, page in enumerate(pages)
        ]
        return "text", units, excerpt[:900]

    chunks = chunk_words(excerpt, PREVIEW_UNIT_WORDS)
    if not chunks:
        chunks = [path.stem]
    return (
        "text",
        [
            {
                "label": f"Excerpt {index + 1}" if len(chunks) > 1 else "Preview",
                "text": chunk,
                "page_number": index + 1,
                "ocr_used": False,
            }
            for index, chunk in enumerate(chunks)
        ],
        excerpt[:900],
    )


def _merge_retry_strategies(existing, latest: str) -> list[str]:
    values: list[str] = []
    for value in list(existing or []) + [latest or "default"]:
        text = str(value or "default").strip() or "default"
        if text not in values:
            values.append(text)
    return values or ["default"]


def _unique_texts(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _safe_record_path(value) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    return Path(text)
