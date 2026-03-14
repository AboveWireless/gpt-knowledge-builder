# Windows Build

## Windows version for end users

When a tagged GitHub release is published, it includes:

- `GPTKnowledgeBuilder-<version>-Setup.exe`
- `GPTKnowledgeBuilder-<version>-portable.zip`

Install it like this:

1. Download the latest Windows asset from GitHub Releases.
2. Run `GPTKnowledgeBuilder-<version>-Setup.exe` for the normal installer path.
3. Or unzip `GPTKnowledgeBuilder-<version>-portable.zip` and launch `GPTKnowledgeBuilder.exe` directly.

If the Releases page is empty, use the local build steps below to produce the Windows app yourself.

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
