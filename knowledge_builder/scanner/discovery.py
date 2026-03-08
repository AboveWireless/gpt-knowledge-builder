from __future__ import annotations

import os
from pathlib import Path

from ..extractors import get_supported_doc_type
from .models import DiscoveredFile


IGNORED_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".gptkb",
}


def discover_corpus_files(input_dir: Path) -> list[DiscoveredFile]:
    files: list[DiscoveredFile] = []
    for root, dir_names, file_names in os.walk(input_dir):
        current_root = Path(root)
        dir_names[:] = sorted(name for name in dir_names if not _should_skip_dir(current_root / name))
        for file_name in sorted(file_names):
            path = current_root / file_name
            if _should_skip_file(path):
                continue
            file_type = get_supported_doc_type(path)
            if not file_type:
                continue
            files.append(DiscoveredFile(path=path, file_type=file_type, corpus_root=input_dir))
    return files


def discover_batch_corpora(input_root: Path) -> list[Path]:
    return sorted(path for path in input_root.iterdir() if path.is_dir() and not _should_skip_dir(path))


def _should_skip_dir(path: Path) -> bool:
    name = path.name.strip()
    lowered = name.lower()
    if not name:
        return True
    if name.startswith(".") or name in IGNORED_DIR_NAMES:
        return True
    if lowered.endswith("_gpt_knowledge") or lowered.endswith("_debug"):
        return True
    return False


def _should_skip_file(path: Path) -> bool:
    name = path.name.strip()
    if not name or name.startswith("."):
        return True
    if path.suffix.lower() in {".tmp", ".bak"}:
        return True
    return any(_should_skip_dir(parent) for parent in path.parents if parent.name)
