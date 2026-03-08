from pathlib import Path

from knowledge_builder.scanner.discovery import discover_batch_corpora, discover_corpus_files


def test_discover_corpus_files_filters_supported_types(tmp_path: Path):
    corpus = tmp_path / "Corpus"
    corpus.mkdir()
    (corpus / "manual.txt").write_text("hello", encoding="utf-8")
    (corpus / "image.jpg").write_text("not-a-real-image", encoding="utf-8")
    (corpus / "ignore.bin").write_text("x", encoding="utf-8")

    discovered = discover_corpus_files(corpus)

    assert [item.path.name for item in discovered] == ["image.jpg", "manual.txt"]
    assert {item.file_type for item in discovered} == {"jpg", "txt"}


def test_discover_batch_corpora_only_returns_immediate_child_folders(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "Folder_A").mkdir()
    (root / "Folder_B").mkdir()
    (root / "loose.txt").write_text("skip", encoding="utf-8")

    corpora = discover_batch_corpora(root)

    assert [path.name for path in corpora] == ["Folder_A", "Folder_B"]


def test_discover_corpus_files_skips_hidden_cache_and_generated_output_dirs(tmp_path: Path):
    corpus = tmp_path / "Corpus"
    corpus.mkdir()
    (corpus / "manual.txt").write_text("hello", encoding="utf-8")
    (corpus / ".git").mkdir()
    (corpus / ".git" / "ignored.txt").write_text("ignore", encoding="utf-8")
    (corpus / "__pycache__").mkdir()
    (corpus / "__pycache__" / "ignored.txt").write_text("ignore", encoding="utf-8")
    (corpus / "demo_GPT_KNOWLEDGE").mkdir()
    (corpus / "demo_GPT_KNOWLEDGE" / "reprocessed.txt").write_text("ignore", encoding="utf-8")
    (corpus / "demo_DEBUG").mkdir()
    (corpus / "demo_DEBUG" / "debug.txt").write_text("ignore", encoding="utf-8")

    discovered = discover_corpus_files(corpus)

    assert [item.path.name for item in discovered] == ["manual.txt"]
