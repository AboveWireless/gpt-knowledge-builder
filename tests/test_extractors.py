import sys
from pathlib import Path

from knowledge_builder.extractors import _extract_pdf, _extract_pdf_with_fitz
from knowledge_builder.models import ExtractedContent, PageText


class _FakeTools:
    def __init__(self) -> None:
        self.errors = True
        self.warnings = True
        self.calls: list[tuple[str, bool | None]] = []
        self.reset_called = False

    def mupdf_display_errors(self, value=None):
        self.calls.append(("errors", value))
        if value is None:
            return self.errors
        self.errors = bool(value)
        return self.errors

    def mupdf_display_warnings(self, value=None):
        self.calls.append(("warnings", value))
        if value is None:
            return self.warnings
        self.warnings = bool(value)
        return self.warnings

    def reset_mupdf_warnings(self):
        self.reset_called = True


class _FakeFitzFailure:
    TOOLS = _FakeTools()

    @staticmethod
    def open(_path):
        raise RuntimeError("bad pdf")


def test_extract_pdf_with_fitz_suppresses_messages_and_falls_back_on_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "fitz", _FakeFitzFailure)

    result = _extract_pdf_with_fitz(Path("broken.pdf"), None)

    assert result is None
    assert ("errors", False) in _FakeFitzFailure.TOOLS.calls
    assert ("warnings", False) in _FakeFitzFailure.TOOLS.calls
    assert _FakeFitzFailure.TOOLS.reset_called is True
    assert _FakeFitzFailure.TOOLS.errors is True
    assert _FakeFitzFailure.TOOLS.warnings is True


def test_extract_pdf_falls_back_when_fitz_returns_none(monkeypatch):
    monkeypatch.setattr("knowledge_builder.extractors._extract_pdf_with_fitz", lambda path, config: None)
    monkeypatch.setattr(
        "knowledge_builder.extractors._extract_pdf_with_pdfplumber",
        lambda path: ExtractedContent(
            text="fallback text",
            title="fallback",
            extraction_method="pdfplumber",
            pages=[PageText(page_number=1, text="fallback text")],
        ),
    )

    result = _extract_pdf(Path("broken.pdf"), None)

    assert result.extraction_method == "pdfplumber"
    assert result.text == "fallback text"
