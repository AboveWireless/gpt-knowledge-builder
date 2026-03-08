from __future__ import annotations

import shutil
from pathlib import Path

from ..compiler_models import BuildResult
from ..knowledge.file_guide import build_file_guide
from ..knowledge.instructions import build_instructions
from ..naming import make_safe_corpus_name
from ..utils import ensure_dir, word_count


def write_gpt_package(
    output_dir: Path,
    corpus_name: str,
    source_folder_name: str,
    zip_pack: bool,
    knowledge_pages: list[str],
    reference_facts: str,
    glossary: str,
    procedures: str,
    entities: str,
) -> BuildResult:
    safe_corpus_name = make_safe_corpus_name(corpus_name)
    package_dir = output_dir / f"{safe_corpus_name}_GPT_KNOWLEDGE"
    zip_path = output_dir / f"{safe_corpus_name}_GPT_KNOWLEDGE.zip" if zip_pack else None

    shutil.rmtree(package_dir, ignore_errors=True)
    ensure_dir(package_dir)

    written_files: list[Path] = []

    for index, content in enumerate(knowledge_pages, start=1):
        file_name = f"{safe_corpus_name}__knowledge_core__p{index:02d}.md"
        path = package_dir / file_name
        path.write_text(content.strip() + "\n", encoding="utf-8")
        written_files.append(path)

    for base_name, content in _paginate_optional_files(
        safe_corpus_name=safe_corpus_name,
        reference_facts=reference_facts,
        glossary=glossary,
        procedures=procedures,
        entities=entities,
    ):
        path = package_dir / base_name
        path.write_text(content.strip() + "\n", encoding="utf-8")
        written_files.append(path)

    package_file_names = sorted(path.name for path in written_files)
    instructions_path = package_dir / "INSTRUCTIONS.txt"
    instructions_path.write_text(build_instructions(corpus_name, package_file_names).strip() + "\n", encoding="utf-8")
    written_files.append(instructions_path)

    guide_path = package_dir / "FILE_GUIDE.txt"
    guide_path.write_text(build_file_guide(sorted(path.name for path in written_files)).strip() + "\n", encoding="utf-8")
    written_files.append(guide_path)

    return BuildResult(
        package_dir=package_dir,
        zip_path=zip_path,
        written_files=sorted(written_files),
        corpus_name=safe_corpus_name,
        source_folder_name=source_folder_name,
    )


def _paginate_optional_files(
    safe_corpus_name: str,
    reference_facts: str,
    glossary: str,
    procedures: str,
    entities: str,
) -> list[tuple[str, str]]:
    outputs: list[tuple[str, str]] = []
    for stem, content in (
        ("reference_facts", reference_facts),
        ("glossary", glossary),
        ("procedures", procedures),
        ("entities", entities),
    ):
        if not content.strip():
            continue
        pages = _split_markdown_pages(content)
        if len(pages) == 1:
            outputs.append((f"{safe_corpus_name}__{stem}.md", pages[0]))
            continue
        for index, page in enumerate(pages, start=1):
            outputs.append((f"{safe_corpus_name}__{stem}__p{index:02d}.md", page))
    return outputs


def _split_markdown_pages(content: str, target_words: int = 1700) -> list[str]:
    if word_count(content) <= target_words:
        single = content.strip()
        return [single] if _has_substantive_markdown_content(single) else []

    sections = [section.strip() for section in content.split("\n## ") if section.strip()]
    rebuilt_sections: list[str] = []
    for index, section in enumerate(sections):
        if index == 0 and section.startswith("# "):
            rebuilt_sections.append(section)
        elif section.startswith("# "):
            rebuilt_sections.append(section)
        else:
            rebuilt_sections.append(f"## {section}")

    pages: list[str] = []
    current = ""
    for section in rebuilt_sections:
        candidate = f"{current}\n\n{section}".strip() if current else section
        if current and word_count(candidate) > target_words:
            pages.append(current.strip())
            current = section
        else:
            current = candidate
    if current.strip():
        pages.append(current.strip())
    filtered = [page for page in pages if _has_substantive_markdown_content(page)]
    if len(filtered) >= 2 and word_count(filtered[-1]) < 100:
        merged = f"{filtered[-2]}\n\n{filtered[-1]}".strip()
        if _has_substantive_markdown_content(merged) and word_count(merged) <= int(target_words * 1.25):
            filtered[-2] = merged
            filtered.pop()
    return filtered


def _has_substantive_markdown_content(content: str) -> bool:
    meaningful_lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not meaningful_lines:
        return False
    substantive = [line for line in meaningful_lines if word_count(line) >= 3]
    if not substantive:
        return False
    total_words = word_count(" ".join(substantive))
    if total_words >= 8:
        return True
    return any(word_count(line) >= 4 for line in substantive)
