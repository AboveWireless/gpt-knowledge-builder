from pathlib import Path
from tkinter import Tk, TclError

import pytest

from knowledge_builder.gui import App, merge_batch_folder_selection, selected_batch_folder_names
from knowledge_builder.project.pipeline import export_diagnostics_report, export_project, review_project, scan_project, update_review_item
from knowledge_builder.project.store import PROJECT_FILE, init_project, load_project_config, load_reviews, save_project_config


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


def test_simple_setup_creates_project_from_source_and_output_only(tmp_path: Path):
    source_dir = tmp_path / "input"
    output_dir = tmp_path / "exports"
    source_dir.mkdir()
    (source_dir / "doc.txt").write_text("Grounding means connection to earth.", encoding="utf-8")

    root = _make_root()
    try:
        app = App(root)
        app.source_dir.set(str(source_dir))
        app.output_dir.set(str(output_dir))
        app.project_name.set("")
        app.on_simple_setup()
        root.update_idletasks()
        project_dir = Path(app.project_dir.get())
        assert project_dir.parent == output_dir / ".gptkb_workspace"
        assert (project_dir / PROJECT_FILE).exists()
        assert app.view_state.has_project is True
        assert app.project_name.get() == source_dir.name
    finally:
        root.destroy()


def test_simple_setup_persists_multiple_source_roots(tmp_path: Path):
    source_a = tmp_path / "alpha"
    source_b = tmp_path / "bravo"
    output_dir = tmp_path / "exports"
    source_a.mkdir()
    source_b.mkdir()
    (source_a / "doc-a.txt").write_text("Alpha knowledge file.", encoding="utf-8")
    (source_b / "doc-b.txt").write_text("Bravo knowledge file.", encoding="utf-8")

    root = _make_root()
    try:
        app = App(root)
        app._set_source_roots([str(source_a), str(source_b)])
        app.output_dir.set(str(output_dir))
        app.project_name.set("")
        app.on_simple_setup()
        root.update_idletasks()
        project_dir = Path(app.project_dir.get())
        config = load_project_config(project_dir)
        resolved_roots = {str(source_a.resolve()), str(source_b.resolve())}
        assert set(config.source_roots) == resolved_roots
        assert app.project_name.get().lower().startswith(source_a.name.lower())
    finally:
        root.destroy()


def test_simple_setup_and_scan_hands_off_to_processing(tmp_path: Path):
    source_dir = tmp_path / "input"
    output_dir = tmp_path / "exports"
    source_dir.mkdir()
    (source_dir / "doc.txt").write_text("Grounding means connection to earth.", encoding="utf-8")

    root = _make_root()
    try:
        app = App(root)
        called = {"scan": False}
        app.source_dir.set(str(source_dir))
        app.output_dir.set(str(output_dir))
        app.on_scan = lambda: called.__setitem__("scan", True)
        app.on_simple_setup_and_scan()
        root.update_idletasks()
        assert app.view_state.active_view == "processing"
        assert called["scan"] is True
        assert "folders saved" in app.transition_notice_title_var.get().lower()
    finally:
        root.destroy()


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
        assert app.home_primary_button.cget("text") == "Pick Folders To Start"
        assert app.home_guided_button is not None
        assert "folder" in app.sidebar_next_step_var.get().lower() or "scan" in app.sidebar_next_step_var.get().lower()
    finally:
        root.destroy()


def test_beginner_home_primary_action_opens_sources_setup():
    root = _make_root()
    try:
        app = App(root)
        root.update_idletasks()
        app.home_primary_button.invoke()
        root.update_idletasks()
        assert app.view_state.active_view == "sources"
    finally:
        root.destroy()


def test_beginner_sidebar_uses_simple_labels_and_hides_advanced_views():
    root = _make_root()
    try:
        app = App(root)
        root.update_idletasks()
        assert app._nav_buttons["home"].cget("text") == "Start"
        assert app._nav_buttons["sources"].cget("text") == "Choose Folders"
        assert app._nav_buttons["processing"].cget("text") == "Scan Files"
        assert app._nav_buttons["review"].cget("text") == "Fix Issues"
        assert app._nav_buttons["export"].cget("text") == "Get GPT Files"
        assert app._nav_buttons["diagnostics"].winfo_manager() == ""
        assert app._nav_buttons["history"].winfo_manager() == ""
        assert app._nav_buttons["settings"].winfo_manager() == ""
    finally:
        root.destroy()


def test_open_path_uses_platform_opener_on_macos(tmp_path: Path, monkeypatch):
    target = tmp_path / "exports"
    target.mkdir()
    root = _make_root()
    calls = []
    try:
        app = App(root)
        monkeypatch.setattr("knowledge_builder.gui.os.name", "posix", raising=False)
        monkeypatch.setattr("knowledge_builder.gui.sys.platform", "darwin", raising=False)
        monkeypatch.setattr("knowledge_builder.gui.subprocess.run", lambda args, check=False: calls.append((args, check)))
        app._open_path(target)
        assert calls == [(["open", str(target)], False)]
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
        assert "project: premium project" in app.status_project_var.get().lower()
    finally:
        root.destroy()


def test_shell_layout_reflows_for_narrower_widths():
    root = _make_root()
    try:
        app = App(root)
        app._apply_responsive_layout_for_width(1400)
        assert int(app.header_right.grid_info()["row"]) == 0
        assert int(app.context_frame.grid_info()["row"]) == 0
        assert int(app.context_frame.grid_info()["column"]) == 1

        app._apply_responsive_layout_for_width(1320)
        assert int(app.header_right.grid_info()["row"]) == 1
        assert int(app.context_frame.grid_info()["row"]) == 1
        assert int(app.context_frame.grid_info()["column"]) == 0
    finally:
        root.destroy()


