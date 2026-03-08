from pathlib import Path

from knowledge_builder.gui_entry import main
from knowledge_builder.version import APP_NAME, APP_VERSION, EXECUTABLE_NAME


def test_windows_packaging_assets_exist():
    repo_root = Path(__file__).resolve().parents[1]
    assert (repo_root / "packaging" / "windows" / "GPTKnowledgeBuilder.spec").exists()
    assert (repo_root / "packaging" / "windows" / "GPTKnowledgeBuilder.iss").exists()
    assert (repo_root / "scripts" / "build_windows.ps1").exists()
    assert (repo_root / "packaging" / "windows" / "assets" / "app.ico").exists()


def test_gui_entrypoint_is_callable(monkeypatch):
    monkeypatch.setattr("knowledge_builder.gui_entry.run_gui", lambda _config: 0)
    assert main() == 0


def test_version_metadata_is_defined():
    assert APP_NAME == "GPT Knowledge Builder"
    assert APP_VERSION == "0.1.0"
    assert EXECUTABLE_NAME == "GPTKnowledgeBuilder"


def test_windows_packaging_uses_single_version_source():
    repo_root = Path(__file__).resolve().parents[1]
    build_script = (repo_root / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    spec_text = (repo_root / "packaging" / "windows" / "GPTKnowledgeBuilder.spec").read_text(encoding="utf-8")
    installer_text = (repo_root / "packaging" / "windows" / "GPTKnowledgeBuilder.iss").read_text(encoding="utf-8")

    assert "knowledge_builder.version" in build_script
    assert "PYINSTALLER_VERSION_FILE" in build_script
    assert "version=version_file" in spec_text
    assert "MyOutputBaseFilename" in installer_text
