from __future__ import annotations

import argparse
from pathlib import Path

from ..project import register_project_parser, run_project_command
from .config import default_pack_name
from .discovery import discover_batch_corpora, discover_corpus_files
from .logging_utils import format_batch_run_summary, format_single_run_summary
from .models import RunConfig
from .routing import route_build


def build_parser(prog: str = "knowledge_builder") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Build Custom GPT Knowledge packages.")
    sub = parser.add_subparsers(dest="command", required=False)

    scan_parser = sub.add_parser("scan-docs", help="Compile an input folder into a GPT Knowledge package.")
    _add_build_args(scan_parser)

    scan_alias = sub.add_parser("scan", help="Alias for scan-docs.")
    _add_build_args(scan_alias)

    reindex_alias = sub.add_parser("reindex", help="Alias for scan-docs.")
    _add_build_args(reindex_alias)

    validate_parser = sub.add_parser("validate", help="Validate build inputs without writing the package.")
    _add_build_args(validate_parser, include_output_flags=False)

    gui_parser = sub.add_parser("gui", help="Launch the GUI package builder.")
    gui_parser.add_argument("--config", help="Unused legacy option retained for compatibility.")
    register_project_parser(sub)
    return parser


def build_scan_docs_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scan-docs", description="Compile documents into a GPT Knowledge package.")
    _add_build_args(parser)
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "gui"):
        from ..gui import run_gui

        return run_gui(None)

    if args.command == "project":
        return run_project_command(args)

    config = _run_config_from_args(args)
    if args.command == "validate":
        return _run_validate(config)
    result = route_build(config)
    for line in _format_result_lines(result):
        print(line)
    return 0


def run_scan_docs(argv: list[str] | None = None) -> int:
    parser = build_scan_docs_parser()
    args = parser.parse_args(argv)
    config = _run_config_from_args(args)
    issues = validate_inputs(config)
    if issues:
        for issue in issues:
            print(issue)
        return 1
    result = route_build(config)
    for line in _format_result_lines(result):
        print(line)
    return 0


def validate_inputs(config: RunConfig) -> list[str]:
    issues: list[str] = []
    if not config.input_dir.exists():
        issues.append(f"Input directory not found: {config.input_dir}")
        return issues
    if not config.input_dir.is_dir():
        issues.append(f"Input path is not a directory: {config.input_dir}")
        return issues
    if config.batch_subfolders:
        child_dirs = discover_batch_corpora(config.input_dir)
        if not child_dirs:
            issues.append("No immediate child folders were found in the batch root.")
            return issues
        if not any(discover_corpus_files(child_dir) for child_dir in child_dirs):
            issues.append("No supported input files were found in any immediate child folder.")
        return issues

    if not discover_corpus_files(config.input_dir):
        issues.append("No supported input files were found.")
    return issues


def _run_validate(config: RunConfig) -> int:
    issues = validate_inputs(config)
    if issues:
        print("Validation findings:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    if config.batch_subfolders:
        print("Validation passed: batch root is readable and contains processable child folders.")
    else:
        print("Validation passed: input folder is readable and contains supported documents.")
    return 0


def _run_config_from_args(args) -> RunConfig:
    input_dir = Path(args.input_dir).resolve()
    return RunConfig(
        input_dir=input_dir,
        output_dir=Path(args.output_dir).resolve(),
        pack_name=(args.pack_name.strip() if getattr(args, "pack_name", "") else "") or ("" if getattr(args, "batch_root", False) else default_pack_name(input_dir)),
        zip_pack=getattr(args, "zip_pack", False),
        debug_outputs=getattr(args, "debug_outputs", False),
        batch_subfolders=getattr(args, "batch_root", False),
    )


def _format_result_lines(result) -> list[str]:
    if hasattr(result, "folder_results"):
        return format_batch_run_summary(result)
    return format_single_run_summary(result)


def _add_build_args(parser: argparse.ArgumentParser, include_output_flags: bool = True) -> None:
    parser.add_argument("--input-dir", required=True, help="Directory containing source documents.")
    parser.add_argument("--output-dir", required=True, help="Directory where the GPT package should be created.")
    parser.add_argument(
        "--pack-name",
        default="",
        help="Base name for the GPT Knowledge package. In batch mode each child folder name is used.",
    )
    parser.add_argument(
        "--batch-root",
        type=_parse_bool,
        dest="batch_root",
        default=False,
        help="Treat each immediate child subfolder of input-dir as an independent corpus.",
    )
    parser.add_argument(
        "--batch-subfolders",
        type=_parse_bool,
        dest="batch_root",
        help="Alias for --batch-root.",
    )
    if include_output_flags:
        parser.add_argument("--zip-pack", type=_parse_bool, default=False, help="Create a sibling zip package.")
        parser.add_argument(
            "--debug-outputs",
            type=_parse_bool,
            default=False,
            help="Write a separate sibling debug folder with extracted text and diagnostics.",
        )
    else:
        parser.add_argument("--zip-pack", type=_parse_bool, default=False, help=argparse.SUPPRESS)
        parser.add_argument("--debug-outputs", type=_parse_bool, default=False, help=argparse.SUPPRESS)


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")
