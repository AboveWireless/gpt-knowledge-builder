from __future__ import annotations

from dataclasses import dataclass
import fnmatch
from pathlib import Path

from .analysis import analyze_document
from .chunking import build_chunks
from .extractors import extract, get_supported_doc_type
from .manifest import ManifestStore
from .models import Config, DocumentRecord, KnowledgeMetadata, ManifestRecord, ProcessingFailure, SourceDocument
from .naming import canonical_filename, choose_doc_date, is_canonical_filename
from .normalization import normalize_pages, normalize_text
from .outputs import build_aggregate_outputs, load_document_state, log_pipeline, remove_derived_outputs, write_document_state
from .structured import extract_structured_records
from .taxonomy import resolve_taxonomy
from .utils import ensure_dir, iso_now, mtime, parse_since, sha256_file
from .writer import render_markdown, write_markdown


@dataclass(slots=True)
class Action:
    kind: str
    detail: str


@dataclass(slots=True)
class RunResult:
    actions: list[Action]
    scanned: int
    written: int
    skipped: int
    deleted: int


def scan(config: Config, dry_run: bool = False, force: bool = False, since: str | None = None) -> RunResult:
    return _run_pipeline(config, dry_run=dry_run, force=force, since=since, mode="scan")


def validate(config: Config) -> list[str]:
    messages: list[str] = []
    for root in config.input_roots:
        if not root.exists():
            messages.append(f"Input root missing: {root}")
        elif _is_within(config.output_root, root):
            messages.append(f"Output root is inside an input root and will be ignored during scanning: {config.output_root}")
    if not config.output_root.exists():
        messages.append(f"Output root missing (will be created by scan): {config.output_root}")
    else:
        for md in config.output_root.glob("*.md"):
            if not is_canonical_filename(md.name):
                messages.append(f"Non-canonical output filename: {md.name}")
    for rule in config.taxonomy_rules:
        if "**" not in rule.pattern and "*" not in rule.pattern:
            messages.append(f"Taxonomy rule has no wildcard, may be too strict: {rule.pattern}")
    if config.chunking.overlap_words >= config.chunking.target_words:
        messages.append("chunking.overlap_words should be smaller than chunking.target_words")
    if not config.outputs.write_root_markdown and not config.outputs.write_clean_docs:
        messages.append("At least one markdown output should be enabled in outputs.write_root_markdown or outputs.write_clean_docs")
    return messages


def reindex(config: Config, dry_run: bool = False) -> RunResult:
    return _run_pipeline(config, dry_run=dry_run, force=False, since=None, mode="reindex")


def iter_sources(config: Config):
    output_root = config.output_root.resolve()
    skip_large_mb = config.performance.skip_large_files_mb
    for root in config.input_roots:
        root = root.resolve()
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            resolved_path = path.resolve()
            if _is_within(resolved_path, output_root):
                continue
            rel = path.relative_to(root).as_posix()
            if not _matches_any(rel, config.include_globs):
                continue
            if _matches_any(rel, config.exclude_globs):
                continue
            doc_type = get_supported_doc_type(path)
            if not doc_type:
                continue
            size_bytes = path.stat().st_size
            if skip_large_mb and size_bytes > skip_large_mb * 1024 * 1024:
                continue
            yield SourceDocument(
                path=resolved_path,
                root=root,
                doc_type=doc_type,
                checksum=sha256_file(path),
                modified_at=mtime(path),
                size_bytes=size_bytes,
            )


def _run_pipeline(
    config: Config,
    dry_run: bool,
    force: bool,
    since: str | None,
    mode: str,
) -> RunResult:
    if not dry_run:
        ensure_dir(config.output_root)
    manifest = ManifestStore(config.output_root)
    manifest.load()
    cutoff = parse_since(since)
    failures: list[ProcessingFailure] = []
    actions: list[Action] = []
    scanned = written = skipped = deleted = 0
    processed_doc_ids: set[str] = set()
    seen_source_paths: set[str] = set()

    for source in iter_sources(config):
        if cutoff and source.modified_at < cutoff:
            continue
        scanned += 1
        seen_source_paths.add(str(source.path))
        try:
            outcome = _process_source(source, config, manifest, dry_run=dry_run, force=force, mode=mode)
        except Exception as exc:
            failures.append(
                ProcessingFailure(
                    source_path=str(source.path),
                    error=str(exc),
                    document_type=source.doc_type,
                    checksum=source.checksum,
                )
            )
            actions.append(Action("error", f"{source.path}: {exc}"))
            if not dry_run:
                log_pipeline(config.output_root, f"ERROR {source.path}: {exc}")
            continue

        actions.extend(outcome["actions"])
        written += outcome["written"]
        skipped += outcome["skipped"]
        deleted += outcome["deleted"]
        if outcome["doc_id"]:
            processed_doc_ids.add(outcome["doc_id"])

    removed_sources = [path for path in list(manifest.records.keys()) if path not in seen_source_paths]
    for source_path in removed_sources:
        record = manifest.records.pop(source_path)
        deleted += 1
        actions.append(Action("delete", record.output_file))
        if not dry_run:
            output_path = Path(record.output_file)
            if output_path.exists():
                output_path.unlink()
            remove_derived_outputs(config.output_root, Path(record.canonical_name).stem)

    if not dry_run:
        manifest.save()
        build_aggregate_outputs(
            output_root=config.output_root,
            manifest=manifest,
            failures=failures,
            run_stats={
                "mode": mode,
                "scanned": scanned,
                "written": written,
                "skipped": skipped,
                "deleted": deleted,
                "processed_doc_ids": sorted(processed_doc_ids),
            },
            outputs_config=config.outputs,
        )
        log_pipeline(
            config.output_root,
            f"{mode.upper()} scanned={scanned} written={written} skipped={skipped} deleted={deleted} failures={len(failures)}",
        )

    return RunResult(actions=actions, scanned=scanned, written=written, skipped=skipped, deleted=deleted)


