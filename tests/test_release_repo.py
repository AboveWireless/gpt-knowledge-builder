from __future__ import annotations

import re
from pathlib import Path

import yaml


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data.startswith(PNG_SIGNATURE), path
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _readme_image_paths(readme: str) -> list[str]:
    return re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme)


def test_public_repo_scaffolding_exists():
    repo_root = Path(__file__).resolve().parents[1]
    expected = [
        ".gitignore",
        "LICENSE",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "docs/privacy-and-data-handling.md",
        "docs/windows-build.md",
        "docs/macos-build.md",
        "docs/release-process.md",
        "docs/images/app-icon.png",
        "docs/images/github-home.png",
        "docs/images/github-sources.png",
        "docs/images/github-processing.png",
        "docs/images/github-review.png",
        "docs/images/github-export.png",
        "packaging/windows/assets/app.ico",
        "packaging/macos/assets/app.icns",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
        "scripts/render_github_screenshot.py",
    ]
    for relative in expected:
        assert (repo_root / relative).exists(), relative


def test_readme_positions_truthful_cross_platform_release_story():
    repo_root = Path(__file__).resolve().parents[1]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    assert "Local-first desktop app for Windows and macOS" in readme
    assert "When a tagged GitHub release is published" in readme
    assert "If the [Releases](https://github.com/AboveWireless/gpt-knowledge-builder/releases) page is empty" in readme
    assert "Windows version" in readme
    assert "macOS version" in readme
    assert "GPTKnowledgeBuilder-<version>-portable.zip" in readme
    assert "Quick start for Windows users" in readme
    assert "Quick start for macOS users" in readme
    assert "render_github_screenshot.py --render-repo-assets" in readme
    assert "docs/images/github-home.png" in readme
    assert "docs/images/github-sources.png" in readme
    assert "docs/images/github-processing.png" in readme
    assert "docs/images/github-review.png" in readme
    assert "docs/images/github-export.png" in readme
    assert "docs/images/hero-banner.svg" not in readme
    assert "docs/images/workspace-preview.svg" not in readme
    assert "docs/images/export-preview.svg" not in readme


def test_readme_image_references_resolve():
    repo_root = Path(__file__).resolve().parents[1]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    image_paths = [path for path in _readme_image_paths(readme) if not path.startswith("http")]
    assert image_paths, "README should include product images"
    for relative in image_paths:
        assert (repo_root / relative).exists(), relative


def test_public_png_assets_have_expected_dimensions():
    repo_root = Path(__file__).resolve().parents[1]
    screenshot_paths = [
        repo_root / "docs" / "images" / "github-home.png",
        repo_root / "docs" / "images" / "github-sources.png",
        repo_root / "docs" / "images" / "github-processing.png",
        repo_root / "docs" / "images" / "github-review.png",
        repo_root / "docs" / "images" / "github-export.png",
    ]
    for path in screenshot_paths:
        assert _png_size(path) == (1400, 850), path
    assert _png_size(repo_root / "docs" / "images" / "app-icon.png") == (1024, 1024)


def test_windows_and_macos_build_guides_cover_end_user_install():
    repo_root = Path(__file__).resolve().parents[1]
    windows_guide = (repo_root / "docs" / "windows-build.md").read_text(encoding="utf-8")
    mac_guide = (repo_root / "docs" / "macos-build.md").read_text(encoding="utf-8")

    assert "Windows version for end users" in windows_guide
    assert "GPTKnowledgeBuilder-<version>-portable.zip" in windows_guide
    assert "If the Releases page is empty" in windows_guide

    assert "macOS version for end users" in mac_guide
    assert "When a tagged GitHub release is published" in mac_guide
    assert "Privacy & Security" in mac_guide
    assert "Open Anyway" in mac_guide


def test_release_process_and_changelog_match_current_repo_state():
    repo_root = Path(__file__).resolve().parents[1]
    release_process = (repo_root / "docs" / "release-process.md").read_text(encoding="utf-8")
    changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "replace the placeholder GitHub URLs" not in release_process
    assert "AboveWireless/gpt-knowledge-builder" in release_process
    assert "artifact names still match the release workflow outputs" in release_process

    assert "## [Unreleased]" in changelog
    assert "macOS desktop packaging" in changelog
    assert "GitHub screenshot generation" in changelog
    assert "guided desktop UI" in changelog


def test_contributing_and_security_docs_reflect_cross_platform_repo_state():
    repo_root = Path(__file__).resolve().parents[1]
    contributing = (repo_root / "CONTRIBUTING.md").read_text(encoding="utf-8")
    security = (repo_root / "SECURITY.md").read_text(encoding="utf-8")
    bug_template = (repo_root / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(encoding="utf-8")

    assert "macos-build" in contributing
    assert "packaging under `packaging/macos/`" in contributing
    assert "public screenshots, build guides, and release wording aligned" in contributing

    assert "after the repository is published" not in security
    assert "private vulnerability reporting flow" in security

    assert "- macOS app" in bug_template


def test_pyproject_has_public_release_metadata():
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert 'License :: OSI Approved :: MIT License' in pyproject
    assert "Homepage =" in pyproject
    assert "Issues =" in pyproject


def test_github_workflows_cover_ci_and_release_outputs():
    repo_root = Path(__file__).resolve().parents[1]
    ci = yaml.safe_load((repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    release_path = repo_root / ".github" / "workflows" / "release.yml"
    release = yaml.safe_load(release_path.read_text(encoding="utf-8"))
    release_text = release_path.read_text(encoding="utf-8")
    ci_on = ci.get("on", ci.get(True))
    release_on = release.get("on", release.get(True))

    assert "push" in ci_on
    assert "pull_request" in ci_on
    assert "test" in ci["jobs"]

    assert "push" in release_on
    assert "workflow_dispatch" in release_on
    assert "build-windows" in release["jobs"]
    assert "build-macos" in release["jobs"]
    assert "publish-release" in release["jobs"]
    assert "dist/installer/*.exe" in release_text
    assert "dist/*portable.zip" in release_text
    assert "dist/installer/*.dmg" in release_text
    assert "dist/*macos.zip" in release_text
