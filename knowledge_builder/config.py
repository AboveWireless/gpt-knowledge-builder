from __future__ import annotations

from pathlib import Path

import yaml

from .models import (
    ChunkingConfig,
    Config,
    Defaults,
    ExtractionConfig,
    LoggingConfig,
    OCRConfig,
    OutputsConfig,
    PerformanceConfig,
    TaxonomyRule,
)


REQUIRED_KEYS = {"input_roots", "output_root", "include_globs", "exclude_globs", "taxonomy_rules", "defaults"}


def load_config(path: Path) -> Config:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return parse_config_dict(raw, path.parent)


def parse_config_dict(raw: dict, base_dir: Path) -> Config:
    validate_config_dict(raw)
    input_roots = [_resolve_path(base_dir, Path(p)) for p in raw["input_roots"]]
    output_root = _resolve_path(base_dir, Path(raw["output_root"]))
    rules = [
        TaxonomyRule(
            pattern=str(item["pattern"]),
            gpt_purpose=str(item["gpt_purpose"]),
            topic=str(item["topic"]),
        )
        for item in raw["taxonomy_rules"]
    ]

    defaults_raw = raw["defaults"]
    defaults = Defaults(
        gpt_purpose=str(defaults_raw["gpt_purpose"]),
        topic=str(defaults_raw["topic"]),
        language=str(defaults_raw.get("language", "en")),
    )

    ocr_raw = raw.get("ocr") or {}
    chunking_raw = raw.get("chunking") or {}
    outputs_raw = raw.get("outputs") or {}
    extraction_raw = raw.get("extraction") or {}
    performance_raw = raw.get("performance") or {}
    logging_raw = raw.get("logging") or {}

    return Config(
        input_roots=input_roots,
        output_root=output_root,
        include_globs=[str(v) for v in raw["include_globs"]],
        exclude_globs=[str(v) for v in raw["exclude_globs"]],
        taxonomy_rules=rules,
        defaults=defaults,
        ocr=OCRConfig(
            enabled=bool(ocr_raw.get("enabled", False)),
            engine=str(ocr_raw.get("engine", "tesseract")),
            threshold=float(ocr_raw.get("threshold", 0.45)),
        ),
        chunking=ChunkingConfig(
            target_words=int(chunking_raw.get("target_words", 800)),
            overlap_words=int(chunking_raw.get("overlap_words", 120)),
            min_words=int(chunking_raw.get("min_words", 250)),
        ),
        outputs=OutputsConfig(
            write_chunks=bool(outputs_raw.get("write_chunks", True)),
            write_structured_data=bool(outputs_raw.get("write_structured_data", True)),
            write_manifests=bool(outputs_raw.get("write_manifests", True)),
            write_raw_text=bool(outputs_raw.get("write_raw_text", True)),
            write_clean_docs=bool(outputs_raw.get("write_clean_docs", True)),
            write_root_markdown=bool(outputs_raw.get("write_root_markdown", True)),
        ),
        extraction=ExtractionConfig(
            preserve_page_numbers=bool(extraction_raw.get("preserve_page_numbers", False)),
            detect_tables=bool(extraction_raw.get("detect_tables", True)),
            detect_parts=bool(extraction_raw.get("detect_parts", True)),
            detect_requirements=bool(extraction_raw.get("detect_requirements", True)),
            remove_repeated_headers=bool(extraction_raw.get("remove_repeated_headers", True)),
        ),
        performance=PerformanceConfig(
            max_workers=int(performance_raw.get("max_workers", 4)),
            skip_large_files_mb=int(performance_raw.get("skip_large_files_mb", 0)),
        ),
        logging=LoggingConfig(
            level=str(logging_raw.get("level", "INFO")).upper(),
        ),
    )


def validate_config_dict(raw: dict) -> None:
    missing = REQUIRED_KEYS - set(raw.keys())
    if missing:
        raise ValueError(f"Missing config keys: {', '.join(sorted(missing))}")
    if not raw["input_roots"]:
        raise ValueError("input_roots must not be empty")
    if not raw["include_globs"]:
        raise ValueError("include_globs must not be empty")

    defaults = raw.get("defaults") or {}
    for key in ("gpt_purpose", "topic"):
        if not defaults.get(key):
            raise ValueError(f"defaults.{key} must be set")

    for idx, rule in enumerate(raw.get("taxonomy_rules", []), start=1):
        for field in ("pattern", "gpt_purpose", "topic"):
            if not rule.get(field):
                raise ValueError(f"taxonomy_rules[{idx}].{field} must be set")

    ocr_raw = raw.get("ocr") or {}
    threshold = float(ocr_raw.get("threshold", 0.45))
    if not 0 <= threshold <= 1:
        raise ValueError("ocr.threshold must be between 0 and 1")

    chunking_raw = raw.get("chunking") or {}
    if int(chunking_raw.get("target_words", 800)) <= 0:
        raise ValueError("chunking.target_words must be > 0")
    if int(chunking_raw.get("overlap_words", 120)) < 0:
        raise ValueError("chunking.overlap_words must be >= 0")
    if int(chunking_raw.get("min_words", 250)) <= 0:
        raise ValueError("chunking.min_words must be > 0")

    performance_raw = raw.get("performance") or {}
    if int(performance_raw.get("max_workers", 4)) <= 0:
        raise ValueError("performance.max_workers must be > 0")
    if int(performance_raw.get("skip_large_files_mb", 0)) < 0:
        raise ValueError("performance.skip_large_files_mb must be >= 0")


def _resolve_path(cfg_dir: Path, maybe_relative: Path) -> Path:
    if maybe_relative.is_absolute():
        return maybe_relative
    return (cfg_dir / maybe_relative).resolve()
