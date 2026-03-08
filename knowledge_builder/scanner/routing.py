from __future__ import annotations

from ..compiler_models import BatchBuildResult, BuildResult
from .batch import compile_batch_root
from .models import RunConfig
from .pipeline import compile_single_corpus


def route_build(config: RunConfig) -> BuildResult | BatchBuildResult:
    if config.batch_subfolders:
        return compile_batch_root(
            input_root=config.input_dir,
            output_dir=config.output_dir,
            zip_pack=config.zip_pack,
            debug_outputs=config.debug_outputs,
        )
    return compile_single_corpus(config)
