from pathlib import Path

from knowledge_builder.scanner.models import RunConfig
from knowledge_builder.scanner.routing import route_build
from knowledge_builder.gpt_compiler import compile_gpt_knowledge_batch


def test_route_build_batch_mode_returns_batch_summary(tmp_path: Path):
    root = tmp_path / "root"
    out = tmp_path / "out"
    (root / "Folder_A").mkdir(parents=True)
    (root / "Folder_B").mkdir(parents=True)
    (root / "Folder_A" / "a.txt").write_text("Grounding means connection to earth.", encoding="utf-8")
    (root / "Folder_B" / "b.txt").write_text("The installer shall verify continuity.", encoding="utf-8")

    result = route_build(
        RunConfig(
            input_dir=root,
            output_dir=out,
            batch_subfolders=True,
            zip_pack=False,
            debug_outputs=False,
        )
    )

    assert result.summary_path.exists()
    assert len(result.folder_results) == 2
    assert all(item.success for item in result.folder_results)


def test_batch_processing_only_selected_folders_and_reports_skips(tmp_path: Path):
    root = tmp_path / "root"
    out = tmp_path / "out"
    (root / "Folder_A").mkdir(parents=True)
    (root / "Folder_B").mkdir(parents=True)
    (root / "Folder_C").mkdir(parents=True)
    (root / "Folder_A" / "a.txt").write_text("Grounding means connection to earth.", encoding="utf-8")
    (root / "Folder_B" / "b.txt").write_text("The installer shall verify continuity.", encoding="utf-8")
    (root / "Folder_C" / "c.txt").write_text("1. Remove cover.\n2. Tighten lug.\n", encoding="utf-8")

    result = compile_gpt_knowledge_batch(
        input_root=root,
        output_dir=out,
        selected_folder_names=["Folder_A", "Folder_C"],
    )

    assert sorted(result.selected_folder_names) == ["Folder_A", "Folder_C"]
    assert result.skipped_folder_names == ["Folder_B"]
    assert (out / "folder_a_GPT_KNOWLEDGE").exists()
    assert (out / "folder_c_GPT_KNOWLEDGE").exists()
    assert not (out / "folder_b_GPT_KNOWLEDGE").exists()

    summary = result.summary_path.read_text(encoding="utf-8")
    assert "Selected folders: Folder_A, Folder_C" in summary
    assert "Skipped folders: Folder_B" in summary
    assert "[SKIPPED] Folder_B" in summary
