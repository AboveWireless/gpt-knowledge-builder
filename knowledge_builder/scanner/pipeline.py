from __future__ import annotations

from ..compiler_models import BuildResult
from ..gpt_compiler import compile_gpt_knowledge_pack
from .config import default_pack_name, to_build_options
from .models import RunConfig


def compile_single_corpus(config: RunConfig) -> BuildResult:
    if not config.pack_name.strip():
        config = RunConfig(
            input_dir=config.input_dir,
            output_dir=config.output_dir,
            pack_name=default_pack_name(config.input_dir),
            zip_pack=config.zip_pack,
            debug_outputs=config.debug_outputs,
            batch_subfolders=config.batch_subfolders,
        )
    return compile_gpt_knowledge_pack(to_build_options(config))
