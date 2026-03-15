# GPT Knowledge Builder

[![CI](https://github.com/AboveWireless/gpt-knowledge-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/AboveWireless/gpt-knowledge-builder/actions/workflows/ci.yml)
[![Release status](https://img.shields.io/badge/release-preview-orange)](https://github.com/AboveWireless/gpt-knowledge-builder/releases)
[![License](https://img.shields.io/github/license/AboveWireless/gpt-knowledge-builder)](https://github.com/AboveWireless/gpt-knowledge-builder/blob/main/LICENSE)

Local-first desktop app for Windows and macOS that turns messy document folders into clean, upload-ready Custom GPT knowledge packages.

![GPT Knowledge Builder hero](docs/images/repo-hero.png)

Turn a folder mess into GPT-ready files with a simple four-step desktop flow:

1. `Pick Folders`
2. `Scan Files`
3. `Fix Issues`
4. `Get GPT Files`

![GPT Knowledge Builder workflow tour](docs/images/repo-tour.png)

## Why it works

- Beginner-first desktop workflow with one clear next action on every main screen.
- Review queue catches duplicates, low-signal content, weak OCR, and extraction issues before export.
- Final package stays small and traceable instead of dumping raw source folders into a model.
- Optional OpenAI enrichment stays off until the user explicitly enables it.

## Review and export with confidence

![GPT Knowledge Builder review detail](docs/images/repo-review-detail.png)

![GPT Knowledge Builder export detail](docs/images/repo-export-detail.png)

## Download status

When a tagged GitHub release is published, it will include Windows and macOS desktop packages plus `SHA256SUMS.txt`.

This repo is prepared for the first public-preview desktop release, but the first tagged GitHub release has not been published yet.

- `Windows version`: when a tagged release is published it will include `GPTKnowledgeBuilder-<version>-Setup.exe` and `GPTKnowledgeBuilder-<version>-portable.zip`.
- `macOS version`: when a tagged release is published it will include `GPTKnowledgeBuilder-<version>-macos.dmg` and `GPTKnowledgeBuilder-<version>-macos.zip`.
- `Checksums`: release assets are paired with `SHA256SUMS.txt` so downloads can be verified before launch.
- `No release yet`: If the [Releases](https://github.com/AboveWireless/gpt-knowledge-builder/releases) page is empty, use the Windows or macOS build guides below to create the desktop app locally.
- `macOS first launch`: if Gatekeeper blocks the app, Control-click it, choose `Open`, and use `System Settings` -> `Privacy & Security` -> `Open Anyway` if needed.

## Docs

- [Developer setup](docs/developer-setup.md)
- [Product capabilities](docs/product-capabilities.md)
- [Windows build guide](docs/windows-build.md)
- [macOS build guide](docs/macos-build.md)
- [Release process](docs/release-process.md)
- [Privacy and data handling](docs/privacy-and-data-handling.md)

## Project status

- CI is green across Windows, macOS, and Linux.
- The release workflow builds Windows and macOS packages and publishes `SHA256SUMS.txt` on tagged releases.
- Remaining release hardening is mostly around the first public tag, code signing, Windows Credential Manager, and richer review editing.

## License

MIT. See [LICENSE](LICENSE).
