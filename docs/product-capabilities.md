# Product Capabilities

## What it is

GPT Knowledge Builder is a beginner-friendly desktop workspace for turning raw folders into clean GPT knowledge files.

It is designed for:

- consultants packaging client document sets for Custom GPTs
- teams organizing SOPs, policies, product docs, and training material
- power users who want deterministic exports and persistent project workspaces

## Guided workflow

The main desktop flow is:

1. `Pick Folders`
2. `Scan Files`
3. `Fix Issues`
4. `Get GPT Files`

The app keeps a project workspace so users can reopen the same corpus, review queue, and export history without rebuilding everything from scratch.

## Feature highlights

| Area | What it does |
| --- | --- |
| Ingestion | Scans PDFs, DOCX, XLSX, CSV, TXT, Markdown, HTML, XML, JSON, and OCR-supported images |
| Review | Flags duplicates, low-signal content, OCR issues, and taxonomy uncertainty before export |
| Packaging | Produces a curated GPT upload pack instead of a raw text dump |
| Traceability | Writes provenance sidecars without polluting the upload package |
| Desktop UX | Keeps the workflow GUI-first while still offering advanced controls and CLI entrypoints |

## Feature-by-feature breakdown

### Guided mode

Guided mode is the default experience.

It keeps the app easier to understand by:

- showing one clear next action on each main screen
- using plain labels such as `Pick Folders`, `Scan Files`, `Fix Issues`, and `Get GPT Files`
- hiding denser diagnostics and bulk controls until the user explicitly asks for them

### Folder setup and project saving

The setup flow is designed to feel lightweight for normal users.

Users can:

- choose one or more source folders
- choose the export folder
- save the project and reopen it later
- use a simple setup path without manually managing internal workspace files

This makes it easier to work with real document folders without needing to understand the project internals first.

### Source preview and dependency health

Before the first scan, the app can estimate what the workload looks like.

That includes:

- rough file counts
- a summary of supported versus unsupported files
- heavy-file indicators
- OCR-likely file counts
- dependency health checks for optional extractors and OCR tooling

This helps users spot likely trouble before they run a full scan.

### Scan and triage

The scan step builds the working corpus and records what needs attention.

It is meant to answer three questions quickly:

- how much content was processed
- what failed or only partially extracted
- whether the project is ready for review or export

The beginner view keeps this step focused on the current scan, the result summary, and the next recommended action.

### Review queue and preview tools

The review queue is one of the main product features.

It exists so the final package is curated instead of blindly exported.

The queue can surface:

- extraction failures
- duplicates
- taxonomy uncertainty
- low-confidence OCR
- low-signal documents
- AI low-confidence items when enrichment is enabled

The user can then work through each item with preview-first actions such as `Accept`, `Skip`, `Retry`, and `Next`.

### Export, validation, and provenance

Export is more than a single write step.

The app can:

- create the final GPT-ready files
- show export readiness and next-step guidance
- run validation checks
- list package artifacts
- write provenance sidecars and related manifests outside the upload payload

That keeps the deliverable cleaner while still preserving traceability for the person building the package.

### Beginner path and advanced controls

The product supports two levels of complexity:

- a guided beginner path for fast, low-stress use
- advanced controls for deeper setup, filtering, retry, diagnostics, and export inspection

This is useful when one person wants a simple workflow but another person on the same team needs more control.

### Persistent workspace

Projects are meant to be reopened.

That allows users to:

- scan in stages
- continue review later
- rescan after source changes
- compare progress across export runs

This is especially useful for larger document sets that are cleaned over time instead of in one sitting.

## Supported inputs

- PDF
- DOCX
- XLSX
- CSV
- TXT
- Markdown
- HTML
- XML
- JSON
- PNG / JPG / JPEG via OCR when OCR support is installed

## Export output

The final GPT package is intentionally clean:

```text
<output_dir>/<pack_name>_GPT_KNOWLEDGE/
  INSTRUCTIONS.txt
  FILE_GUIDE.txt
  <corpus_name>__knowledge_core__p01.md
  <corpus_name>__knowledge_core__p02.md
  <corpus_name>__reference_facts.md
  <corpus_name>__glossary.md
  <corpus_name>__procedures.md
  <corpus_name>__entities.md
```

Files are omitted when they would be empty or weak, except for `INSTRUCTIONS.txt` and `FILE_GUIDE.txt`.

Project exports can also write provenance sidecars such as:

- `package_index.md`
- `knowledge_items.jsonl`
- `provenance_manifest.json`
- split artifact pages when content grows too large

The final package focuses on the GPT payload, while the sidecars help with auditing and troubleshooting.

## AI enrichment

AI enrichment is optional.

Current enrichment features include:

- title cleanup
- domain and topic suggestion
- synopsis and glossary hints
- cached Responses API outputs keyed by checksum, model, and prompt version

Important behavior:

- AI is off by default
- text is only sent to the provider when the user enables enrichment
- project-local API keys are currently stored in `.knowledge_builder/secrets.json`
- Windows Credential Manager support is a planned upgrade, not part of this first public release

## OCR behavior

OCR is optional.

To enable OCR-assisted extraction for image documents and scanned PDFs:

```powershell
python -m pip install -e ".[ocr]"
```

Users also need the external Tesseract OCR runtime installed and available on the system path.

If OCR dependencies are missing, the extractor degrades gracefully and records the missing extractor state instead of crashing.
