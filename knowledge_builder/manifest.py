from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import ManifestRecord


STATE_DIR = ".gptkb"
MANIFEST_FILE = "manifest.json"


class ManifestStore:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root
        self.state_dir = output_root / STATE_DIR
        self.path = self.state_dir / MANIFEST_FILE
        self.legacy_path = output_root / MANIFEST_FILE
        self.records: dict[str, ManifestRecord] = {}

    def load(self) -> None:
        if not self.path.exists():
            if self.legacy_path.exists():
                raw = json.loads(self.legacy_path.read_text(encoding="utf-8"))
                self.records = {
                    key: ManifestRecord(**value)
                    for key, value in (raw.get("records") or {}).items()
                }
                return
            self.records = {}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.records = {
            key: ManifestRecord(**value)
            for key, value in (raw.get("records") or {}).items()
        }

    def save(self) -> None:
        payload = {
            "version": 1,
            "records": {key: asdict(record) for key, record in self.records.items()},
        }
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        if self.legacy_path.exists():
            self.legacy_path.unlink()

    def get(self, source_path: str) -> ManifestRecord | None:
        return self.records.get(source_path)

    def upsert(self, record: ManifestRecord) -> None:
        self.records[record.source_path] = record
