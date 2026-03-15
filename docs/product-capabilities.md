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
