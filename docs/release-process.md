# Release Process

## Release flow

Before the first public tag, replace the placeholder GitHub URLs in `pyproject.toml`, `knowledge_builder/version.py`, and `packaging/windows/GPTKnowledgeBuilder.iss` with the real repository path.

1. Update `CHANGELOG.md`.
2. Ensure `knowledge_builder/version.py` contains the release version.
3. Verify `python -m pytest` passes locally.
4. Push the release branch or merge into `main`.
5. Create and push a tag like `v0.1.0`.
6. GitHub Actions will run tests, build the Windows app, package the installer, and publish release artifacts.

## Manual release checklist

- Fresh Windows install test with the generated installer
- GUI launch without Python installed
- Create project, scan, review, and export package
- AI enrichment flow with a user-supplied API key
- OCR-disabled behavior
- OCR-enabled behavior on a machine with Tesseract installed
- Installer uninstall and reinstall
- README commands and screenshots match the product

## Signing

Code signing is intentionally out of scope for this first public release.

If signing infrastructure is added later:

- sign the executable and installer in the release workflow
- document the certificate requirements and storage
- update release acceptance criteria
