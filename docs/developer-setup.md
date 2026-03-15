# Developer Setup

If you want to learn the app as a normal user first, start with [user-guide.md](user-guide.md).

## Local install

Core install:

```powershell
python -m pip install -e .
```

Recommended local development install:

```powershell
python -m pip install -e ".[dev,extractors,ai]"
```

Optional OCR support:

```powershell
python -m pip install -e ".[ocr]"
```

## Launch the desktop app

```powershell
python -m knowledge_builder
```

Or use the installed GUI script:

```powershell
gpt-knowledge-builder
```

## Advanced CLI

Project workflow:

```powershell
python -m knowledge_builder project init --project-dir C:\gptkb\workspace --source-root C:\docs --output-dir C:\gptkb\exports --project-name tower_library
python -m knowledge_builder project scan --project-dir C:\gptkb\workspace
python -m knowledge_builder project review --project-dir C:\gptkb\workspace --approve-all
python -m knowledge_builder project export --project-dir C:\gptkb\workspace --zip-pack
```

Validation and targeted review updates:

```powershell
python -m knowledge_builder project validate --project-dir C:\gptkb\workspace
python -m knowledge_builder project review --project-dir C:\gptkb\workspace --review-id "<doc>::taxonomy" --status accepted --override-title "Grounding Basics" --override-domain operations --note "Reviewed manually"
```

Compatibility one-shot compiler:

```powershell
python -m knowledge_builder scan-docs --input-dir C:\docs --output-dir C:\out --pack-name tower_library
scan-docs --input-dir C:\docs --output-dir C:\out --pack-name tower_library
```

## Packaging entrypoints

- Windows packaging: see [windows-build.md](windows-build.md)
- macOS packaging: see [macos-build.md](macos-build.md)
- Release mechanics: see [release-process.md](release-process.md)

Useful build commands:

```powershell
python -m pip install -e ".[windows-build,extractors,ocr,ai]"
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

```bash
python -m pip install -e ".[macos-build,extractors,ocr,ai]"
bash ./scripts/build_macos.sh
```

## AI and OCR notes

- AI enrichment is off by default and only sends text to the configured provider when the user enables it.
- Users can provide an API key through the app or via `OPENAI_API_KEY`.
- OCR requires both the Python extras and an external Tesseract runtime on the system path.
- If OCR dependencies are missing, the app degrades gracefully and records the missing extractor state instead of crashing.

## Refresh GitHub assets

Regenerate the repo screenshots and presentation assets with:

```powershell
python .\scripts\render_github_screenshot.py --render-repo-assets
```

That command refreshes:

- `docs/images/github-home.png`
- `docs/images/github-sources.png`
- `docs/images/github-processing.png`
- `docs/images/github-review.png`
- `docs/images/github-export.png`
- `docs/images/repo-hero.png`
- `docs/images/repo-tour.png`
- `docs/images/repo-review-detail.png`
- `docs/images/repo-export-detail.png`

## Troubleshooting

- If the GUI does not launch, verify Tk is available in your Python installation.
- If OCR results are empty, verify Tesseract is installed and callable from the command line.
- If AI enrichment is enabled but nothing runs, verify the API key and provider settings.
- If Windows packaging fails, confirm Inno Setup 6 is installed or rerun the build script with `-SkipInstaller`.
- If macOS packaging fails, confirm Xcode Command Line Tools are installed and rerun `bash ./scripts/build_macos.sh`.
