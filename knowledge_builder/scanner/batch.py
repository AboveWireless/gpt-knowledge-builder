from __future__ import annotations

from pathlib import Path

from ..compiler_models import BatchBuildResult
from ..gpt_compiler import compile_gpt_knowledge_batch
from .discovery import discover_batch_corpora


def compile_batch_root(input_root: Path, output_dir: Path, zip_pack: bool, debug_outputs: bool) -> BatchBuildResult:
    # Discover child folders first so routing/validation can reason about batch contents deterministically.
    discover_batch_corpora(input_root)
    return compile_gpt_knowledge_batch(
        input_root=input_root,
        output_dir=output_dir,
        zip_pack=zip_pack,
        debug_outputs=debug_outputs,
    )
