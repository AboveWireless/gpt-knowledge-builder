# User Guide

## What this app does

GPT Knowledge Builder helps you turn a messy folder of documents into a smaller, cleaner set of GPT-ready knowledge files.

The app is designed to feel simple in guided mode:

1. `Pick Folders`
2. `Scan Files`
3. `Fix Issues`
4. `Get GPT Files`

## Before you start

- Put the source documents you want to use in one folder or a few related folders.
- Decide where you want the finished GPT files to be saved.
- If you want to read scanned PDFs or images, install OCR support first.
- If you want AI enrichment, keep in mind it is off by default until you turn it on and add a key.

## Start on the Home screen

The Home screen is the simplest starting point.

- Click `Pick Folders To Start` to begin a new guided project.
- Click `Open Existing Project` if you already saved a workspace and want to continue.
- Use the workflow cards to see whether your next step is to scan files, fix issues, or export.

## Step 1: Pick Folders

This screen tells the app what to read and where to save the finished package.

What you do:

- Add one folder or many folders to scan.
- Choose `Save GPT Files To` so exports go to the right place.
- Click `Scan Files` if you want to save the folder choices and start immediately.
- Click `Save Folder Choices` if you want to stop after setup and scan later.

What the app does for you:

- It keeps its internal project files in its own workspace.
- It previews how many files it found and whether the workload looks light, moderate, or heavy.
- It checks whether optional tooling such as OCR support appears available on the computer.

Useful details on this screen:

- `Show More` opens the scan forecast, folder preview, and dependency health summary.
- Beginner mode keeps this screen simple.
- `Show Advanced Controls` exposes more setup options when you want them.

## Step 2: Scan Files

This is where the app reads the selected documents and builds the working corpus.

What you do:

- Click `Scan Files` the first time.
- Click `Scan Again` after changing folders, dependencies, or source files.
- Use the continue button to move to review or export based on the scan result.

What the app shows:

- how many files were scanned
- how many files still need review
- how many files failed to read cleanly
- a recommendation for what to do next

If the scan is clean, you can usually move on to export. If not, go to `Fix Issues`.

## Step 3: Fix Issues

This screen is the review queue. It exists so the app does not guess silently when the scan finds weak or ambiguous content.

Common issue types:

- extraction issues
- duplicates
- low-confidence OCR
- taxonomy uncertainty
- low-signal files

How to work through the queue:

- Use `Accept`, `Skip`, `Retry`, and `Next` to move through the queue with simple, preview-first decisions.
- Read the preview for the selected issue.
- Use `Accept` if the result is good enough.
- Use `Skip` if the file is noise or should stay out of the package.
- Use `Retry` if the file should be kept but the extraction needs another attempt.
- Use `Next` to move forward quickly through the queue.

Helpful behavior:

- Guided mode keeps this screen focused on one issue at a time.
- The preview helps you judge whether text is usable before export.
- Advanced mode adds denser filters, bulk retry tools, diagnostics links, and editing controls.

## Step 4: Get GPT Files

This is where the final package is created.

What you do:

- Click `Get GPT Files` when the project looks ready.
- Click `Check Package` if you want one more validation pass before or after export.
- Click `Open GPT Files Folder` to inspect the results.

What you get:

- GPT-ready package files for upload
- package summaries and artifact lists
- provenance and validation sidecars kept outside the main GPT payload

This helps you deliver something cleaner than a raw folder dump.

## Advanced controls

Guided mode is the default path. It is meant to keep the app easy to use.

Turn on `Show Advanced Controls` only when you want:

- more setup tuning
- deeper review filters
- bulk retry controls
- diagnostics and history views
- extra validation and export actions

If you are helping other people use the app, guided mode is usually the best default.

## AI and OCR

AI enrichment:

- is optional
- is off by default
- only runs after you enable it and provide a key

OCR:

- is optional
- helps with scanned PDFs and image files
- depends on both the Python extras and the external Tesseract runtime

If OCR is missing, the app still runs. It just has fewer extraction paths available.

## Reopening a project later

The app keeps a reusable project workspace so you can come back later and continue.

That means you can:

- rescan after adding new source files
- keep working through review items over time
- export more than once
- inspect old outputs without starting over

## Quick success tips

- Start with guided mode unless you know you need advanced controls.
- Keep source folders focused so the review queue stays manageable.
- Use the preview in `Fix Issues` before accepting weak OCR or partial extraction.
- Run `Check Package` when you want one more confidence pass before sharing the output.
- Keep the output folder separate from the source folders so exports stay easy to find.
