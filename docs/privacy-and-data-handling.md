# Privacy and Data Handling

GPT Knowledge Builder is designed as a local-first desktop application.

## What stays local

By default, source discovery, extraction, normalization, review, and package export run on the local machine.

The application writes project state into the workspace:

```text
<project_dir>/
  project.yaml
  .knowledge_builder/
    cache/
    logs/
    reviews.json
    state.json
    secrets.json
```

Generated GPT upload packages and provenance/debug sidecars are written under the configured export location.

## Optional network use

Network calls are optional and only used when AI enrichment is enabled and a provider API key is configured.

When OpenAI enrichment is enabled:

- selected document text may be sent to the OpenAI API
- responses are cached locally by checksum, model, and prompt version
- disabling AI enrichment stops those outbound calls

## API key handling

Users can provide an API key through the GUI or environment variables.

Resolution order:

1. `OPENAI_API_KEY`
2. project-local `.knowledge_builder/secrets.json`

The project-local secret store is convenient but not equivalent to OS keychain storage. For this public release, it is documented as an interim approach.

## OCR requirements

OCR is optional. The Python dependencies can be installed without OCR support.

When OCR is enabled for image documents or scanned PDFs:

- `pytesseract` and `Pillow` are required
- the external Tesseract OCR runtime must be installed and available on the system path

If OCR dependencies are missing, the app degrades gracefully and marks the extraction method accordingly.
