from __future__ import annotations

import sys
from pathlib import Path

from knowledge_builder.project.previews import render_document_preview, render_document_preview_strip
from knowledge_builder.project.store import init_project, save_state


class _FakePixmap:
    def __init__(self) -> None:
        self.saved_paths: list[str] = []

    def save(self, path: str) -> None:
        Path(path).write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
            b"\x90wS\xde"
            b"\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
            b"\xe2!\xbc3"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        self.saved_paths.append(path)


class _FakePage:
    class rect:
        width = 600

    def get_pixmap(self, matrix=None, alpha=False):
        return _FakePixmap()


class _FakePdf:
    def __getitem__(self, index):
        if index != 0:
            raise IndexError(index)
        return _FakePage()


class _FakeFitz:
    open_calls = 0

    @staticmethod
    def open(_path):
        _FakeFitz.open_calls += 1
        return _FakePdf()

    class Matrix:
        def __init__(self, x, y):
            self.x = x
            self.y = y


def test_render_document_preview_renders_and_caches_pdf_page(monkeypatch, tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    pdf_path = source_dir / "manual.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    init_project(project_dir, "Preview Project", [source_dir], output_dir, "mixed-office-documents", "custom-gpt-balanced")
    save_state(
        project_dir,
        {
            "version": 1,
            "documents": {
                str(pdf_path): {
                    "document": {
                        "source_path": str(pdf_path),
                        "checksum": "abc123",
                        "preview_mode": "pdf_image",
                        "preview_units": [{"label": "Page 1", "text": "fallback text", "page_number": 1, "ocr_used": False}],
                        "preview_cache": {},
                        "last_preview_error": "",
                        "preview_excerpt": "fallback text",
                    }
                }
            },
            "exports": [],
        },
    )
    monkeypatch.setitem(sys.modules, "fitz", _FakeFitz)

    first = render_document_preview(project_dir, str(pdf_path), 0)
    second = render_document_preview(project_dir, str(pdf_path), 0)

    assert first["mode"] == "pdf_image"
    assert Path(first["image_path"]).exists()
    assert second["image_path"] == first["image_path"]
    assert _FakeFitz.open_calls == 1


def test_render_document_preview_strip_returns_entries_for_each_unit(monkeypatch, tmp_path: Path):
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    pdf_path = source_dir / "manual.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    init_project(project_dir, "Preview Strip", [source_dir], output_dir, "mixed-office-documents", "custom-gpt-balanced")
    save_state(
        project_dir,
        {
            "version": 1,
            "documents": {
                str(pdf_path): {
                    "document": {
                        "source_path": str(pdf_path),
                        "checksum": "abc456",
                        "preview_mode": "pdf_image",
                        "preview_units": [
                            {"label": "Page 1", "text": "page one", "page_number": 1, "ocr_used": False},
                            {"label": "Page 2", "text": "page two", "page_number": 1, "ocr_used": False},
                        ],
                        "preview_cache": {},
                        "last_preview_error": "",
                        "preview_excerpt": "fallback text",
                    }
                }
            },
            "exports": [],
        },
    )
    monkeypatch.setitem(sys.modules, "fitz", _FakeFitz)

    strip = render_document_preview_strip(project_dir, str(pdf_path))

    assert len(strip) == 2
    assert strip[0]["label"] == "Page 1"
    assert Path(strip[0]["image_path"]).exists()