def _process_source(
    source: SourceDocument,
    config: Config,
    manifest: ManifestStore,
    dry_run: bool,
    force: bool,
    mode: str,
) -> dict:
    extracted = extract(source.path, source.doc_type, config)
    normalized_pages, normalization_metrics = normalize_pages(extracted.pages, config)
    normalized_text_value = normalize_text("\n\n".join(page.text for page in normalized_pages if page.text.strip()))
    extracted.pages = normalized_pages
    extracted.text = normalized_text_value

    gpt_purpose, topic = resolve_taxonomy(config, source.path, source.root)
    doc_date = choose_doc_date(extracted.doc_date, source.path.name)
    metadata = KnowledgeMetadata(
        source_path=str(source.path),
        source_type=source.doc_type,
        checksum=source.checksum,
        extracted_at=iso_now(),
        doc_date=doc_date,
        gpt_purpose=gpt_purpose,
        topic=topic,
        title=(extracted.title or source.path.stem).strip(),
        language=config.defaults.language,
        source_root=str(source.root),
    )
    profile = analyze_document(extracted, source.doc_type, fallback_language=config.defaults.language)
    profile.diagnostics.update(normalization_metrics)

    filename = canonical_filename(source, metadata)
    doc_id = Path(filename).stem
    output_path = config.output_root / filename
    existing = manifest.get(str(source.path))
    existing_doc_id = Path(existing.canonical_name).stem if existing else None
    existing_state = load_document_state(config.output_root, doc_id)

    if _should_skip(source, filename, existing, existing_state, force):
        return {
            "actions": [Action("skip", str(source.path))],
            "written": 0,
            "skipped": 1,
            "deleted": 0,
            "doc_id": doc_id,
        }

    deleted = 0
    actions: list[Action] = []
    if existing and Path(existing.output_file).name != filename:
        old_file = Path(existing.output_file)
        if old_file.exists():
            deleted += 1
            actions.append(Action("delete", str(old_file)))
            if not dry_run:
                old_file.unlink()
        if existing_doc_id and existing_doc_id != doc_id and not dry_run:
            remove_derived_outputs(config.output_root, existing_doc_id)

    extraction_notes = list(profile.quality_flags)
    if profile.ocr_used:
        extraction_notes.append("OCR fallback used on low-text PDF pages.")
    markdown_content = render_markdown(metadata, normalized_text_value, profile=profile, extraction_notes=extraction_notes)

    clean_doc_path = config.output_root / "clean_docs" / f"{doc_id}.md"
    raw_text_path = config.output_root / "raw_text" / f"{doc_id}.txt"
    should_write_root_markdown = config.outputs.write_root_markdown or not config.outputs.write_clean_docs
    primary_markdown_path = output_path if should_write_root_markdown else clean_doc_path

    doc_record = DocumentRecord(
        doc_id=doc_id,
        source_path=str(source.path),
        source_filename=source.path.name,
        source_sha256=source.checksum,
        document_type=source.doc_type,
        title=metadata.title,
        doc_date=doc_date,
        topic=topic,
        gpt_purpose=gpt_purpose,
        extraction_method=profile.extraction_method,
        extraction_quality_score=profile.extraction_quality_score,
        ocr_used=profile.ocr_used,
        output_markdown_file=str(primary_markdown_path),
        chunk_count=0,
        processing_status="processed",
        probable_domain=profile.probable_domain,
        document_kind=profile.document_kind,
        language=profile.language,
        mostly_tabular=profile.mostly_tabular,
        quality_flags=profile.quality_flags,
    )

    chunks = build_chunks(doc_record, extracted, config) if config.outputs.write_chunks else []
    doc_record.chunk_count = len(chunks)
    structured_data = extract_structured_records(doc_record, chunks, config) if config.outputs.write_structured_data else {}

    actions.append(Action("write", str(primary_markdown_path)))
    if config.outputs.write_clean_docs:
        if clean_doc_path != primary_markdown_path:
            actions.append(Action("write", str(clean_doc_path)))
    if config.outputs.write_raw_text:
        actions.append(Action("write", str(raw_text_path)))

    if not dry_run:
        if should_write_root_markdown:
            write_markdown(output_path, markdown_content)
        if config.outputs.write_clean_docs:
            ensure_dir(clean_doc_path.parent)
            write_markdown(clean_doc_path, markdown_content)
        if config.outputs.write_raw_text:
            ensure_dir(raw_text_path.parent)
            raw_text_path.write_text(normalized_text_value, encoding="utf-8")

        write_document_state(
            config.output_root,
            doc_record,
            chunks,
            structured_data,
            str(raw_text_path) if config.outputs.write_raw_text else None,
            str(clean_doc_path) if config.outputs.write_clean_docs else None,
        )
        manifest.upsert(
            ManifestRecord(
                source_path=str(source.path),
                checksum=source.checksum,
                output_file=str(primary_markdown_path),
                canonical_name=filename,
                last_updated=iso_now(),
            )
        )

    return {
        "actions": actions,
        "written": 1,
        "skipped": 0,
        "deleted": deleted,
        "doc_id": doc_id,
    }


def _should_skip(
    source: SourceDocument,
    filename: str,
    existing: ManifestRecord | None,
    existing_state: dict | None,
    force: bool,
) -> bool:
    return bool(
        not force
        and existing is not None
        and existing.checksum == source.checksum
        and Path(existing.output_file).name == filename
        and Path(existing.output_file).exists()
        and existing_state is not None
    )


def _matches_any(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        if pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]):
            return True
    return False


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
