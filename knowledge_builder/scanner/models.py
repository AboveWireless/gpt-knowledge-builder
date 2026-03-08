from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RunConfig:
    input_dir: Path
    output_dir: Path
    pack_name: str = ""
    zip_pack: bool = False
    debug_outputs: bool = False
    batch_subfolders: bool = False


@dataclass(slots=True)
class DiscoveredFile:
    path: Path
    file_type: str
    corpus_root: Path
