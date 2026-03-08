from pathlib import Path

from knowledge_builder.cli import run, run_scan_docs


def test_validate_command_succeeds_for_supported_input(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "doc.txt").write_text("A useful note.", encoding="utf-8")

    code = run(
        [
            "validate",
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--pack-name",
            "demo",
        ]
    )

    assert code == 0


def test_scan_docs_entrypoint_builds_package(tmp_path: Path):
    input_dir = tmp_path / "demo"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "manual.txt").write_text("The installer shall inspect the bond.", encoding="utf-8")

    code = run_scan_docs(
        [
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--pack-name",
            "demo",
            "--zip-pack",
            "false",
            "--debug-outputs",
            "false",
        ]
    )

    assert code == 0
    assert (output_dir / "demo_GPT_KNOWLEDGE").exists()
    assert (output_dir / "demo_GPT_KNOWLEDGE" / "demo__reference_facts.md").exists()


def test_scan_docs_batch_root_builds_summary_and_packages(tmp_path: Path):
    input_root = tmp_path / "batch"
    output_dir = tmp_path / "output"
    folder_a = input_root / "Folder_A"
    folder_b = input_root / "Folder_B"
    input_root.mkdir()
    folder_a.mkdir()
    folder_b.mkdir()
    (folder_a / "a.txt").write_text("Grounding means connection to earth.", encoding="utf-8")
    (folder_b / "b.txt").write_text("The installer shall verify the bond.", encoding="utf-8")

    code = run_scan_docs(
        [
            "--input-dir",
            str(input_root),
            "--output-dir",
            str(output_dir),
            "--batch-subfolders",
            "true",
            "--zip-pack",
            "false",
            "--debug-outputs",
            "false",
        ]
    )

    assert code == 0
    assert (output_dir / "batch_summary.txt").exists()
    assert (output_dir / "folder_a_GPT_KNOWLEDGE").exists()
    assert (output_dir / "folder_b_GPT_KNOWLEDGE").exists()
    assert any(path.name.startswith("folder_a__") for path in (output_dir / "folder_a_GPT_KNOWLEDGE").iterdir() if path.suffix == ".md")
