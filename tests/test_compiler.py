from pathlib import Path

from knowledge_builder.compiler_models import BuildOptions
from knowledge_builder.gpt_compiler import compile_gpt_knowledge_batch, compile_gpt_knowledge_pack


def test_default_build_writes_only_gpt_uploadable_files(tmp_path: Path):
    input_dir = tmp_path / "Tower Library"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "manual.txt").write_text(
        "Scope\n\nTerm means something useful.\n\nThe installer shall verify grounding.\n"
        "WARNING: Disconnect power.\nPart Number: ABC-1234\n1. Remove cover.\n",
        encoding="utf-8",
    )

    result = compile_gpt_knowledge_pack(
        BuildOptions(
            input_dir=input_dir,
            output_dir=output_dir,
            pack_name="Tower Library",
            zip_pack=False,
            debug_outputs=False,
        )
    )

    package_files = sorted(path.name for path in result.package_dir.iterdir())
    assert result.package_dir.name == "tower_library_GPT_KNOWLEDGE"
    assert "INSTRUCTIONS.txt" in package_files
    assert "FILE_GUIDE.txt" in package_files
    assert any(name.startswith("tower_library__knowledge_core__p") for name in package_files)
    assert any(name == "tower_library__reference_facts.md" for name in package_files)
    assert not any(name == "knowledge_core__p01.md" for name in package_files)
    assert not any(name == "reference_facts.md" for name in package_files)
    assert not any(name == "glossary.md" for name in package_files)
    assert all(
        name in {"INSTRUCTIONS.txt", "FILE_GUIDE.txt"} or name.startswith("tower_library__")
        for name in package_files
    )
    assert all(Path(name).suffix in {".md", ".txt"} for name in package_files)
    assert not any(name.startswith(".") for name in package_files)
    assert result.debug_dir is None


def test_zip_and_debug_outputs_are_separate(tmp_path: Path):
    input_dir = tmp_path / "Bonding Pack"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "notes.md").write_text("## Overview\n\nThe system shall remain bonded.\n", encoding="utf-8")

    result = compile_gpt_knowledge_pack(
        BuildOptions(
            input_dir=input_dir,
            output_dir=output_dir,
            pack_name="Bonding Pack",
            zip_pack=True,
            debug_outputs=True,
        )
    )

    assert result.zip_path is not None and result.zip_path.exists()
    assert result.zip_path.name == "bonding_pack_GPT_KNOWLEDGE.zip"
    assert result.debug_dir is not None and result.debug_dir.exists()
    assert not any(path.name.startswith(".") for path in result.package_dir.iterdir())
    assert (result.debug_dir / "extracted").exists()
    assert (result.debug_dir / "normalized").exists()
    assert (result.debug_dir / "chunks").exists()
    assert (result.debug_dir / "promotion_candidates").exists()
    assert (result.debug_dir / "rejected_candidates").exists()
    assert (result.debug_dir / "evidence_maps").exists()
    assert (result.debug_dir / "logs").exists()
    assert (result.debug_dir / "quality_report.txt").exists()


def test_short_non_empty_docs_contribute_useful_output(tmp_path: Path):
    input_dir = tmp_path / "Tiny Pack"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "tiny.txt").write_text("Ground lug torque: 45 Nm.", encoding="utf-8")

    result = compile_gpt_knowledge_pack(
        BuildOptions(
            input_dir=input_dir,
            output_dir=output_dir,
            pack_name="Tiny Pack",
        )
    )

    assert result.contributed_documents == 1
    core_file = next(path for path in result.written_files if "__knowledge_core__p" in path.name)
    content = core_file.read_text(encoding="utf-8")
    assert "Ground lug torque: 45 Nm." in content or "Ground lug torque" in content


