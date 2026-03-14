from __future__ import annotations

import json
import sys
from pathlib import Path

from knowledge_builder.cli import run
from knowledge_builder.project.pipeline import export_diagnostics_report, export_project, promote_duplicate_as_canonical, retry_document_extraction, retry_review_items, review_project, scan_project, update_review_item, validate_project
from knowledge_builder.project.store import load_project_config, load_reviews, load_secrets, load_state, save_project_config, save_secrets
from tests.fixture_builders import build_mixed_stress_corpus


def test_project_init_scan_and_export(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    (source_dir / "manual.txt").write_text(
        "Grounding means connection to earth.\n\n1. Remove cover.\n2. Tighten lug.\n",
        encoding="utf-8",
    )

    code = run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Tower Library",
        ]
    )
    assert code == 0

    summary = scan_project(project_dir)
    assert summary["scanned"] == 1
    assert summary["processed"] == 1

    result = export_project(project_dir)
    package_dir = Path(result["package_dir"])
    provenance_dir = Path(result["provenance_dir"])
    assert package_dir.exists()
    assert provenance_dir.exists()
    assert (package_dir / "package_index.md").exists()
    assert any(path.name.startswith("knowledge_core_") for path in package_dir.iterdir())
    assert (provenance_dir / "provenance_manifest.json").exists()


def test_project_scan_skips_unchanged_files_and_tracks_duplicate_review(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    body = "Ground lug torque: 45 Nm.\nDisconnect power before service.\n"
    (source_dir / "one.txt").write_text(body, encoding="utf-8")
    (source_dir / "two.txt").write_text(body, encoding="utf-8")

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Duplicate Review",
        ]
    )

    first = scan_project(project_dir)
    second = scan_project(project_dir)
    reviews = load_reviews(project_dir)
    assert first["scanned"] == 2
    assert second["skipped"] == 2
    assert any(item["kind"] == "duplicate" for item in reviews["items"])

    review_summary = review_project(project_dir, reject_duplicates=True)
    assert review_summary["rejected"] >= 1


def test_promote_duplicate_as_canonical_flips_duplicate_preference(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    body = "Ground lug torque: 45 Nm.\nDisconnect power before service.\n"
    one = source_dir / "one.txt"
    two = source_dir / "two.txt"
    one.write_text(body, encoding="utf-8")
    two.write_text(body, encoding="utf-8")

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Canonical Duplicate",
        ]
    )

    scan_project(project_dir)
    duplicate_review = next(item for item in load_reviews(project_dir)["items"] if item["kind"] == "duplicate")
    result = promote_duplicate_as_canonical(project_dir, duplicate_review["review_id"])
    reviews = load_reviews(project_dir)["items"]
    state = load_state(project_dir)

    assert Path(result["canonical_source"]).name == "two.txt"
    assert state["documents"][str(two)]["document"]["duplicate_of"] is None
    assert state["documents"][str(one)]["document"]["duplicate_of"] == str(two)
    assert state["documents"][str(two)]["document"]["duplicate_canonical_source"] == str(two)
    assert any(item["kind"] == "duplicate" and item["source_path"] == str(one) for item in reviews)


def test_project_scan_tracks_partial_and_failed_quality_report(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    (source_dir / "broken.json").write_text('{"alpha": 1,,}', encoding="utf-8")
    (source_dir / "tiny.txt").write_text("short note", encoding="utf-8")

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Quality Report",
        ]
    )

    summary = scan_project(project_dir)
    state = load_state(project_dir)
    report = state["last_scan_report"]

    assert summary["partial"] >= 1
    assert report["partial"] >= 1
    assert report["document_types"]["json"] == 1
    assert report["recent_issues"]
    assert any(item["kind"] == "extraction_issue" for item in load_reviews(project_dir)["items"])


def test_project_scan_handles_large_corpus_incrementally(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    for index in range(40):
        (source_dir / f"doc_{index:02d}.txt").write_text(
            f"Tower procedure {index}\n\n1. Inspect site.\n2. Confirm identifier {index}.\n3. Record findings.\n",
            encoding="utf-8",
        )

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Large Corpus",
        ]
    )

    first = scan_project(project_dir)
    second = scan_project(project_dir)

    assert first["scanned"] == 40
    assert first["processed"] == 40
    assert second["skipped"] == 40


