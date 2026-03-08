# Windows Build

## Prerequisites

- Python 3.10 or newer
- Inno Setup 6 for installer creation
- optional Tesseract OCR runtime if OCR support is needed

## Local build

```powershell
python -m pip install -e ".[windows-build,extractors,ocr,ai]"
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

Outputs:

```text
dist\
  GPT Knowledge Builder\
    GPTKnowledgeBuilder.exe
  installer\
    GPTKnowledgeBuilder-<version>-Setup.exe
```

## Deterministic versioning

The Windows build reads version metadata from `knowledge_builder.version`.

That version is used for:

- Python package metadata
- PyInstaller version resource generation
- Inno Setup installer version and output filename

## OCR packaging note

The packaged app can include the Python OCR dependencies, but users still need the Tesseract runtime installed unless you separately bundle that dependency.
