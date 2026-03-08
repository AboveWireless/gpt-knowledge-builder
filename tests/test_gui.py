from pathlib import Path
from tkinter import Tk, TclError

import pytest

from knowledge_builder.gui import App, merge_batch_folder_selection, selected_batch_folder_names
from knowledge_builder.project.pipeline import export_project, scan_project
from knowledge_builder.project.store import PROJECT_FILE, init_project, load_project_config


def test_merge_batch_folder_selection_preserves_existing_choices_and_defaults_new_folders_selected():
    merged = merge_batch_folder_selection(
        ["Alpha", "Bravo", "Charlie"],
        {"Alpha": False, "Bravo": True, "Legacy": False},
    )

    assert merged == {
        "Alpha": False,
        "Bravo": True,
        "Charlie": True,
    }


def test_selected_batch_folder_names_returns_only_checked_folders_in_display_order():
    selected = selected_batch_folder_names(
        {
            "Alpha": True,
            "Bravo": False,
            "Charlie": True,
        }
    )

    assert selected == ["Alpha", "Charlie"]


def _make_root():
    try:
        root = Tk()
    except TclError as exc:
        pytest.skip(f"Tk runtime unavailable in test environment: {exc}")
    root.withdraw()
    return root


def _make_project(tmp_path: Path, files: dict[str, str], name: str = "Demo Project") -> Path:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    project_dir = tmp_path / "workspace"
    source_dir.mkdir()
    for filename, content in files.items():
        (source_dir / filename).write_text(content, encoding="utf-8")
    init_project(project_dir, name, [source_dir], output_dir, "mixed-office-documents", "custom-gpt-balanced")
    return project_dir


def test_app_starts_in_first_run_dashboard_when_no_project_loaded():
    root = _make_root()
    try:
        app = App(root)
        root.update_idletasks()
        assert app.view_state.active_view == "home"
        assert app.view_state.has_project is False
        assert app.header_title_var.get() == "Home"
        assert app.home_primary_button.cget("text") == "Create Project"
    finally:
        root.destroy()


def test_loading_project_updates_header_and_badges(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Premium Project")
    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        root.update_idletasks()
        assert app.view_state.has_project is True
        assert app.project_badge_var.get() == "Premium Project"
        assert app.profile_badge_var.get() == "custom-gpt-balanced"
        assert app.home_summary_var.get().startswith("Loaded project Premium Project")
    finally:
        root.destroy()


def test_review_selection_populates_detail_pane_and_filter_changes_visible_items(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "one.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
            "two.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
        },
        name="Review Project",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        root.update_idletasks()
        assert app.selected_review_id.get()
        assert app.review_tree is not None
        all_items = len(app.review_tree.get_children())
        app._set_review_filter("Duplicates")
        root.update_idletasks()
        duplicate_items = len(app.review_tree.get_children())
        assert duplicate_items >= 1
        assert duplicate_items <= all_items
    finally:
        root.destroy()


def test_export_view_reflects_latest_export_summary(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"manual.txt": "1. Remove cover.\n2. Tighten lug.\n"}, name="Export Project")
    scan_project(project_dir)
    result = export_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("export")
        root.update_idletasks()
        assert "Latest export:" in app.export_summary_var.get() or "Export ready:" in app.export_summary_var.get()
        assert Path(result["package_dir"]).name in app.export_summary_var.get()
    finally:
        root.destroy()


def test_navigation_preserves_loaded_state_and_settings_persist(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"doc.txt": "Operations procedure."}, name="Settings Project")
    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app.model_enabled.set(True)
        app.model_name.set("gpt-5.4")
        app.review_low_signal_var.set("88")
        app.api_key_value.set("secret")
        app.save_api_key.set(True)
        app.on_save_ai_settings()
        app._set_active_view("settings")
        app._set_active_view("sources")
        assert app.project_name.get() == "Settings Project"
        config = load_project_config(project_dir)
        assert config.optional_model_settings.enabled is True
        assert config.review_thresholds.low_signal_word_count == 88
    finally:
        root.destroy()


def test_review_edit_and_open_output_actions_remain_wired(tmp_path: Path, monkeypatch):
    project_dir = _make_project(tmp_path, {"doc.txt": "Ground lug torque: 45 Nm."}, name="Action Project")
    scan_project(project_dir)
    root = _make_root()
    calls = {"review": False, "open": False}

    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        root.update_idletasks()
        review_id = app.selected_review_id.get()

        monkeypatch.setattr("knowledge_builder.gui.update_review_item", lambda *args, **kwargs: calls.__setitem__("review", True) or {"review_id": review_id})
        monkeypatch.setattr(app, "_run_async", lambda _kind, fn: fn())
        monkeypatch.setattr("os.startfile", lambda _path: calls.__setitem__("open", True))

        app.review_title_edit.set("Grounding Basics")
        app.on_apply_review_edit()
        app.on_open_output()

        assert calls["review"] is True
        assert calls["open"] is True
    finally:
        root.destroy()
