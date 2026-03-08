from __future__ import annotations

import sys
from pathlib import Path

try:
    from .cli import run
except ImportError as exc:
    if "attempted relative import with no known parent package" not in str(exc):
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from knowledge_builder.cli import run


if __name__ == "__main__":
    raise SystemExit(run())
