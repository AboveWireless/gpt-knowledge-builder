from __future__ import annotations

from pathlib import Path

import yaml


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
        "docs/images/hero-banner.svg",
        "docs/images/workspace-preview.svg",
        "docs/images/export-preview.svg",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
        "scripts/render_github_screenshot.py",
    ]
    for relative in expected:
        assert (repo_root / relative).exists(), relative


def test_readme_positions_gui_first_release():
    repo_root = Path(__file__).resolve().parents[1]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    assert "Local-first desktop app for Windows and macOS" in readme
    assert "Download the right version" in readme
    assert "macOS version" in readme
    assert "Open Anyway" in readme
    assert "GUI-first workflow" in readme
    assert "Advanced CLI" in readme
    assert "scan-docs" in readme
    assert "render_github_screenshot.py --render-repo-assets" in readme
    assert "docs/images/github-home.png" in readme
    assert "docs/images/github-review.png" in readme
    assert "docs/images/github-export.png" in readme
    assert "docs/images/hero-banner.svg" in readme


def test_readme_screenshot_assets_exist():
    repo_root = Path(__file__).resolve().parents[1]
    assert (repo_root / "docs" / "images" / "hero-banner.svg").exists()
    assert (repo_root / "docs" / "images" / "workspace-preview.svg").exists()
    assert (repo_root / "docs" / "images" / "export-preview.svg").exists()
    assert (repo_root / "docs" / "images" / "github-home.png").exists()
    assert (repo_root / "docs" / "images" / "github-review.png").exists()
    assert (repo_root / "docs" / "images" / "github-export.png").exists()


def test_macos_build_guide_covers_install_and_gatekeeper():
    repo_root = Path(__file__).resolve().parents[1]
    guide = (repo_root / "docs" / "macos-build.md").read_text(encoding="utf-8")
    assert "macOS version for end users" in guide
    assert "Applications" in guide
    assert "Privacy & Security" in guide
    assert "Open Anyway" in guide


def test_pyproject_has_public_release_metadata():
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert 'License :: OSI Approved :: MIT License' in pyproject
    assert "Homepage =" in pyproject
    assert "Issues =" in pyproject


def test_github_workflows_cover_ci_and_release():
    repo_root = Path(__file__).resolve().parents[1]
    ci = yaml.safe_load((repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    release = yaml.safe_load((repo_root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
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
