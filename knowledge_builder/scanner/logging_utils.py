from __future__ import annotations

from ..compiler_models import BatchBuildResult, BuildResult


def format_single_run_summary(result: BuildResult) -> list[str]:
    lines = [f"package_dir={result.package_dir}"]
    if result.zip_path:
        lines.append(f"zip_path={result.zip_path}")
    lines.append(
        f"processed={result.processed_documents} "
        f"contributed={result.contributed_documents} "
        f"failed={result.failed_documents}"
    )
    return lines


def format_batch_run_summary(result: BatchBuildResult) -> list[str]:
    return [
        f"batch_summary={result.summary_path}",
        f"folders={len(result.folder_results)} "
        f"succeeded={sum(1 for item in result.folder_results if item.success)} "
        f"failed={sum(1 for item in result.folder_results if not item.success)}",
    ]
