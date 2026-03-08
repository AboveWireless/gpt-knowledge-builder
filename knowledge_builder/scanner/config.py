from __future__ import annotations

from pathlib import Path

from ..compiler_models import BuildOptions
from .models import RunConfig


def to_build_options(config: RunConfig) -> BuildOptions:
    return BuildOptions(
        input_dir=config.input_dir.resolve(),
        output_dir=config.output_dir.resolve(),
        pack_name=config.pack_name,
        zip_pack=config.zip_pack,
        debug_outputs=config.debug_outputs,
        source_folder_name=config.input_dir.name,
    )


def default_pack_name(input_dir: Path) -> str:
    return input_dir.name or "knowledge_pack"
