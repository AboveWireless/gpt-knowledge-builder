from __future__ import annotations

import fnmatch
from pathlib import Path

from .models import Config
from .utils import slugify


def resolve_taxonomy(config: Config, source_path: Path, root: Path) -> tuple[str, str]:
    rel = _as_posix_safe(source_path.relative_to(root))
    abs_path = _as_posix_safe(source_path)

    for rule in config.taxonomy_rules:
        if _match(rel, rule.pattern) or _match(abs_path, rule.pattern):
            return slugify(rule.gpt_purpose), slugify(rule.topic)
    return slugify(config.defaults.gpt_purpose), slugify(config.defaults.topic)


def _as_posix_safe(path: Path) -> str:
    return path.as_posix()


def _match(path: str, pattern: str) -> bool:
    if fnmatch.fnmatch(path, pattern):
        return True
    if pattern.startswith("**/"):
        return fnmatch.fnmatch(path, pattern[3:])
    return False
