# Security Policy

## Supported versions

Security fixes are applied to the latest public release branch or tag line.

## Reporting a vulnerability

Do not open public GitHub issues for security-sensitive findings.

Use GitHub's private vulnerability reporting flow for this repository when it is available. If private reporting is not enabled yet, contact the repository maintainer privately instead of opening a public issue.

Include:

- affected version
- operating system
- reproduction steps
- impact assessment
- whether sensitive data exposure is involved

## Security notes for users

- The app is local-first by default.
- Optional AI enrichment sends selected text to the configured model provider only when enabled by the user.
- Saved API keys are currently stored in the project workspace under `.knowledge_builder/secrets.json`.
- Windows Credential Manager integration is planned, but not required for this first public release.
