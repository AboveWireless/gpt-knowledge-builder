# Contributing

## Development setup

```powershell
python -m pip install -e ".[dev,extractors,ai]"
python -m pytest
```

OCR and desktop packaging extras are optional:

```powershell
python -m pip install -e ".[ocr,windows-build,macos-build]"
```

## Contribution expectations

- Keep the product GUI-first. CLI additions should support advanced use, not complicate the main flow.
- Preserve local-first behavior. Network use must stay optional and explicit.
- Keep exported GPT packages clean. Debug and provenance artifacts belong outside the upload package.
- Add or update tests for behavioral changes.
- Update docs when user-facing behavior changes.
- Keep public screenshots, build guides, and release wording aligned with the current product and release state.

## Pull requests

- Open a focused branch.
- Describe the problem, solution, and any user-visible tradeoffs.
- Include screenshots for GUI changes when practical.
- Ensure `python -m pytest` passes before requesting review.

## Release-sensitive areas

Take extra care when changing:

- packaging under `packaging/windows/`
- packaging under `packaging/macos/`
- project persistence under `.knowledge_builder/`
- export format and GPT package naming
- API-key handling and privacy-sensitive flows

## Versioning

This repository uses semantic versioning. Public releases are tagged as `vX.Y.Z`.
