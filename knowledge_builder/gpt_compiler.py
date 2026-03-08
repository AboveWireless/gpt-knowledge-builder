from __future__ import annotations

import json
from pathlib import Path

from .compiler_models import BatchBuildResult, BatchFolderResult, BuildOptions, BuildResult, SourceKnowledge
from .export.debug_package import write_debug_package
from .export.gpt_package import write_gpt_package
from .export.zipper import write_zip
from .extractors import extract, get_supported_doc_type
from .naming import make_safe_corpus_name
from .scanner.discovery import discover_corpus_files
from .synthesis import (
    build_entities,
    build_glossary,
    build_knowledge_core_pages,
    build_procedures,
    build_reference_facts,
    build_source_knowledge,
    clean_text_for_knowledge,
)
from .utils import ensure_dir, slugify


IMAGE_TYPES = {"png", "jpg", "jpeg"}


def compile_gpt_knowledge_pack(options: BuildOptions) -> BuildResult:
    input_dir = options.input_dir.resolve()
    output_dir = options.output_dir.resolve()
    if not input_dir.exists():
        raise ValueError(f"Input directory not found: {input_dir}")

    _emit_event(options.event_callback, "status", f"Scanning {input_dir}")
    source_folder_name = options.source_folder_name or input_dir.name
    corpus_name = options.pack_name.strip() or source_folder_name

    documents = _collect_documents(input_dir, None, source_folder_name=source_folder_name, event_callback=options.event_callback)
    contributed = [doc for doc in documents if not doc.empty_reason]
    failed = [doc for doc in documents if doc.empty_reason]

    if not contributed:
        raise ValueError("No usable knowledge could be extracted from the input directory.")

    _emit_event(options.event_callback, "status", f"Writing package for {corpus_name}")
    knowledge_pages = build_knowledge_core_pages(contributed)
    result = write_gpt_package(
        output_dir=output_dir,
        corpus_name=corpus_name,
        source_folder_name=source_folder_name,
        zip_pack=options.zip_pack,
        knowledge_pages=knowledge_pages,
        reference_facts=build_reference_facts(contributed),
        glossary=build_glossary(contributed),
        procedures=build_procedures(contributed),
        entities=build_entities(contributed),
    )

    debug_dir = None
    if options.debug_outputs:
        _emit_event(options.event_callback, "log", f"Writing debug outputs for {corpus_name}")
        debug_dir = write_debug_package(
            output_dir=output_dir,
            corpus_name=corpus_name,
            items=documents,
            processed_documents=len(documents),
            failed_documents=len(failed),
        )

    if options.zip_pack and result.zip_path is not None:
        _emit_event(options.event_callback, "log", f"Creating zip {result.zip_path.name}")
        write_zip(result.package_dir, result.zip_path)

    _emit_event(
        options.event_callback,
        "done",
        f"Finished {corpus_name}: processed={len(documents)} contributed={len(contributed)} failed={len(failed)}",
    )

    return BuildResult(
        package_dir=result.package_dir,
        zip_path=result.zip_path if options.zip_pack else None,
        written_files=sorted(result.written_files),
        corpus_name=result.corpus_name,
        source_folder_name=result.source_folder_name,
        debug_dir=debug_dir,
        processed_documents=len(documents),
        contributed_documents=len(contributed),
        failed_documents=len(failed),
    )


def compile_gpt_knowledge_batch(
    input_root: Path,
    output_dir: Path,
    zip_pack: bool = False,
    debug_outputs: bool = False,
    selected_folder_names: list[str] | None = None,
    event_callback=None,
) -> BatchBuildResult:
    input_root = input_root.resolve()
    output_dir = output_dir.resolve()
    if not input_root.exists():
        raise ValueError(f"Input directory not found: {input_root}")
    if not input_root.is_dir():
        raise ValueError(f"Input path is not a directory: {input_root}")

    _emit_event(event_callback, "status", f"Scanning batch root {input_root}")
    ensure_dir(output_dir)
    folder_results: list[BatchFolderResult] = []
    child_dirs = sorted(path for path in input_root.iterdir() if path.is_dir())
    requested_names = {name for name in (selected_folder_names or []) if name}
    selected_dirs = [path for path in child_dirs if not requested_names or path.name in requested_names]
    skipped_dirs = [path for path in child_dirs if path not in selected_dirs]

    for child_dir in selected_dirs:
        try:
            _emit_event(event_callback, "status", f"Processing {child_dir.name}")
            result = compile_gpt_knowledge_pack(
                BuildOptions(
                    input_dir=child_dir,
                    output_dir=output_dir,
                    pack_name=child_dir.name,
                    zip_pack=zip_pack,
                    debug_outputs=debug_outputs,
                    event_callback=event_callback,
                )
            )
            folder_results.append(
                BatchFolderResult(
                    folder_name=child_dir.name,
                    input_dir=child_dir,
                    success=True,
                    corpus_name=result.corpus_name,
                    package_dir=result.package_dir,
                    zip_path=result.zip_path,
                    debug_dir=result.debug_dir,
                    processed_documents=result.processed_documents,
                    contributed_documents=result.contributed_documents,
                    failed_documents=result.failed_documents,
                )
            )
            _emit_event(event_callback, "log", f"[ok] {child_dir.name}")
        except Exception as exc:
            folder_results.append(
                BatchFolderResult(
                    folder_name=child_dir.name,
                    input_dir=child_dir,
                    success=False,
                    error=str(exc),
                )
            )
            _emit_event(event_callback, "log", f"[failed] {child_dir.name}: {exc}")

    summary_path = output_dir / "batch_summary.txt"
    summary_path.write_text(
        _build_batch_summary(
            input_root=input_root,
            folder_results=folder_results,
            selected_folder_names=[path.name for path in selected_dirs],
            skipped_folder_names=[path.name for path in skipped_dirs],
        ),
        encoding="utf-8",
    )
    _emit_event(event_callback, "done", f"Batch complete: {len(folder_results)} folder(s) processed")
    return BatchBuildResult(
        output_dir=output_dir,
        summary_path=summary_path,
        folder_results=folder_results,
        selected_folder_names=[path.name for path in selected_dirs],
        skipped_folder_names=[path.name for path in skipped_dirs],
    )


