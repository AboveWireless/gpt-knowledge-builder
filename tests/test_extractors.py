import sys
from pathlib import Path

from knowledge_builder.extractors import _extract_csv, _extract_docx, _extract_json, _extract_pdf, _extract_pdf_with_fitz, get_supported_doc_type
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

    assert result is not None
    assert result.extraction_status == "failed"
    assert result.failure_reason == "bad pdf"
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
    assert result.fallback_chain == ["pymupdf", "pdfplumber"]


def test_extract_json_marks_malformed_payload_as_partial(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text('{"alpha": 1,,}', encoding="utf-8")

    result = _extract_json(path, None)

    assert result.extraction_status == "partial"
    assert "Malformed JSON" in result.warnings[0]
    assert result.text.startswith('{"alpha"')


def test_supported_doc_type_includes_common_text_like_and_tsv_files(tmp_path: Path):
    assert get_supported_doc_type(tmp_path / "notes.yaml") == "txt"
    assert get_supported_doc_type(tmp_path / "server.log") == "txt"
    assert get_supported_doc_type(tmp_path / "settings.toml") == "txt"
    assert get_supported_doc_type(tmp_path / "table.tsv") == "tsv"


def test_extract_csv_handles_tsv_delimiter(tmp_path: Path):
    path = tmp_path / "table.tsv"
    path.write_text("part\ttorque\nlug\t45 Nm\n", encoding="utf-8")

    result = _extract_csv(path, None)

    assert "part | torque" in result.text
    assert "lug | 45 Nm" in result.text


def test_extract_docx_builds_structure_units_from_headings(monkeypatch, tmp_path: Path):
    class _FakeStyle:
        def __init__(self, name):
            self.name = name

    class _FakeParagraph:
        def __init__(self, text, style):
            self.text = text
            self.style = _FakeStyle(style)

    class _FakeCore:
        title = "Tower Guide"

    class _FakeDoc:
        def __init__(self):
            self.core_properties = _FakeCore()
            self.paragraphs = [
                _FakeParagraph("Overview", "Heading 1"),
                _FakeParagraph("Ground the cabinet before service.", "Normal"),
                _FakeParagraph("Checklist item", "List Paragraph"),
                _FakeParagraph("1.1 Procedure", "Normal"),
                _FakeParagraph("Tighten lug to 45 Nm.", "Normal"),
            ]
            self.tables = [
                type(
                    "FakeTable",
                    (),
                    {
                        "rows": [
                            type("FakeRow", (), {"cells": [type("FakeCell", (), {"text": "Part"}), type("FakeCell", (), {"text": "Torque"})]})(),
                            type("FakeRow", (), {"cells": [type("FakeCell", (), {"text": "Lug"}), type("FakeCell", (), {"text": "45 Nm"})]})(),
                        ]
                    },
                )()
            ]

    monkeypatch.setitem(sys.modules, "docx", type("FakeDocx", (), {"Document": lambda _path: _FakeDoc()}))

    result = _extract_docx(tmp_path / "guide.docx", None)

    assert result.extraction_status in {"success", "partial"}
    assert result.extra["structure_units"]
    assert result.extra["structure_units"][0]["label"] == "Overview"
    assert "Checklist item" in result.extra["structure_units"][0]["text"]
    labels = [unit["label"] for unit in result.extra["structure_units"]]
    assert "1.1 Procedure" in labels
    assert "Table 1" in labels
    table_unit = next(unit for unit in result.extra["structure_units"] if unit["label"] == "Table 1")
    assert "Part" in table_unit["text"]
    assert "Torque" in table_unit["text"]
    assert "Lug" in table_unit["text"]
    assert "45 Nm" in table_unit["text"]
    assert "-+-" in table_unit["text"]