def test_batch_processing_builds_separate_packages_and_summary(tmp_path: Path):
    input_root = tmp_path / "input_root"
    output_dir = tmp_path / "output"
    folder_a = input_root / "Folder_A"
    folder_b = input_root / "Folder_B"
    input_root.mkdir()
    folder_a.mkdir()
    folder_b.mkdir()
    (input_root / "loose.txt").write_text("Loose root file should be skipped.", encoding="utf-8")
    (folder_a / "manual.txt").write_text("Grounding means connection to earth.", encoding="utf-8")
    (folder_b / "steps.txt").write_text("1. Remove cover.\n2. Tighten lug.\n", encoding="utf-8")

    result = compile_gpt_knowledge_batch(input_root=input_root, output_dir=output_dir, zip_pack=True)

    assert result.summary_path.exists()
    assert (output_dir / "folder_a_GPT_KNOWLEDGE").exists()
    assert (output_dir / "folder_b_GPT_KNOWLEDGE").exists()
    assert (output_dir / "folder_a_GPT_KNOWLEDGE.zip").exists()
    assert (output_dir / "folder_b_GPT_KNOWLEDGE.zip").exists()
    assert any(path.name.startswith("folder_a__") for path in (output_dir / "folder_a_GPT_KNOWLEDGE").iterdir() if path.suffix == ".md")
    assert any(path.name.startswith("folder_b__") for path in (output_dir / "folder_b_GPT_KNOWLEDGE").iterdir() if path.suffix == ".md")
    assert not any(path.name == "reference_facts.md" for path in (output_dir / "folder_a_GPT_KNOWLEDGE").iterdir())
    assert not any(path.name == "glossary.md" for path in (output_dir / "folder_b_GPT_KNOWLEDGE").iterdir())
    assert not (output_dir / "input_root_GPT_KNOWLEDGE").exists()
    summary = result.summary_path.read_text(encoding="utf-8")
    assert "[SUCCESS] Folder_A" in summary
    assert "[SUCCESS] Folder_B" in summary
    assert "Loose files in the root folder were skipped." in summary


def test_batch_processing_continues_after_folder_failure(tmp_path: Path):
    input_root = tmp_path / "batch"
    output_dir = tmp_path / "output"
    good = input_root / "Good"
    bad = input_root / "Bad"
    input_root.mkdir()
    good.mkdir()
    bad.mkdir()
    (good / "doc.txt").write_text("The installer shall verify grounding continuity.", encoding="utf-8")
    (bad / "empty.txt").write_text("", encoding="utf-8")

    result = compile_gpt_knowledge_batch(input_root=input_root, output_dir=output_dir)

    assert (output_dir / "good_GPT_KNOWLEDGE").exists()
    assert result.summary_path.exists()
    summary = result.summary_path.read_text(encoding="utf-8")
    assert "[SUCCESS] Good" in summary
    assert "[FAILED] Bad" in summary


def test_explicit_single_folder_pack_name_overrides_folder_name_but_keeps_source_folder_name(tmp_path: Path):
    input_dir = tmp_path / "Original Folder"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "doc.txt").write_text("Grounding means connection to earth.", encoding="utf-8")

    result = compile_gpt_knowledge_pack(
        BuildOptions(
            input_dir=input_dir,
            output_dir=output_dir,
            pack_name="Override Pack",
        )
    )

    assert result.package_dir.name == "override_pack_GPT_KNOWLEDGE"
    assert result.source_folder_name == "Original Folder"
    assert any(path.name.startswith("override_pack__") for path in result.written_files if path.suffix == ".md")


def test_tiny_optional_tail_pages_are_not_emitted(tmp_path: Path):
    input_dir = tmp_path / "Paging Pack"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    long_body = "\n".join(
        f"Term {index}: Definition text for grounding and bonding practice {index}."
        for index in range(1, 40)
    )
    (input_dir / "glossary.txt").write_text(long_body, encoding="utf-8")

    result = compile_gpt_knowledge_pack(
        BuildOptions(
            input_dir=input_dir,
            output_dir=output_dir,
            pack_name="Paging Pack",
        )
    )

    glossary_pages = sorted(path.name for path in result.written_files if "__glossary" in path.name)
    assert glossary_pages
    if len(glossary_pages) > 1:
        tail = result.package_dir / glossary_pages[-1]
        assert len(tail.read_text(encoding="utf-8").split()) >= 40


def test_single_build_emits_progress_events(tmp_path: Path):
    input_dir = tmp_path / "Progress Pack"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "doc.txt").write_text("Ground lug torque: 45 Nm.", encoding="utf-8")
    events: list[tuple[str, str]] = []

    result = compile_gpt_knowledge_pack(
        BuildOptions(
            input_dir=input_dir,
            output_dir=output_dir,
            pack_name="Progress Pack",
            event_callback=lambda kind, message: events.append((kind, message)),
        )
    )

    assert result.package_dir.exists()
    assert any(kind == "status" and "Scanning" in message for kind, message in events)
    assert any(kind == "log" and "Discovered 1 supported file(s)" in message for kind, message in events)
    assert any(kind == "done" and "Finished Progress Pack" in message for kind, message in events)