def test_project_scan_persists_unsupported_and_oversize_inputs_and_export_skips_them(tmp_path: Path, monkeypatch):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    (source_dir / "usable.txt").write_text(
        "Tower grounding procedure.\n\n1. Inspect lug.\n2. Tighten hardware.\n3. Record torque.\n",
        encoding="utf-8",
    )
    (source_dir / "unknown.bin").write_bytes(b"\x00\x01\x02unsupported")
    (source_dir / "oversized.txt").write_text("A" * 2048, encoding="utf-8")

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Mixed Degraded Corpus",
        ]
    )
    config = load_project_config(project_dir)
    config.include_globs = ["**/*"]
    save_project_config(project_dir, config)

    monkeypatch.setattr("knowledge_builder.project.pipeline.MAX_SOURCE_FILE_BYTES", 512)

    first = scan_project(project_dir)
    second = scan_project(project_dir)
    state = load_state(project_dir)
    reviews = load_reviews(project_dir)

    assert first["unsupported"] == 1
    assert first["metadata_only"] >= 1
    assert second["skipped"] == 3
    assert str(source_dir / "unknown.bin") in state["documents"]
    assert str(source_dir / "oversized.txt") in state["documents"]
    assert state["documents"][str(source_dir / "unknown.bin")]["document"]["extraction_status"] == "unsupported"
    assert state["documents"][str(source_dir / "oversized.txt")]["document"]["extraction_status"] == "metadata_only"
    assert any(item["kind"] == "extraction_issue" and item["source_path"].endswith("unknown.bin") for item in reviews["items"])
    assert any(item["kind"] == "extraction_issue" and item["source_path"].endswith("oversized.txt") for item in reviews["items"])

    result = export_project(project_dir)
    provenance_manifest = json.loads(Path(result["provenance_manifest"]).read_text(encoding="utf-8"))
    assert Path(result["package_dir"]).exists()
    assert len(provenance_manifest["documents"]) == 1
    assert provenance_manifest["documents"][0]["document"]["source_filename"] == "usable.txt"


def test_project_scan_handles_large_mixed_corpus_without_pipeline_collapse(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    build_mixed_stress_corpus(source_dir)

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Stress Corpus",
        ]
    )

    first = scan_project(project_dir)
    second = scan_project(project_dir)
    state = load_state(project_dir)
    report = state["last_scan_report"]
    reviews = load_reviews(project_dir)

    assert first["scanned"] == 85
    assert first["processed"] == 85
    assert first["partial"] >= 10
    assert first["duplicates"] >= 1
    assert first["review_required"] >= 1
    assert second["skipped"] == 85
    assert report["partial"] >= 10
    assert report["duplicates"] >= 1
    assert report["review_required"] >= 1
    assert report["document_types"]["txt"] == 75
    assert report["document_types"]["json"] == 6
    assert report["document_types"]["xml"] == 4
    assert report["recent_issues"]
    assert any(item["kind"] == "duplicate" for item in reviews["items"])
    assert any(item["kind"] == "extraction_issue" for item in reviews["items"])

    result = export_project(project_dir)
    assert Path(result["package_dir"]).exists()
    assert (Path(result["package_dir"]) / "package_index.md").exists()


def test_retry_document_extraction_reprocesses_only_selected_review_item(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    target = source_dir / "broken.json"
    target.write_text('{"alpha": 1,,}', encoding="utf-8")
    (source_dir / "good.txt").write_text("Grounding procedure.\n1. Inspect.\n2. Tighten.\n", encoding="utf-8")

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Retry Target",
        ]
    )

    scan_project(project_dir)
    target_review = next(
        item for item in load_reviews(project_dir)["items"]
        if item["kind"] == "extraction_issue" and item["source_path"].endswith("broken.json")
    )
    target.write_text('{"alpha": 1, "fixed": true}', encoding="utf-8")

    result = retry_document_extraction(project_dir, review_id=target_review["review_id"], strategy="raw")
    state = load_state(project_dir)
    document = state["documents"][str(target)]["document"]

    assert result["summary"]["scanned"] == 1
    assert result["summary"]["processed"] == 1
    assert result["strategy"] == "raw"
    assert document["extraction_status"] == "partial"
    assert document["extraction_method"] == "json-raw"
    assert document["last_retry_strategy"] == "raw"
    assert document["retry_strategies"] == ["default", "raw"]
    assert document["preview_units"]


def test_export_diagnostics_report_writes_json_and_markdown(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    build_mixed_stress_corpus(source_dir, text_docs=8, broken_json=2, broken_xml=1, duplicates_every=4)

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Diagnostics Corpus",
        ]
    )

    scan_project(project_dir)
    result = export_diagnostics_report(project_dir)
    diagnostics_json = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
    diagnostics_md = Path(result["markdown_path"]).read_text(encoding="utf-8")

    assert Path(result["diagnostics_dir"]).exists()
    assert diagnostics_json["corpus_metrics"]["documents"] == 11
    assert diagnostics_json["degraded_documents"]
    assert "# Corpus Diagnostics" in diagnostics_md
    assert "## Degraded Documents" in diagnostics_md


