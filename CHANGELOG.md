# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [Unreleased]

### Added
- macOS desktop packaging, release artifacts, and end-user install guidance alongside the Windows release flow.
- Branded cross-platform app icons plus deterministic GitHub screenshot generation for the public repo.
- Repo verification coverage for screenshots, release docs, and cross-platform workflow outputs.
- Release checksum publishing via `SHA256SUMS.txt` plus repo-level editor and Git attributes for cleaner cross-platform collaboration.

### Changed
- Refined the guided desktop UI with larger spacing, plainer beginner wording, and clearer next-step actions.
- Refreshed the README, build guides, and release process docs so they match the current Windows and macOS release story.
- Standardized the public screenshot set around consistent real-product captures for home, sources, processing, review, and export.

## [0.1.0] - 2026-03-08

### Added
- Local-first desktop workspace for building Custom GPT knowledge packages.
- GUI-first workflow for source discovery, processing, review, export, and settings.
- Windows packaging via PyInstaller and Inno Setup.
- Optional OpenAI-powered enrichment with cached results.
- Review queue editing, provenance sidecars, and export splitting.
- GitHub release scaffolding, CI workflows, governance files, and public docs.
