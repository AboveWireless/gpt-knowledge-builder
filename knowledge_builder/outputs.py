from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .manifest import ManifestStore
from .models import ChunkRecord, DocumentRecord, OutputsConfig, ProcessingFailure
from .utils import append_log, ensure_dir, json_ready, write_csv, write_json, write_jsonl


STATE_DOCS_DIR = "documents"


def document_state_path(output_root: Path, doc_id: str) -> Path:
    return output_root / ".gptkb" / STATE_DOCS_DIR / f"{doc_id}.json"


def write_document_state(
    output_root: Path,
    doc: DocumentRecord,
    chunks: list[ChunkRecord],
    structured_data: dict[str, list[dict]],
    raw_text_file: str | None,
    clean_doc_file: str | None,
) -> None:
    payload = {
        "document": json_ready(asdict(doc)),
        "chunks": [json_ready(asdict(chunk)) for chunk in chunks],
        "structured_data": json_ready(structured_data),
        "raw_text_file": raw_text_file,
        "clean_doc_file": clean_doc_file,
    }
    path = document_state_path(output_root, doc.doc_id)
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_document_state(output_root: Path, doc_id: str) -> dict | None:
    path = document_state_path(output_root, doc_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def prune_document_states(output_root: Path, valid_doc_ids: set[str]) -> None:
    state_dir = output_root / ".gptkb" / STATE_DOCS_DIR
    if not state_dir.exists():
        return
    for path in state_dir.glob("*.json"):
        if path.stem not in valid_doc_ids:
            path.unlink()


def remove_derived_outputs(output_root: Path, doc_id: str) -> None:
    candidates = [
        output_root / "clean_docs" / f"{doc_id}.md",
        output_root / "raw_text" / f"{doc_id}.txt",
        output_root / "chunks" / "by_document" / f"{doc_id}.jsonl",
        document_state_path(output_root, doc_id),
    ]
    for path in candidates:
        if path.exists():
            path.unlink()


def build_aggregate_outputs(
    output_root: Path,
    manifest: ManifestStore,
    failures: list[ProcessingFailure],
    run_stats: dict,
    outputs_config: OutputsConfig,
) -> None:
    doc_states = []
    all_chunks: list[dict] = []
    structured: dict[str, list[dict]] = {
        "definitions": [],
        "requirements": [],
        "warnings": [],
        "parts": [],
        "specs": [],
        "procedures": [],
        "tables": [],
    }

    valid_doc_ids = {Path(record.canonical_name).stem for record in manifest.records.values()}
    prune_document_states(output_root, valid_doc_ids)

    for doc_id in sorted(valid_doc_ids):
        state = load_document_state(output_root, doc_id)
        if not state:
            continue
        doc_states.append(state)
        all_chunks.extend(state.get("chunks") or [])
        for key, values in (state.get("structured_data") or {}).items():
            structured.setdefault(key, []).extend(values or [])

    documents = [state["document"] for state in doc_states]
    documents_json_path = output_root / "manifests" / "documents.json"
    documents_csv_path = output_root / "manifests" / "documents.csv"
    report_path = output_root / "manifests" / "processing_report.json"
    failures_path = output_root / "manifests" / "failures.json"

    if outputs_config.write_manifests:
        write_json(documents_json_path, documents)
        write_csv(documents_csv_path, documents)
        write_json(
            report_path,
            {
                "documents_processed": len(documents),
                "chunks_written": len(all_chunks),
                "failures": len(failures),
                **run_stats,
            },
        )
        write_json(failures_path, [json_ready(asdict(failure)) for failure in failures])

    if outputs_config.write_chunks:
        write_jsonl(output_root / "chunks" / "all_chunks.jsonl", all_chunks)
        for state in doc_states:
            doc = state["document"]
            write_jsonl(output_root / "chunks" / "by_document" / f"{doc['doc_id']}.jsonl", state.get("chunks") or [])

    if outputs_config.write_structured_data:
        for name, rows in structured.items():
            write_jsonl(output_root / "extracted_data" / f"{name}.jsonl", rows)

    metrics_rows = []
    flag_rows = []
    for doc in documents:
        metrics_rows.append(
            {
                "doc_id": doc["doc_id"],
                "source_filename": doc["source_filename"],
                "document_type": doc["document_type"],
                "extraction_method": doc["extraction_method"],
                "extraction_quality_score": doc["extraction_quality_score"],
                "ocr_used": doc["ocr_used"],
                "chunk_count": doc["chunk_count"],
                "document_kind": doc.get("document_kind", ""),
                "probable_domain": doc.get("probable_domain", ""),
            }
        )
        for flag in doc.get("quality_flags", []):
            flag_rows.append(
                {
                    "doc_id": doc["doc_id"],
                    "source_filename": doc["source_filename"],
                    "quality_flag": flag,
                }
            )
    if outputs_config.write_manifests:
        write_csv(output_root / "diagnostics" / "extraction_metrics.csv", metrics_rows)
        write_csv(output_root / "diagnostics" / "quality_flags.csv", flag_rows)


def log_pipeline(output_root: Path, message: str) -> None:
    append_log(output_root / "logs" / "pipeline.log", message)
