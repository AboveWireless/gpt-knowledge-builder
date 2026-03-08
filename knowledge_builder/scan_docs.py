from __future__ import annotations

from .cli import run_scan_docs


def main() -> int:
    return run_scan_docs()


if __name__ == "__main__":
    raise SystemExit(main())