def _collect_documents(
    input_dir: Path,
    debug_dir: Path | None,
    source_folder_name: str,
    event_callback=None,
) -> list[SourceKnowledge]:
    documents: list[SourceKnowledge] = []
    discovered = discover_corpus_files(input_dir)
    _emit_event(event_callback, "log", f"Discovered {len(discovered)} supported file(s)")
    if debug_dir:
        ensure_dir(debug_dir)
        ensure_dir(debug_dir / "raw_text")
        ensure_dir(debug_dir / "normalized_text")

    for discovered_file in discovered:
        path = discovered_file.path
        doc_type = discovered_file.file_type
        _emit_event(event_callback, "log", f"Reading {path.name}")
        extracted = extract(path, doc_type, None)
        raw_text = extracted.text or ""
        clean_text = clean_text_for_knowledge(raw_text)
        knowledge = build_source_knowledge(
            path,
            doc_type,
            extracted.title or path.stem,
            raw_text,
            clean_text,
            extraction_method=extracted.extraction_method,
            ocr_used=extracted.ocr_used,
            source_folder_name=source_folder_name,
        )
        if doc_type in IMAGE_TYPES and not clean_text.strip():
            knowledge.empty_reason = "ocr_empty"
        elif not clean_text.strip():
            knowledge.empty_reason = "empty_after_extraction"
        if knowledge.empty_reason:
            _emit_event(event_callback, "log", f"[skip] {path.name}: {knowledge.empty_reason}")
        else:
            _emit_event(event_callback, "log", f"[use] {path.name}")

        if debug_dir:
            stem = slugify(path.stem, max_len=80)
            (debug_dir / "raw_text" / f"{stem}.txt").write_text(raw_text, encoding="utf-8")
            (debug_dir / "normalized_text" / f"{stem}.txt").write_text(clean_text, encoding="utf-8")

        documents.append(knowledge)

    if debug_dir:
        summary = {
            "processed_documents": len(documents),
            "contributed_documents": sum(1 for doc in documents if not doc.empty_reason),
            "failed_documents": sum(1 for doc in documents if doc.empty_reason),
            "documents": [
                {
                    "source_filename": doc.source_filename,
                    "document_type": doc.document_type,
                    "title": doc.title,
                    "empty_reason": doc.empty_reason,
                }
                for doc in documents
            ],
        }
        (debug_dir / "processing_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return documents


def _emit_event(callback, kind: str, message: str) -> None:
    if callback is None:
        return
    callback(kind, message)


def _build_batch_summary(
    input_root: Path,
    folder_results: list[BatchFolderResult],
    selected_folder_names: list[str],
    skipped_folder_names: list[str],
) -> str:
    success_count = sum(1 for result in folder_results if result.success)
    failure_count = sum(1 for result in folder_results if not result.success)
    lines = [
        "GPT Knowledge Batch Summary",
        "",
        f"Input root: {input_root}",
        f"Folders discovered: {len(folder_results) + len(skipped_folder_names)}",
        f"Folders selected: {len(selected_folder_names)}",
        f"Folders skipped: {len(skipped_folder_names)}",
        f"Folders processed: {len(folder_results)}",
        f"Successful folders: {success_count}",
        f"Failed folders: {failure_count}",
        "Loose files in the root folder were skipped.",
        "",
    ]
    if selected_folder_names:
        lines.append(f"Selected folders: {', '.join(selected_folder_names)}")
    if skipped_folder_names:
        lines.append(f"Skipped folders: {', '.join(skipped_folder_names)}")
    if selected_folder_names or skipped_folder_names:
        lines.append("")
    if not folder_results:
        lines.append("No immediate child folders were found.")
        return "\n".join(lines).strip() + "\n"

    for result in folder_results:
        status = "SUCCESS" if result.success else "FAILED"
        lines.append(f"[{status}] {result.folder_name}")
        lines.append(f"Input: {result.input_dir}")
        if result.success:
            lines.append(f"Package: {result.package_dir}")
            if result.zip_path:
                lines.append(f"Zip: {result.zip_path}")
            lines.append(f"Corpus name: {result.corpus_name}")
            lines.append(
                "Counts: "
                f"processed={result.processed_documents} "
                f"contributed={result.contributed_documents} "
                f"failed={result.failed_documents}"
            )
        else:
            lines.append(f"Error: {result.error}")
        lines.append("")
    for folder_name in skipped_folder_names:
        lines.append(f"[SKIPPED] {folder_name}")
        lines.append("Reason: not selected")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
