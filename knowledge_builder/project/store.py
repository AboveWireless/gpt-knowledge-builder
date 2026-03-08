from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import yaml

from ..utils import ensure_dir
from .models import ModelSettings, ProjectConfig, ReviewThresholds


PROJECT_FILE = "project.yaml"
STATE_DIR = ".knowledge_builder"
SECRETS_FILE = "secrets.json"


def init_project(
    project_root: Path,
    project_name: str,
    source_roots: list[Path],
    output_root: Path,
    preset: str,
    export_profile: str,
    model_enabled: bool = False,
) -> Path:
    project_root = project_root.resolve()
    ensure_dir(project_root)
    ensure_dir(_state_root(project_root))
    for subdir in ("cache/raw", "cache/clean", "cache/model", "exports", "logs"):
        ensure_dir(_state_root(project_root) / subdir)

    config = ProjectConfig(
        version=1,
        project_name=project_name.strip() or project_root.name,
        source_roots=[_to_project_relative(project_root, path.resolve()) for path in source_roots],
        output_root=_to_project_relative(project_root, output_root.resolve()),
        preset=preset,
        export_profile=export_profile,
        optional_model_settings=ModelSettings(enabled=model_enabled, provider="openai", model="gpt-5.4"),
    )
    save_project_config(project_root, config)
    _write_json(project_root, "state.json", {"version": 1, "documents": {}, "exports": []})
    _write_json(project_root, "reviews.json", {"version": 1, "items": []})
    return project_root / PROJECT_FILE


def load_project_config(project_root: Path) -> ProjectConfig:
    project_root = project_root.resolve()
    raw = yaml.safe_load((project_root / PROJECT_FILE).read_text(encoding="utf-8")) or {}
    model_raw = raw.get("optional_model_settings") or {}
    review_raw = raw.get("review_thresholds") or {}
    defaults = ProjectConfig(
        version=1,
        project_name=str(raw.get("project_name", project_root.name)),
        source_roots=[str(value) for value in raw.get("source_roots") or []],
        output_root=str(raw.get("output_root", "exports")),
    )
    return ProjectConfig(
        version=int(raw.get("version", 1)),
        project_name=str(raw.get("project_name", defaults.project_name)),
        source_roots=[str(value) for value in raw.get("source_roots") or defaults.source_roots],
        output_root=str(raw.get("output_root", defaults.output_root)),
        preset=str(raw.get("preset", defaults.preset)),
        export_profile=str(raw.get("export_profile", defaults.export_profile)),
        include_globs=[str(value) for value in raw.get("include_globs") or defaults.include_globs],
        exclude_globs=[str(value) for value in raw.get("exclude_globs") or defaults.exclude_globs],
        optional_model_settings=ModelSettings(
            enabled=bool(model_raw.get("enabled", defaults.optional_model_settings.enabled)),
            provider=str(model_raw.get("provider", defaults.optional_model_settings.provider)),
            model=str(model_raw.get("model", defaults.optional_model_settings.model)),
            prompt_version=str(model_raw.get("prompt_version", defaults.optional_model_settings.prompt_version)),
        ),
        review_thresholds=ReviewThresholds(
            low_signal_word_count=int(review_raw.get("low_signal_word_count", defaults.review_thresholds.low_signal_word_count)),
            duplicate_similarity_threshold=float(review_raw.get("duplicate_similarity_threshold", defaults.review_thresholds.duplicate_similarity_threshold)),
            low_confidence_threshold=float(review_raw.get("low_confidence_threshold", defaults.review_thresholds.low_confidence_threshold)),
        ),
        taxonomy_presets={str(key): value for key, value in (raw.get("taxonomy_presets") or {}).items()},
    )


def save_project_config(project_root: Path, config: ProjectConfig) -> None:
    payload = asdict(config)
    (project_root / PROJECT_FILE).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def load_state(project_root: Path) -> dict:
    return _read_json(project_root, "state.json", {"version": 1, "documents": {}, "exports": []})


def save_state(project_root: Path, payload: dict) -> None:
    _write_json(project_root, "state.json", payload)


def load_reviews(project_root: Path) -> dict:
    return _read_json(project_root, "reviews.json", {"version": 1, "items": []})


def save_reviews(project_root: Path, payload: dict) -> None:
    _write_json(project_root, "reviews.json", payload)


def load_secrets(project_root: Path) -> dict:
    return _read_json(project_root, SECRETS_FILE, {"version": 1, "providers": {}})


def save_secrets(project_root: Path, payload: dict) -> None:
    _write_json(project_root, SECRETS_FILE, payload)


def resolve_provider_api_key(project_root: Path, provider: str) -> str:
    provider = provider.strip().lower()
    env_map = {
        "openai": "OPENAI_API_KEY",
    }
    env_name = env_map.get(provider, "")
    if env_name:
        from_env = os.environ.get(env_name)
        if from_env:
            return from_env
    secrets = load_secrets(project_root)
    providers = secrets.get("providers") or {}
    provider_record = providers.get(provider) or {}
    return str(provider_record.get("api_key") or "")


def state_root(project_root: Path) -> Path:
    return _state_root(project_root.resolve())


def resolve_project_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (project_root / path).resolve()


def _state_root(project_root: Path) -> Path:
    return project_root / STATE_DIR


def _read_json(project_root: Path, name: str, fallback: dict) -> dict:
    path = _state_root(project_root.resolve()) / name
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(project_root: Path, name: str, payload: dict) -> None:
    path = _state_root(project_root.resolve()) / name
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _to_project_relative(project_root: Path, path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return str(path)