def test_retry_review_items_filters_open_matching_documents(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    (source_dir / "broken_a.json").write_text('{"alpha": 1,,}', encoding="utf-8")
    (source_dir / "broken_b.json").write_text('{"beta": 2,,}', encoding="utf-8")
    (source_dir / "broken.xml").write_text("<root><node>broken", encoding="utf-8")

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Bulk Retry",
        ]
    )

    scan_project(project_dir)
    reviews = load_reviews(project_dir)
    first_json_review = next(item for item in reviews["items"] if item["source_path"].endswith("broken_a.json"))
    update_review_item(project_dir, review_id=first_json_review["review_id"], status="accepted")

    result = retry_review_items(
        project_dir,
        kind="extraction_issue",
        document_type="json",
        extraction_status="partial",
        strategy="raw",
        status="open",
    )

    assert len(result["matched_sources"]) == 1
    assert result["matched_sources"][0].endswith("broken_b.json")
    state = load_state(project_dir)
    assert state["documents"][str(source_dir / "broken_b.json")]["document"]["last_retry_strategy"] == "raw"


def test_project_validate_reports_open_high_severity_reviews(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    (source_dir / "empty.txt").write_text("", encoding="utf-8")

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Validation Demo",
        ]
    )
    scan_project(project_dir)
    issues = validate_project(project_dir)
    assert any("high-severity review" in issue for issue in issues)
    state = load_state(project_dir)
    assert state["documents"]


def test_review_item_edit_updates_document_metadata(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    (source_dir / "doc.txt").write_text("Grounding means connection to earth.", encoding="utf-8")

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Edit Review",
        ]
    )
    scan_project(project_dir)
    reviews = load_reviews(project_dir)
    target = next(item for item in reviews["items"] if item["kind"] in {"taxonomy", "low_signal"})

    updated = update_review_item(
        project_dir,
        review_id=target["review_id"],
        status="accepted",
        override_title="Grounding Basics",
        override_domain="operations",
        resolution_note="Reviewed manually.",
    )
    assert updated["status"] == "accepted"
    state = load_state(project_dir)
    document = next(iter(state["documents"].values()))["document"]
    assert document["title"] == "Grounding Basics"
    assert document["probable_domain"] == "operations"


def test_openai_enrichment_uses_mocked_client_and_saved_project_key(tmp_path: Path, monkeypatch):
    class _FakeResponse:
        output_text = json.dumps(
            {
                "clean_title": "AI Refined Title",
                "taxonomy": {"domain": "product", "topic": "roadmap"},
                "synopsis": "A refined synopsis.",
                "glossary_hints": ["Roadmap"],
                "review_notes": ["Needs human verification."],
                "confidence": 0.88,
            }
        )

    class _FakeResponses:
        def create(self, **_kwargs):
            return _FakeResponse()

    class _FakeOpenAI:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.responses = _FakeResponses()

    monkeypatch.setitem(sys.modules, "openai", type("FakeModule", (), {"OpenAI": _FakeOpenAI}))

    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    (source_dir / "doc.txt").write_text("Product roadmap and release planning.", encoding="utf-8")

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "AI Project",
        ]
    )
    config = load_project_config(project_dir)
    config.optional_model_settings.enabled = True
    save_project_config(project_dir, config)
    save_secrets(project_dir, {"version": 1, "providers": {"openai": {"api_key": "test-key"}}})

    summary = scan_project(project_dir)
    assert summary["processed"] == 1
    state = load_state(project_dir)
    document = next(iter(state["documents"].values()))["document"]
    knowledge_summary = next(iter(state["documents"].values()))["knowledge_summary"]
    assert document["title"] == "AI Refined Title"
    assert document["probable_domain"] == "product"
    assert knowledge_summary["enrichment"]["mode"] == "openai"
    assert load_secrets(project_dir)["providers"]["openai"]["api_key"] == "test-key"


def test_export_writes_item_level_provenance_and_splits_large_artifacts(tmp_path: Path, monkeypatch):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    large_text = "\n".join(
        f"Term {index}: Definition for grounding and bonding concept number {index} with extra context."
        for index in range(1, 180)
    )
    (source_dir / "glossary.txt").write_text(large_text, encoding="utf-8")

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Split Export",
        ]
    )
    scan_project(project_dir)
    monkeypatch.setattr("knowledge_builder.project.pipeline.TARGET_PACKAGE_BYTES", 6000)
    result = export_project(project_dir)
    package_dir = Path(result["package_dir"])
    provenance_file = Path(result["knowledge_items_file"])
    assert provenance_file.exists()
    rows = provenance_file.read_text(encoding="utf-8").splitlines()
    assert rows
    glossary_pages = sorted(path.name for path in package_dir.glob("glossary*.md"))
    assert len(glossary_pages) >= 2


def test_validate_project_flags_enabled_ai_without_key(tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "exports"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    (source_dir / "doc.txt").write_text("Operations procedure.", encoding="utf-8")

    run(
        [
            "project",
            "init",
            "--project-dir",
            str(project_dir),
            "--source-root",
            str(source_dir),
            "--output-dir",
            str(output_dir),
            "--project-name",
            "Missing Key",
        ]
    )
    config = load_project_config(project_dir)
    config.optional_model_settings.enabled = True
    save_project_config(project_dir, config)

    issues = validate_project(project_dir)
    assert any("API key" in issue for issue in issues)
