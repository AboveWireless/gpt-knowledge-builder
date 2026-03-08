from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import export_project, review_project, scan_project, update_review_item, validate_project
from .store import init_project


def register_project_parser(subparsers) -> None:
    project_parser = subparsers.add_parser("project", help="Project/workspace workflow for GPT knowledge builds.")
    project_sub = project_parser.add_subparsers(dest="project_command", required=True)

    init_parser = project_sub.add_parser("init", help="Create a project workspace.")
    init_parser.add_argument("--project-dir", required=True, help="Directory for the project workspace.")
    init_parser.add_argument("--source-root", action="append", required=True, help="Source folder to scan. Repeat for multiple roots.")
    init_parser.add_argument("--output-dir", required=True, help="Directory for exported GPT packages.")
    init_parser.add_argument("--project-name", default="", help="Friendly project name.")
    init_parser.add_argument("--preset", default="mixed-office-documents", help="Document preset.")
    init_parser.add_argument("--export-profile", default="custom-gpt-balanced", help="Export profile.")

    scan_parser = project_sub.add_parser("scan", help="Scan project sources into cached corpus state.")
    scan_parser.add_argument("--project-dir", required=True, help="Project workspace directory.")
    scan_parser.add_argument("--force", action="store_true", help="Reprocess files even when checksums match.")

    review_parser = project_sub.add_parser("review", help="List or resolve review queue items.")
    review_parser.add_argument("--project-dir", required=True, help="Project workspace directory.")
    review_parser.add_argument("--approve-all", action="store_true", help="Mark all open review items accepted.")
    review_parser.add_argument("--reject-duplicates", action="store_true", help="Reject open duplicate review items.")
    review_parser.add_argument("--review-id", default="", help="Specific review item id to edit.")
    review_parser.add_argument("--status", default="", help="New status for --review-id.")
    review_parser.add_argument("--override-title", default="", help="Optional title override for --review-id.")
    review_parser.add_argument("--override-domain", default="", help="Optional domain override for --review-id.")
    review_parser.add_argument("--note", default="", help="Resolution note for --review-id.")

    export_parser = project_sub.add_parser("export", help="Export the project into a GPT-ready package.")
    export_parser.add_argument("--project-dir", required=True, help="Project workspace directory.")
    export_parser.add_argument("--zip-pack", action="store_true", help="Zip the final GPT package.")

    validate_parser = project_sub.add_parser("validate", help="Validate project config, review state, and package readiness.")
    validate_parser.add_argument("--project-dir", required=True, help="Project workspace directory.")


def run_project_command(args) -> int:
    project_dir = Path(args.project_dir).resolve()

    if args.project_command == "init":
        project_file = init_project(
            project_root=project_dir,
            project_name=args.project_name,
            source_roots=[Path(value).resolve() for value in args.source_root],
            output_root=Path(args.output_dir).resolve(),
            preset=args.preset,
            export_profile=args.export_profile,
            model_enabled=False,
        )
        print(f"Project initialized: {project_file}")
        return 0

    if args.project_command == "scan":
        summary = scan_project(project_dir, force=args.force)
        print(
            "project scan: "
            f"scanned={summary['scanned']} processed={summary['processed']} "
            f"skipped={summary['skipped']} flagged={summary['flagged']} removed={summary['removed']}"
        )
        return 0

    if args.project_command == "review":
        if args.review_id:
            result = update_review_item(
                project_dir,
                review_id=args.review_id,
                status=args.status or None,
                override_title=args.override_title if args.override_title else None,
                override_domain=args.override_domain if args.override_domain else None,
                resolution_note=args.note if args.note else None,
            )
            print(f"project review updated: {result['review_id']} status={result['status']}")
            return 0
        summary = review_project(
            project_dir,
            approve_all=args.approve_all,
            reject_duplicates=args.reject_duplicates,
        )
        print(
            "project review: "
            f"open={summary['open']} accepted={summary['accepted']} "
            f"rejected={summary['rejected']} changed={summary['changed']}"
        )
        return 0

    if args.project_command == "export":
        result = export_project(project_dir, zip_pack=args.zip_pack)
        print(f"project export: package={result['package_dir']}")
        print(f"provenance: {result['provenance_dir']}")
        if result["zip_path"]:
            print(f"zip: {result['zip_path']}")
        if result["validation_messages"]:
            print("validation:")
            for message in result["validation_messages"]:
                print(f"- {message}")
        return 0

    if args.project_command == "validate":
        issues = validate_project(project_dir)
        if not issues:
            print("Project validation passed.")
            return 0
        print("Project validation findings:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    raise argparse.ArgumentError(None, f"Unknown project command: {args.project_command}")
