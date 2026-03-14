# Release Process

## Release flow

Before the first public tag, replace the placeholder GitHub URLs in `pyproject.toml`, `knowledge_builder/version.py`, and `packaging/windows/GPTKnowledgeBuilder.iss` with the real repository path.

1. Update `CHANGELOG.md`.
2. Ensure `knowledge_builder/version.py` contains the release version.
3. Verify `python -m pytest` passes locally.
4. Refresh the GitHub screenshots with `python .\scripts\render_github_screenshot.py --render-repo-assets`.
5. Push the release branch or merge into `main`.
6. Create and push a tag like `v0.1.0`.
7. GitHub Actions will run tests, build the Windows and macOS desktop packages, and publish the release artifacts.

## Manual release checklist

- Fresh Windows install test with the generated installer
- Fresh macOS install test with the generated `.dmg` or `.zip`
- GUI launch without Python installed
- Create project, scan, review, and export package
- README copy and screenshots match the current guided workflow
- README clearly lists both the Windows installer and the macOS version plus first-launch instructions
- AI enrichment flow with a user-supplied API key
- OCR-disabled behavior
- OCR-enabled behavior on a machine with Tesseract installed
- Installer uninstall and reinstall
- macOS first-launch Gatekeeper flow

## Signing

Code signing is intentionally out of scope for this first public release.

If signing infrastructure is added later:

- sign the Windows executable and installer plus the macOS app and disk image in the release workflow
- document the certificate and notarization requirements and storage
- update release acceptance criteria
