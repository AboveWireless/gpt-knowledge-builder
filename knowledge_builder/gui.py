from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import queue
import re
import shutil
import sys
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, TOP, W, X, BooleanVar, PhotoImage, StringVar, Tk, Toplevel, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .naming import make_safe_corpus_name
from .project.pipeline import diagnostics_paths, export_diagnostics_report, export_project, promote_duplicate_as_canonical, retry_document_extraction, retry_review_items, review_project, scan_project, update_review_item, validate_project
from .project.previews import render_document_preview, render_document_preview_strip
from .project.store import (
    PROJECT_FILE,
    init_project,
    load_project_config,
    load_reviews,
    load_secrets,
    load_state,
    resolve_project_path,
    save_project_config,
    save_secrets,
    state_root,
)
from .extractors import get_supported_doc_type
from .ui.models import MetricCardModel, ViewState
from .ui.theme import configure_theme, default_theme
from .ui.widgets import build_info_button, build_metric_card, build_status_chip, configure_status_chip, style_scrolled_text
from .version import APP_NAME

try:
    from tkinterdnd2 import DND_FILES
except Exception:  # pragma: no cover - optional dependency
    DND_FILES = None


def merge_batch_folder_selection(folder_names: list[str], previous_selection: dict[str, bool] | None = None) -> dict[str, bool]:
    prior = previous_selection or {}
    return {name: prior.get(name, True) for name in folder_names}


def selected_batch_folder_names(selection: dict[str, bool]) -> list[str]:
    return [name for name, is_selected in selection.items() if is_selected]