def test_home_view_shows_recent_project_launcher(tmp_path: Path, monkeypatch):
    project_dir = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Recent Project")
    recent_file = tmp_path / "recent_projects.json"
    root = _make_root()
    try:
        monkeypatch.setattr(App, "_recent_projects_path", lambda self: recent_file)
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        root.update_idletasks()
        recent = app._recent_projects_display()
        assert recent
        assert recent[0]["project_name"] == "Recent Project"
        assert recent[0]["exists"] is True
    finally:
        root.destroy()


def test_home_view_shows_guided_workflow_hint_before_project_loaded():
    root = _make_root()
    try:
        app = App(root)
        root.update_idletasks()
        assert "pick" in app.workflow_hint_var.get().lower()
        assert "folder" in app.workflow_hint_var.get().lower()
        assert app.primary_action_button.cget("text") == "Pick Folders To Start"
    finally:
        root.destroy()


def test_save_and_continue_to_scan_moves_user_into_processing(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Guided Project")
    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("sources")
        root.update_idletasks()
        app.on_save_and_go_to_scan()
        root.update_idletasks()
        assert app.view_state.active_view == "processing"
        assert "continue with the first scan" in app.banner_var.get().lower()
    finally:
        root.destroy()


def test_sources_view_surfaces_setup_validation_guidance(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Setup Guidance")
    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("sources")
        root.update_idletasks()
        assert "setup" in app.setup_validation_var.get().lower()
        assert "preset:" in " ".join(app._setup_validation_lines()).lower()
    finally:
        root.destroy()


def test_sources_view_shows_and_dismisses_onboarding_tip(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Setup Tip")
    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("sources")
        root.update_idletasks()
        assert "sources" not in app._view_tips_seen
        app._dismiss_screen_tip("sources")
        root.update_idletasks()
        assert "sources" in app._view_tips_seen
    finally:
        root.destroy()


def test_sources_view_builds_source_preview_summary(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "doc.txt": "Grounding means connection to earth.",
            "table.csv": "part,torque\nlug,45 Nm\n",
            "unknown.bin": "binary-ish",
        },
        name="Source Preview",
    )
    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("sources")
        root.update_idletasks()
        assert "found 3 file" in app.source_preview_var.get().lower()
        preview_lines = " ".join(app._source_preview_lines()).lower()
        assert "txt: 1" in preview_lines
        assert "csv: 1" in preview_lines
        assert "unsupported examples" in preview_lines
    finally:
        root.destroy()


def test_sources_view_surfaces_scan_forecast(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "doc.txt": "Grounding means connection to earth.",
            "scan.pdf": "placeholder pdf name",
            "photo.jpg": "placeholder image name",
        },
        name="Scan Forecast",
    )
    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("sources")
        root.update_idletasks()
        assert "estimated workload" in app.scan_forecast_var.get().lower()
        assert "ocr-likely" in " ".join(app._source_preview_lines()).lower()
    finally:
        root.destroy()


def test_sources_view_aggregates_preview_across_multiple_source_roots(tmp_path: Path):
    source_a = tmp_path / "alpha"
    source_b = tmp_path / "bravo"
    source_a.mkdir()
    source_b.mkdir()
    (source_a / "doc.txt").write_text("Grounding means connection to earth.", encoding="utf-8")
    (source_b / "table.csv").write_text("part,torque\nlug,45 Nm\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    project_dir = tmp_path / "workspace"
    init_project(project_dir, "Multi Root Preview", [source_a, source_b], output_dir, "mixed-office-documents", "custom-gpt-balanced")

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("sources")
        root.update_idletasks()
        preview = app._source_preview_data()
        assert preview["source_roots"] == 2
        assert preview["files"] == 2
        assert preview["supported"] == 2
        assert "across 2 scan folder" in app.source_preview_var.get().lower()
        joined = " ".join(app._source_preview_lines()).lower()
        assert "txt: 1" in joined
        assert "csv: 1" in joined
    finally:
        root.destroy()


def test_sources_view_surfaces_folder_level_preview_breakdown(tmp_path: Path):
    source_dir = tmp_path / "source"
    (source_dir / "batch_a").mkdir(parents=True)
    (source_dir / "batch_b").mkdir(parents=True)
    (source_dir / "batch_a" / "one.txt").write_text("a", encoding="utf-8")
    (source_dir / "batch_a" / "two.txt").write_text("b", encoding="utf-8")
    (source_dir / "batch_b" / "three.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    project_dir = tmp_path / "workspace"
    init_project(project_dir, "Folder Breakdown", [source_dir], output_dir, "mixed-office-documents", "custom-gpt-balanced")

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("sources")
        root.update_idletasks()
        joined = " ".join(app._source_preview_lines()).lower()
        assert "busiest folders" in joined
        assert "batch_a: 2" in joined
        assert "batch_b: 1" in joined
        metrics = app._source_preview_data()["folder_metrics"]
        assert metrics["batch_a"]["files"] == 2
    finally:
        root.destroy()


def test_source_folder_selection_persists_as_exclude_globs(tmp_path: Path):
    source_dir = tmp_path / "source"
    (source_dir / "batch_a").mkdir(parents=True)
    (source_dir / "batch_b").mkdir(parents=True)
    (source_dir / "batch_a" / "one.txt").write_text("a", encoding="utf-8")
    (source_dir / "batch_b" / "two.txt").write_text("b", encoding="utf-8")
    output_dir = tmp_path / "output"
    project_dir = tmp_path / "workspace"
    init_project(project_dir, "Folder Selection", [source_dir], output_dir, "mixed-office-documents", "custom-gpt-balanced")

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("sources")
        root.update_idletasks()
        app._source_folder_selection = {"batch_a": True, "batch_b": False}
        app.on_apply_source_folder_selection()
        config = load_project_config(project_dir)
        assert "batch_b/**" in config.exclude_globs
        assert "batch_a/**" not in config.exclude_globs
        assert "1/2 top-level folders included" in app.status_selection_var.get().lower()
    finally:
        root.destroy()


def test_sources_view_surfaces_dependency_health(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Dependency Health")
    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("sources")
        root.update_idletasks()
        assert app.dependency_health_var.get()
        joined = " ".join(app._dependency_health_lines())
        assert "PyMuPDF" in joined
        assert "Tesseract OCR" in joined
    finally:
        root.destroy()


def test_guided_setup_opens_wizard_window():
    root = _make_root()
    try:
        app = App(root)
        app.on_start_guided_setup()
        root.update_idletasks()
        assert app.guided_wizard is not None
        assert app.guided_wizard.winfo_exists()
        assert "step 1 of 4" in app.guided_wizard_title_var.get().lower()
        app._close_guided_wizard()
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
        assert "File:" in app.review_meta_var.get()
        assert app.review_issue_title_var.get()
        assert app.review_issue_action_var.get()
        assert app.review_preview_text is not None
        assert app.review_preview_text.get("1.0", "end").strip()
    finally:
        root.destroy()


def test_review_items_are_sorted_by_priority(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "broken.json": '{"alpha": 1,,}',
            "dup_one.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
            "dup_two.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
        },
        name="Priority Review",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        items = app._filtered_review_items(project_dir)
        assert items
        assert items[0]["kind"] == "extraction_issue"
        assert Path(str(items[0]["source_path"])).name == "broken.json"
    finally:
        root.destroy()


def test_review_tree_can_sort_by_file_and_applies_tags(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "zeta.json": '{"alpha": 1,,}',
            "alpha.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
            "beta.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
        },
        name="Review Sort",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        app._set_review_queue_mode("table")
        root.update_idletasks()
        children = list(app.review_tree.get_children())
        assert children
        first_tags = app.review_tree.item(children[0], "tags")
        assert first_tags
        app._sort_review_by("file")
        root.update_idletasks()
        children = list(app.review_tree.get_children())
        first_file = app.review_tree.item(children[0], "values")[3]
        assert first_file == "alpha.txt"
    finally:
        root.destroy()


def test_undo_last_review_action_replays_previous_snapshot(tmp_path: Path, monkeypatch):
    project_dir = _make_project(tmp_path, {"doc.txt": "Ground lug torque: 45 Nm."}, name="Undo Review")
    scan_project(project_dir)

    root = _make_root()
    calls = {}
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        root.update_idletasks()
        review_id = app.selected_review_id.get()
        app._last_undo_action = {
            "kind": "review_edit",
            "snapshot": {
                "review_id": review_id,
                "status": "open",
                "override_title": "Original",
                "override_domain": "general",
                "resolution_note": "restore me",
            },
        }
        monkeypatch.setattr(
            "knowledge_builder.gui.update_review_item",
            lambda *args, **kwargs: calls.update(kwargs) or {"review_id": review_id, "status": "open"},
        )
        monkeypatch.setattr(app, "_run_async", lambda _kind, fn: fn())

        app.on_undo_last_action()

        assert calls["review_id"] == review_id
        assert calls["status"] == "open"
        assert calls["override_title"] == "Original"
        assert calls["override_domain"] == "general"
        assert calls["resolution_note"] == "restore me"
    finally:
        root.destroy()


def test_review_preview_navigation_shows_multiple_units_for_long_document(tmp_path: Path):
    long_body = " ".join(f"step{index}" for index in range(900))
    project_dir = _make_project(
        tmp_path,
        {
            "long.txt": long_body,
            "long_copy.txt": long_body,
        },
        name="Preview Navigation",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        root.update_idletasks()
        assert len(app.review_preview_units) >= 2
        first_label = app.review_preview_label_var.get()
        first_text = app.review_preview_text.get("1.0", "end").strip()
        app.on_next_preview_unit()
        root.update_idletasks()
        assert app.review_preview_label_var.get() != first_label
        assert app.review_preview_text.get("1.0", "end").strip() != first_text
    finally:
        root.destroy()


def test_review_pdf_thumbnail_strip_renders_buttons(tmp_path: Path, monkeypatch):
    project_dir = _make_project(
        tmp_path,
        {
            "one.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
            "two.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
        },
        name="Thumbnail Review",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        root.update_idletasks()
        monkeypatch.setattr(
            "knowledge_builder.gui.render_document_preview_strip",
            lambda *_args, **_kwargs: [
                {"label": "Page 1", "image_path": "", "unit_index": 0, "error": ""},
                {"label": "Page 2", "image_path": "", "unit_index": 1, "error": ""},
            ],
        )
        monkeypatch.setattr(
            "knowledge_builder.gui.render_document_preview",
            lambda *_args, **_kwargs: {
                "label": "Page 2" if _args[-1] == 1 else "Page 1",
                "text": "preview text",
                "image_path": "",
                "unit_index": _args[-1],
                "unit_count": 2,
            },
        )
        app.review_preview_units = [
            {"label": "Page 1", "text": "preview text", "unit_index": 0, "unit_count": 2},
            {"label": "Page 2", "text": "preview text", "unit_index": 1, "unit_count": 2},
        ]
        app._render_preview_unit()
        root.update_idletasks()
        assert app.review_thumbnail_strip is not None
        assert len(app.review_thumbnail_strip.winfo_children()) == 2
        assert len(app.review_thumbnail_buttons) == 2
        assert str(app.review_thumbnail_buttons[0].cget("style")) == "Primary.TButton"
        assert str(app.review_thumbnail_buttons[1].cget("style")) == "Ghost.TButton"
        app._select_preview_unit(1)
        root.update_idletasks()
        assert str(app.review_thumbnail_buttons[0].cget("style")) == "Ghost.TButton"
        assert str(app.review_thumbnail_buttons[1].cget("style")) == "Primary.TButton"
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
        assert "completed export" in app.export_completion_var.get().lower()
        assert app.export_next_action_var.get()
        assert Path(result["package_dir"]).name in app.export_summary_var.get()
    finally:
        root.destroy()


def test_export_view_surfaces_readiness_state_before_export(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "broken.json": '{"alpha": 1,,}',
            "good.txt": "Grounding procedure.\n1. Inspect.\n2. Tighten.\n",
        },
        name="Export Readiness",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("export")
        root.update_idletasks()
        assert app.export_readiness_var.get() in {"Blocked", "Needs Review", "Ready", "Ready With Warnings", "Not Ready"}
        assert app.export_readiness_var.get() == "Needs Review"
        assert "open reviews" in app.export_readiness_detail_var.get().lower() or "partial" in app.export_readiness_detail_var.get().lower()
    finally:
        root.destroy()


def test_export_view_surfaces_checklist_lines(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "broken.json": '{"alpha": 1,,}',
            "good.txt": "Grounding procedure.\n1. Inspect.\n2. Tighten.\n",
        },
        name="Export Checklist",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("export")
        root.update_idletasks()
        checklist = " ".join(app._export_checklist_lines(None)).lower()
        assert "scanned documents" in checklist
        assert "open review blockers" in checklist
        assert "failed extraction documents excluded from export" in checklist
    finally:
        root.destroy()


def test_export_completion_opens_summary_dialog(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"manual.txt": "1. Remove cover.\n2. Tighten lug.\n"}, name="Export Dialog")
    scan_project(project_dir)
    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        result = export_project(project_dir)
        app._handle_export_complete(result)
        root.update_idletasks()
        assert app.export_summary_dialog is not None
        assert app.export_summary_dialog.winfo_exists()
    finally:
        if 'app' in locals() and app.export_summary_dialog is not None and app.export_summary_dialog.winfo_exists():
            app.export_summary_dialog.destroy()
        root.destroy()


def test_accept_and_next_moves_review_selection_forward(tmp_path: Path, monkeypatch):
    project_dir = _make_project(
        tmp_path,
        {
            "broken.json": '{"alpha": 1,,}',
            "dup_one.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
            "dup_two.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
        },
        name="Review Next",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        root.update_idletasks()
        first_review_id = app.selected_review_id.get()
        assert first_review_id

        def fake_update(*_args, **kwargs):
            return {"review_id": kwargs["review_id"], "status": kwargs.get("status", "accepted")}

        monkeypatch.setattr("knowledge_builder.gui.update_review_item", fake_update)
        monkeypatch.setattr(app, "_run_async", lambda _kind, fn: app._handle_review_edit_complete(fn()))

        app.on_mark_review_accepted_and_next()
        root.update_idletasks()

        assert app.selected_review_id.get()
        assert app.selected_review_id.get() != first_review_id
    finally:
        root.destroy()


def test_review_shortcut_dispatches_accept_and_next(tmp_path: Path, monkeypatch):
    project_dir = _make_project(
        tmp_path,
        {
            "broken.json": '{"alpha": 1,,}',
            "dup_one.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
            "dup_two.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
        },
        name="Shortcut Review",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        root.update_idletasks()
        called = {"accept_next": 0}
        monkeypatch.setattr(app, "on_mark_review_accepted_and_next", lambda: called.__setitem__("accept_next", called["accept_next"] + 1))
        result = app._handle_review_shortcut("accept_next")
        assert result == "break"
        assert called["accept_next"] == 1
    finally:
        root.destroy()


def test_promote_duplicate_canonical_action_remains_wired(tmp_path: Path, monkeypatch):
    project_dir = _make_project(
        tmp_path,
        {
            "dup_one.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
            "dup_two.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
        },
        name="Canonical Action",
    )
    scan_project(project_dir)
    root = _make_root()
    calls = {"canonical": False}
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        app._set_review_filter("Duplicates")
        root.update_idletasks()
        monkeypatch.setattr(
            "knowledge_builder.gui.promote_duplicate_as_canonical",
            lambda *args, **kwargs: calls.__setitem__("canonical", True) or {
                "review_id": app.selected_review_id.get(),
                "canonical_source": str(tmp_path / "source" / "dup_two.txt"),
                "duplicate_source": str(tmp_path / "source" / "dup_one.txt"),
            },
        )
        monkeypatch.setattr(app, "_run_async", lambda _kind, fn: app._handle_duplicate_promote_complete(fn()))
        app.on_promote_duplicate_canonical()
        root.update_idletasks()
        assert calls["canonical"] is True
    finally:
        root.destroy()


def test_review_queue_mode_switches_tree_columns(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "broken.json": '{"alpha": 1,,}',
            "dup_one.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
            "dup_two.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
        },
        name="Queue Mode",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        root.update_idletasks()
        assert app.review_tree["columns"] == ("kind", "file")
        app._set_review_queue_mode("table")
        root.update_idletasks()
        assert app.review_tree["columns"] == ("status", "severity", "kind", "file")
    finally:
        root.destroy()


def test_drop_path_updates_source_folder(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Drop Path")
    dropped_dir = tmp_path / "dropped"
    dropped_dir.mkdir()
    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        event = type("Event", (), {"data": "{" + str(dropped_dir) + "}"})()
        result = app._handle_drop_path(event, "source")
        assert result == "break"
        assert app.source_dir.get() == str(dropped_dir)
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


def test_create_project_creates_missing_default_folders(tmp_path: Path, monkeypatch):
    project_dir = tmp_path / "workspace"
    source_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    root = _make_root()

    try:
        app = App(root)
        app.project_dir.set(str(project_dir))
        app.source_dir.set(str(source_dir))
        app.output_dir.set(str(output_dir))
        app.project_name.set("Created Project")
        monkeypatch.setattr("knowledge_builder.gui.messagebox.showerror", lambda *args, **kwargs: pytest.fail("showerror should not be called"))

        app.on_create_project()
        root.update_idletasks()

        assert project_dir.exists()
        assert source_dir.exists()
        assert output_dir.exists()
        assert (project_dir / PROJECT_FILE).exists()
        assert app.view_state.has_project is True
        assert app.project_badge_var.get() == "Created Project"
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


def test_retry_review_and_export_diagnostics_actions_remain_wired(tmp_path: Path, monkeypatch):
    project_dir = _make_project(
        tmp_path,
        {
            "broken.json": '{"alpha": 1,,}',
            "good.txt": "Grounding procedure.\n1. Inspect.\n2. Tighten.\n",
        },
        name="Diagnostics Actions",
    )
    scan_project(project_dir)
    root = _make_root()
    calls = {
        "retry": False,
        "bulk_retry": False,
        "diagnostics": False,
        "open_diag": False,
        "diag_bulk": [],
    }

    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        root.update_idletasks()
        review_id = app.selected_review_id.get()

        monkeypatch.setattr(
            "knowledge_builder.gui.retry_document_extraction",
            lambda *args, **kwargs: calls.__setitem__("retry", True) or {"review_id": review_id, "source_path": "broken.json", "strategy": "raw", "summary": {"processed": 1}},
        )
        monkeypatch.setattr(
            "knowledge_builder.gui.export_diagnostics_report",
            lambda *args, **kwargs: calls.__setitem__("diagnostics", True) or {"markdown_path": "diag.md", "json_path": "diag.json"},
        )
        monkeypatch.setattr(
            "knowledge_builder.gui.retry_review_items",
            lambda *args, **kwargs: calls.__setitem__("bulk_retry", True) or {"matched_sources": [], "summary": {"processed": 0}},
        )
        monkeypatch.setattr("os.startfile", lambda _path: calls.__setitem__("open_diag", True))
        monkeypatch.setattr(app, "_run_async", lambda _kind, fn: fn())

        app.review_retry_strategy.set("raw")
        app.on_retry_selected_review()
        app.on_retry_filtered_reviews()
        app.on_export_diagnostics()
        app.on_open_diagnostics_folder()
        monkeypatch.setattr(
            app,
            "on_retry_filtered_reviews",
            lambda: calls["diag_bulk"].append(
                (
                    app.bulk_retry_doc_type.get(),
                    app.bulk_retry_extraction_status.get(),
                    app.bulk_retry_strategy.get(),
                )
            ),
        )
        app._run_diagnostics_bulk_retry("pdf", "failed", "pypdf_only")
        app._run_diagnostics_bulk_retry("all", "failed", "default")
        app._run_diagnostics_bulk_retry("html", "partial", "raw")

        assert calls["retry"] is True
        assert calls["bulk_retry"] is True
        assert calls["diagnostics"] is True
        assert calls["open_diag"] is True
        assert ("pdf", "failed", "pypdf_only") in calls["diag_bulk"]
        assert ("all", "failed", "default") in calls["diag_bulk"]
        assert ("html", "partial", "raw") in calls["diag_bulk"]
    finally:
        root.destroy()


def test_processing_view_uses_scan_quality_report(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "good.txt": "Grounding means connection to earth.\nProcedure and checklist text for review.",
            "broken.json": '{"alpha": 1,,}',
        },
        name="Processing Project",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("processing")
        root.update_idletasks()
        app.show_beginner_processing_details.set(True)
        app._render_current_view()
        root.update_idletasks()
        assert "partial=" in app.processing_summary_var.get()
        assert app.processing_recommendation_var.get()
        assert app.processing_decision_title_var.get()
        assert app.processing_decision_detail_var.get()
        assert app.operation_phase_var.get()
        assert app.operation_detail_var.get()
        assert app.process_log is not None
        assert "Scan complete" in app.process_log.get("1.0", "end")
    finally:
        root.destroy()


def test_processing_view_stacks_supporting_panels_in_compact_layout(tmp_path: Path, monkeypatch):
    project_dir = _make_project(
        tmp_path,
        {
            "good.txt": "Grounding means connection to earth.\nProcedure and checklist text for review.",
            "broken.json": '{"alpha": 1,,}',
        },
        name="Compact Processing Layout",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        monkeypatch.setattr(app, "_shell_width", lambda: 1160)
        app._set_active_view("processing")
        root.update_idletasks()
        app.show_beginner_processing_details.set(True)
        app._render_current_view()
        root.update_idletasks()
        assert app.processing_issue_frame is not None
        assert app.processing_detail_frame is not None
        assert int(app.processing_issue_frame.grid_info()["row"]) == 0
        assert int(app.processing_detail_frame.grid_info()["row"]) == 1
        assert int(app.processing_detail_frame.grid_info()["column"]) == 0
    finally:
        root.destroy()


def test_processing_view_keeps_extra_details_collapsed_until_requested(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "good.txt": "Grounding means connection to earth.\nProcedure and checklist text for review.",
            "broken.json": '{"alpha": 1,,}',
        },
        name="Collapsed Processing Details",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("processing")
        root.update_idletasks()
        assert app.show_beginner_processing_details.get() is False
        assert app.processing_issue_log is None
        app.show_beginner_processing_details.set(True)
        app._render_current_view()
        root.update_idletasks()
        assert app.processing_issue_log is not None
        assert app.processing_type_log is not None
    finally:
        root.destroy()


def test_primary_action_tracks_next_workflow_step(tmp_path: Path):
    unscanned_project = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Smart Action Unscanned")
    root = _make_root()
    try:
        app = App(root, initial_config=unscanned_project / PROJECT_FILE)
        root.update_idletasks()
        assert app.primary_action_button.cget("text") == "Scan Files"
    finally:
        root.destroy()

    blocked_root = tmp_path / "blocked"
    blocked_root.mkdir()
    blocked_project = _make_project(blocked_root, {"broken.json": '{"alpha": 1,,}'}, name="Smart Action Blocked")
    scan_project(blocked_project)
    root = _make_root()
    try:
        app = App(root, initial_config=blocked_project / PROJECT_FILE)
        root.update_idletasks()
        assert app.primary_action_button.cget("text") == "Fix Issues"
    finally:
        root.destroy()


def test_scan_completion_auto_opens_processing_view(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {"doc.txt": "Grounding means connection to earth.\nProcedure and checklist text for review."},
        name="Auto Processing View",
    )
    payload = scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("sources")
        root.update_idletasks()
        app._handle_scan_complete(payload)
        root.update_idletasks()
        assert app.view_state.active_view == "processing"
        assert "scan complete" in app.operation_phase_var.get().lower()
        assert app.transition_notice_step.get() == "processing"
        assert "scan finished" in app.transition_notice_title_var.get().lower()
        checklist = app._transition_notice_lines("processing")
        assert any("next:" in line.lower() for line in checklist)
    finally:
        root.destroy()


def test_sources_view_surfaces_setup_completion_handoff(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Setup Complete")

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("sources")
        root.update_idletasks()
        assert "setup is complete" in app.setup_completion_var.get().lower()
    finally:
        root.destroy()


def test_save_and_go_to_scan_sets_processing_transition_notice(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Setup Transition")

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app.on_save_and_go_to_scan()
        root.update_idletasks()
        assert app.view_state.active_view == "processing"
        assert app.transition_notice_step.get() == "processing"
        assert "setup saved" in app.transition_notice_title_var.get().lower()
    finally:
        root.destroy()


def test_transition_notice_can_be_dismissed(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Dismiss Notice")

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_transition_notice("sources", "Step Complete: Settings Saved", "Continue to scan.")
        root.update_idletasks()
        assert app.transition_notice_title_var.get()
        app._clear_transition_notice()
        root.update_idletasks()
        assert app.transition_notice_step.get() == ""
        assert app.transition_notice_title_var.get() == ""
    finally:
        root.destroy()


def test_beginner_mode_forces_review_inbox_and_advanced_can_be_restored(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "good.txt": "Grounding means connection to earth.\nProcedure and checklist text for review.",
            "broken.json": '{"alpha": 1,,}',
        },
        name="Workflow Mode",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_workflow_mode("advanced")
        app._set_review_queue_mode("table")
        root.update_idletasks()
        assert app.workflow_mode.get() == "advanced"
        assert app.review_queue_mode.get() == "table"
        app._set_workflow_mode("beginner")
        root.update_idletasks()
        assert app.workflow_mode.get() == "beginner"
        assert app.review_queue_mode.get() == "inbox"
    finally:
        root.destroy()


def test_beginner_mode_can_temporarily_show_advanced_controls(tmp_path: Path):
    project_dir = _make_project(tmp_path, {"doc.txt": "Grounding means connection to earth."}, name="Advanced Toggle")

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        assert app.workflow_mode.get() == "beginner"
        assert app._advanced_controls_visible() is False
        app._toggle_advanced_controls()
        root.update_idletasks()
        assert app.show_advanced_controls.get() is True
        assert app._advanced_controls_visible() is True
        app._toggle_advanced_controls()
        root.update_idletasks()
        assert app.show_advanced_controls.get() is False
    finally:
        root.destroy()


def test_advanced_review_table_restores_bulk_retry_controls(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "broken.json": '{"alpha": 1,,}',
            "dup_one.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
            "dup_two.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
        },
        name="Advanced Review Table",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_workflow_mode("advanced")
        app._set_review_queue_mode("table")
        app._set_active_view("review")
        root.update_idletasks()
        assert app.bulk_retry_doc_type_combo is not None
        assert app.bulk_retry_strategy_combo is not None
        assert app.review_tree["columns"] == ("status", "severity", "kind", "file")
    finally:
        root.destroy()


def test_header_metrics_reflect_active_workflow_state(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "good.txt": "Grounding means connection to earth.\nProcedure and checklist text for review.",
            "broken.json": '{"alpha": 1,,}',
        },
        name="Header Metrics",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("processing")
        root.update_idletasks()
        assert "docs" in app.header_metrics_var.get().lower()
        assert "failed" in app.header_metrics_var.get().lower()
        app._set_active_view("review")
        root.update_idletasks()
        assert "review" in app.header_metrics_var.get().lower()
    finally:
        root.destroy()



def test_review_view_surfaces_guided_progress_in_inbox_mode(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "broken.json": '{"alpha": 1,,}',
            "good.txt": "Grounding means connection to earth.\nProcedure and checklist text for review.",
        },
        name="Guided Review Progress",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        root.update_idletasks()
        assert app.review_filter.get() == "Open"
        assert app.review_queue_mode.get() == "inbox"
        assert app.review_session_primary_button is not None
        assert app.review_session_primary_button.cget("text")
        assert "issue 1 of" in app.review_progress_var.get().lower()
    finally:
        root.destroy()


def test_review_view_stacks_detail_panel_below_queue_in_compact_layout(tmp_path: Path, monkeypatch):
    project_dir = _make_project(
        tmp_path,
        {
            "broken.json": '{"alpha": 1,,}',
            "dup_one.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
            "dup_two.txt": "Ground lug torque: 45 Nm.\nDisconnect power before service.\n",
        },
        name="Compact Review Layout",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        monkeypatch.setattr(app, "_shell_width", lambda: 1160)
        app._set_workflow_mode("advanced")
        app._set_review_queue_mode("table")
        app._set_active_view("review")
        root.update_idletasks()
        assert app.review_tree is not None
        assert app.review_note_text is not None
        assert app.review_queue_frame is not None
        assert app.review_detail_frame is not None
        assert int(app.review_queue_frame.grid_info()["row"]) == 0
        assert int(app.review_detail_frame.grid_info()["row"]) == 1
        assert int(app.review_detail_frame.grid_info()["column"]) == 0
    finally:
        root.destroy()


def test_export_view_applies_queued_artifact_focus(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {"doc.txt": "Grounding means connection to earth.\nProcedure and checklist text for review."},
        name="Export Focus",
    )
    scan_project(project_dir)
    export_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._queue_view_focus("export", "artifacts")
        app._set_active_view("export")
        root.update_idletasks()
        assert app.view_state.active_view == "export"
        assert app.focus_target_view.get() == ""
    finally:
        root.destroy()


def test_go_to_diagnostics_queues_issue_focus(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "good.txt": "Grounding means connection to earth.\nProcedure and checklist text for review.",
            "broken.json": '{"alpha": 1,,}',
        },
        name="Diagnostics Focus",
    )
    scan_project(project_dir)
    export_diagnostics_report(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app.on_go_to_diagnostics()
        root.update_idletasks()
        assert app.view_state.active_view == "diagnostics"
        assert app.diagnostics_issue_log is not None
    finally:
        root.destroy()


def test_review_refresh_prefers_first_open_item(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "broken_a.json": '{"alpha": 1,,}',
            "broken_b.json": '{"bravo": 2,,}',
        },
        name="Review Selection",
    )
    scan_project(project_dir)
    review_project(project_dir)
    reviews = load_reviews(project_dir).get("items", [])
    first_review_id = str(reviews[0]["review_id"])
    update_review_item(project_dir, review_id=first_review_id, status="accepted")

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app.selected_review_id.set(first_review_id)
        app._set_active_view("review")
        root.update_idletasks()
        current = app._current_selected_review_item()
        assert current is not None
        assert current.get("status") == "open"
    finally:
        root.destroy()


def test_review_view_shows_completion_handoff_when_queue_is_clear(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {"doc.txt": "Grounding means connection to earth.\nProcedure and checklist text for review."},
        name="Review Complete",
    )
    scan_project(project_dir)
    review_project(project_dir, approve_all=True)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        root.update_idletasks()
        assert "continue to export" in app.review_completion_var.get().lower()
        assert app.primary_action_button.cget("text") in {"Get GPT Files", "Open GPT Files Folder", "Fix Issues"}
    finally:
        root.destroy()


def test_export_view_shows_step_complete_when_export_exists(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {"doc.txt": "Grounding means connection to earth.\nProcedure and checklist text for review."},
        name="Export Complete",
    )
    scan_project(project_dir)
    export_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("export")
        root.update_idletasks()
        assert "export" in app.export_completion_var.get().lower()
        assert app.export_next_action_var.get()
    finally:
        root.destroy()


def test_export_view_stacks_artifact_and_validation_panels_in_compact_layout(tmp_path: Path, monkeypatch):
    project_dir = _make_project(
        tmp_path,
        {"doc.txt": "Grounding means connection to earth.\nProcedure and checklist text for review."},
        name="Compact Export Layout",
    )
    scan_project(project_dir)
    export_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        monkeypatch.setattr(app, "_shell_width", lambda: 1160)
        app._set_active_view("export")
        root.update_idletasks()
        assert app.export_artifact_frame is not None
        assert app.export_validation_frame is not None
        assert int(app.export_artifact_frame.grid_info()["row"]) == 0
        assert int(app.export_validation_frame.grid_info()["row"]) == 1
        assert int(app.export_validation_frame.grid_info()["column"]) == 0
    finally:
        root.destroy()


def test_processing_continue_action_routes_to_review_when_blockers_exist(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "good.txt": "Grounding means connection to earth.\nProcedure and checklist text for review.",
            "broken.json": '{"alpha": 1,,}',
        },
        name="Processing Continue",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("processing")
        root.update_idletasks()
        assert "issue" in app.workflow_hint_var.get().lower() or "fix" in app.workflow_hint_var.get().lower()
        app.on_continue_from_processing()
        root.update_idletasks()
        assert app.view_state.active_view == "review"
    finally:
        root.destroy()


def test_processing_view_surfaces_recent_extraction_issues_and_type_distribution(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "good.txt": "Grounding means connection to earth.\nProcedure and checklist text for review.",
            "broken.json": '{"alpha": 1,,}',
            "unknown.bin": "binary-ish placeholder",
        },
        name="Diagnostics Project",
    )
    config = load_project_config(project_dir)
    config.include_globs = ["**/*"]
    save_project_config(project_dir, config)
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("processing")
        root.update_idletasks()
        app.show_beginner_processing_details.set(True)
        app._render_current_view()
        root.update_idletasks()
        assert "unsupported=" in app.processing_summary_var.get()
        assert app.processing_issue_log is not None
        assert "unsupported" in app.processing_issue_log.get("1.0", "end").lower()
        assert app.processing_type_log is not None
        type_text = app.processing_type_log.get("1.0", "end").lower()
        assert "txt: 1" in type_text
        assert "json: 1" in type_text
        assert "unknown: 1" in type_text
    finally:
        root.destroy()


def test_diagnostics_view_reads_exported_json(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "good.txt": "Grounding means connection to earth.\nProcedure and checklist text for review.",
            "broken.json": '{"alpha": 1,,}',
        },
        name="Diagnostics View",
    )
    scan_project(project_dir)
    export_diagnostics_report(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("diagnostics")
        root.update_idletasks()
        assert "Diagnostics loaded" in app.diagnostics_summary_var.get()
        assert app.diagnostics_issue_log is not None
        assert "broken.json" in app.diagnostics_issue_log.get("1.0", "end")
        assert app.diagnostics_review_log is not None
        assert "broken.json" in app.diagnostics_review_log.get("1.0", "end").lower()
    finally:
        root.destroy()


def test_diagnostics_folder_action_persists_exclude_globs(tmp_path: Path):
    source_dir = tmp_path / "source"
    (source_dir / "batch_a").mkdir(parents=True)
    (source_dir / "batch_b").mkdir(parents=True)
    (source_dir / "batch_a" / "broken.json").write_text('{"alpha": 1,,}', encoding="utf-8")
    (source_dir / "batch_b" / "good.txt").write_text("Grounding means connection to earth.", encoding="utf-8")
    output_dir = tmp_path / "output"
    project_dir = tmp_path / "workspace"
    init_project(project_dir, "Diagnostics Folder Actions", [source_dir], output_dir, "mixed-office-documents", "custom-gpt-balanced")
    config = load_project_config(project_dir)
    config.include_globs = ["**/*"]
    save_project_config(project_dir, config)
    scan_project(project_dir)
    export_diagnostics_report(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("diagnostics")
        root.update_idletasks()
        app.on_exclude_folder_from_diagnostics("batch_a")
        config = load_project_config(project_dir)
        assert "batch_a/**" in config.exclude_globs
        assert "1/2 top-level folders included" in app.status_selection_var.get().lower()
    finally:
        root.destroy()


def test_review_duplicate_selection_populates_side_by_side_comparison(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {
            "dup_one.txt": ("\n".join(["Ground lug torque: 45 Nm."] * 20)) + "\nDisconnect power before service.\n",
            "dup_two.txt": ("\n".join(["Ground lug torque: 45 Nm."] * 20)) + "\nDisconnect all DC power before service.\n",
        },
        name="Duplicate Compare",
    )
    scan_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("review")
        app._set_review_filter("Duplicates")
        root.update_idletasks()
        assert app.review_duplicate_compare_frame is not None
        assert app.review_duplicate_current_text is not None
        assert app.review_duplicate_target_text is not None
        left_text = app.review_duplicate_current_text.get("1.0", "end")
        right_text = app.review_duplicate_target_text.get("1.0", "end")
        assert "dup_" in left_text.lower()
        assert "dup_" in right_text.lower()
        assert left_text != right_text
        assert "- disconnect" in left_text.lower() or "+ disconnect" in right_text.lower()
    finally:
        root.destroy()


def test_history_view_reads_project_activity_log(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {"doc.txt": "Grounding means connection to earth.\nProcedure guidance."},
        name="History View",
    )
    scan_project(project_dir)
    export_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._append_recent_action("Manual session action")
        app._set_active_view("history")
        root.update_idletasks()
        assert app.history_project_log is not None
        assert "scan " in app.history_project_log.get("1.0", "end").lower()
        assert "export " in app.history_project_log.get("1.0", "end").lower()
        assert app.history_session_log is not None
        assert "manual session action" in app.history_session_log.get("1.0", "end").lower()
    finally:
        root.destroy()


def test_history_view_can_open_selected_context(tmp_path: Path):
    project_dir = _make_project(
        tmp_path,
        {"doc.txt": "Grounding means connection to earth.\nProcedure guidance."},
        name="History Jump",
    )
    scan_project(project_dir)
    export_project(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("history")
        root.update_idletasks()
        assert app.history_activity_tree is not None
        children = list(app.history_activity_tree.get_children())
        assert children
        export_row = next(
            row for row in children
            if "export" in str(app.history_activity_tree.item(row, "values")[1]).lower()
        )
        app.history_activity_tree.selection_set(export_row)
        app.on_open_selected_history_context()
        root.update_idletasks()
        assert app.view_state.active_view == "export"
    finally:
        root.destroy()


def test_history_view_folder_action_persists_exclude_globs(tmp_path: Path):
    source_dir = tmp_path / "source"
    (source_dir / "batch_a").mkdir(parents=True)
    (source_dir / "batch_b").mkdir(parents=True)
    (source_dir / "batch_a" / "broken.json").write_text('{"alpha": 1,,}', encoding="utf-8")
    (source_dir / "batch_b" / "good.txt").write_text("Grounding means connection to earth.", encoding="utf-8")
    output_dir = tmp_path / "output"
    project_dir = tmp_path / "workspace"
    init_project(project_dir, "History Folder Actions", [source_dir], output_dir, "mixed-office-documents", "custom-gpt-balanced")
    config = load_project_config(project_dir)
    config.include_globs = ["**/*"]
    save_project_config(project_dir, config)
    scan_project(project_dir)
    export_diagnostics_report(project_dir)

    root = _make_root()
    try:
        app = App(root, initial_config=project_dir / PROJECT_FILE)
        app._set_active_view("history")
        root.update_idletasks()
        app.on_exclude_folder_from_diagnostics("batch_a")
        config = load_project_config(project_dir)
        assert "batch_a/**" in config.exclude_globs
        assert app.view_state.active_view == "history"
    finally:
        root.destroy()
