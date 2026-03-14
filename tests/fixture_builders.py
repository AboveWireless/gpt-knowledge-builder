from __future__ import annotations

from pathlib import Path


def build_mixed_stress_corpus(
    source_dir: Path,
    *,
    text_docs: int = 75,
    broken_json: int = 6,
    broken_xml: int = 4,
    duplicates_every: int = 15,
) -> None:
    duplicate_body = "Ground lug torque: 45 Nm.\nDisconnect power before service.\n"
    for index in range(text_docs):
        body = duplicate_body if duplicates_every and index % duplicates_every == 0 else (
            f"Tower installation procedure {index}\n\n"
            f"1. Inspect sector {index}.\n2. Confirm grounding path.\n3. Log result {index}.\n"
        )
        (source_dir / f"doc_{index:03d}.txt").write_text(body, encoding="utf-8")
    for index in range(broken_json):
        (source_dir / f"broken_{index:02d}.json").write_text('{"alpha": 1,,}', encoding="utf-8")
    for index in range(broken_xml):
        (source_dir / f"broken_{index:02d}.xml").write_text("<root><node>broken", encoding="utf-8")
