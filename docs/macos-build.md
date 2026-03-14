# macOS Build

## macOS version for end users

When a tagged GitHub release is published, it includes a dedicated macOS version of the app:

- `GPTKnowledgeBuilder-<version>-macos.dmg`
- `GPTKnowledgeBuilder-<version>-macos.zip`
- `SHA256SUMS.txt`

Install it like this:

1. Download the latest macOS asset from GitHub Releases.
2. Open the `.dmg` or unzip the `.zip`.
3. Drag `GPT Knowledge Builder.app` into `Applications`.
4. Open the app from Finder or Spotlight.

If the Releases page is empty, use the local build steps below to produce the macOS app on a Mac.

If you want to verify the download before launching it, compare the asset's SHA-256 checksum against the matching line in `SHA256SUMS.txt`.

If macOS blocks the first launch:

1. Control-click `GPT Knowledge Builder.app`.
2. Choose `Open`.
3. Confirm the prompt.
4. If needed, open `System Settings` -> `Privacy & Security` and click `Open Anyway`.

## Prerequisites

- macOS 13 or newer recommended
- Python 3.10 or newer
- Xcode Command Line Tools installed
- optional Tesseract OCR runtime if OCR support is needed

Install Command Line Tools if needed:

```bash
xcode-select --install
```

## Local build

```bash
python -m pip install -e ".[macos-build,extractors,ocr,ai]"
bash ./scripts/build_macos.sh
```

Outputs:

```text
dist/
  GPT Knowledge Builder.app
  GPTKnowledgeBuilder-<version>-macos.zip
  installer/
    GPTKnowledgeBuilder-<version>-macos.dmg
```

## Notes

- The mac build must be produced on macOS. PyInstaller does not support cross-compiling a mac app bundle from Windows.
- The build uses a dedicated macOS `.icns` icon alongside the Windows `.ico` asset.
- The packaged app can include the Python OCR dependencies, but users still need the external Tesseract runtime installed unless you separately bundle it.
- Because the app is not code signed or notarized yet, the first-launch Gatekeeper prompt is expected in this public-preview phase.
