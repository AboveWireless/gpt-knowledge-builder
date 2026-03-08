from __future__ import annotations

import json
import sys
from pathlib import Path

from knowledge_builder.cli import run
from knowledge_builder.project.pipeline import export_project, review_project, scan_project, update_review_item, validate_project
from knowledge_builder.project.store import load_project_config, load_reviews, load_secrets, load_state, save_project_config, save_secrets


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