class App:
    def __init__(self, root: Tk, initial_config: Path | None = None) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1400x900")
        self.root.minsize(1160, 760)

        self.palette, self.type_scale, self.spacing = default_theme()
        configure_theme(root, self.palette, self.type_scale)

        self.project_dir = StringVar(value=str(initial_config.parent if initial_config else Path.cwd()))
        self.source_dir = StringVar(value=str(Path.cwd() / "input"))
        self.output_dir = StringVar(value=str(Path.cwd() / "output"))
        self.project_name = StringVar(value="knowledge_project")
        self._selected_source_roots: list[str] = [str(Path.cwd() / "input")]
        self.preset = StringVar(value="mixed-office-documents")
        self.export_profile = StringVar(value="custom-gpt-balanced")
        self.model_enabled = BooleanVar(value=False)
        self.model_name = StringVar(value="gpt-5.4")
        self.api_key_value = StringVar(value="")
        self.save_api_key = BooleanVar(value=False)
        self.force_scan = BooleanVar(value=False)
        self.zip_pack = BooleanVar(value=False)
        self.selected_review_id = StringVar(value="")
        self.review_status_edit = StringVar(value="accepted")
        self.review_title_edit = StringVar(value="")
        self.review_domain_edit = StringVar(value="")
        self.review_filter = StringVar(value="All")
        self.review_queue_mode = StringVar(value="inbox")
        self.workflow_mode = StringVar(value="beginner")
        self.show_advanced_controls = BooleanVar(value=False)
        self.show_beginner_source_details = BooleanVar(value=False)
        self.show_beginner_processing_details = BooleanVar(value=False)
        self.review_preview_label_var = StringVar(value="Preview")
        self.review_retry_strategy = StringVar(value="default")
        self.bulk_retry_kind = StringVar(value="extraction_issue")
        self.bulk_retry_doc_type = StringVar(value="all")
        self.bulk_retry_extraction_status = StringVar(value="all")
        self.bulk_retry_strategy = StringVar(value="default")
        self.review_low_signal_var = StringVar(value="60")
        self.review_duplicate_threshold_var = StringVar(value="0.96")
        self.review_confidence_var = StringVar(value="0.55")
        self.banner_var = StringVar(value="Create or open a project to begin.")
        self.header_title_var = StringVar(value="Home")
        self.header_subtitle_var = StringVar(value="Start with a polished project workspace and build toward export-ready GPT knowledge.")
        self.header_metrics_var = StringVar(value="Docs 0 | Review 0 | Exports 0")
        self.context_title_var = StringVar(value="Workspace Health")
        self.workflow_hint_var = StringVar(value="Create a project, then move through setup, scan, review, and export.")
        self.sidebar_next_step_var = StringVar(value="Next step: create or open a project.")
        self.sidebar_progress_var = StringVar(value="No workspace loaded yet.")
        self.processing_recommendation_var = StringVar(value="Run the first scan after setup.")
        self.processing_decision_title_var = StringVar(value="No scan decision yet.")
        self.processing_decision_detail_var = StringVar(value="Run the first scan to see the recommended next action.")
        self.operation_phase_var = StringVar(value="Idle")
        self.operation_detail_var = StringVar(value="No active scan, review, or export operation.")
        self.home_summary_var = StringVar(value="No project loaded yet.")
        self.processing_summary_var = StringVar(value="No scan has run yet.")
        self.review_summary_var = StringVar(value="No review items loaded.")
        self.export_summary_var = StringVar(value="No export has been generated yet.")
        self.diagnostics_summary_var = StringVar(value="No diagnostics file loaded.")
        self.diagnostics_filter_var = StringVar(value="All")
        self.review_meta_var = StringVar(value="No review item selected.")
        self.review_issue_title_var = StringVar(value="No review item selected.")
        self.review_issue_reason_var = StringVar(value="Select an item to see why it matters.")
        self.review_issue_action_var = StringVar(value="Recommended action will appear here.")
        self.review_session_title_var = StringVar(value="No review issue loaded.")
        self.review_session_detail_var = StringVar(value="Open Review to start a guided session.")
        self.review_progress_var = StringVar(value="No review queue loaded.")
        self.review_completion_var = StringVar(value="Review still has open issues.")
        self.setup_completion_var = StringVar(value="Complete setup to unlock the next step.")
        self.scan_completion_var = StringVar(value="Run the first scan to complete this step.")
        self.transition_notice_step = StringVar(value="")
        self.transition_notice_title_var = StringVar(value="")
        self.transition_notice_detail_var = StringVar(value="")
        self.setup_validation_var = StringVar(value="Setup validation has not run yet.")
        self.source_preview_var = StringVar(value="No source preview available yet.")
        self.scan_forecast_var = StringVar(value="No scan forecast available yet.")
        self.export_completion_var = StringVar(value="No export has completed yet.")
        self.export_next_action_var = StringVar(value="Export a package to see next steps.")
        self.export_readiness_var = StringVar(value="Not ready")
        self.export_readiness_detail_var = StringVar(value="Scan the corpus before exporting.")
        self.dependency_health_var = StringVar(value="Dependency health has not been checked yet.")
        self.project_badge_var = StringVar(value="No project")
        self.profile_badge_var = StringVar(value="custom-gpt-balanced")
        self.ai_badge_var = StringVar(value="AI off")
        self.status_project_var = StringVar(value="Project: no project loaded")
        self.status_selection_var = StringVar(value="Sources: all folders")
        self.status_action_var = StringVar(value="Last action: waiting")

        self.view_state = ViewState(active_view="home", has_project=False, review_filter="All", selected_review_id="")
        self._event_queue: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self._process_log_lines: list[str] = []
        self._export_log_lines: list[str] = []
        self._context_notes: list[str] = []
        self._nav_buttons: dict[str, ttk.Button] = {}
        self._review_tree_map: dict[str, dict] = {}
        self._history_activity_map: dict[str, dict] = {}
        self.header_frame = None
        self.header_left = None
        self.header_right = None
        self.header_subtitle_label = None
        self.header_metrics_label = None
        self.sidebar_intro_label = None
        self.sidebar_next_step_label = None
        self.sidebar_progress_label = None
        self.body_frame = None
        self.review_queue_frame = None
        self.review_detail_frame = None
        self.processing_issue_frame = None
        self.processing_detail_frame = None
        self.export_artifact_frame = None
        self.export_validation_frame = None
        self.review_tree = None
        self.review_note_text = None
        self.review_preview_text = None
        self.review_preview_image_label = None
        self.review_preview_photo = None
        self.review_thumbnail_strip = None
        self.review_thumbnail_buttons: list[ttk.Button] = []
        self.review_thumbnail_photos: list[PhotoImage] = []
        self.review_retry_combo = None
        self.review_duplicate_compare_frame = None
        self.review_duplicate_current_text = None
        self.review_duplicate_target_text = None
        self.review_session_primary_button = None
        self.bulk_retry_doc_type_combo = None
        self.bulk_retry_status_combo = None
        self.bulk_retry_strategy_combo = None
        self.review_preview_units: list[dict] = []
        self.review_preview_index = 0
        self.process_log = None
        self.processing_issue_log = None
        self.processing_type_log = None
        self.export_log = None
        self.export_artifact_list = None
        self.diagnostics_issue_log = None
        self.diagnostics_review_log = None
        self.focus_target_view = StringVar(value="")
        self.focus_target_name = StringVar(value="")
        self.history_activity_tree = None
        self.history_project_log = None
        self.history_session_log = None
        self.history_export_history_log = None
        self.review_list = None
        self.review_history_log = None
        self.home_primary_button = None
        self.home_guided_button = None
        self.sidebar_footer = None
        self.workflow_mode_beginner_button = None
        self.workflow_mode_advanced_button = None
        self.sidebar_progress_frame = None
        self.guided_wizard = None
        self.guided_wizard_body = None
        self.guided_wizard_step = 0
        self.guided_wizard_title_var = StringVar(value="Guided Setup")
        self.guided_wizard_hint_var = StringVar(value="Follow the steps to create a project.")
        self.export_summary_dialog = None
        self.review_sort_column = "priority"
        self.review_sort_desc = False
        self._recent_action_lines: list[str] = []
        self._pending_undo_snapshot: dict | None = None
        self._last_undo_action: dict | None = None
        self._pending_review_followup: str | None = None
        self._view_tips_seen: set[str] = set()
        self._source_folder_selection: dict[str, bool] = {}
        self._responsive_layout_job = None
        self._compact_shell_layout_active = False

        self._build_shell()
        self._bind_shortcuts()
        self.root.bind("<Configure>", self._queue_responsive_layout_refresh, add="+")
        self.root.after(150, self._pump_events)
        self.root.after(0, self._apply_responsive_layout)

        if initial_config and initial_config.exists():
            self._load_project(initial_config.parent)
        else:
            self._refresh_shell()

    def _recent_projects_path(self) -> Path:
        base = Path.home() / ".gpt_knowledge_builder"
        base.mkdir(parents=True, exist_ok=True)
        return base / "recent_projects.json"

    def _load_recent_projects(self) -> list[dict]:
        path = self._recent_projects_path()
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = payload if isinstance(payload, list) else []
        return [item for item in items if isinstance(item, dict) and item.get("project_dir")]

    def _save_recent_projects(self, items: list[dict]) -> None:
        path = self._recent_projects_path()
        path.write_text(json.dumps(items[:8], indent=2), encoding="utf-8")

    def _record_recent_project(self, project_dir: Path, project_name: str) -> None:
        normalized = str(project_dir.resolve())
        items = [item for item in self._load_recent_projects() if str(item.get("project_dir") or "") != normalized]
        items.insert(
            0,
            {
                "project_dir": normalized,
                "project_name": project_name,
                "last_opened": time.time(),
            },
        )
        self._save_recent_projects(items)

    def _recent_projects_display(self) -> list[dict]:
        rows: list[dict] = []
        for item in self._load_recent_projects():
            project_dir = Path(str(item.get("project_dir") or ""))
            rows.append(
                {
                    "project_dir": project_dir,
                    "project_name": str(item.get("project_name") or project_dir.name),
                    "last_opened": float(item.get("last_opened") or 0.0),
                    "exists": project_dir.exists() and (project_dir / PROJECT_FILE).exists(),
                }
            )
        return rows

    def _build_shell(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=0)
        outer.pack(fill=BOTH, expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)
        outer.rowconfigure(1, weight=0)

        self.sidebar = ttk.Frame(outer, style="Sidebar.TFrame", padding=(18, 20))
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.main = ttk.Frame(outer, style="App.TFrame", padding=(18, 18, 18, 18))
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(1, weight=1)
        self.status_bar = ttk.Frame(outer, style="PanelAlt.TFrame", padding=(16, 8))
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")

        self._build_sidebar()
        self._build_header()
        self._build_body()
        self._build_status_bar()

    def _build_sidebar(self) -> None:
        ttk.Label(self.sidebar, text=APP_NAME, style="Header.TLabel").pack(anchor=W, pady=(0, 4))
        self.sidebar_intro_label = ttk.Label(
            self.sidebar,
            text="Simple desktop app for turning a folder of documents into Custom GPT knowledge files.",
            style="Muted.TLabel",
            wraplength=220,
            justify=LEFT,
        )
        self.sidebar_intro_label.pack(anchor=W, pady=(0, 18))

        for view_id in ("home", "sources", "processing", "review", "export", "diagnostics", "history", "settings"):
            button = ttk.Button(self.sidebar, text=self._nav_label(view_id), style="Nav.TButton", command=lambda value=view_id: self._set_active_view(value))
            button.pack(fill=X, pady=(0, 6))
            self._nav_buttons[view_id] = button

        footer = ttk.Frame(self.sidebar, style="Sidebar.TFrame", padding=(0, 18, 0, 0))
        footer.pack(fill=X, side=TOP)
        self.sidebar_footer = footer
        self.sidebar_progress_frame = ttk.Frame(footer, style="PanelAlt.TFrame", padding=12)
        self.sidebar_progress_frame.pack(fill=X, pady=(0, 12))
        ttk.Label(self.sidebar_progress_frame, text="Workflow Status", style="Section.TLabel").pack(anchor=W)
        self.sidebar_next_step_label = ttk.Label(self.sidebar_progress_frame, textvariable=self.sidebar_next_step_var, style="Caption.TLabel", wraplength=220, justify=LEFT)
        self.sidebar_next_step_label.pack(anchor=W, pady=(6, 0))
        self.sidebar_progress_label = ttk.Label(self.sidebar_progress_frame, textvariable=self.sidebar_progress_var, style="Muted.TLabel", wraplength=220, justify=LEFT)
        self.sidebar_progress_label.pack(anchor=W, pady=(6, 0))
        self.project_badge = build_status_chip(footer, self.project_badge_var.get(), self.palette, tone="primary", wraplength=self._sidebar_chip_wraplength())
        self.project_badge.pack(anchor=W, pady=(0, 8))
        self.profile_badge = build_status_chip(footer, self.profile_badge_var.get(), self.palette, tone="success", wraplength=self._sidebar_chip_wraplength())
        self.profile_badge.pack(anchor=W, pady=(0, 8))
        self.ai_badge = build_status_chip(footer, self.ai_badge_var.get(), self.palette, tone="muted", wraplength=self._sidebar_chip_wraplength())
        self.ai_badge.pack(anchor=W)

    def _build_header(self) -> None:
        header = ttk.Frame(self.main, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)
        self.header_frame = header

        left = ttk.Frame(header, style="App.TFrame")
        left.grid(row=0, column=0, sticky="w")
        self.header_left = left
        ttk.Label(left, textvariable=self.header_title_var, style="Header.TLabel").pack(anchor=W)
        self.header_subtitle_label = ttk.Label(left, textvariable=self.header_subtitle_var, style="Subhead.TLabel", wraplength=760, justify=LEFT)
        self.header_subtitle_label.pack(anchor=W, pady=(4, 0))
        self.header_metrics_label = ttk.Label(left, textvariable=self.header_metrics_var, style="Caption.TLabel", wraplength=760, justify=LEFT)
        self.header_metrics_label.pack(anchor=W, pady=(6, 0))

        right = ttk.Frame(header, style="App.TFrame")
        right.grid(row=0, column=1, sticky="e")
        self.header_right = right
        mode_frame = ttk.Frame(right, style="App.TFrame")
        mode_frame.pack(side=RIGHT, padx=(0, 12))
        ttk.Label(mode_frame, text="Mode", style="Caption.TLabel").pack(side=LEFT, padx=(0, 6))
        self.workflow_mode_beginner_button = ttk.Button(mode_frame, text="Beginner", style="Primary.TButton", command=lambda: self._set_workflow_mode("beginner"))
        self.workflow_mode_beginner_button.pack(side=LEFT)
        self.workflow_mode_advanced_button = ttk.Button(mode_frame, text="Advanced", style="Ghost.TButton", command=lambda: self._set_workflow_mode("advanced"))
        self.workflow_mode_advanced_button.pack(side=LEFT, padx=(8, 0))
        self.primary_action_button = ttk.Button(right, text="Create Project", style="Primary.TButton", command=self.on_create_project)
        self.primary_action_button.pack(side=RIGHT)
        self.banner_chip = build_status_chip(right, self.banner_var.get(), self.palette, tone="primary", wraplength=self._banner_chip_wraplength())
        self.banner_chip.pack(side=RIGHT, padx=(0, 12))

    def _build_body(self) -> None:
        body = ttk.Frame(self.main, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=0)
        self.body_frame = body

        self.content_frame = ttk.Frame(body, style="Panel.TFrame", padding=18)
        self.content_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.context_frame = ttk.Frame(body, style="Panel.TFrame", padding=18)
        self.context_frame.grid(row=0, column=1, sticky="nsew")

    def _build_status_bar(self) -> None:
        ttk.Label(self.status_bar, textvariable=self.status_project_var, style="Caption.TLabel").pack(side=LEFT)
        ttk.Label(self.status_bar, text=" | ", style="Caption.TLabel").pack(side=LEFT)
        ttk.Label(self.status_bar, textvariable=self.status_selection_var, style="Caption.TLabel").pack(side=LEFT)
        ttk.Label(self.status_bar, text=" | ", style="Caption.TLabel").pack(side=LEFT)
        ttk.Label(self.status_bar, textvariable=self.status_action_var, style="Caption.TLabel").pack(side=LEFT)

    def _shell_width(self) -> int:
        width = int(self.root.winfo_width() or 0)
        if width <= 1:
            geometry = str(self.root.winfo_geometry() or "")
            if "x" in geometry:
                try:
                    width = int(geometry.split("x", 1)[0])
                except ValueError:
                    width = 0
        return max(width, 1160)

    def _use_compact_shell_layout(self, width: int | None = None) -> bool:
        return (width or self._shell_width()) < 1360

    def _content_wraplength(self, max_width: int = 900) -> int:
        content_width = int(self.content_frame.winfo_width() or 0) if self.content_frame is not None else 0
        if content_width <= 1:
            content_width = self._shell_width() - (140 if self._use_compact_shell_layout() else 420)
        return max(320, min(max_width, content_width - (self.spacing.xl * 2)))

    def _sidebar_chip_wraplength(self) -> int:
        return 190 if self._use_compact_shell_layout() else 220

    def _banner_chip_wraplength(self) -> int:
        return 520 if self._use_compact_shell_layout() else 260

    def _queue_responsive_layout_refresh(self, event=None) -> None:
        if event is not None and getattr(event, "widget", None) is not self.root:
            return
        if self._responsive_layout_job is not None:
            self.root.after_cancel(self._responsive_layout_job)
        self._responsive_layout_job = self.root.after(30, self._apply_responsive_layout)

    def _apply_responsive_layout(self) -> None:
        self._responsive_layout_job = None
        self._apply_responsive_layout_for_width(self._shell_width())

    def _apply_responsive_layout_for_width(self, width: int) -> None:
        compact = self._use_compact_shell_layout(width)
        self._compact_shell_layout_active = compact
        if self.header_left is not None and self.header_right is not None:
            self.header_left.grid_configure(row=0, column=0, sticky="ew")
            if compact:
                self.header_right.grid_configure(row=1, column=0, columnspan=2, sticky="w", pady=(12, 0))
            else:
                self.header_right.grid_configure(row=0, column=1, columnspan=1, sticky="e", pady=0)
        if self.body_frame is not None:
            self.body_frame.columnconfigure(0, weight=1)
            self.body_frame.columnconfigure(1, weight=0 if compact else 1)
            self.body_frame.rowconfigure(0, weight=1)
            self.body_frame.rowconfigure(1, weight=0 if not compact else 1)
        if self.content_frame is not None and self.context_frame is not None:
            if compact:
                self.content_frame.grid_configure(row=0, column=0, padx=0, pady=(0, 14))
                self.context_frame.grid_configure(row=1, column=0, padx=0, pady=0)
            else:
                self.content_frame.grid_configure(row=0, column=0, padx=(0, 14), pady=0)
                self.context_frame.grid_configure(row=0, column=1, padx=0, pady=0)
        subtitle_wrap = max(360, min(840, width - (120 if compact else 520)))
        if self.header_subtitle_label is not None:
            self.header_subtitle_label.configure(wraplength=subtitle_wrap)
        if self.header_metrics_label is not None:
            self.header_metrics_label.configure(wraplength=subtitle_wrap)
        sidebar_wrap = 200 if compact else 220
        if self.sidebar_intro_label is not None:
            self.sidebar_intro_label.configure(wraplength=sidebar_wrap)
        if self.sidebar_next_step_label is not None:
            self.sidebar_next_step_label.configure(wraplength=sidebar_wrap)
        if self.sidebar_progress_label is not None:
            self.sidebar_progress_label.configure(wraplength=sidebar_wrap)
        if self.project_badge is not None:
            configure_status_chip(self.project_badge, self.project_badge_var.get(), self.palette, tone="primary", wraplength=self._sidebar_chip_wraplength())
        if self.profile_badge is not None:
            configure_status_chip(self.profile_badge, self.profile_badge_var.get(), self.palette, tone="success", wraplength=self._sidebar_chip_wraplength())
        if self.ai_badge is not None:
            configure_status_chip(self.ai_badge, self.ai_badge_var.get(), self.palette, tone="warn" if self.model_enabled.get() else "muted", wraplength=self._sidebar_chip_wraplength())
        if self.banner_chip is not None:
            configure_status_chip(self.banner_chip, self.banner_var.get(), self.palette, tone="primary", wraplength=self._banner_chip_wraplength())

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Alt-a>", lambda event: self._handle_review_shortcut("accept_next", event))
        self.root.bind_all("<Alt-i>", lambda event: self._handle_review_shortcut("ignore_next", event))
        self.root.bind_all("<Alt-r>", lambda event: self._handle_review_shortcut("retry_next", event))
        self.root.bind_all("<Alt-j>", lambda event: self._handle_review_shortcut("next_issue", event))
        self.root.bind_all("<Alt-k>", lambda event: self._handle_review_shortcut("prev_issue", event))

    def _handle_review_shortcut(self, action: str, event=None):
        if self.view_state.active_view != "review":
            return None
        widget = getattr(event, "widget", None)
        widget_name = str(getattr(widget, "winfo_class", lambda: "")()).lower() if widget else ""
        if widget_name in {"entry", "text", "tentry", "tcombobox", "combobox"}:
            return None
        actions = {
            "accept_next": self.on_mark_review_accepted_and_next,
            "ignore_next": self.on_mark_review_rejected_and_next,
            "retry_next": self.on_retry_selected_review_and_next,
            "next_issue": self.on_next_review_item,
            "prev_issue": self.on_prev_review_item,
        }
        handler = actions.get(action)
        if handler:
            handler()
            return "break"
        return None

    def _render_screen_tip(self, parent, view_id: str, title: str, lines: list[str]) -> None:
        if view_id in self._view_tips_seen:
            return
        panel = ttk.Frame(parent, style="PanelAlt.TFrame", padding=14)
        panel.pack(fill=X, pady=(0, 14))
        header = ttk.Frame(panel, style="PanelAlt.TFrame")
        header.pack(fill=X)
        ttk.Label(header, text=title, style="Section.TLabel").pack(side=LEFT)
        ttk.Button(header, text="Dismiss", style="Ghost.TButton", command=lambda value=view_id: self._dismiss_screen_tip(value)).pack(side=RIGHT)
        wraplength = self._content_wraplength()
        for line in lines:
            ttk.Label(panel, text=f"- {line}", style="Caption.TLabel", wraplength=wraplength, justify=LEFT).pack(anchor=W, pady=(6, 0))

    def _dismiss_screen_tip(self, view_id: str) -> None:
        self._view_tips_seen.add(view_id)
        self._render_current_view()

    def _render_drop_zone(self, parent) -> None:
        panel = ttk.Frame(parent, style="PanelAlt.TFrame", padding=12)
        panel.pack(fill=X, pady=(0, 14))
        ttk.Label(panel, text="Drag And Drop Intake", style="Section.TLabel").pack(anchor=W)
        hint = (
            "Drop a folder path onto this card to set the Source Folder."
            if DND_FILES and hasattr(panel, "drop_target_register")
            else "Drag-and-drop is optional. Install tkinterdnd2 for folder drop support, or use Browse."
        )
        ttk.Label(panel, text=hint, style="Caption.TLabel", wraplength=self._content_wraplength(), justify=LEFT).pack(anchor=W, pady=(6, 0))
        self._enable_drop_target(panel, "source")

    def _enable_drop_target(self, widget, target: str) -> None:
        if not DND_FILES or not hasattr(widget, "drop_target_register"):
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", lambda event, value=target: self._handle_drop_path(event, value))
        except Exception:
            return

    def _handle_drop_path(self, event, target: str):
        data = str(getattr(event, "data", "") or "").strip()
        if not data:
            return None
        path_text = self._normalize_dropped_path(data)
        path = Path(path_text)
        if not path.exists():
            self.banner_var.set(f"Dropped path not found: {path_text}")
            self._refresh_shell()
            return None
        if target == "source":
            self.source_dir.set(str(path))
            if not self.project_name.get().strip():
                self.project_name.set(path.name)
        elif target == "project":
            self.project_dir.set(str(path))
        elif target == "output":
            self.output_dir.set(str(path))
        self.banner_var.set(f"{target.title()} folder updated from drag-and-drop.")
        self._refresh_shell()
        return "break"

    def _normalize_dropped_path(self, data: str) -> str:
        if data.startswith("{") and data.endswith("}"):
            return data[1:-1]
        if "}" in data and " {" in data:
            return data.split("} {", 1)[0].lstrip("{")
        return data

    def _set_review_queue_mode(self, mode: str) -> None:
        self.review_queue_mode.set(mode)
        if self.view_state.active_view == "review":
            self._render_current_view()

    def _set_workflow_mode(self, mode: str) -> None:
        normalized = "advanced" if mode == "advanced" else "beginner"
        self.workflow_mode.set(normalized)
        if normalized == "beginner":
            self.review_queue_mode.set("inbox")
            self.show_advanced_controls.set(False)
        self.banner_var.set(f"{normalized.title()} mode active.")
        self._refresh_shell()

    def _toggle_advanced_controls(self) -> None:
        self.show_advanced_controls.set(not self.show_advanced_controls.get())
        state = "shown" if self.show_advanced_controls.get() else "hidden"
        self.banner_var.set(f"Advanced controls {state}.")
        self._refresh_shell()

    def _clear_transition_notice(self) -> None:
        self.transition_notice_step.set("")
        self.transition_notice_title_var.set("")
        self.transition_notice_detail_var.set("")
        self._refresh_shell()

    def _queue_view_focus(self, view_id: str, target: str) -> None:
        self.focus_target_view.set(view_id)
        self.focus_target_name.set(target)

    def _apply_view_focus(self, view_id: str, target: str, widget) -> None:
        if self.focus_target_view.get() != view_id or self.focus_target_name.get() != target or widget is None:
            return
        try:
            widget.focus_set()
            if hasattr(widget, "see"):
                widget.see("1.0")
        except Exception:
            pass
        self.focus_target_view.set("")
        self.focus_target_name.set("")

    def _set_active_view(self, view_id: str) -> None:
        if view_id == "review" and self.workflow_mode.get() != "advanced":
            self.review_filter.set("Open")
            self.view_state.review_filter = "Open"
            self.review_queue_mode.set("inbox")
        self.view_state.active_view = view_id
        self._refresh_shell()

    def _refresh_shell(self) -> None:
        self._update_header()
        self._update_nav_styles()
        self._refresh_sidebar_progress()
        self._refresh_status_bar()
        self._render_current_view()
        self._render_context_panel()
        self._apply_responsive_layout()

    def _update_header(self) -> None:
        titles = {
            "home": ("Home", "Open a project, inspect the corpus, and drive the next high-value action."),
            "sources": ("Sources", "Configure project roots, presets, export profile, and AI settings."),
            "processing": ("Processing", "Scan the corpus, track incremental work, and monitor pipeline health."),
            "review": ("Review", "Resolve low-confidence, duplicate, OCR, and taxonomy issues before export."),
            "export": ("Export", "Preview package artifacts, validation warnings, and provenance outputs."),
            "diagnostics": ("Diagnostics", "Inspect corpus health, degraded documents, and open review blockers."),
            "history": ("History", "Review scans, retries, exports, and duplicate decisions across the workspace."),
            "settings": ("Settings", "Tune thresholds, model behavior, and workspace defaults."),
        }
        if self._guided_mode_active():
            titles.update(
                {
                    "home": ("Home", "Start here. Pick folders, scan files, fix anything that needs attention, then get your GPT files."),
                    "sources": ("Sources", "Pick the folders to scan and choose where the GPT files should go."),
                    "processing": ("Processing", "Scan the files and see what needs attention next."),
                    "review": ("Review", "Fix one issue at a time, then move to the next one."),
                    "export": ("Export", "Check readiness and create the final GPT files."),
                }
            )
        title, subtitle = titles.get(self.view_state.active_view, ("Workspace", ""))
        self.header_title_var.set(title)
        self.header_subtitle_var.set(subtitle)
        self.header_metrics_var.set(self._header_progress_text())

        primary_text, primary_action = self._smart_primary_action()
        self.primary_action_button.configure(text=primary_text, command=primary_action)
        if self.workflow_mode_beginner_button is not None and self.workflow_mode_advanced_button is not None:
            is_beginner = self.workflow_mode.get() != "advanced"
            self.workflow_mode_beginner_button.configure(style="Primary.TButton" if is_beginner else "Ghost.TButton")
            self.workflow_mode_advanced_button.configure(style="Primary.TButton" if not is_beginner else "Ghost.TButton")
        self._refresh_badges()

    def _refresh_badges(self) -> None:
        self.project_badge_var.set(self.project_name.get().strip() or "No project")
        self.profile_badge_var.set(self.export_profile.get().strip() or "profile")
        self.ai_badge_var.set("AI on" if self.model_enabled.get() else "AI off")
        configure_status_chip(self.project_badge, self.project_badge_var.get(), self.palette, tone="primary", wraplength=self._sidebar_chip_wraplength())
        configure_status_chip(self.profile_badge, self.profile_badge_var.get(), self.palette, tone="success", wraplength=self._sidebar_chip_wraplength())
        configure_status_chip(
            self.ai_badge,
            self.ai_badge_var.get(),
            self.palette,
            tone="warn" if self.model_enabled.get() else "muted",
            wraplength=self._sidebar_chip_wraplength(),
        )
        configure_status_chip(self.banner_chip, self.banner_var.get(), self.palette, tone="primary", wraplength=self._banner_chip_wraplength())

    def _refresh_status_bar(self) -> None:
        if self.view_state.has_project:
            self.status_project_var.set(f"Project: {self.project_name.get().strip() or 'unnamed'}")
        else:
            self.status_project_var.set("Project: no project loaded")
        selected = selected_batch_folder_names(self._source_folder_selection)
        total = len(self._source_folder_names())
        if total:
            self.status_selection_var.set(f"Sources: {len(selected)}/{total} top-level folders included")
        else:
            self.status_selection_var.set("Sources: all folders")
        self.status_action_var.set(f"Last action: {self.banner_var.get()}")

    def _update_nav_styles(self) -> None:
        visible = set(self._visible_nav_views())
        for view_id, button in self._nav_buttons.items():
            button.configure(text=self._nav_label(view_id), style="NavActive.TButton" if view_id == self.view_state.active_view else "Nav.TButton")
            if view_id in visible:
                button.pack(fill=X, pady=(0, 6), before=self.sidebar_footer)
            else:
                button.pack_forget()

    def _render_current_view(self) -> None:
        self._clear_frame(self.content_frame)
        builders = {
            "home": self._render_home_view,
            "sources": self._render_sources_view,
            "processing": self._render_processing_view,
            "review": self._render_review_view,
            "export": self._render_export_view,
            "diagnostics": self._render_diagnostics_view,
            "history": self._render_history_view,
            "settings": self._render_settings_view,
        }
        builders.get(self.view_state.active_view, self._render_home_view)()

    def _visible_nav_views(self) -> list[str]:
        if self._advanced_controls_visible():
            return ["home", "sources", "processing", "review", "export", "diagnostics", "history", "settings"]
        return ["home", "sources", "processing", "review", "export"]

    def _nav_label(self, view_id: str) -> str:
        if self._advanced_controls_visible():
            labels = {
                "home": "Dashboard",
                "sources": "1. Setup",
                "processing": "2. Scan",
                "review": "3. Review",
                "export": "4. Export",
                "diagnostics": "Diagnostics",
                "history": "History",
                "settings": "Settings",
            }
        else:
            labels = {
                "home": "Start",
                "sources": "Choose Folders",
                "processing": "Scan Files",
                "review": "Fix Issues",
                "export": "Get GPT Files",
                "diagnostics": "Diagnostics",
                "history": "History",
                "settings": "Settings",
            }
        return labels.get(view_id, view_id.title())

    def _render_context_panel(self) -> None:
        self._clear_frame(self.context_frame)
        ttk.Label(self.context_frame, textvariable=self.context_title_var, style="Section.TLabel").pack(anchor=W)

        summary = self._current_workspace_summary()
        metric_row = ttk.Frame(self.context_frame, style="Panel.TFrame")
        metric_row.pack(fill=X, pady=(12, 14))
        health_tone = "success"
        if summary.get("failed_docs", 0) or summary["open_reviews"]:
            health_tone = "danger" if summary.get("failed_docs", 0) else "warn"
        health_chip = build_status_chip(self.context_frame, self._corpus_health_label(summary), self.palette, tone=health_tone)
        health_chip.pack(anchor=W, pady=(0, 12))
        for model in (
            MetricCardModel("Documents", str(summary["documents"]), "primary", "Tracked in the current workspace."),
            MetricCardModel("Open Review", str(summary["open_reviews"]), "warn" if summary["open_reviews"] else "success", "Items still blocking a clean export."),
            MetricCardModel("Exports", str(summary["exports"]), "success", "Completed export runs for this project."),
        ):
            build_metric_card(metric_row, model, self.palette)

        actions_panel = ttk.Frame(self.context_frame, style="PanelAlt.TFrame", padding=14)
        actions_panel.pack(fill=X, pady=(0, 14))
        ttk.Label(actions_panel, text="What To Do Next", style="Section.TLabel").pack(anchor=W)
        for note in self._build_next_actions(summary):
            ttk.Label(actions_panel, text=f"- {note}", style="Caption.TLabel", wraplength=260, justify=LEFT).pack(anchor=W, pady=(6, 0))

        status_panel = ttk.Frame(self.context_frame, style="PanelAlt.TFrame", padding=14)
        status_panel.pack(fill=BOTH, expand=True)
        ttk.Label(status_panel, text="Recent Activity", style="Section.TLabel").pack(anchor=W)
        notes = self._context_notes or ["Recent scan, review, and export notes will appear here."]
        for line in notes[-8:]:
            ttk.Label(status_panel, text=line, style="Caption.TLabel", wraplength=260, justify=LEFT).pack(anchor=W, pady=(6, 0))

    def _render_home_view(self) -> None:
        summary = self._current_workspace_summary()
        next_label, next_action, next_detail = self._smart_next_step_descriptor(summary)
        if self._guided_mode_active():
            self._render_beginner_home_view(summary, next_label, next_action, next_detail)
            return

        self._render_workflow_guide(self.content_frame, focus_step="sources")

        hero = ttk.Frame(self.content_frame, style="Panel.TFrame")
        hero.pack(fill=X, pady=(16, 0))
        hero_left = ttk.Frame(hero, style="Panel.TFrame", padding=18)
        hero_left.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Label(hero_left, text="Create knowledge packs that feel production-ready.", style="Heading.TLabel").pack(anchor=W)
        ttk.Label(
            hero_left,
            text=(
                "This workspace turns raw document corpora into reviewable, provenance-backed Custom GPT packages "
                "with a cleaner pipeline and a stronger desktop workflow."
            ),
            style="Muted.TLabel",
            wraplength=680,
            justify=LEFT,
        ).pack(anchor=W, pady=(8, 14))
        ctas = ttk.Frame(hero_left, style="Panel.TFrame")
        ctas.pack(anchor=W)
        self.home_primary_button = ttk.Button(ctas, text=next_label, style="Primary.TButton", command=next_action)
        self.home_primary_button.pack(side=LEFT)
        self.home_guided_button = ttk.Button(ctas, text="Start Guided Setup", style="Ghost.TButton", command=self.on_start_guided_setup)
        self.home_guided_button.pack(side=LEFT, padx=(10, 0))
        ttk.Button(ctas, text="Open Existing Project", style="Ghost.TButton", command=self.on_open_project).pack(side=LEFT, padx=(10, 0))
        ttk.Label(hero_left, text=next_detail, style="Caption.TLabel", wraplength=760, justify=LEFT).pack(anchor=W, pady=(10, 0))

        hero_right = ttk.Frame(hero, style="PanelAlt.TFrame", padding=18)
        hero_right.pack(side=RIGHT, fill=BOTH, expand=False, padx=(16, 0))
        ttk.Label(hero_right, text="Workspace Snapshot", style="Section.TLabel").pack(anchor=W)
        ttk.Label(hero_right, textvariable=self.home_summary_var, style="Muted.TLabel", wraplength=280, justify=LEFT).pack(anchor=W, pady=(8, 0))
        self._render_recent_projects(hero_right)

        metrics = ttk.Frame(self.content_frame, style="Panel.TFrame")
        metrics.pack(fill=X, pady=(18, 0))
        for model in (
            MetricCardModel("Source Roots", str(summary["source_roots"]), "primary", "Configured input locations."),
            MetricCardModel("Knowledge Items", str(summary["knowledge_items"]), "success", "Accepted items tracked across the corpus."),
            MetricCardModel("Latest Validation", str(summary["validation_count"]), "warn" if summary["validation_count"] else "success", "Issues found in the latest export."),
        ):
            build_metric_card(metrics, model, self.palette)

        next_card = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=16)
        next_card.pack(fill=X, pady=(18, 0))
        ttk.Label(next_card, text="What To Do Next", style="Section.TLabel").pack(anchor=W)
        build_status_chip(next_card, next_label, self.palette, tone="primary").pack(anchor=W, pady=(8, 0))
        ttk.Label(next_card, text=next_detail, style="Muted.TLabel", wraplength=900, justify=LEFT).pack(anchor=W, pady=(8, 0))

        cards = ttk.Frame(self.content_frame, style="Panel.TFrame")
        cards.pack(fill=BOTH, expand=True, pady=(18, 0))
        for title, body in (
            ("Smart Start", "Begin with sane defaults: mixed office documents, balanced export profile, AI off until you add a key."),
            ("Review-Ready", "Low-confidence OCR, duplicates, and weak taxonomy signals surface before export instead of after."),
            ("Clean Delivery", "Export produces upload-ready package files with provenance sidecars kept separate from the GPT payload."),
        ):
            card = ttk.Frame(cards, style="PanelAlt.TFrame", padding=16)
            card.pack(fill=X, pady=(0, 10))
            ttk.Label(card, text=title, style="Section.TLabel").pack(anchor=W)
            ttk.Label(card, text=body, style="Muted.TLabel", wraplength=860, justify=LEFT).pack(anchor=W, pady=(6, 0))

    def _render_recent_projects(self, parent, heading: bool = True) -> None:
        panel = ttk.Frame(parent, style="PanelAlt.TFrame")
        panel.pack(fill=X, pady=(16, 0))
        if heading:
            ttk.Label(panel, text="Recent Projects", style="Section.TLabel").pack(anchor=W)
        recent = self._recent_projects_display()
        if not recent:
            ttk.Label(panel, text="No recent projects recorded yet.", style="Caption.TLabel", wraplength=280, justify=LEFT).pack(anchor=W, pady=(8, 0))
            return
        for item in recent[:4]:
            row = ttk.Frame(panel, style="PanelAlt.TFrame")
            row.pack(fill=X, pady=(8, 0))
            label = f"{item['project_name']} | {self._format_recent_timestamp(item['last_opened'])}"
            ttk.Button(
                row,
                text=label,
                style="Ghost.TButton",
                command=lambda value=item["project_dir"]: self.on_open_recent_project(value),
            ).pack(side=LEFT)
            status_tone = "success" if item["exists"] else "danger"
            build_status_chip(row, "available" if item["exists"] else "missing", self.palette, tone=status_tone).pack(side=LEFT, padx=(8, 0))

    def _render_sources_view(self) -> None:
        self._render_workflow_guide(self.content_frame, focus_step="sources")
        self._render_transition_notice(self.content_frame, "sources")
        self._render_advanced_controls_toggle(self.content_frame, "Setup")
        if self._guided_mode_active():
            self._render_beginner_sources_view()
            return
        form = ttk.Frame(self.content_frame, style="Panel.TFrame")
        form.pack(fill=BOTH, expand=True, pady=(16, 0))
        self._render_screen_tip(
            form,
            "sources",
            "Setup Walkthrough",
            [
                "Point the app at your project, source, and output folders.",
                "Use the source preview to estimate workload and trim folders you do not want scanned.",
                "Save settings, then continue to Scan to build the working corpus.",
            ],
        )
        guide = ttk.Frame(form, style="PanelAlt.TFrame", padding=16)
        guide.pack(fill=X, pady=(0, 14))
        ttk.Label(guide, text="Step 1: Configure the workspace", style="Section.TLabel").pack(anchor=W)
        for line in (
            "Choose the project folder, source folder, and output folder.",
            "Pick the preset that best matches the document mix you expect.",
            "Save settings, then continue to Scan to build the working corpus.",
        ):
            ttk.Label(guide, text=f"- {line}", style="Caption.TLabel", wraplength=900, justify=LEFT).pack(anchor=W, pady=(6, 0))
        mode_note = ttk.Frame(form, style="PanelAlt.TFrame", padding=12)
        mode_note.pack(fill=X, pady=(0, 14))
        if self._advanced_controls_visible():
            build_status_chip(mode_note, "Advanced Mode", self.palette, tone="warn").pack(side=LEFT)
            ttk.Label(mode_note, text="Advanced controls are visible across setup, review, diagnostics, and export.", style="Caption.TLabel", wraplength=760, justify=LEFT).pack(side=LEFT, padx=(10, 0))
        else:
            build_status_chip(mode_note, "Beginner Mode", self.palette, tone="primary").pack(side=LEFT)
            ttk.Label(mode_note, text="The app keeps the workflow simpler by default. Switch to Advanced when you want deeper retry, diagnostics, and tuning controls.", style="Caption.TLabel", wraplength=760, justify=LEFT).pack(side=LEFT, padx=(10, 0))
        if self._is_setup_complete():
            self.setup_completion_var.set(self._setup_completion_text())
            self._render_step_complete_panel(form, "Step Complete: Setup", self.setup_completion_var.get(), "Continue To Scan", lambda: self._set_active_view("processing"))
        else:
            self.setup_completion_var.set(self._setup_completion_text())
        beginner_simple = self.workflow_mode.get() != "advanced" and not self.show_advanced_controls.get()
        self._render_drop_zone(form)
        if beginner_simple:
            simple = ttk.Frame(form, style="PanelAlt.TFrame", padding=18)
            simple.pack(fill=X, pady=(0, 18))
            ttk.Label(simple, text="Simple Setup", style="Section.TLabel").pack(anchor=W)
            ttk.Label(
                simple,
                text="Pick one folder or many folders to scan and one output folder for the finished GPT files. The app creates its internal project data automatically, so you do not need to manage a project folder.",
                style="Muted.TLabel",
                wraplength=960,
                justify=LEFT,
            ).pack(anchor=W, pady=(8, 12))
            self._render_simple_source_roots_picker(simple)
            self._build_inline_folder_picker(simple, "Output Folder", self.output_dir, self._browse_output_dir)
            ttk.Label(simple, text=self._simple_setup_hint_text(), style="Caption.TLabel", wraplength=960, justify=LEFT).pack(anchor=W, pady=(8, 0))
            default_row = ttk.Frame(simple, style="PanelAlt.TFrame")
            default_row.pack(fill=X, pady=(10, 0))
            build_status_chip(default_row, self.preset.get(), self.palette, tone="primary").pack(side=LEFT)
            build_status_chip(default_row, self.export_profile.get(), self.palette, tone="success").pack(side=LEFT, padx=(8, 0))
            build_status_chip(default_row, "AI off by default", self.palette, tone="muted").pack(side=LEFT, padx=(8, 0))
            actions = ttk.Frame(simple, style="PanelAlt.TFrame")
            actions.pack(fill=X, pady=(12, 0))
            ttk.Button(actions, text="Scan These Folders", style="Primary.TButton", command=self.on_simple_setup_and_scan).pack(side=LEFT)
            ttk.Button(actions, text="Save These Folders", style="Ghost.TButton", command=self.on_simple_setup).pack(side=LEFT, padx=(10, 0))
            ttk.Button(actions, text="Open Existing Project", style="Ghost.TButton", command=self.on_open_project).pack(side=LEFT, padx=(10, 0))
        else:
            top = ttk.Frame(form, style="Panel.TFrame")
            top.pack(fill=X)
            self._build_field_card(top, "Project Folder", self.project_dir, self._browse_project_dir)
            self._build_field_card(top, "Source Folder", self.source_dir, self._browse_source_dir)
            self._build_field_card(top, "Output Folder", self.output_dir, self._browse_output_dir)

            settings = ttk.Frame(form, style="Panel.TFrame")
            settings.pack(fill=X, pady=(18, 0))

            left = ttk.Frame(settings, style="PanelAlt.TFrame", padding=18)
            left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
            detail_header = ttk.Frame(left, style="PanelAlt.TFrame")
            detail_header.pack(fill=X)
            ttk.Label(detail_header, text="Project Details", style="Section.TLabel").pack(side=LEFT, anchor=W)
            build_info_button(detail_header, "Project name labels the workspace. Preset tunes extraction and review behavior. Export profile controls how package files are shaped.", self.palette).pack(side=LEFT, padx=(8, 0))
            self._labeled_entry(left, "Project Name", self.project_name)
            self._labeled_combo(left, "Preset", self.preset, [
                "business-sops",
                "product-docs",
                "policies-contracts",
                "course-training",
                "mixed-office-documents",
            ], help_text="Presets bias the workflow for different document mixes, review thresholds, and synthesis choices.")
            self._labeled_combo(left, "Export Profile", self.export_profile, [
                "custom-gpt-balanced",
                "custom-gpt-max-traceability",
                "debug-research",
            ], help_text="Balanced is the default GPT upload package. Max traceability keeps more evidence. Debug research favors inspection over compact delivery.")

            right = ttk.Frame(settings, style="PanelAlt.TFrame", padding=18)
            right.pack(side=LEFT, fill=BOTH, expand=True)
            ai_header = ttk.Frame(right, style="PanelAlt.TFrame")
            ai_header.pack(fill=X)
            ttk.Label(ai_header, text="AI Settings", style="Section.TLabel").pack(side=LEFT, anchor=W)
            build_info_button(ai_header, "AI enrichment is optional. It can help with title cleanup, taxonomy suggestions, and synthesis, but deterministic extraction still works without it.", self.palette).pack(side=LEFT, padx=(8, 0))
            ttk.Checkbutton(right, text="Enable model-assisted enrichment", variable=self.model_enabled).pack(anchor=W, pady=(8, 10))
            self._labeled_entry(right, "Model", self.model_name)
            self._labeled_entry(right, "API Key", self.api_key_value, show="*")
            ttk.Checkbutton(right, text="Save API key in local project secrets", variable=self.save_api_key).pack(anchor=W, pady=(8, 0))
            ttk.Label(
                right,
                text="Saved locally per project." if self.save_api_key.get() else "Environment variable fallback supported.",
                style="Caption.TLabel",
            ).pack(anchor=W, pady=(8, 0))

            actions = ttk.Frame(form, style="Panel.TFrame")
            actions.pack(fill=X, pady=(18, 0))
            ttk.Button(actions, text="Create Project", style="Primary.TButton", command=self.on_create_project).pack(side=LEFT)
            ttk.Button(actions, text="Open Project", style="Ghost.TButton", command=self.on_open_project).pack(side=LEFT, padx=(10, 0))
            ttk.Button(actions, text="Save And Continue To Scan", style="Ghost.TButton", command=self.on_save_and_go_to_scan).pack(side=LEFT, padx=(10, 0))
            if self._advanced_controls_visible():
                ttk.Button(actions, text="Save AI Settings", style="Ghost.TButton", command=self.on_save_ai_settings).pack(side=LEFT, padx=(10, 0))
                ttk.Button(actions, text="Clear Saved Key", style="Ghost.TButton", command=self.on_clear_saved_key).pack(side=LEFT, padx=(10, 0))

        validation = ttk.Frame(form, style="PanelAlt.TFrame", padding=16)
        validation.pack(fill=X, pady=(18, 0))
        ttk.Label(validation, text="Setup Validation", style="Section.TLabel").pack(anchor=W)
        self.setup_validation_var.set(self._setup_validation_summary())
        ttk.Label(validation, textvariable=self.setup_validation_var, style="Muted.TLabel", wraplength=900, justify=LEFT).pack(anchor=W, pady=(8, 10))
        for line in self._setup_validation_lines():
            ttk.Label(validation, text=f"- {line}", style="Caption.TLabel", wraplength=900, justify=LEFT).pack(anchor=W, pady=(4, 0))

        preview = ttk.Frame(form, style="PanelAlt.TFrame", padding=16)
        preview.pack(fill=X, pady=(18, 0))
        preview_header = ttk.Frame(preview, style="PanelAlt.TFrame")
        preview_header.pack(fill=X)
        ttk.Label(preview_header, text="Source Folder Preview", style="Section.TLabel").pack(side=LEFT, anchor=W)
        build_info_button(preview_header, "This preview scans filenames and extensions only. It estimates workload and highlights likely unsupported files before you run the actual extraction pipeline.", self.palette).pack(side=LEFT, padx=(8, 0))
        self.source_preview_var.set(self._source_preview_summary())
        self.scan_forecast_var.set(self._scan_forecast_summary())
        ttk.Label(preview, textvariable=self.source_preview_var, style="Muted.TLabel", wraplength=900, justify=LEFT).pack(anchor=W, pady=(8, 10))
        build_status_chip(preview, self.scan_forecast_var.get(), self.palette, tone="primary").pack(anchor=W, pady=(0, 10))
        for line in self._source_preview_lines():
            ttk.Label(preview, text=f"- {line}", style="Caption.TLabel", wraplength=900, justify=LEFT).pack(anchor=W, pady=(4, 0))
        self._render_source_folder_controls(preview)

        dependency = ttk.Frame(form, style="PanelAlt.TFrame", padding=16)
        dependency.pack(fill=X, pady=(18, 0))
        dependency_header = ttk.Frame(dependency, style="PanelAlt.TFrame")
        dependency_header.pack(fill=X)
        ttk.Label(dependency_header, text="Dependency Health", style="Section.TLabel").pack(side=LEFT, anchor=W)
        build_info_button(dependency_header, "This checks whether optional extractors and OCR tools appear available on this machine. Missing tools do not block the app, but they can reduce extraction quality.", self.palette).pack(side=LEFT, padx=(8, 0))
        self.dependency_health_var.set(self._dependency_health_summary())
        ttk.Label(dependency, textvariable=self.dependency_health_var, style="Muted.TLabel", wraplength=900, justify=LEFT).pack(anchor=W, pady=(8, 10))
        if self._advanced_controls_visible():
            for line in self._dependency_health_lines():
                ttk.Label(dependency, text=f"- {line}", style="Caption.TLabel", wraplength=900, justify=LEFT).pack(anchor=W, pady=(4, 0))
        else:
            ttk.Label(dependency, text="Switch to Advanced to inspect the full dependency checklist and optional extractor details.", style="Caption.TLabel", wraplength=900, justify=LEFT).pack(anchor=W)

    def _render_processing_view(self) -> None:
        compact_processing = self._use_compact_shell_layout()
        summary_wrap = self._content_wraplength()
        project_dir = self._current_project_dir(optional=True)
        state = load_state(project_dir) if project_dir else {"last_scan_report": {}, "documents": {}}
        report = state.get("last_scan_report") or {}
        summary = self._current_workspace_summary()
        self._render_workflow_guide(self.content_frame, focus_step="processing")
        self._render_transition_notice(self.content_frame, "processing")
        self._render_advanced_controls_toggle(self.content_frame, "Scan")
        if self._guided_mode_active():
            self._render_beginner_processing_view(summary, report, compact_processing, summary_wrap)
            return
        self._render_screen_tip(
            self.content_frame,
            "processing",
            "Scan Walkthrough",
            [
                "Run the first scan to create the corpus snapshot.",
                "Use recent extraction issues and type distribution to decide whether to fix dependencies or go to Review.",
                "If the scan is clean, continue directly to Export.",
            ],
        )
        controls = ttk.Frame(self.content_frame, style="Panel.TFrame")
        controls.pack(fill=X, pady=(16, 0))
        scan_card = ttk.Frame(controls, style="PanelAlt.TFrame", padding=18)
        scan_card.pack(fill=X)
        ttk.Label(scan_card, text="2. Scan The Corpus", style="Section.TLabel").pack(anchor=W)
        ttk.Label(scan_card, textvariable=self.processing_summary_var, style="Muted.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        guidance = self._processing_guidance(summary, report)
        ttk.Label(scan_card, text=guidance, style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(10, 0))
        self.processing_recommendation_var.set(self._processing_recommendation(summary, report))
        decision_label, decision_tone, decision_detail = self._post_scan_decision(summary, report)
        self.processing_decision_title_var.set(decision_label)
        self.processing_decision_detail_var.set(decision_detail)
        recommendation_panel = ttk.Frame(scan_card, style="Panel.TFrame")
        recommendation_panel.pack(fill=X, pady=(12, 0))
        if compact_processing:
            build_status_chip(recommendation_panel, "Recommended Next Move", self.palette, tone="primary", wraplength=180).pack(anchor=W)
            ttk.Label(recommendation_panel, textvariable=self.processing_recommendation_var, style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        else:
            build_status_chip(recommendation_panel, "Recommended Next Move", self.palette, tone="primary").pack(side=LEFT)
            ttk.Label(recommendation_panel, textvariable=self.processing_recommendation_var, style="Caption.TLabel", wraplength=620, justify=LEFT).pack(side=LEFT, padx=(10, 0))
        phase_panel = ttk.Frame(scan_card, style="PanelAlt.TFrame", padding=14)
        phase_panel.pack(fill=X, pady=(12, 0))
        build_status_chip(phase_panel, self.operation_phase_var.get(), self.palette, tone="warn").pack(anchor=W)
        ttk.Label(phase_panel, textvariable=self.operation_detail_var, style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        decision_panel = ttk.Frame(scan_card, style="PanelAlt.TFrame", padding=14)
        decision_panel.pack(fill=X, pady=(12, 0))
        build_status_chip(decision_panel, self.processing_decision_title_var.get(), self.palette, tone=decision_tone).pack(anchor=W)
        ttk.Label(decision_panel, textvariable=self.processing_decision_detail_var, style="Muted.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        next_actions = ttk.Frame(decision_panel, style="PanelAlt.TFrame")
        next_actions.pack(fill=X, pady=(10, 0))
        if compact_processing:
            next_actions.columnconfigure(0, weight=1)
            next_actions.columnconfigure(1, weight=1)
            ttk.Button(next_actions, text=self._processing_continue_label(summary), style="Primary.TButton", command=self.on_continue_from_processing).grid(row=0, column=0, sticky="ew", padx=(0, 8))
            ttk.Button(next_actions, text="Open Diagnostics", style="Ghost.TButton", command=self.on_go_to_diagnostics).grid(row=0, column=1, sticky="ew")
        else:
            ttk.Button(next_actions, text=self._processing_continue_label(summary), style="Primary.TButton", command=self.on_continue_from_processing).pack(side=LEFT)
            ttk.Button(next_actions, text="Open Diagnostics", style="Ghost.TButton", command=self.on_go_to_diagnostics).pack(side=LEFT, padx=(10, 0))
        self.scan_completion_var.set(self._scan_completion_text(summary, report))
        if summary.get("documents", 0):
            self._render_step_complete_panel(
                scan_card,
                "Step Complete: Scan",
                self.scan_completion_var.get(),
                self._processing_continue_label(summary),
                self.on_continue_from_processing,
                tone="warn" if report.get("failed", 0) or report.get("partial", 0) or report.get("review_required", 0) else "success",
            )
        control_row = ttk.Frame(scan_card, style="PanelAlt.TFrame")
        control_row.pack(fill=X, pady=(14, 0))
        if compact_processing:
            for column in range(2):
                control_row.columnconfigure(column, weight=1)
            ttk.Checkbutton(control_row, text="Force reprocess unchanged files", variable=self.force_scan).grid(row=0, column=0, columnspan=2, sticky=W, pady=(0, 10))
            action_specs = [
                ("Scan Project", "Primary.TButton", self.on_scan),
                ("Review Issues", "Ghost.TButton", lambda: self._set_active_view("review")),
                ("Rescan Failed", "Ghost.TButton", self.on_rescan_failed),
                ("Export Diagnostics", "Ghost.TButton", self.on_export_diagnostics),
                (self._processing_continue_label(summary), "Ghost.TButton", self.on_continue_from_processing),
            ]
            for index, (label, style, command) in enumerate(action_specs):
                ttk.Button(control_row, text=label, style=style, command=command).grid(
                    row=1 + (index // 2),
                    column=index % 2,
                    sticky="ew",
                    padx=(0, 8) if index % 2 == 0 else (0, 0),
                    pady=(0, 8),
                )
        else:
            ttk.Checkbutton(control_row, text="Force reprocess unchanged files", variable=self.force_scan).pack(side=LEFT)
            ttk.Button(control_row, text="Scan Project", style="Primary.TButton", command=self.on_scan).pack(side=LEFT, padx=(12, 0))
            ttk.Button(control_row, text="Review Issues", style="Ghost.TButton", command=lambda: self._set_active_view("review")).pack(side=LEFT, padx=(10, 0))
            ttk.Button(control_row, text="Rescan Failed", style="Ghost.TButton", command=self.on_rescan_failed).pack(side=LEFT, padx=(10, 0))
            ttk.Button(control_row, text="Export Diagnostics", style="Ghost.TButton", command=self.on_export_diagnostics).pack(side=LEFT, padx=(10, 0))
            ttk.Button(control_row, text=self._processing_continue_label(summary), style="Ghost.TButton", command=self.on_continue_from_processing).pack(side=LEFT, padx=(10, 0))

        metrics = ttk.Frame(self.content_frame, style="Panel.TFrame")
        metrics.pack(fill=X, pady=(18, 0))
        for model in (
            MetricCardModel("Processed", str(report.get("processed", 0)), "primary", "Documents attempted in the latest scan."),
            MetricCardModel("Partial", str(report.get("partial", 0)), "warn" if report.get("partial", 0) else "success", "Documents with degraded extraction."),
            MetricCardModel("Failed", str(report.get("failed", 0)), "danger" if report.get("failed", 0) else "success", "Documents that failed extraction."),
            MetricCardModel("Review Needed", str(summary["open_reviews"]), "warn" if summary["open_reviews"] else "success", "Issues blocking clean export."),
        ):
            build_metric_card(metrics, model, self.palette)

        lower = ttk.Frame(self.content_frame, style="Panel.TFrame")
        lower.pack(fill=BOTH, expand=True, pady=(18, 0))
        left = ttk.Frame(lower, style="PanelAlt.TFrame", padding=18)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 0 if compact_processing else 10), pady=(0, 10 if compact_processing else 0))
        right = ttk.Frame(lower, style="PanelAlt.TFrame", padding=18)
        right.grid(row=1 if compact_processing else 0, column=0 if compact_processing else 1, sticky="nsew")
        self.processing_issue_frame = left
        self.processing_detail_frame = right
        lower.columnconfigure(0, weight=1)
        lower.columnconfigure(1, weight=1 if not compact_processing else 0)
        lower.rowconfigure(0, weight=1)
        lower.rowconfigure(1, weight=1 if compact_processing else 0)

        ttk.Label(left, text="Recent Extraction Issues", style="Section.TLabel").pack(anchor=W)
        issue_lines = [
            f"[{item.get('status')}] {Path(item.get('source_path', '')).name} :: {item.get('reason')}"
            for item in report.get("recent_issues", [])
        ] or ["No degraded documents in the latest scan."]
        self.processing_issue_log = ScrolledText(left, height=12)
        style_scrolled_text(self.processing_issue_log, self.palette, self.type_scale)
        self.processing_issue_log.pack(fill=BOTH, expand=True, pady=(10, 0))
        self._populate_text_widget(self.processing_issue_log, issue_lines)

        top_right = ttk.Frame(right, style="PanelAlt.TFrame")
        top_right.pack(fill=BOTH, expand=True)
        ttk.Label(top_right, text="Document Type Distribution", style="Section.TLabel").pack(anchor=W)
        type_lines = [
            f"{doc_type}: {count}"
            for doc_type, count in sorted((report.get("document_types") or {}).items())
        ] or ["No scan report yet."]
        self.processing_type_log = ScrolledText(top_right, height=7)
        style_scrolled_text(self.processing_type_log, self.palette, self.type_scale)
        self.processing_type_log.pack(fill=BOTH, expand=True, pady=(10, 14))
        self._populate_text_widget(self.processing_type_log, type_lines)

        ttk.Label(top_right, text="Processing Timeline", style="Section.TLabel").pack(anchor=W)
        self.process_log = ScrolledText(top_right, height=8)
        style_scrolled_text(self.process_log, self.palette, self.type_scale)
        self.process_log.pack(fill=BOTH, expand=True, pady=(10, 0))
        self._populate_text_widget(self.process_log, self._process_log_lines or ["No scan events yet."])

    def _render_review_view(self) -> None:
        compact_review = self._use_compact_shell_layout()
        summary_wrap = self._content_wraplength()
        detail_wrap = 320 if not compact_review else self._content_wraplength(760)
        beginner_session_only = self._guided_mode_active()
        self._render_workflow_guide(self.content_frame, focus_step="review")
        self._render_transition_notice(self.content_frame, "review")
        self._render_advanced_controls_toggle(self.content_frame, "Review")
        if not beginner_session_only:
            self._render_screen_tip(
                self.content_frame,
                "review",
                "Review Walkthrough",
                [
                    "Start with the highest-priority open issue in the queue.",
                    "Inspect the preview, adjust overrides if needed, then accept, ignore, or retry.",
                    "Use shortcuts to move faster once you trust the flow.",
                ],
            )
        summary_row = ttk.Frame(self.content_frame, style="Panel.TFrame")
        summary_row.pack(fill=X, pady=(16, 0))
        ttk.Label(summary_row, textvariable=self.review_summary_var, style="Muted.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W)
        ttk.Label(
            summary_row,
            text=self._review_guidance(self._current_workspace_summary()),
            style="Caption.TLabel",
            wraplength=summary_wrap,
            justify=LEFT,
        ).pack(anchor=W, pady=(8, 0))
        if not beginner_session_only:
            ttk.Label(
                summary_row,
                text="Shortcuts: Alt+A accept and next, Alt+I ignore and next, Alt+R retry and next, Alt+J next issue, Alt+K previous issue.",
                style="Caption.TLabel",
                wraplength=summary_wrap,
                justify=LEFT,
            ).pack(anchor=W, pady=(6, 0))
        self.review_progress_var.set(self._review_progress_text())
        progress_panel = ttk.Frame(summary_row, style="PanelAlt.TFrame", padding=12)
        progress_panel.pack(fill=X, pady=(10, 0))
        progress_panel.columnconfigure(0, weight=1)
        progress_panel.columnconfigure(1, weight=0)
        progress_chip = build_status_chip(progress_panel, "Easy Review" if beginner_session_only else "Guided Review", self.palette, tone="primary", wraplength=180)
        progress_chip.grid(row=0, column=0, sticky=W)
        ttk.Label(progress_panel, textvariable=self.review_progress_var, style="Caption.TLabel", wraplength=max(280, summary_wrap - 180), justify=LEFT).grid(
            row=1 if compact_review else 0,
            column=0,
            sticky=W,
            padx=(0 if compact_review else 10, 0),
            pady=(8 if compact_review else 0, 0),
        )
        ttk.Button(progress_panel, text="Take Recommended Step" if not beginner_session_only else "Help Me With The Next One", style="Ghost.TButton", command=self.on_take_next_step).grid(
            row=2 if compact_review else 0,
            column=0 if compact_review else 1,
            sticky="ew" if compact_review else "e",
            pady=(10 if compact_review else 0, 0),
        )
        if beginner_session_only:
            session_panel = ttk.Frame(summary_row, style="PanelAlt.TFrame", padding=14)
            session_panel.pack(fill=X, pady=(10, 0))
            build_status_chip(session_panel, "Review Session", self.palette, tone="primary").pack(anchor=W)
            ttk.Label(session_panel, textvariable=self.review_session_title_var, style="Section.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
            ttk.Label(session_panel, textvariable=self.review_session_detail_var, style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
            session_actions = ttk.Frame(session_panel, style="PanelAlt.TFrame")
            session_actions.pack(fill=X, pady=(10, 0))
            if compact_review:
                for column in range(2):
                    session_actions.columnconfigure(column, weight=1)
            else:
                for column in range(4):
                    session_actions.columnconfigure(column, weight=1)
            self.review_session_primary_button = ttk.Button(session_actions, text="Accept", style="Primary.TButton", command=self.on_mark_review_accepted_and_next)
            self.review_session_primary_button.grid(row=0, column=0, sticky="ew")
            ttk.Button(session_actions, text="Skip", style="Ghost.TButton", command=self.on_mark_review_rejected_and_next).grid(
                row=0 if not compact_review else 1,
                column=1 if not compact_review else 0,
                sticky="ew",
                padx=(0, 0 if compact_review else 10),
                pady=(8 if compact_review else 0, 0),
            )
            ttk.Button(session_actions, text="Retry", style="Ghost.TButton", command=self.on_retry_selected_review_and_next).grid(
                row=1 if compact_review else 0,
                column=0 if compact_review else 2,
                sticky="ew",
                pady=(8 if compact_review else 0, 0),
            )
            ttk.Button(session_actions, text="Next", style="Ghost.TButton", command=self.on_next_review_item).grid(
                row=1 if compact_review else 0,
                column=1 if compact_review else 3,
                sticky="ew",
                padx=(0 if compact_review else 10, 0),
                pady=(8 if compact_review else 0, 0),
            )
        if self._current_workspace_summary().get("open_reviews", 0) == 0:
            self.review_completion_var.set("The review queue is clear. Continue to Export unless you want a final diagnostics check.")
            self._render_step_complete_panel(summary_row, "Step Complete: Review", self.review_completion_var.get(), "Continue To Export", lambda: self._set_active_view("export"))

        filter_row = ttk.Frame(self.content_frame, style="Panel.TFrame")
        filter_row.pack(fill=X, pady=(14, 14))
        queue_controls = ttk.Frame(filter_row, style="Panel.TFrame")
        queue_controls.pack(fill=X)
        ttk.Label(queue_controls, text="Queue Mode", style="Caption.TLabel").pack(side=LEFT, padx=(0, 6))
        if self._advanced_controls_visible():
            ttk.Button(
                queue_controls,
                text="Inbox" if self.review_queue_mode.get() != "inbox" else "Inbox Active",
                style="Primary.TButton" if self.review_queue_mode.get() == "inbox" else "Ghost.TButton",
                command=lambda: self._set_review_queue_mode("inbox"),
            ).pack(side=LEFT, padx=(0, 10))
            ttk.Button(
                queue_controls,
                text="Table" if self.review_queue_mode.get() != "table" else "Table Active",
                style="Primary.TButton" if self.review_queue_mode.get() == "table" else "Ghost.TButton",
                command=lambda: self._set_review_queue_mode("table"),
            ).pack(side=LEFT, padx=(0, 14))
        else:
            build_status_chip(queue_controls, "Beginner Inbox", self.palette, tone="primary", wraplength=140).pack(side=LEFT, padx=(0, 10))
            ttk.Label(queue_controls, text="You are in the simple one-issue-at-a-time review view.", style="Caption.TLabel", wraplength=420 if not compact_review else summary_wrap, justify=LEFT).pack(side=LEFT, padx=(0, 14))
            ttk.Button(queue_controls, text="Switch To Advanced", style="Ghost.TButton", command=lambda: self._set_workflow_mode("advanced")).pack(side=LEFT, padx=(0, 14))
        filter_labels = ("All", "Open", "Extraction Issues", "Duplicates", "Taxonomy", "Low Confidence OCR", "Low Signal", "AI Low Confidence") if self.review_queue_mode.get() == "table" else ("Open", "Extraction Issues", "Duplicates", "All")
        filter_buttons = ttk.Frame(filter_row, style="Panel.TFrame")
        filter_buttons.pack(fill=X, pady=(10, 0))
        filter_columns = 2 if compact_review else 4
        for column in range(filter_columns):
            filter_buttons.columnconfigure(column, weight=1)
        for index, label in enumerate(filter_labels):
            style = "Primary.TButton" if self.review_filter.get() == label else "Ghost.TButton"
            ttk.Button(filter_buttons, text=label, style=style, command=lambda value=label: self._set_review_filter(value)).grid(
                row=index // filter_columns,
                column=index % filter_columns,
                sticky="ew",
                padx=(0, self.spacing.sm) if index % filter_columns < filter_columns - 1 else (0, 0),
                pady=(0, self.spacing.sm),
            )

        if self.review_queue_mode.get() == "table" and self._advanced_controls_visible():
            bulk_row = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=12)
            bulk_row.pack(fill=X, pady=(0, 14))
            bulk_header = ttk.Frame(bulk_row, style="PanelAlt.TFrame")
            bulk_header.pack(fill=X)
            ttk.Label(bulk_header, text="Bulk Retry", style="Section.TLabel").pack(side=LEFT)
            build_info_button(bulk_header, "Retry strategies let you rerun weak or failed extractions with alternate parsers. Use raw for malformed JSON/XML/HTML and parser-specific modes for PDFs.", self.palette).pack(side=LEFT, padx=(8, 12))
            bulk_fields = ttk.Frame(bulk_row, style="PanelAlt.TFrame")
            bulk_fields.pack(fill=X, pady=(10, 0))
            field_columns = 2 if compact_review else 4
            for column in range(field_columns):
                bulk_fields.columnconfigure(column, weight=1)
            bulk_specs = [
                ("Kind", lambda parent: ttk.Combobox(parent, textvariable=self.bulk_retry_kind, values=["extraction_issue", "ocr", "low_signal", "all"], state="readonly", width=18)),
                ("Doc Type", lambda parent: ttk.Combobox(parent, textvariable=self.bulk_retry_doc_type, values=self._bulk_retry_doc_type_values(), state="readonly", width=14)),
                ("Extraction", lambda parent: ttk.Combobox(parent, textvariable=self.bulk_retry_extraction_status, values=["all", "failed", "partial", "metadata_only", "unsupported"], state="readonly", width=14)),
                ("Strategy", lambda parent: ttk.Combobox(parent, textvariable=self.bulk_retry_strategy, values=["default", "raw", "pymupdf_only", "pdfplumber_only", "pypdf_only"], state="readonly", width=16)),
            ]
            for index, (label, factory) in enumerate(bulk_specs):
                field = ttk.Frame(bulk_fields, style="PanelAlt.TFrame")
                field.grid(
                    row=index // field_columns,
                    column=index % field_columns,
                    sticky="ew",
                    padx=(0, self.spacing.lg) if index % field_columns < field_columns - 1 else (0, 0),
                    pady=(0, self.spacing.sm),
                )
                ttk.Label(field, text=label, style="Caption.TLabel").pack(anchor=W)
                widget = factory(field)
                widget.pack(fill=X, pady=(4, 0))
                if label == "Doc Type":
                    self.bulk_retry_doc_type_combo = widget
                elif label == "Extraction":
                    self.bulk_retry_status_combo = widget
                elif label == "Strategy":
                    self.bulk_retry_strategy_combo = widget
            bulk_actions = ttk.Frame(bulk_row, style="PanelAlt.TFrame")
            bulk_actions.pack(fill=X, pady=(6, 0))
            ttk.Button(bulk_actions, text="Retry Matching", style="Ghost.TButton", command=self.on_retry_filtered_reviews).pack(side=RIGHT if not compact_review else LEFT)
        else:
            simple_row = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=12)
            simple_row.pack(fill=X, pady=(0, 14))
            ttk.Label(simple_row, text="One Issue At A Time", style="Section.TLabel").pack(anchor=W)
            ttk.Label(simple_row, text="Use Accept, Skip, Retry, or Next. Switch to Advanced only when you need bulk retry or deeper controls.", style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
            if self._advanced_controls_visible():
                ttk.Button(simple_row, text="Switch To Advanced Table", style="Ghost.TButton", command=lambda: self._set_review_queue_mode("table")).pack(anchor=W, pady=(10, 0))

        chips_row = ttk.Frame(self.content_frame, style="Panel.TFrame")
        chips_row.pack(fill=X, pady=(0, 14))
        review_counts = self._review_counts()
        for text, tone in (
            (f"Open {review_counts['open']}", "warn"),
            (f"Accepted {review_counts['accepted']}", "success"),
            (f"Rejected {review_counts['rejected']}", "danger"),
        ):
            chip = build_status_chip(chips_row, text, self.palette, tone=tone)
            chip.pack(side=LEFT, padx=(0, 8))

        split = ttk.Frame(self.content_frame, style="Panel.TFrame")
        split.pack(fill=BOTH, expand=True)
        left = ttk.Frame(split, style="PanelAlt.TFrame", padding=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 0 if compact_review else 10), pady=(0, 10 if compact_review else 0))
        right = ttk.Frame(split, style="PanelAlt.TFrame", padding=14)
        right.grid(row=1 if compact_review else 0, column=0 if compact_review else 1, sticky="nsew")
        self.review_queue_frame = left
        self.review_detail_frame = right
        split.columnconfigure(0, weight=1)
        split.columnconfigure(1, weight=0 if compact_review else 1)
        split.rowconfigure(0, weight=1)
        split.rowconfigure(1, weight=1 if compact_review else 0)

        tree_columns = ("status", "severity", "kind", "file") if self.review_queue_mode.get() == "table" else ("kind", "file")
        tree_height = 14 if self.review_queue_mode.get() == "table" else 8
        self.review_tree = ttk.Treeview(left, columns=tree_columns, show="headings", height=tree_height)
        column_defs = (("status", 90), ("severity", 90), ("kind", 170), ("file", 320)) if self.review_queue_mode.get() == "table" else (("kind", 170), ("file", 380))
        for heading, width in column_defs:
            self.review_tree.heading(heading, text=heading.title(), command=lambda value=heading: self._sort_review_by(value))
            self.review_tree.column(heading, width=width, anchor=W)
        self.review_tree.bind("<<TreeviewSelect>>", self._on_review_selected)
        self.review_tree.tag_configure("sev_high", background="#263246")
        self.review_tree.tag_configure("sev_medium", background="#23384a")
        self.review_tree.tag_configure("status_accepted", foreground=self.palette.success)
        self.review_tree.tag_configure("status_rejected", foreground=self.palette.danger)
        self.review_tree.tag_configure("kind_extraction", foreground=self.palette.warn)

        if beginner_session_only:
            session_left = ttk.Frame(left, style="PanelAlt.TFrame", padding=14)
            session_left.pack(fill=BOTH, expand=True)
            ttk.Label(session_left, text="One Issue At A Time", style="Section.TLabel").pack(anchor=W)
            ttk.Label(
                session_left,
                text="Focus on the current issue only. Read it, check the preview, then choose Accept, Skip, Retry, or Next.",
                style="Muted.TLabel",
                wraplength=detail_wrap,
                justify=LEFT,
            ).pack(anchor=W, pady=(8, 0))
            quick_help = ttk.Frame(session_left, style="PanelAlt.TFrame")
            quick_help.pack(fill=X, pady=(12, 0))
            for line in (
                "1. Read the issue summary.",
                "2. Check the preview on the right.",
                "3. Use Accept, Ignore, or Retry.",
                "4. Move to the next issue.",
            ):
                ttk.Label(quick_help, text=f"- {line}", style="Caption.TLabel", wraplength=detail_wrap, justify=LEFT).pack(anchor=W, pady=(4, 0))
            self.review_list = ScrolledText(session_left, height=14)
            style_scrolled_text(self.review_list, self.palette, self.type_scale)
            self.review_list.pack(fill=BOTH, expand=True, pady=(12, 0))
            self.review_history_log = None
        elif self.review_queue_mode.get() == "table":
            self.review_tree.pack(fill=BOTH, expand=True)
            review_log_frame = ttk.Frame(left, style="PanelAlt.TFrame")
            review_log_frame.pack(fill=BOTH, expand=True, pady=(12, 0))
            self.review_list = ScrolledText(review_log_frame, height=8)
            style_scrolled_text(self.review_list, self.palette, self.type_scale)
            self.review_list.pack(fill=BOTH, expand=True)
            history_frame = ttk.Frame(left, style="PanelAlt.TFrame")
            history_frame.pack(fill=BOTH, expand=True, pady=(12, 0))
            ttk.Label(history_frame, text="Recent Actions", style="Section.TLabel").pack(anchor=W)
            self.review_history_log = ScrolledText(history_frame, height=7)
            style_scrolled_text(self.review_history_log, self.palette, self.type_scale)
            self.review_history_log.pack(fill=BOTH, expand=True, pady=(10, 0))
        else:
            self.review_tree.pack(fill=BOTH, expand=True)
            inbox_frame = ttk.Frame(left, style="PanelAlt.TFrame", padding=12)
            inbox_frame.pack(fill=BOTH, expand=True, pady=(12, 0))
            ttk.Label(inbox_frame, text="Inbox Mode", style="Section.TLabel").pack(anchor=W)
            ttk.Label(
                inbox_frame,
                text="Focus on one issue at a time. Use Previous/Next or the keyboard shortcuts to move through the queue.",
                style="Muted.TLabel",
                wraplength=detail_wrap,
                justify=LEFT,
            ).pack(anchor=W, pady=(8, 0))
            self.review_list = ScrolledText(inbox_frame, height=10)
            style_scrolled_text(self.review_list, self.palette, self.type_scale)
            self.review_list.pack(fill=BOTH, expand=True, pady=(12, 0))

        issue_card = ttk.Frame(right, style="Panel.TFrame", padding=12)
        issue_card.grid(row=0, column=0, sticky="ew")
        ttk.Label(issue_card, text="Current Issue", style="Section.TLabel").pack(anchor=W)
        ttk.Label(issue_card, textvariable=self.review_issue_title_var, style="Heading.TLabel", wraplength=detail_wrap, justify=LEFT).pack(anchor=W, pady=(6, 0))
        ttk.Label(issue_card, textvariable=self.review_issue_reason_var, style="Muted.TLabel", wraplength=detail_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        ttk.Label(issue_card, textvariable=self.review_issue_action_var, style="Caption.TLabel", wraplength=detail_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        ttk.Label(right, text="Review Id", style="Caption.TLabel").grid(row=1, column=0, sticky=W, pady=(12, 4))
        ttk.Label(right, textvariable=self.selected_review_id, style="Caption.TLabel", wraplength=detail_wrap, justify=LEFT).grid(row=2, column=0, sticky=W, pady=(0, 8))
        ttk.Label(right, textvariable=self.review_meta_var, style="Muted.TLabel", wraplength=detail_wrap, justify=LEFT).grid(row=3, column=0, sticky=W)
        preview_row = 12
        if beginner_session_only:
            self.review_retry_combo = None
            self.review_status_edit.set(self.review_status_edit.get() or "accepted")
        else:
            self._grid_labeled_combo(right, 4, "Status", self.review_status_edit, ["open", "accepted", "rejected", "resolved"])
            self._grid_labeled_entry(right, 6, "Override title", self.review_title_edit)
            self._grid_labeled_entry(right, 8, "Override domain", self.review_domain_edit)
            self.review_retry_combo = self._grid_labeled_combo(right, 10, "Retry Strategy", self.review_retry_strategy, ["default"])
        if beginner_session_only:
            preview_row = 4
        preview_header = ttk.Frame(right, style="PanelAlt.TFrame")
        preview_header.grid(row=preview_row, column=0, sticky="ew", pady=(10, 4))
        if compact_review:
            ttk.Label(preview_header, textvariable=self.review_preview_label_var, style="Caption.TLabel").pack(anchor=W)
            preview_nav = ttk.Frame(preview_header, style="PanelAlt.TFrame")
            preview_nav.pack(fill=X, pady=(8, 0))
            preview_nav.columnconfigure(0, weight=1)
            preview_nav.columnconfigure(1, weight=1)
            ttk.Button(preview_nav, text="Previous", style="Ghost.TButton", command=self.on_prev_preview_unit).grid(row=0, column=0, sticky="ew", padx=(0, 8))
            ttk.Button(preview_nav, text="Next", style="Ghost.TButton", command=self.on_next_preview_unit).grid(row=0, column=1, sticky="ew")
        else:
            ttk.Label(preview_header, textvariable=self.review_preview_label_var, style="Caption.TLabel").pack(side=LEFT)
            ttk.Button(preview_header, text="Previous", style="Ghost.TButton", command=self.on_prev_preview_unit).pack(side=RIGHT)
            ttk.Button(preview_header, text="Next", style="Ghost.TButton", command=self.on_next_preview_unit).pack(side=RIGHT, padx=(0, 8))
        preview_stack = ttk.Frame(right, style="PanelAlt.TFrame")
        preview_stack.grid(row=preview_row + 1, column=0, sticky="nsew")
        preview_stack.columnconfigure(0, weight=1)
        preview_stack.rowconfigure(2, weight=1)
        self.review_thumbnail_strip = ttk.Frame(preview_stack, style="PanelAlt.TFrame")
        self.review_thumbnail_strip.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.review_preview_image_label = ttk.Label(preview_stack, style="Muted.TLabel")
        self.review_preview_image_label.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.review_preview_text = ScrolledText(preview_stack, height=12 if beginner_session_only else 8, width=36)
        style_scrolled_text(self.review_preview_text, self.palette, self.type_scale)
        self.review_preview_text.grid(row=2, column=0, sticky="nsew")
        self.review_duplicate_compare_frame = ttk.Frame(preview_stack, style="PanelAlt.TFrame", padding=8)
        self.review_duplicate_compare_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.review_duplicate_compare_frame.columnconfigure(0, weight=1)
        self.review_duplicate_compare_frame.columnconfigure(1, weight=1)
        ttk.Label(self.review_duplicate_compare_frame, text="Current Document", style="Caption.TLabel").grid(row=0, column=0, sticky=W, padx=(0, 8))
        ttk.Label(self.review_duplicate_compare_frame, text="Canonical Comparison", style="Caption.TLabel").grid(row=0, column=1, sticky=W)
        self.review_duplicate_current_text = ScrolledText(self.review_duplicate_compare_frame, height=6, width=22)
        style_scrolled_text(self.review_duplicate_current_text, self.palette, self.type_scale)
        self.review_duplicate_current_text.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(6, 0))
        self.review_duplicate_target_text = ScrolledText(self.review_duplicate_compare_frame, height=6, width=22)
        style_scrolled_text(self.review_duplicate_target_text, self.palette, self.type_scale)
        self.review_duplicate_target_text.grid(row=1, column=1, sticky="nsew", pady=(6, 0))
        self.review_duplicate_compare_frame.grid_remove()
        ttk.Label(right, text="Resolution note", style="Caption.TLabel").grid(row=preview_row + 2, column=0, sticky=W, pady=(10, 4))
        self.review_note_text = ScrolledText(right, height=11 if beginner_session_only else 9, width=36)
        style_scrolled_text(self.review_note_text, self.palette, self.type_scale)
        self.review_note_text.grid(row=preview_row + 3, column=0, sticky="nsew")
        actions = ttk.Frame(right, style="PanelAlt.TFrame")
        actions.grid(row=preview_row + 4, column=0, sticky="ew", pady=(12, 0))
        if beginner_session_only:
            action_specs = [
                ("Accept", "Primary.TButton", self.on_mark_review_accepted_and_next),
                ("Skip", "Ghost.TButton", self.on_mark_review_rejected_and_next),
                ("Retry", "Ghost.TButton", self.on_retry_selected_review_and_next),
                ("Next", "Ghost.TButton", self.on_next_review_item),
            ]
            action_columns = 2
        else:
            action_specs = [
                ("Apply Edit", "Primary.TButton", self.on_apply_review_edit),
                ("Accept", "Ghost.TButton", self.on_mark_review_accepted),
                ("Accept And Next", "Ghost.TButton", self.on_mark_review_accepted_and_next),
                ("Ignore", "Ghost.TButton", self.on_mark_review_rejected),
                ("Ignore And Next", "Ghost.TButton", self.on_mark_review_rejected_and_next),
                ("Keep This As Canonical", "Ghost.TButton", self.on_promote_duplicate_canonical),
                ("Retry Document", "Ghost.TButton", self.on_retry_selected_review),
                ("Retry And Next", "Ghost.TButton", self.on_retry_selected_review_and_next),
                ("Undo Last", "Ghost.TButton", self.on_undo_last_action),
                ("Approve All", "Ghost.TButton", self.on_approve_all),
            ]
            action_columns = 2 if compact_review else 3
        for column in range(action_columns):
            actions.columnconfigure(column, weight=1)
        for index, (label, style, command) in enumerate(action_specs):
            ttk.Button(actions, text=label, style=style, command=command).grid(
                row=index // action_columns,
                column=index % action_columns,
                sticky="ew",
                padx=(0, self.spacing.sm) if index % action_columns < action_columns - 1 else (0, 0),
                pady=(0, self.spacing.sm),
            )
        if not beginner_session_only:
            nav_actions = ttk.Frame(right, style="PanelAlt.TFrame")
            nav_actions.grid(row=preview_row + 5, column=0, sticky="ew", pady=(10, 0))
            nav_actions.columnconfigure(0, weight=1)
            nav_actions.columnconfigure(1, weight=1)
            ttk.Button(nav_actions, text="Previous Issue", style="Ghost.TButton", command=self.on_prev_review_item).grid(row=0, column=0, sticky="ew", padx=(0, 8))
            ttk.Button(nav_actions, text="Next Issue", style="Ghost.TButton", command=self.on_next_review_item).grid(row=0, column=1, sticky="ew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(preview_row + 1, weight=1)
        right.rowconfigure(preview_row + 3, weight=1)

        self._refresh_review_display(self._current_project_dir(optional=True))

    def _render_export_view(self) -> None:
        compact_export = self._use_compact_shell_layout()
        summary_wrap = self._content_wraplength()
        state = load_state(self._current_project_dir(optional=True)) if self.view_state.has_project else {"exports": [], "documents": {}}
        latest = (state.get("exports") or [])[-1] if state.get("exports") else None
        self._render_workflow_guide(self.content_frame, focus_step="export")
        self._render_transition_notice(self.content_frame, "export")
        self._render_advanced_controls_toggle(self.content_frame, "Export")
        if self._guided_mode_active():
            self._render_beginner_export_view(latest, compact_export, summary_wrap)
            return
        self._render_screen_tip(
            self.content_frame,
            "export",
            "Export Walkthrough",
            [
                "Check the readiness state and pre-export checklist before delivery.",
                "Run Validate if you want one more package-quality pass.",
                "After export, use the completion dialog to open the package, diagnostics, or provenance outputs.",
            ],
        )

        hero = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=18)
        hero.pack(fill=X, pady=(16, 0))
        readiness_label, readiness_tone, readiness_detail = self._export_readiness_state()
        self.export_readiness_var.set(readiness_label)
        self.export_readiness_detail_var.set(readiness_detail)
        ttk.Label(hero, text="Export Readiness", style="Section.TLabel").pack(anchor=W)
        build_status_chip(hero, self.export_readiness_var.get(), self.palette, tone=readiness_tone).pack(anchor=W, pady=(8, 0))
        ttk.Label(hero, textvariable=self.export_summary_var, style="Muted.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        ttk.Label(hero, textvariable=self.export_readiness_detail_var, style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        ttk.Label(hero, text=self._export_guidance(self._current_workspace_summary()), style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        phase_panel = ttk.Frame(hero, style="PanelAlt.TFrame", padding=14)
        phase_panel.pack(fill=X, pady=(12, 0))
        build_status_chip(phase_panel, self.operation_phase_var.get(), self.palette, tone="warn").pack(anchor=W)
        ttk.Label(phase_panel, textvariable=self.operation_detail_var, style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        actions = ttk.Frame(hero, style="PanelAlt.TFrame")
        actions.pack(fill=X, pady=(14, 0))
        export_actions = [
            ("Go To Diagnostics", "Ghost.TButton", self.on_go_to_diagnostics),
            ("Export Package", "Primary.TButton", self.on_export),
            ("Open Output Folder", "Ghost.TButton", self.on_open_output),
        ]
        if self._advanced_controls_visible():
            export_actions.extend(
                [
                    ("Validate Project", "Ghost.TButton", self.on_validate),
                    ("Export Diagnostics", "Ghost.TButton", self.on_export_diagnostics),
                    ("Open Diagnostics Folder", "Ghost.TButton", self.on_open_diagnostics_folder),
                ]
            )
        if compact_export:
            for column in range(2):
                actions.columnconfigure(column, weight=1)
            ttk.Checkbutton(actions, text="Create zip beside package", variable=self.zip_pack).grid(row=0, column=0, columnspan=2, sticky=W, pady=(0, 10))
            for index, (label, style, command) in enumerate(export_actions):
                ttk.Button(actions, text=label, style=style, command=command).grid(
                    row=1 + (index // 2),
                    column=index % 2,
                    sticky="ew",
                    padx=(0, 8) if index % 2 == 0 else (0, 0),
                    pady=(0, 8),
                )
        else:
            ttk.Checkbutton(actions, text="Create zip beside package", variable=self.zip_pack).pack(side=LEFT)
            for label, style, command in export_actions:
                ttk.Button(actions, text=label, style=style, command=command).pack(side=LEFT, padx=(10, 0))

        completion = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=16)
        completion.pack(fill=X, pady=(18, 0))
        ttk.Label(completion, text="Your GPT Files Are Ready", style="Section.TLabel").pack(anchor=W)
        ttk.Label(completion, textvariable=self.export_completion_var, style="Muted.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        ttk.Label(completion, textvariable=self.export_next_action_var, style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(8, 0))
        if latest:
            self._render_step_complete_panel(
                completion,
                "GPT Files Ready",
                self.export_completion_var.get(),
                "Open Output Folder",
                self.on_open_output,
            )
            ready_actions = ttk.Frame(completion, style="PanelAlt.TFrame")
            ready_actions.pack(fill=X, pady=(10, 0))
            if compact_export:
                for column in range(2):
                    ready_actions.columnconfigure(column, weight=1)
                ready_specs = [
                    ("Open Output Folder", "Primary.TButton", self.on_open_output),
                    ("Open Package Index", "Ghost.TButton", self.on_open_latest_package_index),
                    ("Open Provenance", "Ghost.TButton", self.on_open_latest_provenance_manifest),
                ]
                for index, (label, style, command) in enumerate(ready_specs):
                    ttk.Button(ready_actions, text=label, style=style, command=command).grid(
                        row=index // 2,
                        column=index % 2,
                        sticky="ew",
                        padx=(0, 8) if index % 2 == 0 else (0, 0),
                        pady=(0, 8),
                    )
            else:
                ttk.Button(ready_actions, text="Open Output Folder", style="Primary.TButton", command=self.on_open_output).pack(side=LEFT)
                ttk.Button(ready_actions, text="Open Package Index", style="Ghost.TButton", command=self.on_open_latest_package_index).pack(side=LEFT, padx=(10, 0))
                ttk.Button(ready_actions, text="Open Provenance", style="Ghost.TButton", command=self.on_open_latest_provenance_manifest).pack(side=LEFT, padx=(10, 0))

        checklist = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=16)
        checklist.pack(fill=X, pady=(18, 0))
        ttk.Label(checklist, text="Pre-Export Checklist", style="Section.TLabel").pack(anchor=W)
        for line in self._export_checklist_lines(latest):
            ttk.Label(checklist, text=f"- {line}", style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(4, 0))

        artifact_row = ttk.Frame(self.content_frame, style="Panel.TFrame")
        artifact_row.pack(fill=X, pady=(18, 0))
        for label, detail in self._build_export_cards(latest):
            build_metric_card(artifact_row, MetricCardModel(label, detail[0], detail[1], detail[2]), self.palette)

        lower = ttk.Frame(self.content_frame, style="Panel.TFrame")
        lower.pack(fill=BOTH, expand=True, pady=(18, 0))
        left = ttk.Frame(lower, style="PanelAlt.TFrame", padding=16)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 0 if compact_export else 10), pady=(0, 10 if compact_export else 0))
        right = ttk.Frame(lower, style="PanelAlt.TFrame", padding=16)
        right.grid(row=1 if compact_export else 0, column=0 if compact_export else 1, sticky="nsew")
        self.export_artifact_frame = left
        self.export_validation_frame = right
        lower.columnconfigure(0, weight=1)
        lower.columnconfigure(1, weight=1 if not compact_export else 0)
        lower.rowconfigure(0, weight=1)
        lower.rowconfigure(1, weight=1 if compact_export else 0)

        ttk.Label(left, text="Artifacts", style="Section.TLabel").pack(anchor=W)
        artifact_list = ScrolledText(left, height=18)
        style_scrolled_text(artifact_list, self.palette, self.type_scale)
        artifact_list.pack(fill=BOTH, expand=True, pady=(10, 0))
        self.export_artifact_list = artifact_list
        artifact_lines = [Path(path).name for path in (latest.get("written_files") or [])] if latest else ["No export artifacts yet."]
        self._populate_text_widget(artifact_list, artifact_lines)

        ttk.Label(right, text="Validation And Provenance", style="Section.TLabel").pack(anchor=W)
        self.export_log = ScrolledText(right, height=18)
        style_scrolled_text(self.export_log, self.palette, self.type_scale)
        self.export_log.pack(fill=BOTH, expand=True, pady=(10, 0))
        lines = self._export_log_lines.copy()
        if latest:
            lines.extend([f"Provenance: {latest.get('provenance_manifest', '')}"])
            lines.extend(latest.get("validation_messages") or ["No validation warnings in the latest export."])
        if not lines:
            lines = ["No export activity yet."]
        self._populate_text_widget(self.export_log, lines)
        self._apply_view_focus("export", "artifacts", self.export_artifact_list)
        self._apply_view_focus("export", "validation", self.export_log)

    def _render_diagnostics_view(self) -> None:
        payload = self._load_diagnostics_payload()
        if not payload:
            empty = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=20)
            empty.pack(fill=BOTH, expand=True)
            ttk.Label(empty, text="Diagnostics Not Generated Yet", style="Heading.TLabel").pack(anchor=W)
            ttk.Label(
                empty,
                text="Create a diagnostics report to inspect degraded documents, type distribution, and open review blockers.",
                style="Muted.TLabel",
                wraplength=860,
                justify=LEFT,
            ).pack(anchor=W, pady=(10, 16))
            ctas = ttk.Frame(empty, style="PanelAlt.TFrame")
            ctas.pack(anchor=W)
            ttk.Button(ctas, text="Export Diagnostics", style="Primary.TButton", command=self.on_export_diagnostics).pack(side=LEFT)
            ttk.Button(ctas, text="Open Diagnostics Folder", style="Ghost.TButton", command=self.on_open_diagnostics_folder).pack(side=LEFT, padx=(10, 0))
            self.diagnostics_summary_var.set("No diagnostics file found. Export diagnostics to populate this view.")
            return

        metrics = payload.get("corpus_metrics") or {}
        self.diagnostics_summary_var.set(
            f"Diagnostics loaded: documents={metrics.get('documents', 0)} partial={metrics.get('partial', 0)} "
            f"failed={metrics.get('failed', 0)} unsupported={metrics.get('unsupported', 0)}"
        )

        hero = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=18)
        hero.pack(fill=X)
        ttk.Label(hero, text="Diagnostics Summary", style="Section.TLabel").pack(anchor=W)
        ttk.Label(hero, textvariable=self.diagnostics_summary_var, style="Muted.TLabel", wraplength=860, justify=LEFT).pack(anchor=W, pady=(8, 0))
        controls = ttk.Frame(hero, style="PanelAlt.TFrame")
        controls.pack(fill=X, pady=(12, 0))
        ttk.Label(controls, text="Filter", style="Caption.TLabel").pack(side=LEFT)
        diagnostics_filter = ttk.Combobox(controls, textvariable=self.diagnostics_filter_var, values=["All", "Degraded", "Open Reviews"], state="readonly")
        diagnostics_filter.pack(side=LEFT, padx=(8, 12))
        diagnostics_filter.bind("<<ComboboxSelected>>", lambda _event: self._render_current_view())
        ttk.Button(controls, text="Refresh Diagnostics", style="Ghost.TButton", command=self.on_refresh_diagnostics).pack(side=LEFT)
        ttk.Button(controls, text="Export Diagnostics", style="Ghost.TButton", command=self.on_export_diagnostics).pack(side=LEFT, padx=(10, 0))
        ttk.Button(controls, text="Open Diagnostics Folder", style="Ghost.TButton", command=self.on_open_diagnostics_folder).pack(side=LEFT, padx=(10, 0))

        bulk_actions = ttk.Frame(hero, style="PanelAlt.TFrame")
        bulk_actions.pack(fill=X, pady=(12, 0))
        ttk.Label(bulk_actions, text="Bulk Actions", style="Caption.TLabel").pack(side=LEFT)
        ttk.Button(
            bulk_actions,
            text="Retry Failed All",
            style="Ghost.TButton",
            command=lambda: self._run_diagnostics_bulk_retry("all", "failed", "default"),
        ).pack(side=LEFT, padx=(12, 0))
        ttk.Button(
            bulk_actions,
            text="Retry Failed PDFs",
            style="Ghost.TButton",
            command=lambda: self._run_diagnostics_bulk_retry("pdf", "failed", "pypdf_only"),
        ).pack(side=LEFT, padx=(12, 0))
        ttk.Button(
            bulk_actions,
            text="Retry Partial JSON",
            style="Ghost.TButton",
            command=lambda: self._run_diagnostics_bulk_retry("json", "partial", "raw"),
        ).pack(side=LEFT, padx=(10, 0))
        ttk.Button(
            bulk_actions,
            text="Retry Partial XML",
            style="Ghost.TButton",
            command=lambda: self._run_diagnostics_bulk_retry("xml", "partial", "raw"),
        ).pack(side=LEFT, padx=(10, 0))
        ttk.Button(
            bulk_actions,
            text="Retry Partial HTML",
            style="Ghost.TButton",
            command=lambda: self._run_diagnostics_bulk_retry("html", "partial", "raw"),
        ).pack(side=LEFT, padx=(10, 0))
        folder_actions = self._diagnostics_folder_candidates(payload)
        if folder_actions:
            folder_row = ttk.Frame(hero, style="PanelAlt.TFrame")
            folder_row.pack(fill=X, pady=(12, 0))
            ttk.Label(folder_row, text="Folder Actions", style="Caption.TLabel").pack(side=LEFT)
            for folder in folder_actions[:3]:
                ttk.Button(
                    folder_row,
                    text=f"Exclude {folder['folder']} ({folder['count']})",
                    style="Ghost.TButton",
                    command=lambda name=folder["folder"]: self.on_exclude_folder_from_diagnostics(name),
                ).pack(side=LEFT, padx=(12, 0))

        metric_row = ttk.Frame(self.content_frame, style="Panel.TFrame")
        metric_row.pack(fill=X, pady=(18, 0))
        for model in (
            MetricCardModel("Documents", str(metrics.get("documents", 0)), "primary", "Tracked documents in workspace."),
            MetricCardModel("Partial", str(metrics.get("partial", 0)), "warn" if metrics.get("partial", 0) else "success", "Degraded but readable."),
            MetricCardModel("Failed", str(metrics.get("failed", 0)), "danger" if metrics.get("failed", 0) else "success", "Extraction failures."),
            MetricCardModel("Open Reviews", str(metrics.get("review_required", 0)), "warn" if metrics.get("review_required", 0) else "success", "Current blockers."),
        ):
            build_metric_card(metric_row, model, self.palette)

        lower = ttk.Frame(self.content_frame, style="Panel.TFrame")
        lower.pack(fill=BOTH, expand=True, pady=(18, 0))
        left = ttk.Frame(lower, style="PanelAlt.TFrame", padding=16)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        right = ttk.Frame(lower, style="PanelAlt.TFrame", padding=16)
        right.pack(side=LEFT, fill=BOTH, expand=True)

        ttk.Label(left, text="Degraded Documents", style="Section.TLabel").pack(anchor=W)
        self.diagnostics_issue_log = ScrolledText(left, height=18)
        style_scrolled_text(self.diagnostics_issue_log, self.palette, self.type_scale)
        self.diagnostics_issue_log.pack(fill=BOTH, expand=True, pady=(10, 0))
        self._populate_text_widget(self.diagnostics_issue_log, self._diagnostics_issue_lines(payload))

        ttk.Label(right, text="Open Review Items", style="Section.TLabel").pack(anchor=W)
        self.diagnostics_review_log = ScrolledText(right, height=18)
        style_scrolled_text(self.diagnostics_review_log, self.palette, self.type_scale)
        self.diagnostics_review_log.pack(fill=BOTH, expand=True, pady=(10, 0))
        self._populate_text_widget(self.diagnostics_review_log, self._diagnostics_review_lines(payload))
        self._apply_view_focus("diagnostics", "issues", self.diagnostics_issue_log)

    def _render_history_view(self) -> None:
        self._render_workflow_guide(self.content_frame, focus_step="processing")
        payload = self._load_diagnostics_payload()
        hero = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=18)
        hero.pack(fill=X, pady=(16, 0))
        ttk.Label(hero, text="Workspace Activity", style="Section.TLabel").pack(anchor=W)
        ttk.Label(
            hero,
            text="Inspect the timeline of scans, retries, review edits, duplicate decisions, and exports so the workflow stays transparent.",
            style="Muted.TLabel",
            wraplength=900,
            justify=LEFT,
        ).pack(anchor=W, pady=(8, 0))
        controls = ttk.Frame(hero, style="PanelAlt.TFrame")
        controls.pack(fill=X, pady=(12, 0))
        ttk.Button(controls, text="Refresh Activity", style="Ghost.TButton", command=self._refresh_shell).pack(side=LEFT)
        ttk.Button(controls, text="Go To Diagnostics", style="Ghost.TButton", command=self.on_go_to_diagnostics).pack(side=LEFT, padx=(10, 0))
        ttk.Button(controls, text="Open Selected Context", style="Ghost.TButton", command=self.on_open_selected_history_context).pack(side=LEFT, padx=(10, 0))
        if payload:
            folder_actions = self._diagnostics_folder_candidates(payload)
            if folder_actions:
                folder_row = ttk.Frame(hero, style="PanelAlt.TFrame")
                folder_row.pack(fill=X, pady=(12, 0))
                ttk.Label(folder_row, text="Folder Actions", style="Caption.TLabel").pack(side=LEFT)
                for folder in folder_actions[:3]:
                    ttk.Button(
                        folder_row,
                        text=f"Exclude {folder['folder']} ({folder['count']})",
                        style="Ghost.TButton",
                        command=lambda name=folder["folder"]: self.on_exclude_folder_from_diagnostics(name),
                    ).pack(side=LEFT, padx=(12, 0))

        grid = ttk.Frame(self.content_frame, style="Panel.TFrame")
        grid.pack(fill=BOTH, expand=True, pady=(18, 0))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)

        activity_card = ttk.Frame(grid, style="PanelAlt.TFrame", padding=14)
        activity_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        ttk.Label(activity_card, text="Activity Feed", style="Section.TLabel").pack(anchor=W)
        self.history_activity_tree = ttk.Treeview(activity_card, columns=("time", "kind", "summary"), show="headings", height=12)
        for heading, width in (("time", 170), ("kind", 120), ("summary", 340)):
            self.history_activity_tree.heading(heading, text=heading.title())
            self.history_activity_tree.column(heading, width=width, anchor=W)
        self.history_activity_tree.pack(fill=BOTH, expand=True, pady=(10, 0))
        self._populate_history_activity_tree()

        session_card = ttk.Frame(grid, style="PanelAlt.TFrame", padding=14)
        session_card.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        ttk.Label(session_card, text="Session Actions", style="Section.TLabel").pack(anchor=W)
        self.history_session_log = ScrolledText(session_card, height=12)
        style_scrolled_text(self.history_session_log, self.palette, self.type_scale)
        self.history_session_log.pack(fill=BOTH, expand=True, pady=(10, 0))
        self._populate_text_widget(self.history_session_log, self._recent_action_lines or ["No in-app actions recorded this session."])

        project_card = ttk.Frame(grid, style="PanelAlt.TFrame", padding=14)
        project_card.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(project_card, text="Project Log", style="Section.TLabel").pack(anchor=W)
        self.history_project_log = ScrolledText(project_card, height=12)
        style_scrolled_text(self.history_project_log, self.palette, self.type_scale)
        self.history_project_log.pack(fill=BOTH, expand=True, pady=(10, 0))
        self._populate_text_widget(self.history_project_log, self._project_log_lines())

        timeline_card = ttk.Frame(grid, style="PanelAlt.TFrame", padding=14)
        timeline_card.grid(row=1, column=1, sticky="nsew")
        ttk.Label(timeline_card, text="Scan And Export Timeline", style="Section.TLabel").pack(anchor=W)
        self.history_export_history_log = ScrolledText(timeline_card, height=12)
        style_scrolled_text(self.history_export_history_log, self.palette, self.type_scale)
        self.history_export_history_log.pack(fill=BOTH, expand=True, pady=(10, 0))
        self._populate_text_widget(self.history_export_history_log, self._history_timeline_lines())

    def _render_settings_view(self) -> None:
        panel = ttk.Frame(self.content_frame, style="Panel.TFrame")
        panel.pack(fill=BOTH, expand=True)

        config_card = ttk.Frame(panel, style="PanelAlt.TFrame", padding=18)
        config_card.pack(fill=X)
        ttk.Label(config_card, text="Model And Review Controls", style="Section.TLabel").pack(anchor=W)
        self._labeled_entry(config_card, "Model", self.model_name)
        ttk.Checkbutton(config_card, text="Enable model-assisted enrichment", variable=self.model_enabled).pack(anchor=W, pady=(8, 10))
        self._labeled_entry(config_card, "API Key", self.api_key_value, show="*")
        ttk.Checkbutton(config_card, text="Save API key in local project secrets", variable=self.save_api_key).pack(anchor=W, pady=(8, 10))
        self._labeled_entry(config_card, "Low-signal word threshold", self.review_low_signal_var)
        self._labeled_entry(config_card, "Duplicate similarity threshold", self.review_duplicate_threshold_var)
        self._labeled_entry(config_card, "AI low-confidence threshold", self.review_confidence_var)

        action_row = ttk.Frame(panel, style="Panel.TFrame")
        action_row.pack(fill=X, pady=(18, 0))
        ttk.Button(action_row, text="Save Settings", style="Primary.TButton", command=self.on_save_ai_settings).pack(side=LEFT)
        ttk.Button(action_row, text="Clear Saved Key", style="Ghost.TButton", command=self.on_clear_saved_key).pack(side=LEFT, padx=(10, 0))
        ttk.Button(action_row, text="Go To Sources", style="Ghost.TButton", command=lambda: self._set_active_view("sources")).pack(side=LEFT, padx=(10, 0))

    def _build_field_card(self, parent, label: str, variable: StringVar, browse_cmd) -> None:
        card = ttk.Frame(parent, style="PanelAlt.TFrame", padding=16)
        card.pack(fill=X, pady=(0, 10))
        ttk.Label(card, text=label, style="Section.TLabel").pack(anchor=W)
        row = ttk.Frame(card, style="PanelAlt.TFrame")
        row.pack(fill=X, pady=(8, 0))
        ttk.Entry(row, textvariable=variable).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(row, text="Browse", style="Ghost.TButton", command=browse_cmd).pack(side=LEFT, padx=(10, 0))

    def _build_inline_folder_picker(self, parent, label: str, variable: StringVar, browse_cmd) -> None:
        row = ttk.Frame(parent, style="PanelAlt.TFrame")
        row.pack(fill=X, pady=(0, 10))
        ttk.Label(row, text=label, style="Caption.TLabel").pack(side=LEFT, padx=(0, 10))
        ttk.Entry(row, textvariable=variable).pack(side=LEFT, fill=X, expand=True)
        ttk.Button(row, text="Browse", style="Ghost.TButton", command=browse_cmd).pack(side=LEFT, padx=(10, 0))

    def _labeled_entry(self, parent, label: str, variable: StringVar, show: str | None = None) -> None:
        ttk.Label(parent, text=label, style="Caption.TLabel").pack(anchor=W, pady=(10, 4))
        ttk.Entry(parent, textvariable=variable, show=show or "").pack(fill=X)

    def _labeled_combo(self, parent, label: str, variable: StringVar, values: list[str], help_text: str | None = None) -> None:
        row = ttk.Frame(parent, style="PanelAlt.TFrame")
        row.pack(fill=X, pady=(10, 4))
        ttk.Label(row, text=label, style="Caption.TLabel").pack(side=LEFT, anchor=W)
        if help_text:
            build_info_button(row, help_text, self.palette).pack(side=LEFT, padx=(8, 0))
        ttk.Combobox(parent, textvariable=variable, values=values, state="readonly").pack(fill=X)

    def _grid_labeled_entry(self, parent, row: int, label: str, variable: StringVar) -> None:
        ttk.Label(parent, text=label, style="Caption.TLabel").grid(row=row, column=0, sticky=W, pady=(10, 4))
        ttk.Entry(parent, textvariable=variable).grid(row=row + 1, column=0, sticky="ew")

    def _grid_labeled_combo(self, parent, row: int, label: str, variable: StringVar, values: list[str]):
        ttk.Label(parent, text=label, style="Caption.TLabel").grid(row=row, column=0, sticky=W, pady=(10, 4))
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        combo.grid(row=row + 1, column=0, sticky="ew")
        return combo

    def _browse_project_dir(self) -> None:
        path = filedialog.askdirectory(title="Select project folder")
        if path:
            self.project_dir.set(path)

    def _browse_source_dir(self) -> None:
        path = filedialog.askdirectory(title="Select source folder")
        if path:
            self._set_source_roots([path])
            if not self.project_name.get().strip():
                self.project_name.set(Path(path).name)

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_dir.set(path)

    def _normalize_source_root_strings(self, values: list[str] | tuple[str, ...] | None) -> list[str]:
        normalized: list[str] = []
        for value in values or []:
            text = str(value).strip()
            if not text:
                continue
            candidate = str(Path(text))
            if candidate not in normalized:
                normalized.append(candidate)
        return normalized

    def _current_source_root_strings(self) -> list[str]:
        roots = self._normalize_source_root_strings(self._selected_source_roots)
        fallback = self.source_dir.get().strip()
        if fallback:
            fallback_path = str(Path(fallback))
            if not roots:
                return [fallback_path]
            if roots[0] != fallback_path:
                remaining = [value for value in roots[1:] if value != fallback_path]
                return [fallback_path, *remaining]
        return roots

    def _current_source_roots(self) -> list[Path]:
        return [Path(value) for value in self._current_source_root_strings()]

    def _set_source_roots(self, values: list[str] | tuple[str, ...] | None) -> None:
        normalized = self._normalize_source_root_strings(values)
        self._selected_source_roots = normalized
        self.source_dir.set(normalized[0] if normalized else "")

    def _add_source_root(self, path: str) -> None:
        normalized = self._current_source_root_strings()
        candidate = str(Path(str(path).strip()))
        if candidate and candidate not in normalized:
            normalized.append(candidate)
            self._set_source_roots(normalized)
        if normalized and not self.project_name.get().strip():
            base_name = Path(normalized[0]).name.strip()
            if base_name:
                self.project_name.set(base_name if len(normalized) == 1 else f"{base_name} knowledge set")

    def _browse_additional_source_dir(self) -> None:
        path = filedialog.askdirectory(title="Add another folder to scan")
        if not path:
            return
        self._add_source_root(path)
        self.banner_var.set(f"Added source folder: {Path(path).name}")
        self._refresh_shell()

    def on_clear_source_roots(self) -> None:
        self._set_source_roots([])
        self.banner_var.set("Cleared selected scan folders.")
        self._refresh_shell()

    def on_remove_source_root(self, path: str) -> None:
        remaining = [value for value in self._current_source_root_strings() if value != path]
        self._set_source_roots(remaining)
        self.banner_var.set(f"Removed source folder: {Path(path).name}")
        self._refresh_shell()

    def _prompt_for_simple_folders(self) -> bool:
        source_choice = filedialog.askdirectory(title="Choose the first folder to scan")
        if not source_choice:
            return False
        source_roots = [source_choice]
        while messagebox.askyesno("Add Another Folder", "Do you want to add another folder to scan?"):
            extra_choice = filedialog.askdirectory(title="Choose another folder to scan")
            if not extra_choice:
                break
            if extra_choice not in source_roots:
                source_roots.append(extra_choice)
        output_choice = filedialog.askdirectory(title="Choose where GPT files should be saved")
        if not output_choice:
            return False
        self._set_source_roots(source_roots)
        self.output_dir.set(output_choice)
        if not self.project_name.get().strip():
            self.project_name.set(Path(source_roots[0]).name)
        return True

    def _simple_project_name(self) -> str:
        current = self.project_name.get().strip()
        if current:
            return current
        source_roots = self._current_source_roots()
        if source_roots:
            source_name = source_roots[0].name.strip()
            if source_name:
                return source_name if len(source_roots) == 1 else f"{source_name} knowledge set"
        return "knowledge_project"

    def _derived_simple_project_dir(self, source_dir: Path, output_dir: Path) -> Path:
        workspace_root = output_dir / ".gptkb_workspace"
        slug = make_safe_corpus_name(self._simple_project_name()) or "knowledge-project"
        candidate = workspace_root / slug
        index = 2
        while candidate.exists() and not (candidate / PROJECT_FILE).exists():
            candidate = workspace_root / f"{slug}-{index}"
            index += 1
        return candidate

    def _render_simple_source_roots_picker(self, parent, *, title: str = "Folders To Scan") -> None:
        panel = ttk.Frame(parent, style="PanelAlt.TFrame")
        panel.pack(fill=X, pady=(0, 8))
        header = ttk.Frame(panel, style="PanelAlt.TFrame")
        header.pack(fill=X)
        ttk.Label(header, text=title, style="Caption.TLabel").pack(side=LEFT)
        build_info_button(
            header,
            "Add one folder or many folders. The app scans all selected folders together and builds one GPT-ready output set.",
            self.palette,
        ).pack(side=LEFT, padx=(8, 0))

        selected_roots = self._current_source_root_strings()
        if not selected_roots:
            ttk.Label(
                panel,
                text="No scan folders selected yet. Add at least one folder to continue.",
                style="Muted.TLabel",
                wraplength=920,
                justify=LEFT,
            ).pack(anchor=W, pady=(6, 8))
        else:
            ttk.Label(
                panel,
                text=f"Selected scan folders: {len(selected_roots)}",
                style="Muted.TLabel",
                wraplength=920,
                justify=LEFT,
            ).pack(anchor=W, pady=(6, 8))
            for source_root in selected_roots:
                row = ttk.Frame(panel, style="PanelAlt.TFrame")
                row.pack(fill=X, pady=(0, 6))
                ttk.Label(row, text=source_root, style="Caption.TLabel", wraplength=820, justify=LEFT).pack(side=LEFT, fill=X, expand=True)
                ttk.Button(
                    row,
                    text="Remove",
                    style="Ghost.TButton",
                    command=lambda value=source_root: self.on_remove_source_root(value),
                ).pack(side=RIGHT)

        actions = ttk.Frame(panel, style="PanelAlt.TFrame")
        actions.pack(fill=X, pady=(4, 0))
        ttk.Button(actions, text="Add Folder", style="Ghost.TButton", command=self._browse_additional_source_dir).pack(side=LEFT)
        ttk.Button(actions, text="Clear Folders", style="Ghost.TButton", command=self.on_clear_source_roots).pack(side=LEFT, padx=(10, 0))

    def _simple_setup_hint_text(self) -> str:
        source_roots = self._current_source_roots()
        output_text = self.output_dir.get().strip()
        if not source_roots or not output_text:
            return "Select one folder or many folders to scan, then choose where GPT files should be saved. The app will derive its internal project data folder automatically."
        source_dir = source_roots[0]
        output_dir = Path(output_text)
        project_dir = self._derived_simple_project_dir(source_dir, output_dir)
        source_label = source_dir.name if len(source_roots) == 1 else f"{len(source_roots)} folders"
        return (
            f"Scan set: {source_label} | "
            f"Internal app data: {project_dir} | "
            f"Project name: {self._simple_project_name()} | "
            f"GPT files will be written to: {output_dir}"
        )

    def _create_or_update_project_from_folders(self, *, start_scan: bool) -> None:
        source_roots = self._current_source_roots()
        output_text = self.output_dir.get().strip()
        if not source_roots:
            messagebox.showerror("Simple Setup", "Choose at least one folder to scan first.")
            return
        if not output_text:
            messagebox.showerror("Simple Setup", "Choose the output folder first.")
            return

        output_dir = Path(output_text)
        invalid_roots = [path for path in source_roots if not path.exists() or not path.is_dir()]
        if invalid_roots:
            label = "\n".join(str(path) for path in invalid_roots[:5])
            suffix = "\n..." if len(invalid_roots) > 5 else ""
            messagebox.showerror("Simple Setup", f"One or more scan folders were not found:\n{label}{suffix}")
            return
        if output_dir.exists() and not output_dir.is_dir():
            messagebox.showerror("Simple Setup", f"Output path is not a folder:\n{output_dir}")
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        source_dir = source_roots[0]
        project_dir = self._derived_simple_project_dir(source_dir, output_dir)
        project_name = self._simple_project_name()
        self.project_name.set(project_name)
        self.project_dir.set(str(project_dir))

        if not (project_dir / PROJECT_FILE).exists():
            init_project(
                project_root=project_dir,
                project_name=project_name,
                source_roots=source_roots,
                output_root=output_dir,
                preset=self.preset.get().strip(),
                export_profile=self.export_profile.get().strip(),
                model_enabled=self.model_enabled.get(),
            )

        config = load_project_config(project_dir)
        config.project_name = project_name
        config.source_roots = [str(path.resolve()) for path in source_roots]
        config.output_root = str(output_dir.resolve())
        config.preset = self.preset.get().strip() or config.preset
        config.export_profile = self.export_profile.get().strip() or config.export_profile
        config.optional_model_settings.enabled = self.model_enabled.get()
        config.optional_model_settings.model = self.model_name.get().strip() or config.optional_model_settings.model
        save_project_config(project_dir, config)
        self._persist_project_settings(project_dir)
        self._load_project(project_dir)

        if start_scan:
            self._set_transition_notice(
                "processing",
                "Step Complete: Folders Saved",
                "The internal project data was created automatically from your scan folders and output folder. The next step is already running: scanning the corpus.",
            )
            self.banner_var.set("Project created from selected scan folders and output folder.")
            self.view_state.active_view = "processing"
            self._refresh_shell()
            self.on_scan()
        else:
            self._set_transition_notice(
                "sources",
                "Step Complete: Folders Saved",
                "The internal project data was created automatically from your scan folders and output folder. Continue to Scan when you are ready.",
            )
            self.banner_var.set("Project created from selected scan folders and output folder.")
            self._set_active_view("sources")

    def on_simple_setup(self) -> None:
        self._create_or_update_project_from_folders(start_scan=False)

    def on_simple_setup_and_scan(self) -> None:
        self._create_or_update_project_from_folders(start_scan=True)

    def on_quick_start_scan(self) -> None:
        if not self._prompt_for_simple_folders():
            return
        self.on_simple_setup_and_scan()

    def on_create_project(self) -> None:
        project_dir = Path(self.project_dir.get().strip())
        source_roots = self._current_source_roots()
        output_dir = Path(self.output_dir.get().strip())
        if not source_roots:
            messagebox.showerror("Create Project", "Choose at least one scan folder.")
            return
        for label, path in (("Project", project_dir), ("Output", output_dir)):
            if path.exists() and not path.is_dir():
                messagebox.showerror("Create Project", f"{label} path is not a folder:\n{path}")
                return
        for source_dir in source_roots:
            if source_dir.exists() and not source_dir.is_dir():
                messagebox.showerror("Create Project", f"Source path is not a folder:\n{source_dir}")
                return

        project_dir.mkdir(parents=True, exist_ok=True)
        for source_dir in source_roots:
            source_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        init_project(
            project_root=project_dir,
            project_name=self.project_name.get().strip() or source_roots[0].name,
            source_roots=source_roots,
            output_root=output_dir,
            preset=self.preset.get().strip(),
            export_profile=self.export_profile.get().strip(),
            model_enabled=self.model_enabled.get(),
        )
        self._persist_project_settings(project_dir)
        self._set_transition_notice(
            "sources",
            "Step Complete: Project Created",
            "The internal project data was created successfully. Review the folder choices if needed, then continue to Scan.",
        )
        self._load_project(project_dir)
        self.banner_var.set(f"Project ready at {project_dir}")
        self._set_active_view("sources")

    def on_open_project(self) -> None:
        chosen = filedialog.askdirectory(title="Select project folder")
        if not chosen:
            return
        project_dir = Path(chosen)
        if not (project_dir / PROJECT_FILE).exists():
            messagebox.showerror("Open Project", f"No {PROJECT_FILE} found in:\n{project_dir}")
            return
        self._load_project(project_dir)

    def on_open_recent_project(self, project_dir: Path | str) -> None:
        path = Path(project_dir)
        if not (path / PROJECT_FILE).exists():
            self.banner_var.set(f"Recent project not found: {path}")
            self._refresh_shell()
            return
        self._load_project(path)

    def on_scan(self) -> None:
        self._run_async("scan", lambda: scan_project(self._require_project_dir(), force=self.force_scan.get()))

    def on_rescan_failed(self) -> None:
        self._run_async("scan", lambda: scan_project(self._require_project_dir(), force=True))

    def on_retry_selected_review(self) -> None:
        review_id = self.selected_review_id.get().strip()
        if not review_id:
            messagebox.showerror("Retry Extraction", "Select a review item first.")
            return
        strategy = self.review_retry_strategy.get().strip() or "default"
        self._run_async("retry_review", lambda: retry_document_extraction(self._require_project_dir(), review_id=review_id, strategy=strategy))

    def on_retry_selected_review_and_next(self) -> None:
        self._pending_review_followup = "next"
        self.on_retry_selected_review()

    def on_retry_filtered_reviews(self) -> None:
        self._run_async(
            "bulk_retry",
            lambda: retry_review_items(
                self._require_project_dir(),
                kind=self.bulk_retry_kind.get().strip() or "extraction_issue",
                document_type=self.bulk_retry_doc_type.get().strip() or "all",
                extraction_status=self.bulk_retry_extraction_status.get().strip() or "all",
                strategy=self.bulk_retry_strategy.get().strip() or None,
                status="open",
            ),
        )

    def on_refresh_reviews(self) -> None:
        project_dir = self._require_project_dir()
        self._refresh_review_display(project_dir)
        self.banner_var.set("Review queue refreshed.")
        self._refresh_shell()

    def on_approve_all(self) -> None:
        self._run_async("review", lambda: review_project(self._require_project_dir(), approve_all=True))

    def on_reject_duplicates(self) -> None:
        self._run_async("review", lambda: review_project(self._require_project_dir(), reject_duplicates=True))

    def on_apply_review_edit(self) -> None:
        review_id = self.selected_review_id.get().strip()
        if not review_id:
            messagebox.showerror("Review Edit", "Select a review item first.")
            return
        note = self.review_note_text.get("1.0", END).strip() if self.review_note_text else ""
        self._pending_undo_snapshot = self._snapshot_review_item(review_id)
        self._run_async(
            "review_edit",
            lambda: update_review_item(
                self._require_project_dir(),
                review_id=review_id,
                status=self.review_status_edit.get().strip() or None,
                override_title=self.review_title_edit.get(),
                override_domain=self.review_domain_edit.get(),
                resolution_note=note,
            ),
        )

    def on_mark_review_accepted(self) -> None:
        self.review_status_edit.set("accepted")
        self.on_apply_review_edit()

    def on_mark_review_accepted_and_next(self) -> None:
        self._pending_review_followup = "next"
        self.on_mark_review_accepted()

    def on_mark_review_rejected(self) -> None:
        self.review_status_edit.set("rejected")
        self.on_apply_review_edit()

    def on_mark_review_rejected_and_next(self) -> None:
        self._pending_review_followup = "next"
        self.on_mark_review_rejected()

    def on_promote_duplicate_canonical(self) -> None:
        item = self._current_selected_review_item()
        if not item or str(item.get("kind") or "") != "duplicate":
            messagebox.showerror("Canonical Duplicate", "Select a duplicate review item first.")
            return
        review_id = str(item.get("review_id") or "")
        self._run_async("duplicate_promote", lambda: promote_duplicate_as_canonical(self._require_project_dir(), review_id))

    def on_undo_last_action(self) -> None:
        action = self._last_undo_action
        if not action:
            messagebox.showerror("Undo Action", "No reversible review action is available.")
            return
        if action.get("kind") != "review_edit":
            messagebox.showerror("Undo Action", "The last recorded action cannot be undone.")
            return
        snapshot = action.get("snapshot") or {}
        review_id = str(snapshot.get("review_id") or "")
        if not review_id:
            messagebox.showerror("Undo Action", "The saved undo state is incomplete.")
            return
        self._run_async(
            "review_edit",
            lambda: update_review_item(
                self._require_project_dir(),
                review_id=review_id,
                status=snapshot.get("status"),
                override_title=snapshot.get("override_title"),
                override_domain=snapshot.get("override_domain"),
                resolution_note=snapshot.get("resolution_note"),
            ),
        )
        self._append_recent_action(f"Undo requested for {review_id}")
        self._last_undo_action = None

    def on_validate(self) -> None:
        self._run_async("validate", lambda: {"issues": validate_project(self._require_project_dir())})

    def on_export(self) -> None:
        self._run_async("export", lambda: export_project(self._require_project_dir(), zip_pack=self.zip_pack.get()))

    def on_export_diagnostics(self) -> None:
        self._run_async("diagnostics", lambda: export_diagnostics_report(self._require_project_dir()))

    def on_refresh_diagnostics(self) -> None:
        payload = self._load_diagnostics_payload()
        if payload:
            self.banner_var.set("Diagnostics refreshed.")
        else:
            self.banner_var.set("No diagnostics file found yet.")
        self._refresh_shell()

    def on_open_selected_history_context(self) -> None:
        item = self._current_history_activity()
        if not item:
            self.banner_var.set("Select a history item first.")
            self._refresh_shell()
            return
        kind = str(item.get("kind") or "")
        fields = item.get("fields") or {}
        if kind == "scan":
            self._set_active_view("processing")
        elif kind == "export":
            self._queue_view_focus("export", "artifacts")
            self._set_active_view("export")
        elif kind == "duplicate_promote":
            self.review_filter.set("Duplicates")
            self.view_state.review_filter = "Duplicates"
            self._set_active_view("review")
            review_id = str(fields.get("review_id") or "")
            if review_id:
                self._select_review_item_by_id(review_id)
        elif kind == "review_update":
            self._set_active_view("review")
            review_id = str(fields.get("review_id") or "")
            if review_id:
                self._select_review_item_by_id(review_id)
        else:
            self._set_active_view("processing")
        self.banner_var.set(f"Opened context for {kind or 'activity'} entry.")
        self._refresh_shell()

    def _run_diagnostics_bulk_retry(self, document_type: str, extraction_status: str, strategy: str) -> None:
        self.bulk_retry_kind.set("extraction_issue")
        self.bulk_retry_doc_type.set(document_type)
        self.bulk_retry_extraction_status.set(extraction_status)
        self.bulk_retry_strategy.set(strategy)
        self.on_retry_filtered_reviews()

    def on_save_ai_settings(self) -> None:
        project_dir = self._require_project_dir()
        self._persist_project_settings(project_dir)
        self._set_transition_notice(
            "sources",
            "Step Complete: Settings Saved",
            "Project settings were saved. Continue to Scan when you are ready to build the corpus.",
        )
        self.banner_var.set("Settings saved for this project.")
        self._refresh_shell()

    def on_save_and_go_to_scan(self) -> None:
        project_dir = self._require_project_dir()
        self._persist_project_settings(project_dir)
        self._set_transition_notice(
            "processing",
            "Step Complete: Setup Saved",
            "Setup is saved. The next step is to run the first scan and build the working corpus.",
        )
        self.banner_var.set("Settings saved. Continue with the first scan.")
        self._set_active_view("processing")

    def on_start_guided_setup(self) -> None:
        if self.guided_wizard is not None and self.guided_wizard.winfo_exists():
            self.guided_wizard.lift()
            self.guided_wizard.focus_force()
            return
        self.guided_wizard_step = 0
        self.guided_wizard = Toplevel(self.root)
        self.guided_wizard.title("Guided Setup")
        self.guided_wizard.geometry("760x560")
        self.guided_wizard.minsize(680, 520)
        self.guided_wizard.configure(bg=self.palette.bg)
        container = ttk.Frame(self.guided_wizard, style="App.TFrame", padding=18)
        container.pack(fill=BOTH, expand=True)
        ttk.Label(container, textvariable=self.guided_wizard_title_var, style="Header.TLabel").pack(anchor=W)
        ttk.Label(container, textvariable=self.guided_wizard_hint_var, style="Subhead.TLabel", wraplength=680, justify=LEFT).pack(anchor=W, pady=(6, 14))
        self.guided_wizard_body = ttk.Frame(container, style="PanelAlt.TFrame", padding=18)
        self.guided_wizard_body.pack(fill=BOTH, expand=True)
        actions = ttk.Frame(container, style="App.TFrame")
        actions.pack(fill=X, pady=(14, 0))
        ttk.Button(actions, text="Back", style="Ghost.TButton", command=self._wizard_back).pack(side=LEFT)
        ttk.Button(actions, text="Next", style="Ghost.TButton", command=self._wizard_next).pack(side=LEFT, padx=(10, 0))
        ttk.Button(actions, text="Create Project", style="Primary.TButton", command=self._wizard_finish).pack(side=RIGHT)
        self.guided_wizard.protocol("WM_DELETE_WINDOW", self._close_guided_wizard)
        self._render_guided_wizard_step()

    def on_continue_from_processing(self) -> None:
        summary = self._current_workspace_summary()
        if summary["documents"] == 0:
            self.on_scan()
            return
        if summary.get("open_reviews", 0) or summary.get("failed_docs", 0) or summary.get("partial_docs", 0):
            self._set_active_view("review")
            return
        self._queue_view_focus("export", "artifacts")
        self._set_active_view("export")

    def on_go_to_diagnostics(self) -> None:
        self._queue_view_focus("diagnostics", "issues")
        self._set_active_view("diagnostics")

    def on_clear_saved_key(self) -> None:
        project_dir = self._require_project_dir()
        secrets = load_secrets(project_dir)
        providers = secrets.get("providers") or {}
        providers["openai"] = {}
        secrets["providers"] = providers
        save_secrets(project_dir, secrets)
        self.api_key_value.set("")
        self.save_api_key.set(False)
        self.banner_var.set("Saved API key cleared. Environment variable fallback still works.")
        self._refresh_shell()

    def on_open_output(self) -> None:
        project_dir = self._require_project_dir()
        config = load_project_config(project_dir)
        output_dir = resolve_project_path(project_dir, config.output_root)
        output_dir.mkdir(parents=True, exist_ok=True)
        self._open_path(output_dir)

    def on_open_latest_package_dir(self) -> None:
        latest = self._latest_export_payload()
        if latest and latest.get("package_dir"):
            self._open_path(latest["package_dir"])

    def on_open_latest_provenance_manifest(self) -> None:
        latest = self._latest_export_payload()
        if latest and latest.get("provenance_manifest"):
            self._open_path(latest["provenance_manifest"])

    def on_open_latest_package_index(self) -> None:
        latest = self._latest_export_payload()
        if latest and latest.get("package_index_file"):
            self._open_path(latest["package_index_file"])

    def on_open_diagnostics_folder(self) -> None:
        project_dir = self._require_project_dir()
        diagnostics_dir = diagnostics_paths(project_dir)["diagnostics_dir"]
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        self._open_path(diagnostics_dir)

    def on_prev_preview_unit(self) -> None:
        self._move_preview_unit(-1)

    def on_next_preview_unit(self) -> None:
        self._move_preview_unit(1)

    def _latest_export_payload(self) -> dict | None:
        project_dir = self._current_project_dir(optional=True)
        if not project_dir:
            return None
        state = load_state(project_dir)
        exports = state.get("exports") or []
        return exports[-1] if exports else None

    def _open_path(self, value: Path | str) -> None:
        target = str(value)
        try:
            if os.name == "nt":
                os.startfile(target)
                return
            command = ["open", target] if sys.platform == "darwin" else ["xdg-open", target]
            subprocess.run(command, check=False)
        except Exception as exc:
            messagebox.showerror("Open Path", f"Could not open:\n{target}\n\n{exc}")

    def _run_async(self, kind: str, fn) -> None:
        phase, detail = self._operation_phase(kind)
        self.operation_phase_var.set(phase)
        self.operation_detail_var.set(detail)
        self.banner_var.set(f"{kind} running...")
        self._refresh_shell()

        def runner() -> None:
            try:
                result = fn()
                self._event_queue.put((kind, result))
            except Exception as exc:
                self._event_queue.put(("error", str(exc)))

        threading.Thread(target=runner, daemon=True).start()

    def _pump_events(self) -> None:
        try:
            while True:
                kind, payload = self._event_queue.get_nowait()
                if kind == "error":
                    self._append_process_log(f"ERROR: {payload}")
                    self._append_export_log(f"ERROR: {payload}")
                    self.banner_var.set(f"Error: {payload}")
                    messagebox.showerror("Run Error", str(payload))
                elif kind == "scan":
                    self._handle_scan_complete(payload)
                elif kind == "review":
                    self._handle_review_complete(payload)
                elif kind == "review_edit":
                    self._handle_review_edit_complete(payload)
                elif kind == "validate":
                    self._handle_validate_complete(payload)
                elif kind == "retry_review":
                    self._handle_retry_review_complete(payload)
                elif kind == "bulk_retry":
                    self._handle_bulk_retry_complete(payload)
                elif kind == "duplicate_promote":
                    self._handle_duplicate_promote_complete(payload)
                elif kind == "diagnostics":
                    self._handle_diagnostics_complete(payload)
                elif kind == "export":
                    self._handle_export_complete(payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(150, self._pump_events)

    def _handle_scan_complete(self, payload) -> None:
        self.processing_summary_var.set(self._format_scan_summary(payload, prefix="Scan complete"))
        self._append_process_log(self.processing_summary_var.get())
        self.banner_var.set("Scan complete.")
        self.operation_phase_var.set("Scan complete")
        self.operation_detail_var.set("Discovery, extraction, and review-queue generation finished.")
        self._set_transition_notice(
            "processing",
            "Step Complete: Scan Finished",
            "The corpus snapshot is ready. Use the decision panel below to move into Review or continue directly to Export.",
        )
        self._append_recent_action(self.processing_summary_var.get())
        self.view_state.active_view = "processing"
        if self.view_state.has_project:
            self._refresh_review_display(self._require_project_dir())
        self._refresh_shell()

    def _handle_review_complete(self, payload) -> None:
        self.review_summary_var.set(
            f"Review updated: open={payload['open']} accepted={payload['accepted']} "
            f"rejected={payload['rejected']} changed={payload['changed']}"
        )
        self.banner_var.set("Review queue updated.")
        self.operation_phase_var.set("Review updated")
        self.operation_detail_var.set("Batch review changes were applied and the queue was recalculated.")
        self._set_transition_notice(
            "review",
            "Step Complete: Review Updated",
            "The queue was recalculated. Keep working through the remaining open items or continue to Export if the queue is clear.",
        )
        self._append_recent_action(
            f"Review batch updated: open={payload['open']} accepted={payload['accepted']} rejected={payload['rejected']}"
        )
        if self.view_state.has_project:
            self._refresh_review_display(self._require_project_dir())
        self._refresh_shell()

    def _handle_review_edit_complete(self, payload) -> None:
        self.banner_var.set(f"Review item updated: {payload.get('review_id', '')}")
        self.operation_phase_var.set("Review item updated")
        self.operation_detail_var.set("The selected review item was saved and the queue was refreshed.")
        self._set_transition_notice(
            "review",
            "Step Complete: Review Decision Saved",
            "The selected review item was saved. Review now focuses the next unresolved item when one is available.",
        )
        self._append_process_log(f"Review edit saved for {payload.get('review_id', '')}")
        if self._pending_undo_snapshot:
            self._last_undo_action = {"kind": "review_edit", "snapshot": self._pending_undo_snapshot}
            self._pending_undo_snapshot = None
        self._append_recent_action(
            f"Review item updated: {payload.get('review_id', '')} -> status={payload.get('status', '')}"
        )
        if self.view_state.has_project:
            self._refresh_review_display(self._require_project_dir())
        should_advance = self._pending_review_followup == "next" and self.selected_review_id.get().strip() == str(payload.get("review_id") or "")
        self._pending_review_followup = None
        if should_advance:
            self.on_next_review_item()
        self._refresh_shell()

    def _handle_validate_complete(self, payload) -> None:
        issues = payload.get("issues") or []
        if issues:
            self.export_summary_var.set(f"Validation found {len(issues)} issue(s).")
            for issue in issues:
                self._append_export_log(issue)
        else:
            self.export_summary_var.set("Validation passed.")
            self._append_export_log("Validation passed with no issues.")
        self.banner_var.set("Validation complete.")
        self.operation_phase_var.set("Validation complete")
        self.operation_detail_var.set("The export package was checked for unresolved blockers and naming issues.")
        self._refresh_shell()

    def _handle_retry_review_complete(self, payload) -> None:
        summary = payload.get("summary") or {}
        project_dir = self._require_project_dir()
        report = load_state(project_dir).get("last_scan_report") or summary
        self.processing_summary_var.set(self._format_scan_summary(report, prefix="Retry complete"))
        self._append_process_log(
            f"Retry complete: {Path(payload.get('source_path', '')).name} :: "
            f"strategy={payload.get('strategy', 'default')} "
            f"processed={summary.get('processed', 0)} partial={summary.get('partial', 0)} "
            f"failed={summary.get('failed', 0)} unsupported={summary.get('unsupported', 0)}"
        )
        self.banner_var.set(f"Retried extraction for {Path(payload.get('source_path', '')).name}")
        self.operation_phase_var.set("Retry complete")
        self.operation_detail_var.set("The selected document was re-extracted and the corpus state was refreshed.")
        self._set_transition_notice(
            "review",
            "Step Complete: Retry Finished",
            "The document was reprocessed. Review now focuses the next open issue when one is available.",
        )
        self._append_recent_action(
            f"Retried extraction: {Path(payload.get('source_path', '')).name} with {payload.get('strategy', 'default')}"
        )
        if self.view_state.has_project:
            self._refresh_review_display(project_dir)
        should_advance = self._pending_review_followup == "next" and self.selected_review_id.get().strip() == str(payload.get("review_id") or "")
        self._pending_review_followup = None
        if should_advance:
            self.on_next_review_item()
        self._refresh_shell()

    def _handle_bulk_retry_complete(self, payload) -> None:
        summary = payload.get("summary") or {}
        project_dir = self._require_project_dir()
        report = load_state(project_dir).get("last_scan_report") or summary
        self.processing_summary_var.set(self._format_scan_summary(report, prefix="Bulk retry complete"))
        self._append_process_log(
            f"Bulk retry complete: matches={len(payload.get('matched_sources') or [])} "
            f"kind={payload.get('kind', 'all')} document_type={payload.get('document_type', 'all')} "
            f"extraction_status={payload.get('extraction_status', 'all')} strategy={payload.get('strategy', 'default')}"
        )
        self.banner_var.set("Bulk retry complete.")
        self.operation_phase_var.set("Bulk retry complete")
        self.operation_detail_var.set("Matching review items were retried and the corpus health was recalculated.")
        self._set_transition_notice(
            "review",
            "Step Complete: Bulk Retry Finished",
            "Matching documents were retried. Review now reflects the refreshed corpus state.",
        )
        self._append_recent_action(
            f"Bulk retry complete: matches={len(payload.get('matched_sources') or [])} strategy={payload.get('strategy', 'default')}"
        )
        if self.view_state.has_project:
            self._refresh_review_display(project_dir)
        self._refresh_shell()

    def _handle_duplicate_promote_complete(self, payload) -> None:
        canonical_name = Path(str(payload.get("canonical_source") or "")).name
        duplicate_name = Path(str(payload.get("duplicate_source") or "")).name
        self.banner_var.set(f"Canonical source updated: {canonical_name}")
        self.operation_phase_var.set("Duplicate decision saved")
        self.operation_detail_var.set("The duplicate winner was updated and the review queue was rebuilt.")
        self._append_recent_action(f"Duplicate canonical set: {canonical_name} over {duplicate_name}")
        if self.view_state.has_project:
            self._refresh_review_display(self._require_project_dir())
        self._refresh_shell()

    def _handle_diagnostics_complete(self, payload) -> None:
        self._append_export_log(f"Diagnostics markdown: {payload.get('markdown_path', '')}")
        self._append_export_log(f"Diagnostics json: {payload.get('json_path', '')}")
        self.banner_var.set("Diagnostics exported.")
        self.operation_phase_var.set("Diagnostics exported")
        self.operation_detail_var.set("The diagnostics files were written and can now be inspected.")
        self._append_recent_action(f"Diagnostics exported: {Path(str(payload.get('json_path', ''))).name}")
        self.on_refresh_diagnostics()
        self._refresh_shell()

    def _handle_export_complete(self, payload) -> None:
        self.export_summary_var.set(
            f"Export ready: {payload['package_dir']} | "
            f"files={len(payload['written_files'])} | validation={len(payload['validation_messages'])}"
        )
        self._append_export_log(self.export_summary_var.get())
        if payload.get("knowledge_items_file"):
            self._append_export_log(f"Knowledge items: {payload['knowledge_items_file']}")
        self.banner_var.set("Export complete.")
        self.operation_phase_var.set("Export complete")
        self.operation_detail_var.set("The GPT-ready package and provenance sidecars were written successfully.")
        self._set_transition_notice(
            "export",
            "Step Complete: Export Finished",
            "The delivery package is ready. Open the output folder, inspect diagnostics, or upload the package to your GPT.",
        )
        self.export_completion_var.set(self._export_completion_text(payload))
        self.export_next_action_var.set(self._export_next_action_text(payload))
        self._append_recent_action(f"Export complete: {Path(str(payload.get('package_dir', ''))).name}")
        self._show_export_completion_dialog(payload)
        self._refresh_shell()

    def _load_project(self, project_dir: Path) -> None:
        config = load_project_config(project_dir)
        state = load_state(project_dir)
        self.project_dir.set(str(project_dir))
        self.project_name.set(config.project_name)
        self.preset.set(config.preset)
        self.export_profile.set(config.export_profile)
        self.model_enabled.set(config.optional_model_settings.enabled)
        self.model_name.set(config.optional_model_settings.model)
        self.review_low_signal_var.set(str(config.review_thresholds.low_signal_word_count))
        self.review_duplicate_threshold_var.set(str(config.review_thresholds.duplicate_similarity_threshold))
        self.review_confidence_var.set(str(config.review_thresholds.low_confidence_threshold))
        if config.source_roots:
            resolved_roots = [str(resolve_project_path(project_dir, value)) for value in config.source_roots]
            self._set_source_roots(resolved_roots)
        else:
            self._set_source_roots([])
        self.output_dir.set(str(resolve_project_path(project_dir, config.output_root)))
        secrets = load_secrets(project_dir)
        saved_key = ((secrets.get("providers") or {}).get("openai") or {}).get("api_key", "")
        self.api_key_value.set(saved_key)
        self.save_api_key.set(bool(saved_key))
        self.view_state.has_project = True
        self.home_summary_var.set(f"Loaded project {config.project_name} with preset {config.preset} and export profile {config.export_profile}.")
        self._record_recent_project(project_dir, config.project_name)
        report = state.get("last_scan_report") or {}
        if report:
            self.processing_summary_var.set(self._format_scan_summary(report, prefix="Scan complete"))
            self._process_log_lines = [self.processing_summary_var.get()]
            for issue in report.get("recent_issues", [])[:5]:
                self._process_log_lines.append(
                    f"{issue.get('status', 'issue').upper()}: {Path(issue.get('source_path', '')).name} :: {issue.get('reason', 'No reason supplied.')}"
                )
        else:
            self.processing_summary_var.set("Project loaded. Run scan to refresh corpus state.")
            self._process_log_lines = []
        self.banner_var.set(f"Loaded project {config.project_name}")
        self._refresh_review_display(project_dir)
        self._refresh_export_display(project_dir)
        self._refresh_shell()

    def _refresh_review_display(self, project_dir: Path | None) -> None:
        items = self._filtered_review_items(project_dir)
        self._review_tree_map = {}
        if self.review_list:
            self._populate_text_widget(
                self.review_list,
                [
                    f"[{item.get('status')}] {item.get('severity')} {item.get('kind')} :: {Path(item.get('source_path', '')).name}\n{item.get('detail')}"
                    for item in items
                ] or ["No review items recorded."],
            )
        if self.review_tree is not None:
            for item_id in self.review_tree.get_children():
                self.review_tree.delete(item_id)
            for index, item in enumerate(items, start=1):
                tree_id = f"{item.get('review_id')}::{index}"
                self._review_tree_map[tree_id] = item
                row_values = (
                    item.get("status"),
                    item.get("severity"),
                    item.get("kind"),
                    Path(item.get("source_path", "")).name,
                ) if self.review_queue_mode.get() == "table" else (
                    item.get("kind"),
                    Path(item.get("source_path", "")).name,
                )
                self.review_tree.insert(
                    "",
                    END,
                    iid=tree_id,
                    values=row_values,
                    tags=self._review_row_tags(item),
                )
        if self.review_history_log is not None:
            self._populate_text_widget(self.review_history_log, self._recent_action_lines or ["No recent review actions yet."])

        all_reviews = load_reviews(project_dir).get("items", []) if project_dir else []
        open_count = sum(1 for item in all_reviews if item.get("status") == "open")
        self.review_summary_var.set(f"{open_count} open review item(s), {len(all_reviews)} total. Filter: {self.review_filter.get()}.")
        if items:
            selected_review_id = self._preferred_review_selection(items)
            self.selected_review_id.set(str(selected_review_id))
            selected_item = next(item for item in items if item.get("review_id") == selected_review_id)
            if self.review_tree is not None:
                tree_id = next((iid for iid, review_item in self._review_tree_map.items() if review_item.get("review_id") == selected_review_id), "")
                if tree_id:
                    self.review_tree.selection_set(tree_id)
            self._populate_review_editor(selected_item)
            self.review_progress_var.set(self._review_progress_text())
        else:
            self.selected_review_id.set("")
            self.review_meta_var.set("No review item selected.")
            self.review_issue_title_var.set("No review item selected.")
            self.review_issue_reason_var.set("The review queue is empty for the current filter.")
            self.review_issue_action_var.set("Switch filters or continue to Export if all blockers are resolved.")
            self.review_title_edit.set("")
            self.review_domain_edit.set("")
            self.review_retry_strategy.set("default")
            self.review_preview_units = []
            self.review_preview_index = 0
            self.review_preview_label_var.set("Preview")
            self.review_preview_photo = None
            self.review_thumbnail_buttons = []
            self.review_thumbnail_photos = []
            if self.review_thumbnail_strip:
                for child in self.review_thumbnail_strip.winfo_children():
                    child.destroy()
            if self.review_preview_image_label:
                self.review_preview_image_label.configure(image="", text="")
            if self.review_preview_text:
                self.review_preview_text.delete("1.0", END)
            if self.review_duplicate_current_text:
                self.review_duplicate_current_text.delete("1.0", END)
            if self.review_duplicate_target_text:
                self.review_duplicate_target_text.delete("1.0", END)
            if self.review_duplicate_compare_frame:
                self.review_duplicate_compare_frame.grid_remove()
            if self.review_note_text:
                self.review_note_text.delete("1.0", END)
            self.review_progress_var.set("No review issues remain. Continue to Export or inspect Diagnostics.")
            self._refresh_review_session_summary(None, None)

    def _preferred_review_selection(self, items: list[dict]) -> str:
        current_id = self.selected_review_id.get().strip()
        current_item = next((item for item in items if str(item.get("review_id") or "") == current_id), None)
        if current_item and str(current_item.get("status") or "") == "open":
            return str(current_item.get("review_id") or "")
        first_open = next((item for item in items if str(item.get("status") or "") == "open"), None)
        if first_open:
            return str(first_open.get("review_id") or "")
        if current_item:
            return str(current_item.get("review_id") or "")
        return str(items[0].get("review_id") or "")

    def _review_session_action(self, item: dict | None, document: dict | None) -> tuple[str, callable, str]:
        if not item:
            if self._guided_mode_active():
                return ("Get GPT Files", lambda: self._set_active_view("export"), "No open issues remain in the current queue.")
            return ("Continue To Export", lambda: self._set_active_view("export"), "No open issues remain in the current queue.")
        status = str(item.get("status") or "open")
        kind = str(item.get("kind") or "")
        if status != "open":
            return ("Next", self.on_next_review_item, "This issue is already resolved. Move to the next unresolved item.") if self._guided_mode_active() else ("Next Open Issue", self.on_next_review_item, "This issue is already resolved. Move to the next unresolved item.")
        if kind == "duplicate":
            return ("Use This One", self.on_promote_duplicate_canonical, "Keep this version and move on.") if self._guided_mode_active() else ("Keep This As Canonical", self.on_promote_duplicate_canonical, "Keep the current document as the source of truth for this duplicate cluster.")
        if kind in {"extraction_issue", "empty", "ocr"}:
            return ("Retry", self.on_retry_selected_review_and_next, "Try reading the file again, then continue to the next issue.") if self._guided_mode_active() else ("Retry And Next", self.on_retry_selected_review_and_next, "Retry extraction first for degraded or unreadable content, then continue to the next issue.")
        return ("Accept", self.on_mark_review_accepted_and_next, "Accept the current issue and continue.") if self._guided_mode_active() else ("Accept And Next", self.on_mark_review_accepted_and_next, "Accept the current issue and continue. Edit title or domain first if you need to override the defaults.")

    def _refresh_review_session_summary(self, item: dict | None, document: dict | None) -> None:
        label, command, detail = self._review_session_action(item, document)
        if item:
            self.review_session_title_var.set(f"Current focus: {Path(str(item.get('source_path') or '')).name}")
        else:
            self.review_session_title_var.set("Review session is clear.")
        self.review_session_detail_var.set(detail)
        if self.review_session_primary_button is not None:
            self.review_session_primary_button.configure(text=label, command=command)

    def _refresh_export_display(self, project_dir: Path) -> None:
        state = load_state(project_dir)
        exports = state.get("exports") or []
        if not exports:
            self.export_summary_var.set("No exports yet.")
            self.export_completion_var.set("No export has completed yet.")
            self.export_next_action_var.set("Validate and export the package after scan and review are in good shape.")
            return
        latest = exports[-1]
        self.export_summary_var.set(
            f"Latest export: {latest.get('package_dir')} | "
            f"files={len(latest.get('written_files') or [])} | "
            f"validation={len(latest.get('validation_messages') or [])}"
        )
        self.export_completion_var.set(self._export_completion_text(latest))
        self.export_next_action_var.set(self._export_next_action_text(latest))

    def _require_project_dir(self) -> Path:
        project_dir = Path(self.project_dir.get().strip())
        if not (project_dir / PROJECT_FILE).exists():
            raise ValueError(f"No {PROJECT_FILE} found in {project_dir}")
        return project_dir.resolve()

    def _current_project_dir(self, optional: bool = False) -> Path | None:
        try:
            return self._require_project_dir()
        except Exception:
            if optional:
                return None
            raise

    def _persist_project_settings(self, project_dir: Path) -> None:
        config = load_project_config(project_dir)
        config.project_name = self.project_name.get().strip() or config.project_name
        source_roots = self._current_source_roots()
        if source_roots:
            config.source_roots = [str(path.resolve()) for path in source_roots]
        output_dir = self.output_dir.get().strip()
        if output_dir:
            config.output_root = str(Path(output_dir).resolve())
        config.preset = self.preset.get().strip() or config.preset
        config.export_profile = self.export_profile.get().strip() or config.export_profile
        config.exclude_globs = self._exclude_globs_with_folder_selection(config.exclude_globs)
        config.optional_model_settings.enabled = self.model_enabled.get()
        config.optional_model_settings.model = self.model_name.get().strip() or "gpt-5.4"
        try:
            config.review_thresholds.low_signal_word_count = int(self.review_low_signal_var.get().strip() or "60")
            config.review_thresholds.duplicate_similarity_threshold = float(self.review_duplicate_threshold_var.get().strip() or "0.96")
            config.review_thresholds.low_confidence_threshold = float(self.review_confidence_var.get().strip() or "0.55")
        except ValueError as exc:
            raise ValueError(f"Invalid review threshold value: {exc}") from exc
        save_project_config(project_dir, config)

        secrets = load_secrets(project_dir)
        providers = secrets.get("providers") or {}
        if self.save_api_key.get() and self.api_key_value.get().strip():
            providers["openai"] = {"api_key": self.api_key_value.get().strip()}
        else:
            providers["openai"] = {}
        secrets["providers"] = providers
        save_secrets(project_dir, secrets)

    def _on_review_selected(self, _event) -> None:
        if self.review_tree is None:
            return
        selection = self.review_tree.selection()
        if not selection:
            return
        tree_id = selection[0]
        item = self._review_tree_map.get(tree_id)
        if item:
            self.selected_review_id.set(str(item.get("review_id") or ""))
            self._populate_review_editor(item)

    def _populate_review_editor(self, item: dict) -> None:
        self.selected_review_id.set(str(item.get("review_id") or ""))
        self.review_status_edit.set(str(item.get("status") or "open"))
        self.review_title_edit.set(str(item.get("override_title") or ""))
        self.review_domain_edit.set(str(item.get("override_domain") or ""))
        document = self._document_for_review_item(item)
        warnings = ", ".join(document.get("warnings") or []) or "No extraction warnings."
        strategies = document.get("retry_strategies") or ["default"]
        self.review_retry_strategy.set(str(document.get("last_retry_strategy") or strategies[0]))
        self.review_meta_var.set(
            f"File: {Path(item.get('source_path', '')).name}\n"
            f"Type: {document.get('document_type', 'unknown')} | Method: {document.get('extraction_method', 'unknown')}\n"
            f"Status: {document.get('extraction_status', 'unknown')} | Quality: {document.get('quality_score', 0):.2f}\n"
            f"Warnings: {warnings}"
        )
        self.review_issue_title_var.set(f"{item.get('kind', 'issue').replace('_', ' ').title()} [{item.get('severity', 'unknown')}]")
        self.review_issue_reason_var.set(item.get("detail") or "No issue detail recorded.")
        self.review_issue_action_var.set(self._review_recommended_action(item, document))
        self._set_review_retry_strategies(strategies)
        self.review_preview_units = list(document.get("preview_units") or [])
        if not self.review_preview_units:
            preview = document.get("preview_excerpt") or item.get("detail") or "No preview available."
            self.review_preview_units = [{"label": "Preview", "text": str(preview), "page_number": 0, "ocr_used": False}]
        self.review_preview_index = 0
        self._render_preview_unit()
        if self.review_note_text:
            self.review_note_text.delete("1.0", END)
            self.review_note_text.insert(END, str(item.get("resolution_note") or ""))
        self._render_duplicate_comparison(item, document)
        self._refresh_review_session_summary(item, document)

    def _sort_review_by(self, column: str) -> None:
        if self.review_sort_column == column:
            self.review_sort_desc = not self.review_sort_desc
        else:
            self.review_sort_column = column
            self.review_sort_desc = False
        self._refresh_review_display(self._current_project_dir(optional=True))

    def _set_review_filter(self, value: str) -> None:
        self.review_filter.set(value)
        self.view_state.review_filter = value
        if self.view_state.active_view == "review":
            self._render_current_view()

    def _filtered_review_items(self, project_dir: Path | None) -> list[dict]:
        if not project_dir:
            return []
        items = load_reviews(project_dir).get("items", []) or []
        mode = self.review_filter.get()
        if mode == "All":
            filtered = items
        elif mode == "Open":
            filtered = [item for item in items if item.get("status") == "open"]
        elif mode == "Accepted":
            filtered = [item for item in items if item.get("status") == "accepted"]
        elif mode == "Rejected":
            filtered = [item for item in items if item.get("status") == "rejected"]
        elif mode == "Extraction Issues":
            filtered = [item for item in items if item.get("kind") in {"extraction_issue", "empty"}]
        elif mode == "Duplicates":
            filtered = [item for item in items if item.get("kind") == "duplicate"]
        elif mode == "Taxonomy":
            filtered = [item for item in items if item.get("kind") == "taxonomy"]
        elif mode == "Low Confidence OCR":
            filtered = [item for item in items if item.get("kind") == "ocr"]
        elif mode == "Low Signal":
            filtered = [item for item in items if item.get("kind") == "low_signal"]
        elif mode == "AI Low Confidence":
            filtered = [item for item in items if item.get("kind") == "ai_low_confidence"]
        else:
            filtered = items
        return sorted(filtered, key=self._review_sort_key, reverse=self.review_sort_desc)

    def _review_counts(self) -> dict[str, int]:
        project_dir = self._current_project_dir(optional=True)
        items = load_reviews(project_dir).get("items", []) if project_dir else []
        return {
            "open": sum(1 for item in items if item.get("status") == "open"),
            "accepted": sum(1 for item in items if item.get("status") == "accepted"),
            "rejected": sum(1 for item in items if item.get("status") == "rejected"),
        }

    def _set_review_retry_strategies(self, strategies: list[str]) -> None:
        normalized = strategies or ["default"]
        if self.review_retry_combo is not None:
            self.review_retry_combo.configure(values=normalized)
        if self.review_retry_strategy.get() not in normalized:
            self.review_retry_strategy.set(normalized[0])

    def _render_preview_unit(self) -> None:
        if not self.review_preview_text:
            return
        self.review_preview_text.delete("1.0", END)
        if not self.review_preview_units:
            self.review_preview_label_var.set("Preview")
            self.review_preview_photo = None
            if self.review_preview_image_label:
                self.review_preview_image_label.configure(image="", text="")
            self.review_preview_text.insert(END, "No preview available.")
            return
        project_dir = self._current_project_dir(optional=True)
        item = self._current_selected_review_item()
        payload = None
        if project_dir and item:
            payload = render_document_preview(project_dir, str(item.get("source_path") or ""), self.review_preview_index)
        current = payload or self.review_preview_units[self.review_preview_index]
        self._render_preview_strip()
        label = current.get("label", "Preview")
        total = int(current.get("unit_count") or len(self.review_preview_units))
        current_index = int(current.get("unit_index", self.review_preview_index) or 0)
        self.review_preview_label_var.set(
            f"{label} ({current_index + 1}/{max(1, total)})"
        )
        if self.review_preview_image_label:
            image_path = str(current.get("image_path") or "")
            if image_path:
                try:
                    image = PhotoImage(file=image_path)
                    if image.width() > 340:
                        image = image.subsample(max(1, image.width() // 340 + (1 if image.width() % 340 else 0)))
                    self.review_preview_photo = image
                    self.review_preview_image_label.configure(image=self.review_preview_photo, text="")
                except Exception:
                    self.review_preview_photo = None
                    self.review_preview_image_label.configure(image="", text="Preview image could not be displayed.")
            else:
                self.review_preview_photo = None
                error = str(current.get("error") or "")
                self.review_preview_image_label.configure(image="", text=error if error else "")
        self.review_preview_text.insert(END, str(current.get("text") or "No preview available."))

    def _move_preview_unit(self, direction: int) -> None:
        if not self.review_preview_units:
            return
        self.review_preview_index = (self.review_preview_index + direction) % len(self.review_preview_units)
        self._render_preview_unit()

    def _current_selected_review_item(self) -> dict | None:
        review_id = self.selected_review_id.get().strip()
        if not review_id:
            return None
        for item in self._review_tree_map.values():
            if str(item.get("review_id") or "") == review_id:
                return item
        project_dir = self._current_project_dir(optional=True)
        if not project_dir:
            return None
        for item in load_reviews(project_dir).get("items", []) or []:
            if str(item.get("review_id") or "") == review_id:
                return item
        return None

    def _bulk_retry_doc_type_values(self) -> list[str]:
        project_dir = self._current_project_dir(optional=True)
        if not project_dir:
            return ["all"]
        state = load_state(project_dir)
        doc_types = sorted({
            str((record.get("document") or {}).get("document_type") or "unknown")
            for record in (state.get("documents") or {}).values()
        })
        return ["all", *[doc_type for doc_type in doc_types if doc_type]]

    def _load_diagnostics_payload(self) -> dict | None:
        project_dir = self._current_project_dir(optional=True)
        if not project_dir:
            self.diagnostics_summary_var.set("No project loaded.")
            return None
        paths = diagnostics_paths(project_dir)
        if not paths["json_path"].exists():
            self.diagnostics_summary_var.set("No diagnostics file found yet.")
            return None
        payload = json.loads(paths["json_path"].read_text(encoding="utf-8"))
        self.diagnostics_summary_var.set(
            f"Diagnostics loaded from {paths['json_path'].name} at {payload.get('generated_at', '')}."
        )
        return payload

    def _diagnostics_issue_lines(self, payload: dict) -> list[str]:
        degraded = payload.get("degraded_documents") or []
        if self.diagnostics_filter_var.get() == "Open Reviews":
            return ["Switch filter to Degraded or All to inspect degraded documents."]
        if not degraded:
            return ["No degraded documents recorded."]
        return [
            f"[{item.get('status', 'unknown')}] {Path(str(item.get('source_path', ''))).name} :: {item.get('reason', '')}"
            for item in degraded
        ]

    def _diagnostics_review_lines(self, payload: dict) -> list[str]:
        reviews = payload.get("open_reviews") or []
        if self.diagnostics_filter_var.get() == "Degraded":
            return ["Switch filter to Open Reviews or All to inspect current blockers."]
        if not reviews:
            return ["No open review items."]
        return [
            f"[{item.get('severity', 'unknown')}] {Path(str(item.get('source_path', ''))).name} :: "
            f"{item.get('kind', 'review')} :: {item.get('title', '')}"
            for item in reviews
        ]

    def _diagnostics_folder_candidates(self, payload: dict) -> list[dict]:
        source_root_text = self.source_dir.get().strip()
        if not source_root_text:
            return []
        source_root = Path(source_root_text)
        counts: dict[str, dict[str, int]] = {}
        for item in payload.get("degraded_documents") or []:
            source_path = Path(str(item.get("source_path") or ""))
            try:
                relative = source_path.relative_to(source_root)
                folder_name = relative.parts[0] if len(relative.parts) > 1 else "."
            except Exception:
                continue
            if folder_name in {"", "."}:
                continue
            bucket = counts.setdefault(folder_name, {"count": 0, "failed": 0, "partial": 0})
            bucket["count"] += 1
            status = str(item.get("status") or "")
            if status == "failed":
                bucket["failed"] += 1
            if status == "partial":
                bucket["partial"] += 1
        rows = [
            {"folder": folder, **metrics}
            for folder, metrics in counts.items()
        ]
        return sorted(rows, key=lambda row: (-row["count"], -row["failed"], row["folder"]))

    def _project_log_lines(self) -> list[str]:
        project_dir = self._current_project_dir(optional=True)
        if not project_dir:
            return ["No project log available."]
        log_path = state_root(project_dir) / "logs" / "project.log"
        if not log_path.exists():
            return ["No project log entries yet."]
        try:
            lines = [line.strip() for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception:
            return [f"Project log could not be read: {log_path}"]
        return lines[-40:] or ["No project log entries yet."]

    def _parse_project_log_line(self, line: str) -> dict:
        trimmed = line.strip()
        if not trimmed:
            return {"timestamp": "", "kind": "unknown", "summary": "", "raw": line}
        if " " not in trimmed:
            return {"timestamp": "", "kind": "unknown", "summary": trimmed, "raw": line}
        timestamp, remainder = trimmed.split(" ", 1)
        kind, detail = (remainder.split(" ", 1) + [""])[:2] if " " in remainder else (remainder, "")
        fields: dict[str, str] = {}
        matches = list(re.finditer(r"(\w+)=", detail))
        for index, match in enumerate(matches):
            key = match.group(1)
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(detail)
            fields[key] = detail[start:end].strip()
        summary = {
            "scan": f"Scan run: {detail.strip()}",
            "review_update": f"Review updated: {fields.get('review_id', '')} -> {fields.get('status', '')}",
            "duplicate_promote": f"Duplicate canonical changed: {Path(fields.get('canonical', '')).name or 'unknown'}",
            "export": f"Export completed: {Path(fields.get('package', '')).name or 'package'}",
        }.get(kind, detail.strip() or kind)
        return {
            "timestamp": timestamp,
            "kind": kind,
            "summary": summary,
            "raw": line,
            "fields": fields,
        }

    def _history_activity_items(self) -> list[dict]:
        rows = []
        for line in self._project_log_lines():
            if line.startswith("No project log") or line.startswith("Project log could not"):
                continue
            rows.append(self._parse_project_log_line(line))
        return rows[-24:]

    def _populate_history_activity_tree(self) -> None:
        if self.history_activity_tree is None:
            return
        self._history_activity_map = {}
        for item_id in self.history_activity_tree.get_children():
            self.history_activity_tree.delete(item_id)
        items = list(reversed(self._history_activity_items()))
        if not items:
            self.history_activity_tree.insert("", END, iid="history-empty", values=("", "none", "No project activity yet."))
            return
        for index, item in enumerate(items, start=1):
            tree_id = f"history::{index}"
            self._history_activity_map[tree_id] = item
            self.history_activity_tree.insert(
                "",
                END,
                iid=tree_id,
                values=(item.get("timestamp", ""), item.get("kind", ""), item.get("summary", "")),
            )
        first = next(iter(self._history_activity_map.keys()), "")
        if first:
            self.history_activity_tree.selection_set(first)

    def _history_timeline_lines(self) -> list[str]:
        lines: list[str] = []
        if self._process_log_lines:
            lines.append("Processing")
            lines.extend(f"- {line}" for line in self._process_log_lines[-12:])
        if self._export_log_lines:
            if lines:
                lines.append("")
            lines.append("Export")
            lines.extend(f"- {line}" for line in self._export_log_lines[-12:])
        if not lines:
            lines.append("No scan or export activity recorded in this session.")
        return lines

    def _current_history_activity(self) -> dict | None:
        if self.history_activity_tree is None:
            return None
        selected = self.history_activity_tree.selection()
        if not selected:
            return None
        return self._history_activity_map.get(selected[0])

    def _render_preview_strip(self) -> None:
        if self.review_thumbnail_strip is None:
            return
        for child in self.review_thumbnail_strip.winfo_children():
            child.destroy()
        self.review_thumbnail_buttons = []
        self.review_thumbnail_photos = []
        project_dir = self._current_project_dir(optional=True)
        item = self._current_selected_review_item()
        if not project_dir or not item:
            return
        strip_items = render_document_preview_strip(project_dir, str(item.get("source_path") or ""))
        if not strip_items:
            return
        for entry in strip_items:
            unit_index = int(entry.get("unit_index", 0))
            image_path = str(entry.get("image_path") or "")
            button = ttk.Button(
                self.review_thumbnail_strip,
                text=str(entry.get("label") or ""),
                style="Primary.TButton" if unit_index == self.review_preview_index else "Ghost.TButton",
                command=lambda index=unit_index: self._select_preview_unit(index),
            )
            if image_path:
                try:
                    thumb = PhotoImage(file=image_path)
                    if thumb.width() > 72:
                        thumb = thumb.subsample(max(1, thumb.width() // 72 + (1 if thumb.width() % 72 else 0)))
                    self.review_thumbnail_photos.append(thumb)
                    button.configure(image=thumb, compound=TOP)
                except Exception:
                    pass
            button.pack(side=LEFT, padx=(0, 6))
            self.review_thumbnail_buttons.append(button)

    def _select_preview_unit(self, index: int) -> None:
        if not self.review_preview_units:
            return
        self.review_preview_index = max(0, min(index, len(self.review_preview_units) - 1))
        self._render_preview_unit()

    def _format_scan_summary(self, report: dict, prefix: str = "Scan complete") -> str:
        return (
            f"{prefix}: processed={report.get('processed', 0)} "
            f"partial={report.get('partial', 0)} "
            f"failed={report.get('failed', 0)} "
            f"unsupported={report.get('unsupported', 0)} "
            f"metadata_only={report.get('metadata_only', 0)} "
            f"review={report.get('review_required', 0)} "
            f"skipped={report.get('skipped', 0)}"
        )

    def _current_workspace_summary(self) -> dict[str, int]:
        project_dir = self._current_project_dir(optional=True)
        if not project_dir:
            return {
                "source_roots": 0,
                "documents": 0,
                "open_reviews": 0,
                "exports": 0,
                "knowledge_items": 0,
                "validation_count": 0,
                "changed_docs": 0,
                "skipped_docs": 0,
                "partial_docs": 0,
                "failed_docs": 0,
                "metadata_only_docs": 0,
            }
        config = load_project_config(project_dir)
        state = load_state(project_dir)
        reviews = load_reviews(project_dir)
        documents = state.get("documents") or {}
        exports = state.get("exports") or []
        latest = exports[-1] if exports else {}
        return {
            "source_roots": len(config.source_roots),
            "documents": len(documents),
            "open_reviews": sum(1 for item in (reviews.get("items") or []) if item.get("status") == "open"),
            "exports": len(exports),
            "knowledge_items": sum(int((record.get("document") or {}).get("knowledge_item_count") or 0) for record in documents.values()),
            "validation_count": len(latest.get("validation_messages") or []),
            "changed_docs": sum(1 for record in documents.values() if (record.get("document") or {}).get("review_status") == "flagged"),
            "skipped_docs": sum(1 for record in documents.values() if (record.get("document") or {}).get("review_status") == "clean"),
            "partial_docs": sum(1 for record in documents.values() if (record.get("document") or {}).get("extraction_status") == "partial"),
            "failed_docs": sum(1 for record in documents.values() if (record.get("document") or {}).get("extraction_status") == "failed"),
            "metadata_only_docs": sum(1 for record in documents.values() if (record.get("document") or {}).get("extraction_status") == "metadata_only"),
        }

    def _build_next_actions(self, summary: dict[str, int]) -> list[str]:
        if not self.view_state.has_project:
            return [
                "Pick the folder to scan and the folder where GPT files should go.",
                "Let the app create the internal project data automatically.",
                "Keep AI disabled until you actually need it.",
            ]
        if summary["documents"] == 0:
            return [
                "Run the first scan to populate the corpus state.",
                "Check source roots and output location in Sources.",
            ]
        if summary.get("failed_docs", 0) > 0:
            return [
                "Review extraction failures before trusting the export package.",
                "Use Rescan Failed after adjusting source files or dependencies.",
            ]
        if summary["open_reviews"] > 0:
            return [
                "Resolve duplicate and low-confidence review items.",
                "Override domain/title where the model was uncertain.",
            ]
        if summary["exports"] == 0:
            return [
                "Validate the project for package readiness.",
                "Export the package once the review queue is clean.",
            ]
        return [
            "Open the latest export folder and inspect artifacts.",
            "Rerun scan when source documents change.",
        ]

    def _corpus_health_label(self, summary: dict[str, int]) -> str:
        if summary.get("failed_docs", 0):
            return f"Corpus health: blocked ({summary['failed_docs']} failed)"
        if summary["open_reviews"] or summary.get("partial_docs", 0):
            return f"Corpus health: review needed ({summary['open_reviews']} open, {summary.get('partial_docs', 0)} partial)"
        if summary["documents"] == 0:
            return "Corpus health: not scanned"
        return "Corpus health: ready for export"

    def _build_export_cards(self, latest: dict | None) -> list[tuple[str, tuple[str, str, str]]]:
        summary = self._current_workspace_summary()
        if not latest:
            return [
                ("knowledge_core", ("0", "muted", "No package exported yet.")),
                ("blockers", (str(summary["open_reviews"]), "warn" if summary["open_reviews"] else "muted", "Open review blockers.")),
                ("footprint", ("0 KB", "muted", "No package exported yet.")),
            ]
        files = [Path(path).name for path in (latest.get("written_files") or [])]
        footprint = sum(Path(path).stat().st_size for path in latest.get("written_files") or [] if Path(path).exists())
        return [
            ("knowledge_core", (str(sum(1 for name in files if name.startswith("knowledge_core"))), "primary", "Core answer files.")),
            ("procedures", (str(sum(1 for name in files if name.startswith("procedures"))), "success", "Actionable workflow pages.")),
            ("blockers", (str(summary["open_reviews"]), "warn" if summary["open_reviews"] else "success", "Unresolved review blockers.")),
            ("footprint", (f"{footprint // 1024} KB", "warn" if latest.get("validation_messages") else "success", "Current package size.")),
        ]

    def _header_progress_text(self) -> str:
        summary = self._current_workspace_summary()
        if self.view_state.active_view == "processing":
            return (
                f"Docs {summary.get('documents', 0)} | Partial {summary.get('partial_docs', 0)} | "
                f"Failed {summary.get('failed_docs', 0)} | Open review {summary.get('open_reviews', 0)}"
            )
        if self.view_state.active_view == "review":
            total_reviews = sum(self._review_counts().values())
            return f"Review {summary.get('open_reviews', 0)} open / {total_reviews} total | Docs {summary.get('documents', 0)}"
        if self.view_state.active_view == "export":
            return (
                f"Readiness {self.export_readiness_var.get() or 'Not ready'} | "
                f"Warnings {summary.get('validation_count', 0)} | Exports {summary.get('exports', 0)}"
            )
        if self.view_state.active_view == "diagnostics":
            return (
                f"Diagnostics: failed {summary.get('failed_docs', 0)} | partial {summary.get('partial_docs', 0)} | "
                f"open review {summary.get('open_reviews', 0)}"
            )
        return f"Docs {summary.get('documents', 0)} | Review {summary.get('open_reviews', 0)} | Exports {summary.get('exports', 0)}"

    def _append_process_log(self, line: str) -> None:
        self._process_log_lines.append(line)
        self._context_notes.append(line)
        if self.process_log:
            self._populate_text_widget(self.process_log, self._process_log_lines)

    def _append_export_log(self, line: str) -> None:
        self._export_log_lines.append(line)
        self._context_notes.append(line)
        if self.export_log:
            self._populate_text_widget(self.export_log, self._export_log_lines)

    def _guided_mode_active(self) -> bool:
        return self.workflow_mode.get() != "advanced" and not self.show_advanced_controls.get()

    def _plain_step_label(self, step_id: str) -> str:
        labels = {
            "home": "Start",
            "sources": "Pick Folders",
            "processing": "Scan Files",
            "review": "Fix Issues",
            "export": "Get GPT Files",
        }
        return labels.get(step_id, step_id.title())

    def _render_guided_card(self, parent, eyebrow: str, title: str, detail: str, *, tone: str = "primary", padding: int | None = None):
        card = ttk.Frame(parent, style="PanelAlt.TFrame", padding=padding or self.spacing.lg)
        card.pack(fill=X, pady=(0, self.spacing.lg))
        build_status_chip(card, eyebrow, self.palette, tone=tone, wraplength=max(180, self._content_wraplength() // 2)).pack(anchor=W)
        ttk.Label(card, text=title, style="Heading.TLabel", wraplength=self._content_wraplength(), justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
        if detail:
            ttk.Label(card, text=detail, style="Muted.TLabel", wraplength=self._content_wraplength(), justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
        return card

    def _toggle_guided_section(self, variable: BooleanVar) -> None:
        variable.set(not variable.get())
        self._render_current_view()

    def _render_beginner_home_view(self, summary: dict[str, int], next_label: str, next_action, next_detail: str) -> None:
        self._render_workflow_guide(self.content_frame, focus_step="sources")
        has_project = self.view_state.has_project
        hero_title = "Pick the folders you want to use" if not has_project else f"Keep going with {self.project_name.get().strip() or 'this project'}"
        hero_detail = (
            "Choose the folders to scan and the folder where the GPT files should go. The app will guide the rest."
            if not has_project
            else next_detail
        )
        hero = self._render_guided_card(self.content_frame, "Do This Now", hero_title, hero_detail)
        if has_project:
            build_status_chip(hero, self.project_name.get().strip() or "Project ready", self.palette, tone="success", wraplength=300).pack(anchor=W, pady=(self.spacing.sm, 0))
        actions = ttk.Frame(hero, style="PanelAlt.TFrame")
        actions.pack(fill=X, pady=(self.spacing.md, 0))
        self.home_primary_button = ttk.Button(actions, text=next_label, style="Primary.TButton", command=next_action)
        self.home_primary_button.pack(side=LEFT)
        secondary_label = "Open Existing Project" if not has_project else "Pick Different Folders"
        secondary_command = self.on_open_project if not has_project else lambda: self._set_active_view("sources")
        self.home_guided_button = ttk.Button(actions, text=secondary_label, style="Ghost.TButton", command=secondary_command)
        self.home_guided_button.pack(side=LEFT, padx=(self.spacing.sm, 0))

        next_step_id, next_step_text = self._next_workflow_step(summary)
        next_card = self._render_guided_card(
            self.content_frame,
            "What Happens Next",
            next_step_text,
            "You only need to focus on one clear step at a time. The app keeps the rest in order for you.",
            tone="success" if has_project else "primary",
        )
        for line in (
            f"Next main step: {self._plain_step_label(next_step_id)}.",
            "If the scan finds anything odd, you fix it one issue at a time.",
            "When everything looks good, you get the final GPT files.",
        ):
            ttk.Label(next_card, text=f"- {line}", style="Caption.TLabel", wraplength=self._content_wraplength(), justify=LEFT).pack(anchor=W, pady=(self.spacing.xs, 0))

        metrics = ttk.Frame(self.content_frame, style="Panel.TFrame")
        metrics.pack(fill=X, pady=(0, self.spacing.lg))
        for model in (
            MetricCardModel("Scan Folders", str(summary.get("source_roots", 0)), "primary", "Folders included in this project."),
            MetricCardModel("Files Scanned", str(summary.get("documents", 0)), "success", "Files already scanned into the project."),
            MetricCardModel("GPT Exports", str(summary.get("exports", 0)), "primary", "Final GPT file sets created so far."),
        ):
            build_metric_card(metrics, model, self.palette)

        recent_panel = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=self.spacing.lg)
        recent_panel.pack(fill=X)
        ttk.Label(recent_panel, text="Recent Projects", style="Section.TLabel").pack(anchor=W)
        ttk.Label(recent_panel, text="Open one of your recent projects if you want to jump back in quickly.", style="Caption.TLabel", wraplength=self._content_wraplength(), justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
        self._render_recent_projects(recent_panel, heading=False)

    def _render_beginner_sources_view(self) -> None:
        wraplength = self._content_wraplength()
        form = ttk.Frame(self.content_frame, style="Panel.TFrame")
        form.pack(fill=BOTH, expand=True, pady=(self.spacing.lg, 0))
        self.setup_completion_var.set(self._setup_completion_text())
        self.setup_validation_var.set(self._setup_validation_summary())
        self.source_preview_var.set(self._source_preview_summary())
        self.scan_forecast_var.set(self._scan_forecast_summary())
        self.dependency_health_var.set(self._dependency_health_summary())

        primary = self._render_guided_card(
            form,
            "Do This Now",
            "Pick folders and choose where the GPT files should go",
            "Choose one folder or many folders to scan. Then choose the folder where the finished GPT files should be saved.",
        )
        self._render_simple_source_roots_picker(primary)
        self._build_inline_folder_picker(primary, "Save GPT Files To", self.output_dir, self._browse_output_dir)
        ttk.Label(primary, text=self._simple_setup_hint_text(), style="Caption.TLabel", wraplength=wraplength, justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
        defaults = ttk.Frame(primary, style="PanelAlt.TFrame")
        defaults.pack(fill=X, pady=(self.spacing.md, 0))
        build_status_chip(defaults, self.preset.get(), self.palette, tone="primary").pack(side=LEFT)
        build_status_chip(defaults, self.export_profile.get(), self.palette, tone="success").pack(side=LEFT, padx=(self.spacing.sm, 0))
        build_status_chip(defaults, "AI off by default" if not self.model_enabled.get() else "AI on", self.palette, tone="muted" if not self.model_enabled.get() else "warn").pack(side=LEFT, padx=(self.spacing.sm, 0))
        actions = ttk.Frame(primary, style="PanelAlt.TFrame")
        actions.pack(fill=X, pady=(self.spacing.md, 0))
        ttk.Button(actions, text="Scan Files", style="Primary.TButton", command=self.on_simple_setup_and_scan).pack(side=LEFT)
        ttk.Button(actions, text="Save Folder Choices", style="Ghost.TButton", command=self.on_simple_setup).pack(side=LEFT, padx=(self.spacing.sm, 0))
        ttk.Button(actions, text="Open Existing Project", style="Ghost.TButton", command=self.on_open_project).pack(side=LEFT, padx=(self.spacing.sm, 0))

        next_card = self._render_guided_card(
            form,
            "What Happens Next",
            "We save these folders and get ready to scan",
            self.setup_validation_var.get(),
            tone="success" if self._is_setup_complete() else "warn",
        )
        for line in (
            "The app saves your folder choices.",
            "It keeps its own workspace files out of your way.",
            "Next you scan the files and fix anything that needs attention.",
        ):
            ttk.Label(next_card, text=f"- {line}", style="Caption.TLabel", wraplength=wraplength, justify=LEFT).pack(anchor=W, pady=(self.spacing.xs, 0))
        if self._is_setup_complete():
            self._render_step_complete_panel(next_card, "Step Complete: Setup", self.setup_completion_var.get(), "Scan Files", self.on_simple_setup_and_scan)

        details = self._render_guided_card(
            form,
            "More Details",
            "Preview the scan and check this computer",
            f"{self.source_preview_var.get()} {self.dependency_health_var.get()}",
            tone="muted",
        )
        ttk.Button(
            details,
            text="Hide Details" if self.show_beginner_source_details.get() else "Show More",
            style="Ghost.TButton",
            command=lambda: self._toggle_guided_section(self.show_beginner_source_details),
        ).pack(anchor=W, pady=(self.spacing.sm, 0))
        build_status_chip(details, self.scan_forecast_var.get(), self.palette, tone="primary", wraplength=wraplength).pack(anchor=W, pady=(self.spacing.sm, 0))
        if self.show_beginner_source_details.get():
            ttk.Label(details, text="Setup Check", style="Section.TLabel").pack(anchor=W, pady=(self.spacing.md, 0))
            for line in self._setup_validation_lines():
                ttk.Label(details, text=f"- {line}", style="Caption.TLabel", wraplength=wraplength, justify=LEFT).pack(anchor=W, pady=(self.spacing.xs, 0))
            ttk.Label(details, text="Source Preview", style="Section.TLabel").pack(anchor=W, pady=(self.spacing.md, 0))
            for line in self._source_preview_lines():
                ttk.Label(details, text=f"- {line}", style="Caption.TLabel", wraplength=wraplength, justify=LEFT).pack(anchor=W, pady=(self.spacing.xs, 0))
            self._render_source_folder_controls(details)
            ttk.Label(details, text="Computer Check", style="Section.TLabel").pack(anchor=W, pady=(self.spacing.md, 0))
            for line in self._dependency_health_lines():
                ttk.Label(details, text=f"- {line}", style="Caption.TLabel", wraplength=wraplength, justify=LEFT).pack(anchor=W, pady=(self.spacing.xs, 0))

    def _render_beginner_processing_view(self, summary: dict[str, int], report: dict, compact_processing: bool, summary_wrap: int) -> None:
        self.processing_recommendation_var.set(self._processing_recommendation(summary, report))
        decision_label, decision_tone, decision_detail = self._post_scan_decision(summary, report)
        self.processing_decision_title_var.set(decision_label)
        self.processing_decision_detail_var.set(decision_detail)
        self.scan_completion_var.set(self._scan_completion_text(summary, report))

        primary = self._render_guided_card(
            self.content_frame,
            "Do This Now",
            "Scan Files",
            self.processing_summary_var.get(),
        )
        ttk.Label(primary, text=self._processing_guidance(summary, report), style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
        build_status_chip(primary, self.processing_recommendation_var.get(), self.palette, tone="primary", wraplength=summary_wrap).pack(anchor=W, pady=(self.spacing.sm, 0))
        actions = ttk.Frame(primary, style="PanelAlt.TFrame")
        actions.pack(fill=X, pady=(self.spacing.md, 0))
        if compact_processing:
            for column in range(2):
                actions.columnconfigure(column, weight=1)
            ttk.Button(actions, text="Scan Files" if summary.get("documents", 0) == 0 else "Scan Again", style="Primary.TButton", command=self.on_scan).grid(row=0, column=0, sticky="ew", padx=(0, self.spacing.sm))
            ttk.Button(actions, text=self._processing_continue_label(summary), style="Ghost.TButton", command=self.on_continue_from_processing).grid(row=0, column=1, sticky="ew")
        else:
            ttk.Button(actions, text="Scan Files" if summary.get("documents", 0) == 0 else "Scan Again", style="Primary.TButton", command=self.on_scan).pack(side=LEFT)
            ttk.Button(actions, text=self._processing_continue_label(summary), style="Ghost.TButton", command=self.on_continue_from_processing).pack(side=LEFT, padx=(self.spacing.sm, 0))

        next_card = self._render_guided_card(
            self.content_frame,
            "What Happens Next",
            self.processing_decision_title_var.get(),
            self.processing_decision_detail_var.get(),
            tone=decision_tone,
        )
        ttk.Label(next_card, text=self.processing_recommendation_var.get(), style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
        if summary.get("documents", 0):
            self._render_step_complete_panel(next_card, "Step Complete: Scan", self.scan_completion_var.get(), self._processing_continue_label(summary), self.on_continue_from_processing, tone=decision_tone)

        metrics = ttk.Frame(self.content_frame, style="Panel.TFrame")
        metrics.pack(fill=X, pady=(0, self.spacing.lg))
        for model in (
            MetricCardModel("Scanned", str(report.get("processed", 0)), "primary", "Files checked in the latest scan."),
            MetricCardModel("Needs Review", str(summary.get("open_reviews", 0)), "warn" if summary.get("open_reviews", 0) else "success", "Files that still need a decision."),
            MetricCardModel("Failed", str(report.get("failed", 0)), "danger" if report.get("failed", 0) else "success", "Files the app could not read cleanly."),
        ):
            build_metric_card(metrics, model, self.palette)

        details = self._render_guided_card(
            self.content_frame,
            "More Details",
            "See the scan details",
            "Open this section if you want to inspect issues, file types, and the scan timeline.",
            tone="muted",
        )
        detail_actions = ttk.Frame(details, style="PanelAlt.TFrame")
        detail_actions.pack(fill=X, pady=(self.spacing.sm, 0))
        ttk.Button(
            detail_actions,
            text="Hide Details" if self.show_beginner_processing_details.get() else "Show More",
            style="Ghost.TButton",
            command=lambda: self._toggle_guided_section(self.show_beginner_processing_details),
        ).pack(side=LEFT)
        ttk.Button(detail_actions, text="Open Diagnostics", style="Ghost.TButton", command=self.on_go_to_diagnostics).pack(side=LEFT, padx=(self.spacing.sm, 0))
        ttk.Button(detail_actions, text="Export Diagnostics", style="Ghost.TButton", command=self.on_export_diagnostics).pack(side=LEFT, padx=(self.spacing.sm, 0))
        if not self.show_beginner_processing_details.get():
            self.processing_issue_frame = None
            self.processing_detail_frame = None
            self.processing_issue_log = None
            self.processing_type_log = None
            self.process_log = None
            return

        lower = ttk.Frame(self.content_frame, style="Panel.TFrame")
        lower.pack(fill=BOTH, expand=True, pady=(0, self.spacing.lg))
        left = ttk.Frame(lower, style="PanelAlt.TFrame", padding=self.spacing.lg)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 0 if compact_processing else self.spacing.sm), pady=(0, self.spacing.sm if compact_processing else 0))
        right = ttk.Frame(lower, style="PanelAlt.TFrame", padding=self.spacing.lg)
        right.grid(row=1 if compact_processing else 0, column=0 if compact_processing else 1, sticky="nsew")
        self.processing_issue_frame = left
        self.processing_detail_frame = right
        lower.columnconfigure(0, weight=1)
        lower.columnconfigure(1, weight=1 if not compact_processing else 0)
        lower.rowconfigure(0, weight=1)
        lower.rowconfigure(1, weight=1 if compact_processing else 0)

        ttk.Label(left, text="Recent Issues", style="Section.TLabel").pack(anchor=W)
        issue_lines = [
            f"[{item.get('status')}] {Path(item.get('source_path', '')).name} :: {item.get('reason')}"
            for item in report.get("recent_issues", [])
        ] or ["No recent scan issues."]
        self.processing_issue_log = ScrolledText(left, height=14)
        style_scrolled_text(self.processing_issue_log, self.palette, self.type_scale)
        self.processing_issue_log.pack(fill=BOTH, expand=True, pady=(self.spacing.sm, 0))
        self._populate_text_widget(self.processing_issue_log, issue_lines)

        ttk.Label(right, text="File Types", style="Section.TLabel").pack(anchor=W)
        type_lines = [f"{doc_type}: {count}" for doc_type, count in sorted((report.get("document_types") or {}).items())] or ["No scan report yet."]
        self.processing_type_log = ScrolledText(right, height=8)
        style_scrolled_text(self.processing_type_log, self.palette, self.type_scale)
        self.processing_type_log.pack(fill=BOTH, expand=True, pady=(self.spacing.sm, self.spacing.md))
        self._populate_text_widget(self.processing_type_log, type_lines)

        ttk.Label(right, text="Scan Timeline", style="Section.TLabel").pack(anchor=W)
        self.process_log = ScrolledText(right, height=10)
        style_scrolled_text(self.process_log, self.palette, self.type_scale)
        self.process_log.pack(fill=BOTH, expand=True, pady=(self.spacing.sm, 0))
        self._populate_text_widget(self.process_log, self._process_log_lines or ["No scan events yet."])

    def _render_beginner_export_view(self, latest: dict | None, compact_export: bool, summary_wrap: int) -> None:
        readiness_label, readiness_tone, readiness_detail = self._export_readiness_state()
        self.export_readiness_var.set(readiness_label)
        self.export_readiness_detail_var.set(readiness_detail)

        hero = self._render_guided_card(
            self.content_frame,
            "Do This Now",
            "Get GPT Files",
            self.export_summary_var.get(),
            tone=readiness_tone,
        )
        build_status_chip(hero, self.export_readiness_var.get(), self.palette, tone=readiness_tone).pack(anchor=W, pady=(self.spacing.sm, 0))
        ttk.Label(hero, text=self.export_readiness_detail_var.get(), style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
        ttk.Label(hero, text=self._export_guidance(self._current_workspace_summary()), style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(self.spacing.xs, 0))
        actions = ttk.Frame(hero, style="PanelAlt.TFrame")
        actions.pack(fill=X, pady=(self.spacing.md, 0))
        if compact_export:
            for column in range(2):
                actions.columnconfigure(column, weight=1)
            ttk.Button(actions, text="Get GPT Files", style="Primary.TButton", command=self.on_export).grid(row=0, column=0, sticky="ew", padx=(0, self.spacing.sm))
            ttk.Button(actions, text="Open GPT Files Folder", style="Ghost.TButton", command=self.on_open_output).grid(row=0, column=1, sticky="ew")
        else:
            ttk.Button(actions, text="Get GPT Files", style="Primary.TButton", command=self.on_export).pack(side=LEFT)
            ttk.Button(actions, text="Open GPT Files Folder", style="Ghost.TButton", command=self.on_open_output).pack(side=LEFT, padx=(self.spacing.sm, 0))

        next_card = self._render_guided_card(
            self.content_frame,
            "What Happens Next",
            "Check the package and open the final files",
            self.export_next_action_var.get(),
            tone="success" if latest else readiness_tone,
        )
        ttk.Label(next_card, text=self.export_completion_var.get(), style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
        if latest:
            self._render_step_complete_panel(next_card, "GPT Files Ready", self.export_completion_var.get(), "Open GPT Files Folder", self.on_open_output)

        checklist = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=self.spacing.lg)
        checklist.pack(fill=X, pady=(0, self.spacing.lg))
        ttk.Label(checklist, text="More Actions", style="Section.TLabel").pack(anchor=W)
        ttk.Label(checklist, text="These are helpful if you want one more quality check or want to inspect the package in more detail.", style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
        action_row = ttk.Frame(checklist, style="PanelAlt.TFrame")
        action_row.pack(fill=X, pady=(self.spacing.md, 0))
        ttk.Button(action_row, text="Check Package", style="Ghost.TButton", command=self.on_validate).pack(side=LEFT)
        ttk.Button(action_row, text="Show Diagnostics", style="Ghost.TButton", command=self.on_export_diagnostics).pack(side=LEFT, padx=(self.spacing.sm, 0))
        ttk.Button(action_row, text="Open Output Folder", style="Ghost.TButton", command=self.on_open_output).pack(side=LEFT, padx=(self.spacing.sm, 0))
        for line in self._export_checklist_lines(latest):
            ttk.Label(checklist, text=f"- {line}", style="Caption.TLabel", wraplength=summary_wrap, justify=LEFT).pack(anchor=W, pady=(self.spacing.xs, 0))

        artifact_row = ttk.Frame(self.content_frame, style="Panel.TFrame")
        artifact_row.pack(fill=X, pady=(0, self.spacing.lg))
        for label, detail in self._build_export_cards(latest):
            build_metric_card(artifact_row, MetricCardModel(label, detail[0], detail[1], detail[2]), self.palette)

        lower = ttk.Frame(self.content_frame, style="Panel.TFrame")
        lower.pack(fill=BOTH, expand=True, pady=(0, self.spacing.lg))
        left = ttk.Frame(lower, style="PanelAlt.TFrame", padding=self.spacing.lg)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 0 if compact_export else self.spacing.sm), pady=(0, self.spacing.sm if compact_export else 0))
        right = ttk.Frame(lower, style="PanelAlt.TFrame", padding=self.spacing.lg)
        right.grid(row=1 if compact_export else 0, column=0 if compact_export else 1, sticky="nsew")
        self.export_artifact_frame = left
        self.export_validation_frame = right
        lower.columnconfigure(0, weight=1)
        lower.columnconfigure(1, weight=1 if not compact_export else 0)
        lower.rowconfigure(0, weight=1)
        lower.rowconfigure(1, weight=1 if compact_export else 0)

        ttk.Label(left, text="Package Files", style="Section.TLabel").pack(anchor=W)
        artifact_list = ScrolledText(left, height=18)
        style_scrolled_text(artifact_list, self.palette, self.type_scale)
        artifact_list.pack(fill=BOTH, expand=True, pady=(self.spacing.sm, 0))
        self.export_artifact_list = artifact_list
        artifact_lines = [Path(path).name for path in (latest.get("written_files") or [])] if latest else ["No export artifacts yet."]
        self._populate_text_widget(artifact_list, artifact_lines)

        ttk.Label(right, text="Checks And Provenance", style="Section.TLabel").pack(anchor=W)
        self.export_log = ScrolledText(right, height=18)
        style_scrolled_text(self.export_log, self.palette, self.type_scale)
        self.export_log.pack(fill=BOTH, expand=True, pady=(self.spacing.sm, 0))
        lines = self._export_log_lines.copy()
        if latest:
            lines.extend([f"Provenance: {latest.get('provenance_manifest', '')}"])
            lines.extend(latest.get("validation_messages") or ["No validation warnings in the latest export."])
        if not lines:
            lines = ["No export activity yet."]
        self._populate_text_widget(self.export_log, lines)
        self._apply_view_focus("export", "artifacts", self.export_artifact_list)
        self._apply_view_focus("export", "validation", self.export_log)

    def _render_workflow_guide(self, parent, focus_step: str) -> None:
        summary = self._current_workspace_summary()
        steps = self._workflow_steps(summary)
        if self._guided_mode_active():
            panel = ttk.Frame(parent, style="PanelAlt.TFrame", padding=self.spacing.lg)
            panel.pack(fill=X)
            ttk.Label(panel, text="Easy Steps", style="Section.TLabel").pack(anchor=W)
            ttk.Label(panel, textvariable=self.workflow_hint_var, style="Muted.TLabel", wraplength=self._content_wraplength(), justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
            current_step = next((step for step in steps if step["id"] == focus_step), None) or next((step for step in steps if step["status"] == "current"), steps[0])
            current_card = ttk.Frame(panel, style="Panel.TFrame", padding=self.spacing.lg)
            current_card.pack(fill=X, pady=(self.spacing.md, 0))
            build_status_chip(current_card, "Do This Now", self.palette, tone=self._workflow_step_tone(current_step["status"], True)).pack(anchor=W)
            ttk.Label(current_card, text=current_step["title"], style="Heading.TLabel", wraplength=self._content_wraplength(), justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
            ttk.Label(current_card, text=current_step["description"], style="Caption.TLabel", wraplength=self._content_wraplength(), justify=LEFT).pack(anchor=W, pady=(self.spacing.sm, 0))
            ttk.Button(current_card, text=current_step["action_label"], style="Primary.TButton", command=lambda value=current_step["id"]: self._go_to_workflow_step(value)).pack(anchor=W, pady=(self.spacing.md, 0))
            upcoming = ttk.Frame(panel, style="PanelAlt.TFrame")
            upcoming.pack(fill=X, pady=(self.spacing.md, 0))
            ttk.Label(upcoming, text="Coming Up", style="Caption.TLabel").pack(anchor=W)
            upcoming_row = ttk.Frame(upcoming, style="PanelAlt.TFrame")
            upcoming_row.pack(fill=X, pady=(self.spacing.sm, 0))
            compact = self._use_compact_shell_layout()
            for step in steps:
                if step["id"] == current_step["id"]:
                    continue
                mini = ttk.Frame(upcoming_row, style="PanelAlt.TFrame", padding=self.spacing.md)
                if compact:
                    mini.pack(fill=X, pady=(0, self.spacing.sm))
                else:
                    mini.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, self.spacing.sm))
                build_status_chip(mini, step["badge"], self.palette, tone=self._workflow_step_tone(step["status"], False), wraplength=180).pack(anchor=W)
                ttk.Label(mini, text=step["title"], style="Caption.TLabel", wraplength=180, justify=LEFT).pack(anchor=W, pady=(self.spacing.xs, 0))
            return
        panel = ttk.Frame(parent, style="PanelAlt.TFrame", padding=16)
        panel.pack(fill=X)
        header = ttk.Frame(panel, style="PanelAlt.TFrame")
        header.pack(fill=X)
        ttk.Label(header, text="Guided Workflow", style="Section.TLabel").pack(side=LEFT)
        ttk.Label(header, textvariable=self.workflow_hint_var, style="Muted.TLabel", wraplength=760, justify=LEFT).pack(side=LEFT, padx=(12, 0))
        row = ttk.Frame(panel, style="PanelAlt.TFrame")
        row.pack(fill=X, pady=(12, 0))
        for step in steps:
            card = ttk.Frame(row, style="Panel.TFrame", padding=12)
            card.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
            tone = self._workflow_step_tone(step["status"], step["id"] == focus_step)
            build_status_chip(card, step["badge"], self.palette, tone=tone).pack(anchor=W)
            ttk.Label(card, text=step["title"], style="Section.TLabel").pack(anchor=W, pady=(8, 0))
            ttk.Label(card, text=step["description"], style="Caption.TLabel", wraplength=180, justify=LEFT).pack(anchor=W, pady=(6, 0))
            ttk.Button(card, text=step["action_label"], style="Ghost.TButton", command=lambda value=step["id"]: self._go_to_workflow_step(value)).pack(anchor=W, pady=(10, 0))

    def _render_step_complete_panel(self, parent, label: str, detail: str, action_label: str, action, tone: str = "success") -> None:
        panel = ttk.Frame(parent, style="PanelAlt.TFrame", padding=14)
        panel.pack(fill=X, pady=(0, 14))
        build_status_chip(panel, label, self.palette, tone=tone).pack(side=LEFT)
        ttk.Label(panel, text=detail, style="Caption.TLabel", wraplength=760, justify=LEFT).pack(side=LEFT, padx=(10, 0))
        ttk.Button(panel, text=action_label, style="Primary.TButton", command=action).pack(side=RIGHT)

    def _advanced_controls_visible(self) -> bool:
        return self.workflow_mode.get() == "advanced" or self.show_advanced_controls.get()

    def _render_advanced_controls_toggle(self, parent, step_label: str) -> None:
        if self.workflow_mode.get() == "advanced":
            return
        panel = ttk.Frame(parent, style="PanelAlt.TFrame", padding=12)
        panel.pack(fill=X, pady=(0, 14))
        build_status_chip(panel, "Easy Mode", self.palette, tone="primary").pack(side=LEFT)
        ttk.Label(panel, text=f"{step_label} is showing the simpler path. Turn on advanced controls only if you want more tools and more detail.", style="Caption.TLabel", wraplength=760, justify=LEFT).pack(side=LEFT, padx=(10, 0))
        ttk.Button(
            panel,
            text="Hide Advanced Controls" if self.show_advanced_controls.get() else "Show Advanced Controls",
            style="Ghost.TButton",
            command=self._toggle_advanced_controls,
        ).pack(side=RIGHT)

    def _set_transition_notice(self, step: str, title: str, detail: str) -> None:
        self.transition_notice_step.set(step)
        self.transition_notice_title_var.set(title)
        self.transition_notice_detail_var.set(detail)

    def _transition_notice_lines(self, step: str) -> list[str]:
        summary = self._current_workspace_summary()
        if step == "sources":
            return [
                "Project settings were saved to the workspace.",
                "Folder paths and defaults are ready for the next step.",
                "Next: run the first scan to build the corpus snapshot.",
            ]
        if step == "processing":
            lines = [
                "Discovery and extraction finished for the latest scan.",
                f"Documents tracked: {summary.get('documents', 0)}.",
            ]
            if summary.get("failed_docs", 0) or summary.get("open_reviews", 0) or summary.get("partial_docs", 0):
                lines.append("Next: open Review and work through the remaining blockers.")
            else:
                lines.append("Next: continue to Export and package the GPT-ready files.")
            return lines
        if step == "review":
            lines = [
                "The review queue was recalculated from the latest workspace state.",
                f"Open review items remaining: {summary.get('open_reviews', 0)}.",
            ]
            if summary.get("open_reviews", 0):
                lines.append("Next: keep resolving open issues, starting with the selected item.")
            else:
                lines.append("Next: continue to Export or run a final diagnostics check.")
            return lines
        if step == "export":
            return [
                "Package files and provenance sidecars were written successfully.",
                f"Completed exports in this project: {summary.get('exports', 0)}.",
                "Next: open the output folder, inspect artifacts, or upload the package to your GPT.",
            ]
        return []

    def _render_transition_notice(self, parent, step: str) -> None:
        if self.transition_notice_step.get() != step or not self.transition_notice_title_var.get().strip():
            return
        panel = ttk.Frame(parent, style="PanelAlt.TFrame", padding=14)
        panel.pack(fill=X, pady=(0, 14))
        build_status_chip(panel, self.transition_notice_title_var.get(), self.palette, tone="success").pack(side=LEFT)
        ttk.Label(panel, textvariable=self.transition_notice_detail_var, style="Caption.TLabel", wraplength=640, justify=LEFT).pack(side=LEFT, padx=(10, 0))
        ttk.Button(panel, text="Dismiss", style="Ghost.TButton", command=self._clear_transition_notice).pack(side=RIGHT)
        details = ttk.Frame(parent, style="PanelAlt.TFrame", padding=(14, 0, 14, 12))
        details.pack(fill=X, pady=(0, 14))
        for line in self._transition_notice_lines(step):
            ttk.Label(details, text=f"- {line}", style="Caption.TLabel", wraplength=900, justify=LEFT).pack(anchor=W, pady=(4, 0))

    def _workflow_steps(self, summary: dict[str, int]) -> list[dict[str, str]]:
        has_scan = summary.get("documents", 0) > 0
        has_blockers = bool(summary.get("open_reviews", 0) or summary.get("failed_docs", 0) or summary.get("partial_docs", 0))
        guided = self._guided_mode_active()
        steps = [
            {
                "id": "sources",
                "title": "1. Pick Folders" if guided else "1. Setup",
                "badge": "saved" if self.view_state.has_project else "start here",
                "status": "done" if self.view_state.has_project else "current",
                "description": "Choose the folders to scan and where the GPT files should go." if guided else "Choose folders, preset, export profile, and optional AI settings.",
                "action_label": "Pick Folders" if guided else "Go To Setup",
            },
            {
                "id": "processing",
                "title": "2. Scan Files" if guided else "2. Scan",
                "badge": "done" if has_scan else ("next" if self.view_state.has_project else "waiting"),
                "status": "done" if has_scan else ("current" if self.view_state.has_project else "pending"),
                "description": "Scan your files and see what needs attention next." if guided else "Build the working corpus and surface degraded or unsupported files.",
                "action_label": "Scan Files" if guided else "Go To Scan",
            },
            {
                "id": "review",
                "title": "3. Fix Issues" if guided else "3. Review",
                "badge": "clear" if has_scan and not has_blockers else ("fix now" if has_scan else "waiting"),
                "status": "done" if has_scan and not has_blockers else ("current" if has_scan else "pending"),
                "description": "Fix anything the scan could not decide on by itself." if guided else "Resolve failures, partial extraction, duplicates, and taxonomy issues.",
                "action_label": "Fix Issues" if guided else "Go To Review",
            },
            {
                "id": "export",
                "title": "4. Get GPT Files" if guided else "4. Export",
                "badge": "done" if summary.get("exports", 0) else ("ready" if has_scan and not has_blockers else "blocked"),
                "status": "done" if summary.get("exports", 0) else ("current" if has_scan and not has_blockers else "pending"),
                "description": "Create the final GPT files when the project looks ready." if guided else "Validate the package, write the GPT-ready files, and inspect provenance outputs.",
                "action_label": "Get GPT Files" if guided else "Go To Export",
            },
        ]
        self.workflow_hint_var.set(self._workflow_hint(steps, summary))
        return steps

    def _refresh_sidebar_progress(self) -> None:
        summary = self._current_workspace_summary()
        next_step = self._next_workflow_step(summary)
        self.sidebar_next_step_var.set(f"Next step: {next_step[1]}")
        self.sidebar_progress_var.set(self._workflow_progress_text(summary))
        if self.sidebar_progress_frame is not None:
            for child in self.sidebar_progress_frame.winfo_children()[3:]:
                child.destroy()
            chips = ttk.Frame(self.sidebar_progress_frame, style="PanelAlt.TFrame")
            chips.pack(fill=X, pady=(8, 0))
            for step in self._workflow_steps(summary):
                chip = build_status_chip(
                    chips,
                    step["title"].split(". ", 1)[-1],
                    self.palette,
                    tone=self._workflow_step_tone(step["status"], step["id"] == self.view_state.active_view),
                )
                chip.pack(anchor=W, pady=(0, 6))

    def _workflow_progress_text(self, summary: dict[str, int]) -> str:
        if not self.view_state.has_project:
            return "Choose one folder or many folders to scan, then choose where GPT files should be saved."
        if summary["documents"] == 0:
            return "Folder setup is done. The files have not been scanned yet." if self._guided_mode_active() else "Setup is complete. The corpus has not been scanned yet."
        if summary.get("failed_docs", 0):
            return f"{summary['failed_docs']} file(s) still need attention before the final GPT files." if self._guided_mode_active() else f"{summary['failed_docs']} failed document(s) need attention before trusting export."
        if summary.get("open_reviews", 0):
            return f"{summary['open_reviews']} issue(s) still need a decision." if self._guided_mode_active() else f"{summary['open_reviews']} review item(s) remain open."
        if summary.get("exports", 0):
            return f"{summary['exports']} GPT file set(s) have been created for this project." if self._guided_mode_active() else f"{summary['exports']} export run(s) completed for this project."
        return "The project is clean and ready for GPT files." if self._guided_mode_active() else "The corpus is clean and ready to export."

    def _next_workflow_step(self, summary: dict[str, int]) -> tuple[str, str]:
        if not self.view_state.has_project:
            if self.workflow_mode.get() != "advanced":
                return ("sources", "Pick folders to start")
            return ("sources", "Create or open a project")
        if summary["documents"] == 0:
            return ("processing", "Scan files")
        if summary.get("failed_docs", 0) or summary.get("open_reviews", 0) or summary.get("partial_docs", 0):
            return ("review", "Fix issues")
        return ("export", "Get GPT files")

    def _workflow_hint(self, steps: list[dict[str, str]], summary: dict[str, int]) -> str:
        if not self.view_state.has_project:
            return "Start by picking the folders to scan and the folder where the GPT files should be saved." if self._guided_mode_active() else "Start by choosing one folder or many folders to scan and the folder where GPT files should be saved."
        if summary.get("documents", 0) == 0:
            return "Your next step is to scan the selected folders." if self._guided_mode_active() else "Your next step is to scan the selected folders and build the working corpus."
        if summary.get("failed_docs", 0):
            return f"{summary['failed_docs']} file(s) could not be read cleanly. Fix those before you get the final GPT files." if self._guided_mode_active() else f"{summary['failed_docs']} document(s) failed extraction. Resolve those in Review before export."
        if summary.get("open_reviews", 0):
            return f"{summary['open_reviews']} issue(s) still need a decision before the final GPT files." if self._guided_mode_active() else f"{summary['open_reviews']} review item(s) are still open. Clear them before export."
        if summary.get("exports", 0):
            return "The GPT files are already ready. Make a new export any time you scan again or change a review decision." if self._guided_mode_active() else "The project has already been exported. Re-export after any new scan or review changes."
        return "The project is ready. Get the GPT files when you are happy with the results." if self._guided_mode_active() else "The corpus is ready. Export the GPT package when you are satisfied with diagnostics and previews."

    def _workflow_step_tone(self, status: str, is_focus: bool) -> str:
        if is_focus:
            return "primary"
        return {
            "done": "success",
            "current": "warn",
            "pending": "muted",
        }.get(status, "muted")

    def _go_to_workflow_step(self, step_id: str) -> None:
        if step_id == "processing" and not self.view_state.has_project:
            self.on_start_guided_setup()
            return
        self._set_active_view(step_id)

    def _smart_next_step_descriptor(self, summary: dict[str, int]) -> tuple[str, callable, str]:
        if not self.view_state.has_project:
            if self.workflow_mode.get() != "advanced":
                return (
                    "Pick Folders To Start",
                    lambda: self._set_active_view("sources"),
                    "Pick the folders to scan and where the GPT files should be saved. The app will guide the rest.",
                )
            return (
                "Create Project",
                self.on_create_project,
                "Start by creating a workspace or use Guided Setup if you want the app to walk you through the first configuration.",
            )
        if summary.get("documents", 0) == 0:
            return (
                "Scan Files" if self._guided_mode_active() else "Run First Scan",
                self.on_continue_from_processing,
                "The folders are ready. Scan the files so the app can show what needs attention next." if self._guided_mode_active() else "The workspace is configured. Build the first corpus snapshot so the app can show review issues, diagnostics, and export readiness.",
            )
        if summary.get("failed_docs", 0):
            return (
                "Fix Issues" if self._guided_mode_active() else "Resolve Extraction Failures",
                self.on_continue_from_processing,
                f"{summary['failed_docs']} file(s) need help before you trust the final GPT files." if self._guided_mode_active() else f"{summary['failed_docs']} file(s) failed extraction. Review those first before trusting the package.",
            )
        if summary.get("open_reviews", 0) or summary.get("partial_docs", 0):
            return (
                "Fix Issues" if self._guided_mode_active() else "Resolve Review Queue",
                self.on_continue_from_processing,
                f"{summary.get('open_reviews', 0)} issue(s) still need a decision." if self._guided_mode_active() else f"{summary.get('open_reviews', 0)} open review item(s) and {summary.get('partial_docs', 0)} partial document(s) still need judgment.",
            )
        if summary.get("exports", 0):
            return (
                "Open GPT Files Folder" if self._guided_mode_active() else "Open Export Folder",
                self.on_open_output,
                "The GPT files are already ready. Open the folder to inspect them or make a fresh export after changes." if self._guided_mode_active() else "The project already has an export. Open the output folder to inspect the package or re-export after further changes.",
            )
        return (
            "Get GPT Files" if self._guided_mode_active() else "Export Package",
            self.on_export,
            "The project is ready. Create the final GPT files now." if self._guided_mode_active() else "The corpus is clean enough to package. Export the GPT-ready files and inspect the final delivery artifacts.",
        )

    def _smart_primary_action(self) -> tuple[str, callable]:
        summary = self._current_workspace_summary()
        label, command, _detail = self._smart_next_step_descriptor(summary)
        return label, command

    def on_take_next_step(self) -> None:
        summary = self._current_workspace_summary()
        _label, command, _detail = self._smart_next_step_descriptor(summary)
        command()

    def _operation_phase(self, kind: str) -> tuple[str, str]:
        return {
            "scan": ("Scanning corpus", "Discovering files, extracting text, and generating the review queue."),
            "review": ("Updating review queue", "Applying bulk review decisions and recalculating blockers."),
            "review_edit": ("Saving review item", "Recording the selected review decision and refreshing the queue."),
            "validate": ("Validating package", "Checking the workspace for blockers before export."),
            "retry_review": ("Retrying extraction", "Re-running extraction for the selected document."),
            "bulk_retry": ("Retrying matching items", "Re-running extraction for the filtered review set."),
            "duplicate_promote": ("Saving duplicate decision", "Updating the canonical duplicate winner."),
            "diagnostics": ("Exporting diagnostics", "Writing diagnostics reports for degraded documents and open issues."),
            "export": ("Exporting package", "Building the GPT-ready files, provenance, and final package outputs."),
        }.get(kind, (f"{kind.title()} running", "The workspace is processing the requested action."))

    def _processing_guidance(self, summary: dict[str, int], report: dict) -> str:
        if summary.get("documents", 0) == 0:
            return "Run the scan after folder setup. The app will show you what it could read and what needs help." if self._guided_mode_active() else "Run the first scan after setup. The app will keep supported files, degraded files, and unsupported files visible instead of silently skipping them."
        if report.get("failed", 0):
            return "Some files could not be read cleanly. Fix those first, then scan again if needed." if self._guided_mode_active() else "The latest scan found extraction failures. Review those first, then retry failed documents or rescan after fixing dependencies."
        if report.get("partial", 0) or report.get("review_required", 0):
            return "The scan finished, but some files still need a quick decision from you." if self._guided_mode_active() else "The scan completed, but some files need human review. Move to Review to approve acceptable partial results or retry weak extractions."
        return "The scan looks clean. You can move on to the GPT files." if self._guided_mode_active() else "The scan is clean. If the corpus looks right, continue to Export."

    def _processing_recommendation(self, summary: dict[str, int], report: dict) -> str:
        if summary.get("documents", 0) == 0:
            return "Click Scan Files to start the first scan." if self._guided_mode_active() else "Click Scan Project to build the first corpus snapshot."
        if report.get("failed", 0):
            return "Open Fix Issues and start with the files that failed." if self._guided_mode_active() else "Open Review and work through extraction failures first."
        if report.get("partial", 0) or report.get("review_required", 0):
            return "Go to Fix Issues and choose Accept, Skip, or Retry for the flagged files." if self._guided_mode_active() else "Continue to Review to accept, ignore, or retry flagged items."
        return "Go to Get GPT Files and create the final files." if self._guided_mode_active() else "Continue to Export and generate the GPT-ready package."

    def _post_scan_decision(self, summary: dict[str, int], report: dict) -> tuple[str, str, str]:
        if summary.get("documents", 0) == 0:
            return (
                "Ready To Scan",
                "primary",
                "No scan has run yet. Start the first scan to see what needs attention." if self._guided_mode_active() else "No corpus snapshot exists yet. Run the first scan to turn the source folder into a reviewable workspace.",
            )
        if report.get("failed", 0):
            return (
                "Needs Fixes" if self._guided_mode_active() else "Blocked By Extraction Failures",
                "danger",
                f"The latest scan found {report.get('failed', 0)} file(s) that need help." if self._guided_mode_active() else f"The latest scan reported {report.get('failed', 0)} failed document(s). Move to Review, inspect the failed items, and retry only the problem documents.",
            )
        if report.get("partial", 0) or report.get("review_required", 0):
            return (
                "Needs A Quick Check" if self._guided_mode_active() else "Needs Human Review",
                "warn",
                f"The scan finished, but {report.get('review_required', 0)} issue(s) still need your decision." if self._guided_mode_active() else f"The scan finished, but {report.get('review_required', 0)} issue(s) still need judgment. Review the queue before exporting.",
            )
        return (
            "Ready For GPT Files" if self._guided_mode_active() else "Ready For Export",
            "success",
            "The latest scan looks clean. You can move on to the GPT files." if self._guided_mode_active() else "The latest scan is clean. If the diagnostics and previews look right, continue directly to Export.",
        )

    def _processing_continue_label(self, summary: dict[str, int]) -> str:
        if summary["documents"] == 0:
            return "Scan Files" if self._guided_mode_active() else "Run First Scan"
        if summary.get("open_reviews", 0) or summary.get("failed_docs", 0) or summary.get("partial_docs", 0):
            return "Fix Issues" if self._guided_mode_active() else "Continue To Review"
        return "Get GPT Files" if self._guided_mode_active() else "Continue To Export"

    def _review_guidance(self, summary: dict[str, int]) -> str:
        if summary.get("open_reviews", 0) == 0:
            return "The review queue is clear. You can move on to GPT files unless you want one more check first." if self._guided_mode_active() else "The review queue is clear. Continue to Export unless you want to inspect diagnostics first."
        return "Look at one issue at a time. Check the preview, then choose Accept, Skip, or Retry." if self._guided_mode_active() else "Work through the flagged items from left to right: inspect the preview, adjust overrides if needed, then accept, ignore, or retry extraction."

    def _review_progress_text(self) -> str:
        project_dir = self._current_project_dir(optional=True)
        if not project_dir:
            return "Load a project to start reviewing."
        items = self._filtered_review_items(project_dir)
        if not items:
            return "No review issues remain. Continue to Export or inspect Diagnostics."
        review_id = self.selected_review_id.get().strip()
        open_items = [item for item in items if item.get("status") == "open"]
        index = 0
        if review_id:
            for idx, item in enumerate(items, start=1):
                if str(item.get("review_id") or "") == review_id:
                    index = idx
                    break
        if index == 0:
            index = 1
        return f"Issue {index} of {len(items)} in the current queue. Open items remaining: {len(open_items)}."

    def _export_guidance(self, summary: dict[str, int]) -> str:
        if summary.get("failed_docs", 0):
            return "You can still make GPT files, but failed files will be left out. Fix them first if they matter." if self._guided_mode_active() else "Export can still run, but failed documents are excluded. Fix extraction failures if those files matter to the package."
        if summary.get("open_reviews", 0):
            return "Some issues are still open. You can still make GPT files, but they may not be ready yet." if self._guided_mode_active() else "Open review blockers remain. You can export, but the package may carry unresolved quality issues."
        return "Check the package once more if you want, then create the GPT files." if self._guided_mode_active() else "Validate first if you want a final preflight check, then export the package and provenance sidecars."

    def _is_setup_complete(self) -> bool:
        if not self.view_state.has_project:
            return False
        lines = self._setup_validation_lines()
        blockers = [line for line in lines if "missing" in line or "not a folder" in line or "not found" in line or "no local key" in line]
        return not blockers

    def _setup_completion_text(self) -> str:
        if not self._is_setup_complete():
            return "Complete the required setup fields before continuing to Scan."
        return "Setup is complete. The folders, defaults, and saved project settings are ready for the first scan."

    def _scan_completion_text(self, summary: dict[str, int], report: dict) -> str:
        if summary.get("documents", 0) == 0:
            return "No scan has completed yet. Run the first scan to finish this step."
        if report.get("failed", 0):
            return f"Scan finished, but {report.get('failed', 0)} file(s) still need help before you trust the GPT files." if self._guided_mode_active() else f"Scan finished, but {report.get('failed', 0)} failed document(s) still need review before you should trust the package."
        if report.get("partial", 0) or report.get("review_required", 0):
            return f"Scan finished and found {report.get('review_required', 0)} issue(s) for you to review." if self._guided_mode_active() else f"Scan finished and surfaced {report.get('review_required', 0)} issue(s) that need human review before export."
        return "Scan finished cleanly. The project is ready for GPT files." if self._guided_mode_active() else "Scan finished cleanly. The corpus is ready to move forward to Export."

    def _setup_validation_lines(self) -> list[str]:
        lines: list[str] = []
        project_dir = Path(self.project_dir.get().strip()) if self.project_dir.get().strip() else None
        output_dir = Path(self.output_dir.get().strip()) if self.output_dir.get().strip() else None
        checks = [("Project folder", project_dir), ("Output folder", output_dir)]
        for label, path in checks:
            if path is None:
                lines.append(f"{label}: missing")
            elif path.exists() and path.is_dir():
                lines.append(f"{label}: ready")
            elif path.exists() and not path.is_dir():
                lines.append(f"{label}: path exists but is not a folder")
            else:
                lines.append(f"{label}: will be created")
        source_roots = self._current_source_roots()
        if not source_roots:
            lines.append("Scan folders: missing")
        else:
            invalid_sources = [path for path in source_roots if path.exists() and not path.is_dir()]
            missing_sources = [path for path in source_roots if not path.exists()]
            if invalid_sources:
                lines.append(f"Scan folders: {len(invalid_sources)} path(s) exist but are not folders")
            elif missing_sources:
                lines.append(f"Scan folders: {len(missing_sources)} folder(s) not found")
            else:
                lines.append(f"Scan folders: ready ({len(source_roots)} selected)")
        if not self.project_name.get().strip():
            lines.append("Project name: missing")
        else:
            lines.append(f"Project name: {self.project_name.get().strip()}")
        if self.model_enabled.get():
            key_present = bool(self.api_key_value.get().strip())
            lines.append("AI enrichment: enabled with local key" if key_present else "AI enrichment: enabled but no local key entered")
        else:
            lines.append("AI enrichment: disabled")
        lines.append(f"Preset: {self.preset.get().strip() or 'missing'}")
        lines.append(f"Export profile: {self.export_profile.get().strip() or 'missing'}")
        return lines

    def _setup_validation_summary(self) -> str:
        lines = self._setup_validation_lines()
        blockers = [line for line in lines if "missing" in line or "not a folder" in line or "not found" in line or "no local key" in line]
        if blockers:
            return f"Folder setup needs attention: {len(blockers)} item(s) should be checked before the first scan." if self._guided_mode_active() else f"Setup needs attention: {len(blockers)} item(s) should be reviewed before the first scan."
        return "Folder setup looks ready. Save it and move on to Scan Files when you are ready." if self._guided_mode_active() else "Setup looks ready. Save settings and continue to Scan when you are ready."

    def _source_preview_data(self) -> dict:
        source_roots = self._current_source_roots()
        if not source_roots:
            return {
                "exists": False,
                "source_roots": 0,
                "files": 0,
                "supported": 0,
                "unsupported": 0,
                "types": {},
                "invalid_roots": [],
                "unsupported_examples": [],
                "heavy_files": 0,
                "ocr_candidates": 0,
                "estimated_workload": "none",
            }
        invalid_roots = [str(path) for path in source_roots if not path.exists() or not path.is_dir()]
        valid_roots = [path for path in source_roots if path.exists() and path.is_dir()]
        if not valid_roots:
            return {
                "exists": False,
                "source_roots": len(source_roots),
                "files": 0,
                "supported": 0,
                "unsupported": 0,
                "types": {},
                "invalid_roots": invalid_roots,
                "unsupported_examples": [],
                "heavy_files": 0,
                "ocr_candidates": 0,
                "estimated_workload": "none",
            }
        type_counts: dict[str, int] = {}
        folder_counts: dict[str, int] = {}
        folder_metrics: dict[str, dict[str, int]] = {}
        unsupported_examples: list[str] = []
        supported = unsupported = 0
        heavy_files = 0
        ocr_candidates = 0
        file_count = 0
        multi_root = len(valid_roots) > 1
        for source_root in valid_roots:
            root_label = source_root.name or str(source_root)
            files = [path for path in source_root.rglob("*") if path.is_file()]
            file_count += len(files)
            for path in files:
                try:
                    relative = path.relative_to(source_root)
                    if multi_root:
                        folder_name = root_label
                    else:
                        folder_name = relative.parts[0] if len(relative.parts) > 1 else "."
                except Exception:
                    folder_name = root_label if multi_root else "."
                folder_counts[folder_name] = folder_counts.get(folder_name, 0) + 1
                folder_metric = folder_metrics.setdefault(folder_name, {"files": 0, "heavy": 0, "ocr": 0})
                folder_metric["files"] += 1
                suffix = path.suffix.lower()
                if path.stat().st_size >= 5 * 1024 * 1024:
                    heavy_files += 1
                    folder_metric["heavy"] += 1
                if suffix in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
                    ocr_candidates += 1
                    folder_metric["ocr"] += 1
                doc_type = get_supported_doc_type(path)
                if doc_type:
                    supported += 1
                    type_counts[doc_type] = type_counts.get(doc_type, 0) + 1
                else:
                    unsupported += 1
                    if len(unsupported_examples) < 5:
                        unsupported_examples.append(path.name)
        if file_count >= 250 or heavy_files >= 15:
            estimated_workload = "heavy"
        elif file_count >= 75 or heavy_files >= 5 or ocr_candidates >= 20:
            estimated_workload = "moderate"
        else:
            estimated_workload = "light"
        return {
            "exists": True,
            "source_roots": len(valid_roots),
            "files": file_count,
            "supported": supported,
            "unsupported": unsupported,
            "types": dict(sorted(type_counts.items())),
            "folders": dict(sorted(folder_counts.items(), key=lambda item: (-item[1], item[0]))),
            "folder_metrics": folder_metrics,
            "invalid_roots": invalid_roots,
            "unsupported_examples": unsupported_examples,
            "heavy_files": heavy_files,
            "ocr_candidates": ocr_candidates,
            "estimated_workload": estimated_workload,
        }

    def _source_preview_summary(self) -> str:
        preview = self._source_preview_data()
        if not preview["exists"]:
            return "Choose one valid scan folder or many valid scan folders to preview the corpus before scanning."
        return (
            f"Found {preview['files']} file(s) across {preview.get('source_roots', 0)} scan folder(s). "
            f"Likely supported={preview['supported']} unsupported={preview['unsupported']}."
        )

    def _source_preview_lines(self) -> list[str]:
        preview = self._source_preview_data()
        if not preview["exists"]:
            return ["No readable scan folders selected yet."]
        lines = [f"{doc_type}: {count}" for doc_type, count in preview["types"].items()]
        lines.append(f"Heavy files (>5 MB): {preview['heavy_files']}")
        lines.append(f"OCR-likely files (PDF/images): {preview['ocr_candidates']}")
        folder_items = list((preview.get("folders") or {}).items())[:5]
        if folder_items:
            lines.append(
                "Busiest folders: "
                + ", ".join(f"{name}: {count}" for name, count in folder_items)
            )
        if not lines:
            lines.append("No supported document types detected yet.")
        if preview["unsupported_examples"]:
            lines.append(f"Unsupported examples: {', '.join(preview['unsupported_examples'])}")
        if preview.get("invalid_roots"):
            lines.append(f"Invalid scan folders: {', '.join(preview['invalid_roots'][:3])}")
        return lines

    def _scan_forecast_summary(self) -> str:
        preview = self._source_preview_data()
        if not preview["exists"]:
            return "Estimated workload: select one readable scan folder or many readable scan folders first."
        return (
            f"Estimated workload: {preview['estimated_workload']} | roots={preview.get('source_roots', 0)} | "
            f"heavy files={preview['heavy_files']} | OCR-likely={preview['ocr_candidates']}"
        )

    def _source_folder_names(self) -> list[str]:
        preview = self._source_preview_data()
        folders = list((preview.get("folders") or {}).keys())
        return [name for name in folders if name and name != "."]

    def _refresh_source_folder_selection(self) -> None:
        folder_names = self._source_folder_names()
        project_dir = self._current_project_dir(optional=True)
        prior = self._source_folder_selection
        if project_dir:
            config = load_project_config(project_dir)
            config_selection = {}
            for name in folder_names:
                excluded = any(pattern in {f"{name}/**", f"**/{name}/**"} for pattern in (config.exclude_globs or []))
                config_selection[name] = not excluded
            if config_selection:
                prior = {**config_selection, **prior}
        self._source_folder_selection = merge_batch_folder_selection(folder_names, prior)

    def _format_recent_timestamp(self, timestamp: float) -> str:
        if not timestamp:
            return "unknown"
        return time.strftime("%Y-%m-%d %I:%M %p", time.localtime(timestamp))

    def _render_source_folder_controls(self, parent) -> None:
        self._refresh_source_folder_selection()
        folder_names = self._source_folder_names()
        preview = self._source_preview_data()
        folder_metrics = preview.get("folder_metrics") or {}
        panel = ttk.Frame(parent, style="PanelAlt.TFrame", padding=self.spacing.lg)
        panel.pack(fill=X, pady=(8, 0))
        header = ttk.Frame(panel, style="PanelAlt.TFrame")
        header.pack(fill=X)
        ttk.Label(header, text="Folder Selection", style="Caption.TLabel").pack(side=LEFT)
        build_info_button(header, "These toggles write top-level folder exclusions into the project config so you can skip noisy or irrelevant batches before scanning.", self.palette).pack(side=LEFT, padx=(8, 0))
        wraplength = self._content_wraplength()
        compact = self._use_compact_shell_layout()
        if preview.get("source_roots", 0) > 1:
            ttk.Label(panel, text="Top-level folder pruning is available after narrowing the scan to one source root. Multiple scan roots are still supported for scanning and export.", style="Caption.TLabel", wraplength=wraplength, justify=LEFT).pack(anchor=W, pady=(6, 0))
            return
        if not folder_names:
            ttk.Label(panel, text="No top-level subfolders detected under the current source folder.", style="Caption.TLabel", wraplength=wraplength, justify=LEFT).pack(anchor=W, pady=(6, 0))
            return
        selected = set(selected_batch_folder_names(self._source_folder_selection))
        ttk.Label(panel, text=f"Selected folders: {', '.join(sorted(selected)) if selected else 'none'}", style="Muted.TLabel", wraplength=wraplength, justify=LEFT).pack(anchor=W, pady=(6, 10))
        controls = ttk.Frame(panel, style="PanelAlt.TFrame")
        controls.pack(fill=X)
        columns = 1 if compact else 2
        for column in range(columns):
            controls.columnconfigure(column, weight=1)
        for index, name in enumerate(folder_names[:12]):
            var = BooleanVar(value=self._source_folder_selection.get(name, True))
            metrics = folder_metrics.get(name) or {}
            label = f"{name} ({metrics.get('files', 0)} files"
            if metrics.get("heavy", 0):
                label += f", {metrics.get('heavy', 0)} heavy"
            if metrics.get("ocr", 0):
                label += f", {metrics.get('ocr', 0)} OCR"
            label += ")"
            checkbox = ttk.Checkbutton(
                controls,
                text=label,
                variable=var,
                command=lambda folder=name, value=var: self._set_source_folder_selected(folder, bool(value.get())),
            )
            row = index // columns
            column = index % columns
            checkbox.grid(row=row, column=column, sticky="w", padx=(0, self.spacing.lg), pady=(0, self.spacing.sm))
        actions = ttk.Frame(panel, style="PanelAlt.TFrame")
        actions.pack(fill=X, pady=(8, 0))
        if compact:
            actions.columnconfigure(0, weight=1)
            ttk.Button(actions, text="Apply Folder Selection", style="Ghost.TButton", command=self.on_apply_source_folder_selection).grid(row=0, column=0, sticky="ew")
            ttk.Button(actions, text="Select All", style="Ghost.TButton", command=self.on_select_all_source_folders).grid(row=1, column=0, sticky="ew", pady=(8, 0))
            ttk.Button(actions, text="Clear All", style="Ghost.TButton", command=self.on_clear_all_source_folders).grid(row=2, column=0, sticky="ew", pady=(8, 0))
        else:
            ttk.Button(actions, text="Apply Folder Selection", style="Ghost.TButton", command=self.on_apply_source_folder_selection).pack(side=LEFT)
            ttk.Button(actions, text="Select All", style="Ghost.TButton", command=self.on_select_all_source_folders).pack(side=LEFT, padx=(10, 0))
            ttk.Button(actions, text="Clear All", style="Ghost.TButton", command=self.on_clear_all_source_folders).pack(side=LEFT, padx=(10, 0))

    def _set_source_folder_selected(self, folder_name: str, selected: bool) -> None:
        self._source_folder_selection[folder_name] = selected

    def _folder_selection_exclude_globs(self) -> list[str]:
        selected = set(selected_batch_folder_names(self._source_folder_selection))
        deselected = [name for name in self._source_folder_names() if name not in selected]
        return [f"{name}/**" for name in deselected]

    def _exclude_globs_with_folder_selection(self, existing_patterns: list[str]) -> list[str]:
        folder_names = set(self._source_folder_names())
        base = []
        for pattern in existing_patterns or []:
            if any(pattern in {f"{name}/**", f"**/{name}/**"} for name in folder_names):
                continue
            base.append(pattern)
        return [*base, *self._folder_selection_exclude_globs()]

    def on_select_all_source_folders(self) -> None:
        for folder_name in self._source_folder_names():
            self._source_folder_selection[folder_name] = True
        self._render_current_view()

    def on_clear_all_source_folders(self) -> None:
        for folder_name in self._source_folder_names():
            self._source_folder_selection[folder_name] = False
        self._render_current_view()

    def on_apply_source_folder_selection(self) -> None:
        project_dir = self._current_project_dir(optional=True)
        if not project_dir:
            self.banner_var.set("Folder selection staged. Create or save the project to persist it.")
            self._refresh_shell()
            return
        config = load_project_config(project_dir)
        selected = set(selected_batch_folder_names(self._source_folder_selection))
        deselected = [name for name in self._source_folder_names() if name not in selected]
        config.exclude_globs = self._exclude_globs_with_folder_selection(config.exclude_globs)
        save_project_config(project_dir, config)
        self.banner_var.set(f"Folder selection applied: {len(selected)} included, {len(deselected)} excluded.")
        self._refresh_shell()

    def on_exclude_folder_from_diagnostics(self, folder_name: str) -> None:
        self._refresh_source_folder_selection()
        if folder_name not in self._source_folder_names():
            self.banner_var.set(f"Folder not found in source selection: {folder_name}")
            self._refresh_shell()
            return
        self._source_folder_selection[folder_name] = False
        self.on_apply_source_folder_selection()
        self._append_recent_action(f"Folder excluded from diagnostics: {folder_name}")
        if self.view_state.active_view in {"diagnostics", "history"}:
            self._render_current_view()

    def _dependency_health_lines(self) -> list[str]:
        checks = [
            ("PyMuPDF", bool(importlib.util.find_spec("fitz"))),
            ("pypdf", bool(importlib.util.find_spec("pypdf"))),
            ("pdfplumber", bool(importlib.util.find_spec("pdfplumber"))),
            ("python-docx", bool(importlib.util.find_spec("docx"))),
            ("openpyxl", bool(importlib.util.find_spec("openpyxl"))),
            ("BeautifulSoup", bool(importlib.util.find_spec("bs4"))),
            ("Tesseract OCR", bool(shutil.which("tesseract"))),
        ]
        return [f"{name}: {'available' if present else 'missing'}" for name, present in checks]

    def _dependency_health_summary(self) -> str:
        lines = self._dependency_health_lines()
        missing = [line for line in lines if line.endswith("missing")]
        if missing:
            return f"Optional tooling is incomplete: {len(missing)} component(s) are missing. Extraction still works, but some formats or OCR paths may degrade."
        return "Optional extractors and OCR tooling appear available."

    def _review_recommended_action(self, item: dict, document: dict) -> str:
        kind = str(item.get("kind") or "")
        status = str(document.get("extraction_status") or "")
        if kind in {"extraction_issue", "empty"} or status in {"failed", "unsupported"}:
            return "Try Retry first. If the file still fails and does not matter, choose Skip." if self._guided_mode_active() else "Retry extraction first. If the file still fails and is not important, ignore it so export can proceed cleanly."
        if kind == "duplicate":
            return "Keep the better version, then skip the duplicate one." if self._guided_mode_active() else "Keep the stronger source as canonical, then ignore or reject the duplicate review item."
        if kind == "taxonomy":
            return "If the title looks wrong, fix it and then accept the item." if self._guided_mode_active() else "Override the title or domain if the inferred category is wrong, then accept the item."
        if kind in {"ocr", "ai_low_confidence"}:
            return "Check the preview. Accept it if the text is good enough, or Retry if it is not." if self._guided_mode_active() else "Inspect the preview closely. Accept if the text is usable, or retry with a different strategy."
        if kind == "low_signal":
            return "Decide if this file is useful. Skip it if it is mostly noise." if self._guided_mode_active() else "Decide whether this document adds useful knowledge. Ignore it if it is mostly noise."
        return "Check the preview, then Accept or Skip the item." if self._guided_mode_active() else "Review the preview, adjust overrides if needed, then accept or ignore the item."

    def _review_priority_key(self, item: dict) -> tuple:
        status_rank = {"open": 0, "resolved": 1, "accepted": 2, "rejected": 3}
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        kind_rank = {
            "empty": 0,
            "extraction_issue": 1,
            "duplicate": 2,
            "ocr": 3,
            "ai_low_confidence": 4,
            "taxonomy": 5,
            "low_signal": 6,
        }
        document = self._document_for_review_item(item)
        extraction_rank = {"failed": 0, "unsupported": 1, "partial": 2, "metadata_only": 3, "success": 4}
        source_name = Path(str(item.get("source_path") or "")).name.lower()
        return (
            status_rank.get(str(item.get("status") or "open"), 9),
            extraction_rank.get(str(document.get("extraction_status") or "success"), 9),
            kind_rank.get(str(item.get("kind") or ""), 9),
            severity_rank.get(str(item.get("severity") or "low"), 9),
            source_name,
        )

    def _review_sort_key(self, item: dict):
        if self.review_sort_column == "priority":
            return self._review_priority_key(item)
        if self.review_sort_column == "file":
            return Path(str(item.get("source_path") or "")).name.lower()
        if self.review_sort_column == "kind":
            return str(item.get("kind") or "")
        if self.review_sort_column == "severity":
            order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            return order.get(str(item.get("severity") or "low"), 9)
        if self.review_sort_column == "status":
            order = {"open": 0, "resolved": 1, "accepted": 2, "rejected": 3}
            return order.get(str(item.get("status") or "open"), 9)
        return self._review_priority_key(item)

    def _review_row_tags(self, item: dict) -> tuple[str, ...]:
        tags: list[str] = []
        severity = str(item.get("severity") or "")
        status = str(item.get("status") or "")
        kind = str(item.get("kind") or "")
        if severity in {"critical", "high"}:
            tags.append("sev_high")
        elif severity == "medium":
            tags.append("sev_medium")
        if status == "accepted":
            tags.append("status_accepted")
        elif status == "rejected":
            tags.append("status_rejected")
        if kind in {"extraction_issue", "empty"}:
            tags.append("kind_extraction")
        return tuple(tags)

    def _snapshot_review_item(self, review_id: str) -> dict | None:
        project_dir = self._current_project_dir(optional=True)
        if not project_dir:
            return None
        items = load_reviews(project_dir).get("items", []) or []
        target = next((item for item in items if str(item.get("review_id") or "") == review_id), None)
        if not target:
            return None
        return {
            "review_id": review_id,
            "status": target.get("status"),
            "override_title": target.get("override_title", ""),
            "override_domain": target.get("override_domain", ""),
            "resolution_note": target.get("resolution_note", ""),
        }

    def _append_recent_action(self, line: str) -> None:
        self._recent_action_lines.append(line)
        self._recent_action_lines = self._recent_action_lines[-12:]
        if self.review_history_log is not None:
            self._populate_text_widget(self.review_history_log, self._recent_action_lines)

    def _export_completion_text(self, payload: dict) -> str:
        package_dir = payload.get("package_dir", "")
        files = len(payload.get("written_files") or [])
        validations = len(payload.get("validation_messages") or [])
        zip_created = "Yes" if payload.get("zip_path") else "No"
        return (
            f"Completed export to {package_dir}. "
            f"Created {files} package file(s), validation warnings={validations}, zip created={zip_created}."
        )

    def _export_next_action_text(self, payload: dict) -> str:
        validations = len(payload.get("validation_messages") or [])
        if validations:
            return "Open Diagnostics or review the validation panel before you upload the package to a GPT."
        return "Open the output folder, inspect the package files, and upload the cleaned knowledge files to your Custom GPT."

    def _show_export_completion_dialog(self, payload: dict) -> None:
        if self.export_summary_dialog is not None and self.export_summary_dialog.winfo_exists():
            self.export_summary_dialog.destroy()
        dialog = Toplevel(self.root)
        dialog.title("Export Complete")
        dialog.geometry("720x420")
        dialog.minsize(640, 360)
        dialog.configure(bg=self.palette.bg)
        container = ttk.Frame(dialog, style="App.TFrame", padding=18)
        container.pack(fill=BOTH, expand=True)
        ttk.Label(container, text="Export Complete", style="Header.TLabel").pack(anchor=W)
        ttk.Label(container, text=self._export_completion_text(payload), style="Muted.TLabel", wraplength=660, justify=LEFT).pack(anchor=W, pady=(8, 0))
        ttk.Label(container, text=self._export_next_action_text(payload), style="Caption.TLabel", wraplength=660, justify=LEFT).pack(anchor=W, pady=(8, 0))
        actions = ttk.Frame(container, style="App.TFrame")
        actions.pack(fill=X, pady=(16, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        action_specs = [
            ("Open Package Folder", "Primary.TButton", self.on_open_latest_package_dir),
            ("Open Package Index", "Ghost.TButton", self.on_open_latest_package_index),
            ("Open Provenance", "Ghost.TButton", self.on_open_latest_provenance_manifest),
            ("Open Diagnostics", "Ghost.TButton", self.on_open_diagnostics_folder),
        ]
        for index, (label, style, command) in enumerate(action_specs):
            row = index // 2
            column = index % 2
            ttk.Button(actions, text=label, style=style, command=command).grid(
                row=row,
                column=column,
                sticky="ew",
                padx=(0, 10) if column == 0 else (0, 0),
                pady=(0, 10),
            )
        ttk.Button(actions, text="Close", style="Ghost.TButton", command=dialog.destroy).grid(row=2, column=0, columnspan=2, sticky="e")
        checklist = ttk.Frame(container, style="PanelAlt.TFrame", padding=14)
        checklist.pack(fill=BOTH, expand=True, pady=(18, 0))
        ttk.Label(checklist, text="Delivery Checklist", style="Section.TLabel").pack(anchor=W)
        for line in self._export_checklist_lines(payload):
            ttk.Label(checklist, text=f"- {line}", style="Caption.TLabel", wraplength=640, justify=LEFT).pack(anchor=W, pady=(4, 0))
        dialog.transient(self.root)
        dialog.lift()
        self.export_summary_dialog = dialog

    def _export_readiness_state(self) -> tuple[str, str, str]:
        summary = self._current_workspace_summary()
        project_dir = self._current_project_dir(optional=True)
        if not self.view_state.has_project:
            return ("Not Ready", "muted", "Create or open a project before export can run.")
        if summary.get("documents", 0) == 0:
            return ("Not Ready", "muted", "Run the first scan so the app can build the working corpus.")
        if summary.get("failed_docs", 0):
            return (
                "Blocked",
                "danger",
                f"{summary['failed_docs']} failed document(s) are excluded from export. Fix or ignore them before trusting the package.",
            )
        if summary.get("open_reviews", 0) or summary.get("partial_docs", 0) or summary.get("metadata_only_docs", 0):
            return (
                "Needs Review",
                "warn",
                f"Open reviews={summary.get('open_reviews', 0)} partial={summary.get('partial_docs', 0)} metadata_only={summary.get('metadata_only_docs', 0)}.",
            )
        latest = None
        if project_dir:
            state = load_state(project_dir)
            exports = state.get("exports") or []
            latest = exports[-1] if exports else None
        if latest and latest.get("validation_messages"):
            return (
                "Ready With Warnings",
                "warn",
                f"Latest export still has {len(latest.get('validation_messages') or [])} validation warning(s).",
            )
        return ("Ready", "success", "The corpus is clean and ready for a GPT package export.")

    def _export_checklist_lines(self, latest: dict | None) -> list[str]:
        summary = self._current_workspace_summary()
        lines = [
            f"Scanned documents: {summary.get('documents', 0)}",
            f"Open review blockers: {summary.get('open_reviews', 0)}",
            f"Failed extraction documents excluded from export: {summary.get('failed_docs', 0)}",
            f"Partial extraction documents needing judgment: {summary.get('partial_docs', 0)}",
            f"Metadata-only documents: {summary.get('metadata_only_docs', 0)}",
        ]
        if latest:
            lines.append(f"Latest export files: {len(latest.get('written_files') or [])}")
            lines.append(f"Latest validation warnings: {len(latest.get('validation_messages') or [])}")
            lines.append(f"Zip created: {'yes' if latest.get('zip_path') else 'no'}")
        else:
            lines.append("Latest export files: none yet")
            lines.append("Latest validation warnings: no export yet")
            lines.append("Zip created: no")
        if summary.get("failed_docs", 0):
            lines.append("Recommendation: fix or ignore failed documents before final delivery.")
        elif summary.get("open_reviews", 0):
            lines.append("Recommendation: clear the review queue before final delivery.")
        else:
            lines.append("Recommendation: validate once more, then export the final GPT package.")
        return lines

    def _wizard_back(self) -> None:
        self.guided_wizard_step = max(0, self.guided_wizard_step - 1)
        self._render_guided_wizard_step()

    def _wizard_next(self) -> None:
        self.guided_wizard_step = min(3, self.guided_wizard_step + 1)
        self._render_guided_wizard_step()

    def _wizard_finish(self) -> None:
        had_project = self.view_state.has_project
        self.on_create_project()
        if self.view_state.has_project and not had_project or Path(self.project_dir.get()).exists():
            self._close_guided_wizard()

    def _close_guided_wizard(self) -> None:
        if self.guided_wizard is not None and self.guided_wizard.winfo_exists():
            self.guided_wizard.destroy()
        self.guided_wizard = None
        self.guided_wizard_body = None

    def _render_guided_wizard_step(self) -> None:
        if self.guided_wizard_body is None:
            return
        self._clear_frame(self.guided_wizard_body)
        steps = [
            (
                "Step 1 of 4: Project Workspace",
                "Choose where the workspace, source documents, and exported files should live.",
                self._render_wizard_folders,
            ),
            (
                "Step 2 of 4: Project Defaults",
                "Set the project name, preset, and export profile. These choices drive how the app interprets the corpus.",
                self._render_wizard_defaults,
            ),
            (
                "Step 3 of 4: Optional AI",
                "Enable model-assisted enrichment only if you want AI help with titles, taxonomy, and synthesis.",
                self._render_wizard_ai,
            ),
            (
                "Step 4 of 4: Create And Continue",
                "Review the setup summary, create the project, then continue into Scan.",
                self._render_wizard_summary,
            ),
        ]
        title, hint, renderer = steps[self.guided_wizard_step]
        self.guided_wizard_title_var.set(title)
        self.guided_wizard_hint_var.set(hint)
        renderer()

    def _render_wizard_folders(self) -> None:
        ttk.Label(self.guided_wizard_body, text="Workspace Paths", style="Section.TLabel").pack(anchor=W)
        for label, variable, command in (
            ("Project Folder", self.project_dir, self._browse_project_dir),
            ("Source Folder", self.source_dir, self._browse_source_dir),
            ("Output Folder", self.output_dir, self._browse_output_dir),
        ):
            self._build_field_card(self.guided_wizard_body, label, variable, command)

    def _render_wizard_defaults(self) -> None:
        panel = ttk.Frame(self.guided_wizard_body, style="PanelAlt.TFrame", padding=16)
        panel.pack(fill=X)
        ttk.Label(panel, text="Project Defaults", style="Section.TLabel").pack(anchor=W)
        self._labeled_entry(panel, "Project Name", self.project_name)
        self._labeled_combo(panel, "Preset", self.preset, [
            "business-sops",
            "product-docs",
            "policies-contracts",
            "course-training",
            "mixed-office-documents",
        ])
        self._labeled_combo(panel, "Export Profile", self.export_profile, [
            "custom-gpt-balanced",
            "custom-gpt-max-traceability",
            "debug-research",
        ])

    def _render_wizard_ai(self) -> None:
        panel = ttk.Frame(self.guided_wizard_body, style="PanelAlt.TFrame", padding=16)
        panel.pack(fill=X)
        ttk.Label(panel, text="Optional AI Settings", style="Section.TLabel").pack(anchor=W)
        ttk.Checkbutton(panel, text="Enable model-assisted enrichment", variable=self.model_enabled).pack(anchor=W, pady=(10, 10))
        self._labeled_entry(panel, "Model", self.model_name)
        self._labeled_entry(panel, "API Key", self.api_key_value, show="*")
        ttk.Checkbutton(panel, text="Save API key in local project secrets", variable=self.save_api_key).pack(anchor=W, pady=(10, 0))

    def _render_wizard_summary(self) -> None:
        panel = ttk.Frame(self.guided_wizard_body, style="PanelAlt.TFrame", padding=16)
        panel.pack(fill=BOTH, expand=True)
        ttk.Label(panel, text="Ready To Create", style="Section.TLabel").pack(anchor=W)
        for line in (
            f"Project folder: {self.project_dir.get()}",
            f"Source folder: {self.source_dir.get()}",
            f"Output folder: {self.output_dir.get()}",
            f"Project name: {self.project_name.get()}",
            f"Preset: {self.preset.get()}",
            f"Export profile: {self.export_profile.get()}",
            f"AI enrichment: {'enabled' if self.model_enabled.get() else 'disabled'}",
        ):
            ttk.Label(panel, text=f"- {line}", style="Caption.TLabel", wraplength=620, justify=LEFT).pack(anchor=W, pady=(6, 0))
        ttk.Label(
            panel,
            text="Click Create Project to make the folders, write the project file, and continue into the setup/scan flow.",
            style="Muted.TLabel",
            wraplength=620,
            justify=LEFT,
        ).pack(anchor=W, pady=(14, 0))

    def _document_for_review_item(self, item: dict) -> dict:
        project_dir = self._current_project_dir(optional=True)
        if not project_dir:
            return {}
        state = load_state(project_dir)
        return ((state.get("documents") or {}).get(item.get("source_path")) or {}).get("document") or {}

    def _duplicate_comparison_text(self, document: dict) -> str:
        preview_units = list(document.get("preview_units") or [])
        if preview_units:
            lines = []
            for unit in preview_units[:2]:
                label = str(unit.get("label") or "Preview")
                text = str(unit.get("text") or "").strip()
                if text:
                    lines.append(f"{label}\n{text}")
            if lines:
                return "\n\n".join(lines)
        preview = str(document.get("preview_excerpt") or "").strip()
        return preview or "No comparison preview available."

    def _write_duplicate_comparison_diff(self, widget: ScrolledText, filename: str, source_text: str, other_text: str, left_side: bool) -> None:
        widget.delete("1.0", END)
        widget.tag_configure("diff_header", foreground=self.palette.primary, font=self.type_scale.subheading)
        widget.tag_configure("diff_same", foreground=self.palette.ink_muted)
        widget.tag_configure("diff_changed", foreground=self.palette.warn)
        widget.insert(END, f"{filename}\n\n", "diff_header")
        source_lines = [line.rstrip() for line in source_text.splitlines()]
        other_lines = [line.rstrip() for line in other_text.splitlines()]
        matcher = SequenceMatcher(None, source_lines, other_lines)
        wrote = False
        for tag, a0, a1, b0, b1 in matcher.get_opcodes():
            if tag == "equal":
                for line in source_lines[a0:a1]:
                    widget.insert(END, f"  {line}\n", "diff_same")
                    wrote = True
            elif left_side and tag in {"replace", "delete"}:
                for line in source_lines[a0:a1]:
                    widget.insert(END, f"- {line}\n", "diff_changed")
                    wrote = True
            elif (not left_side) and tag in {"replace", "insert"}:
                for line in other_lines[b0:b1]:
                    widget.insert(END, f"+ {line}\n", "diff_changed")
                    wrote = True
        if not wrote:
            widget.insert(END, "  No comparison preview available.\n", "diff_same")

    def _render_duplicate_comparison(self, item: dict, document: dict) -> None:
        if not self.review_duplicate_compare_frame or not self.review_duplicate_current_text or not self.review_duplicate_target_text:
            return
        self.review_duplicate_current_text.delete("1.0", END)
        self.review_duplicate_target_text.delete("1.0", END)
        if str(item.get("kind") or "") != "duplicate":
            self.review_duplicate_compare_frame.grid_remove()
            return
        duplicate_target = str(document.get("duplicate_of") or document.get("duplicate_canonical_source") or "")
        if not duplicate_target or duplicate_target == str(item.get("source_path") or ""):
            self.review_duplicate_compare_frame.grid_remove()
            return
        project_dir = self._current_project_dir(optional=True)
        if not project_dir:
            self.review_duplicate_compare_frame.grid_remove()
            return
        state = load_state(project_dir)
        target_document = ((state.get("documents") or {}).get(duplicate_target) or {}).get("document") or {}
        source_text = self._duplicate_comparison_text(document)
        target_text = self._duplicate_comparison_text(target_document)
        self._write_duplicate_comparison_diff(
            self.review_duplicate_current_text,
            Path(str(item.get("source_path") or "")).name,
            source_text,
            target_text,
            left_side=True,
        )
        self._write_duplicate_comparison_diff(
            self.review_duplicate_target_text,
            Path(duplicate_target).name,
            target_text,
            source_text,
            left_side=False,
        )
        self.review_duplicate_compare_frame.grid()

    def on_next_review_item(self) -> None:
        self._move_review_selection(1)

    def on_prev_review_item(self) -> None:
        self._move_review_selection(-1)

    def _select_review_item_by_id(self, review_id: str) -> None:
        if not review_id:
            return
        project_dir = self._current_project_dir(optional=True)
        if project_dir:
            self._refresh_review_display(project_dir)
        self.selected_review_id.set(review_id)
        for tree_id, item in self._review_tree_map.items():
            if str(item.get("review_id") or "") == review_id and self.review_tree is not None:
                self.review_tree.selection_set(tree_id)
                self._populate_review_editor(item)
                break

    def _move_review_selection(self, offset: int) -> None:
        if self.review_tree is None:
            return
        children = list(self.review_tree.get_children())
        if not children:
            return
        current = self.review_tree.selection()
        if not current:
            target = children[0]
        else:
            index = max(0, children.index(current[0]) + offset)
            index = min(index, len(children) - 1)
            target = children[index]
        self.review_tree.selection_set(target)
        self.review_tree.focus(target)
        self.review_tree.see(target)
        item = self._review_tree_map.get(target)
        if item:
            self._populate_review_editor(item)

    def _populate_text_widget(self, widget: ScrolledText, lines: list[str]) -> None:
        widget.delete("1.0", END)
        widget.insert(END, "\n".join(str(line) for line in lines))

    def _clear_frame(self, frame) -> None:
        for child in frame.winfo_children():
            child.destroy()


def run_gui(initial_config: Path | None = None) -> int:
    root = Tk()
    App(root, initial_config=initial_config)
    root.mainloop()
    return 0
