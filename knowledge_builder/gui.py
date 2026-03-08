from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, TOP, W, X, BooleanVar, StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .project.pipeline import export_project, review_project, scan_project, update_review_item, validate_project
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
)
from .ui.models import MetricCardModel, ViewState
from .ui.theme import configure_theme, default_theme
from .ui.widgets import build_metric_card, build_status_chip, style_scrolled_text
from .version import APP_NAME


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
        self.review_low_signal_var = StringVar(value="60")
        self.review_duplicate_threshold_var = StringVar(value="0.96")
        self.review_confidence_var = StringVar(value="0.55")
        self.banner_var = StringVar(value="Create or open a project to begin.")
        self.header_title_var = StringVar(value="Home")
        self.header_subtitle_var = StringVar(value="Start with a polished project workspace and build toward export-ready GPT knowledge.")
        self.context_title_var = StringVar(value="Workspace Health")
        self.home_summary_var = StringVar(value="No project loaded yet.")
        self.processing_summary_var = StringVar(value="No scan has run yet.")
        self.review_summary_var = StringVar(value="No review items loaded.")
        self.export_summary_var = StringVar(value="No export has been generated yet.")
        self.project_badge_var = StringVar(value="No project")
        self.profile_badge_var = StringVar(value="custom-gpt-balanced")
        self.ai_badge_var = StringVar(value="AI off")

        self.view_state = ViewState(active_view="home", has_project=False, review_filter="All", selected_review_id="")
        self._event_queue: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self._process_log_lines: list[str] = []
        self._export_log_lines: list[str] = []
        self._context_notes: list[str] = []
        self._nav_buttons: dict[str, ttk.Button] = {}
        self._review_tree_map: dict[str, dict] = {}
        self.review_tree = None
        self.review_note_text = None
        self.process_log = None
        self.export_log = None
        self.review_list = None
        self.home_primary_button = None

        self._build_shell()
        self.root.after(150, self._pump_events)

        if initial_config and initial_config.exists():
            self._load_project(initial_config.parent)
        else:
            self._refresh_shell()

    def _build_shell(self) -> None:
        outer = ttk.Frame(self.root, style="App.TFrame", padding=0)
        outer.pack(fill=BOTH, expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        self.sidebar = ttk.Frame(outer, style="Sidebar.TFrame", padding=(18, 20))
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.main = ttk.Frame(outer, style="App.TFrame", padding=(18, 18, 18, 18))
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(1, weight=1)

        self._build_sidebar()
        self._build_header()
        self._build_body()

    def _build_sidebar(self) -> None:
        ttk.Label(self.sidebar, text=APP_NAME, style="Header.TLabel").pack(anchor=W, pady=(0, 4))
        ttk.Label(
            self.sidebar,
            text="Premium desktop workspace for turning documents into Custom GPT knowledge packs.",
            style="Muted.TLabel",
            wraplength=220,
            justify=LEFT,
        ).pack(anchor=W, pady=(0, 18))

        for view_id, label in (
            ("home", "Home"),
            ("sources", "Sources"),
            ("processing", "Processing"),
            ("review", "Review"),
            ("export", "Export"),
            ("settings", "Settings"),
        ):
            button = ttk.Button(self.sidebar, text=label, style="Nav.TButton", command=lambda value=view_id: self._set_active_view(value))
            button.pack(fill=X, pady=(0, 6))
            self._nav_buttons[view_id] = button

        footer = ttk.Frame(self.sidebar, style="Sidebar.TFrame", padding=(0, 18, 0, 0))
        footer.pack(fill=X, side=TOP)
        self.project_badge = build_status_chip(footer, self.project_badge_var.get(), self.palette, tone="primary")
        self.project_badge.pack(anchor=W, pady=(0, 8))
        self.profile_badge = build_status_chip(footer, self.profile_badge_var.get(), self.palette, tone="success")
        self.profile_badge.pack(anchor=W, pady=(0, 8))
        self.ai_badge = build_status_chip(footer, self.ai_badge_var.get(), self.palette, tone="muted")
        self.ai_badge.pack(anchor=W)

    def _build_header(self) -> None:
        header = ttk.Frame(self.main, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(0, weight=1)

        left = ttk.Frame(header, style="App.TFrame")
        left.grid(row=0, column=0, sticky="w")
        ttk.Label(left, textvariable=self.header_title_var, style="Header.TLabel").pack(anchor=W)
        ttk.Label(left, textvariable=self.header_subtitle_var, style="Subhead.TLabel", wraplength=760, justify=LEFT).pack(anchor=W, pady=(4, 0))

        right = ttk.Frame(header, style="App.TFrame")
        right.grid(row=0, column=1, sticky="e")
        self.primary_action_button = ttk.Button(right, text="Create Project", style="Primary.TButton", command=self.on_create_project)
        self.primary_action_button.pack(side=RIGHT)
        self.banner_chip = build_status_chip(right, self.banner_var.get(), self.palette, tone="primary")
        self.banner_chip.pack(side=RIGHT, padx=(0, 12))

    def _build_body(self) -> None:
        body = ttk.Frame(self.main, style="App.TFrame")
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self.content_frame = ttk.Frame(body, style="Panel.TFrame", padding=18)
        self.content_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.context_frame = ttk.Frame(body, style="Panel.TFrame", padding=18)
        self.context_frame.grid(row=0, column=1, sticky="nsew")

    def _set_active_view(self, view_id: str) -> None:
        self.view_state.active_view = view_id
        self._refresh_shell()

    def _refresh_shell(self) -> None:
        self._update_header()
        self._update_nav_styles()
        self._render_current_view()
        self._render_context_panel()

    def _update_header(self) -> None:
        titles = {
            "home": ("Home", "Open a project, inspect the corpus, and drive the next high-value action."),
            "sources": ("Sources", "Configure project roots, presets, export profile, and AI settings."),
            "processing": ("Processing", "Scan the corpus, track incremental work, and monitor pipeline health."),
            "review": ("Review", "Resolve low-confidence, duplicate, OCR, and taxonomy issues before export."),
            "export": ("Export", "Preview package artifacts, validation warnings, and provenance outputs."),
            "settings": ("Settings", "Tune thresholds, model behavior, and workspace defaults."),
        }
        title, subtitle = titles.get(self.view_state.active_view, ("Workspace", ""))
        self.header_title_var.set(title)
        self.header_subtitle_var.set(subtitle)

        if not self.view_state.has_project:
            primary_text = "Create Project"
            primary_action = self.on_create_project
        elif self.view_state.active_view == "processing":
            primary_text = "Scan Project"
            primary_action = self.on_scan
        elif self.view_state.active_view == "review":
            primary_text = "Refresh Review"
            primary_action = self.on_refresh_reviews
        elif self.view_state.active_view == "export":
            primary_text = "Export Package"
            primary_action = self.on_export
        else:
            primary_text = "Open Project"
            primary_action = self.on_open_project
        self.primary_action_button.configure(text=primary_text, command=primary_action)
        self._refresh_badges()

    def _refresh_badges(self) -> None:
        self.project_badge_var.set(self.project_name.get().strip() or "No project")
        self.profile_badge_var.set(self.export_profile.get().strip() or "profile")
        self.ai_badge_var.set("AI on" if self.model_enabled.get() else "AI off")

        footer = self.project_badge.master
        self.project_badge.destroy()
        self.profile_badge.destroy()
        self.ai_badge.destroy()
        self.project_badge = build_status_chip(footer, self.project_badge_var.get(), self.palette, tone="primary")
        self.project_badge.pack(anchor=W, pady=(0, 8))
        self.profile_badge = build_status_chip(footer, self.profile_badge_var.get(), self.palette, tone="success")
        self.profile_badge.pack(anchor=W, pady=(0, 8))
        self.ai_badge = build_status_chip(footer, self.ai_badge_var.get(), self.palette, tone="warn" if self.model_enabled.get() else "muted")
        self.ai_badge.pack(anchor=W)

        self.banner_chip.destroy()
        self.banner_chip = build_status_chip(self.primary_action_button.master, self.banner_var.get(), self.palette, tone="primary")
        self.banner_chip.pack(side=RIGHT, padx=(0, 12))

    def _update_nav_styles(self) -> None:
        for view_id, button in self._nav_buttons.items():
            button.configure(style="NavActive.TButton" if view_id == self.view_state.active_view else "Nav.TButton")

    def _render_current_view(self) -> None:
        self._clear_frame(self.content_frame)
        builders = {
            "home": self._render_home_view,
            "sources": self._render_sources_view,
            "processing": self._render_processing_view,
            "review": self._render_review_view,
            "export": self._render_export_view,
            "settings": self._render_settings_view,
        }
        builders.get(self.view_state.active_view, self._render_home_view)()

    def _render_context_panel(self) -> None:
        self._clear_frame(self.context_frame)
        ttk.Label(self.context_frame, textvariable=self.context_title_var, style="Section.TLabel").pack(anchor=W)

        summary = self._current_workspace_summary()
        metric_row = ttk.Frame(self.context_frame, style="Panel.TFrame")
        metric_row.pack(fill=X, pady=(12, 14))
        for model in (
            MetricCardModel("Documents", str(summary["documents"]), "primary", "Tracked in the current workspace."),
            MetricCardModel("Open Review", str(summary["open_reviews"]), "warn" if summary["open_reviews"] else "success", "Items still blocking a clean export."),
            MetricCardModel("Exports", str(summary["exports"]), "success", "Completed export runs for this project."),
        ):
            build_metric_card(metric_row, model, self.palette)

        actions_panel = ttk.Frame(self.context_frame, style="PanelAlt.TFrame", padding=14)
        actions_panel.pack(fill=X, pady=(0, 14))
        ttk.Label(actions_panel, text="Next Best Actions", style="Section.TLabel").pack(anchor=W)
        for note in self._build_next_actions(summary):
            ttk.Label(actions_panel, text=f"- {note}", style="Caption.TLabel", wraplength=260, justify=LEFT).pack(anchor=W, pady=(6, 0))

        status_panel = ttk.Frame(self.context_frame, style="PanelAlt.TFrame", padding=14)
        status_panel.pack(fill=BOTH, expand=True)
        ttk.Label(status_panel, text="Live Notes", style="Section.TLabel").pack(anchor=W)
        notes = self._context_notes or ["Workspace status will appear here as you scan, review, and export."]
        for line in notes[-8:]:
            ttk.Label(status_panel, text=line, style="Caption.TLabel", wraplength=260, justify=LEFT).pack(anchor=W, pady=(6, 0))

    def _render_home_view(self) -> None:
        hero = ttk.Frame(self.content_frame, style="Panel.TFrame")
        hero.pack(fill=X)
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
        self.home_primary_button = ttk.Button(ctas, text="Create Project", style="Primary.TButton", command=self.on_create_project)
        self.home_primary_button.pack(side=LEFT)
        ttk.Button(ctas, text="Open Existing Project", style="Ghost.TButton", command=self.on_open_project).pack(side=LEFT, padx=(10, 0))

        hero_right = ttk.Frame(hero, style="PanelAlt.TFrame", padding=18)
        hero_right.pack(side=RIGHT, fill=BOTH, expand=False, padx=(16, 0))
        ttk.Label(hero_right, text="Workspace Snapshot", style="Section.TLabel").pack(anchor=W)
        ttk.Label(hero_right, textvariable=self.home_summary_var, style="Muted.TLabel", wraplength=280, justify=LEFT).pack(anchor=W, pady=(8, 0))

        metrics = ttk.Frame(self.content_frame, style="Panel.TFrame")
        metrics.pack(fill=X, pady=(18, 0))
        summary = self._current_workspace_summary()
        for model in (
            MetricCardModel("Source Roots", str(summary["source_roots"]), "primary", "Configured input locations."),
            MetricCardModel("Knowledge Items", str(summary["knowledge_items"]), "success", "Accepted items tracked across the corpus."),
            MetricCardModel("Latest Validation", str(summary["validation_count"]), "warn" if summary["validation_count"] else "success", "Issues found in the latest export."),
        ):
            build_metric_card(metrics, model, self.palette)

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

    def _render_sources_view(self) -> None:
        form = ttk.Frame(self.content_frame, style="Panel.TFrame")
        form.pack(fill=BOTH, expand=True)
        top = ttk.Frame(form, style="Panel.TFrame")
        top.pack(fill=X)
        self._build_field_card(top, "Project Folder", self.project_dir, self._browse_project_dir)
        self._build_field_card(top, "Source Folder", self.source_dir, self._browse_source_dir)
        self._build_field_card(top, "Output Folder", self.output_dir, self._browse_output_dir)

        settings = ttk.Frame(form, style="Panel.TFrame")
        settings.pack(fill=X, pady=(18, 0))

        left = ttk.Frame(settings, style="PanelAlt.TFrame", padding=18)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        ttk.Label(left, text="Project Details", style="Section.TLabel").pack(anchor=W)
        self._labeled_entry(left, "Project Name", self.project_name)
        self._labeled_combo(left, "Preset", self.preset, [
            "business-sops",
            "product-docs",
            "policies-contracts",
            "course-training",
            "mixed-office-documents",
        ])
        self._labeled_combo(left, "Export Profile", self.export_profile, [
            "custom-gpt-balanced",
            "custom-gpt-max-traceability",
            "debug-research",
        ])

        right = ttk.Frame(settings, style="PanelAlt.TFrame", padding=18)
        right.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Label(right, text="AI Settings", style="Section.TLabel").pack(anchor=W)
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
        ttk.Button(actions, text="Save AI Settings", style="Ghost.TButton", command=self.on_save_ai_settings).pack(side=LEFT, padx=(10, 0))
        ttk.Button(actions, text="Clear Saved Key", style="Ghost.TButton", command=self.on_clear_saved_key).pack(side=LEFT, padx=(10, 0))

    def _render_processing_view(self) -> None:
        controls = ttk.Frame(self.content_frame, style="Panel.TFrame")
        controls.pack(fill=X)
        scan_card = ttk.Frame(controls, style="PanelAlt.TFrame", padding=18)
        scan_card.pack(fill=X)
        ttk.Label(scan_card, text="Scan Pipeline", style="Section.TLabel").pack(anchor=W)
        ttk.Label(scan_card, textvariable=self.processing_summary_var, style="Muted.TLabel", wraplength=860, justify=LEFT).pack(anchor=W, pady=(8, 0))
        control_row = ttk.Frame(scan_card, style="PanelAlt.TFrame")
        control_row.pack(fill=X, pady=(14, 0))
        ttk.Checkbutton(control_row, text="Force reprocess unchanged files", variable=self.force_scan).pack(side=LEFT)
        ttk.Button(control_row, text="Scan Project", style="Primary.TButton", command=self.on_scan).pack(side=LEFT, padx=(12, 0))
        ttk.Button(control_row, text="Go To Review", style="Ghost.TButton", command=lambda: self._set_active_view("review")).pack(side=LEFT, padx=(10, 0))

        metrics = ttk.Frame(self.content_frame, style="Panel.TFrame")
        metrics.pack(fill=X, pady=(18, 0))
        summary = self._current_workspace_summary()
        for model in (
            MetricCardModel("Scanned Docs", str(summary["documents"]), "primary", "Documents currently in workspace state."),
            MetricCardModel("Flagged Docs", str(summary["changed_docs"]), "warn" if summary["changed_docs"] else "success", "Documents needing review."),
            MetricCardModel("Clean Docs", str(summary["skipped_docs"]), "muted", "Documents currently not flagged."),
        ):
            build_metric_card(metrics, model, self.palette)

        log_panel = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=18)
        log_panel.pack(fill=BOTH, expand=True, pady=(18, 0))
        ttk.Label(log_panel, text="Processing Timeline", style="Section.TLabel").pack(anchor=W)
        self.process_log = ScrolledText(log_panel, height=20)
        style_scrolled_text(self.process_log, self.palette, self.type_scale)
        self.process_log.pack(fill=BOTH, expand=True, pady=(10, 0))
        self._populate_text_widget(self.process_log, self._process_log_lines or ["No scan events yet."])

    def _render_review_view(self) -> None:
        summary_row = ttk.Frame(self.content_frame, style="Panel.TFrame")
        summary_row.pack(fill=X)
        ttk.Label(summary_row, textvariable=self.review_summary_var, style="Muted.TLabel", wraplength=860, justify=LEFT).pack(anchor=W)

        filter_row = ttk.Frame(self.content_frame, style="Panel.TFrame")
        filter_row.pack(fill=X, pady=(14, 14))
        for label in ("All", "Open", "Accepted", "Rejected", "Duplicates", "AI Low Confidence"):
            style = "Primary.TButton" if self.review_filter.get() == label else "Ghost.TButton"
            ttk.Button(filter_row, text=label, style=style, command=lambda value=label: self._set_review_filter(value)).pack(side=LEFT, padx=(0, 8))

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
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        right = ttk.Frame(split, style="PanelAlt.TFrame", padding=14)
        right.pack(side=RIGHT, fill=BOTH, expand=False)

        self.review_tree = ttk.Treeview(left, columns=("status", "severity", "kind", "file"), show="headings", height=16)
        for heading, width in (("status", 90), ("severity", 90), ("kind", 140), ("file", 280)):
            self.review_tree.heading(heading, text=heading.title())
            self.review_tree.column(heading, width=width, anchor=W)
        self.review_tree.pack(fill=BOTH, expand=True)
        self.review_tree.bind("<<TreeviewSelect>>", self._on_review_selected)

        review_log_frame = ttk.Frame(left, style="PanelAlt.TFrame")
        review_log_frame.pack(fill=BOTH, expand=True, pady=(12, 0))
        self.review_list = ScrolledText(review_log_frame, height=8)
        style_scrolled_text(self.review_list, self.palette, self.type_scale)
        self.review_list.pack(fill=BOTH, expand=True)

        ttk.Label(right, text="Selected Item", style="Section.TLabel").grid(row=0, column=0, sticky=W)
        ttk.Label(right, textvariable=self.selected_review_id, style="Caption.TLabel", wraplength=320, justify=LEFT).grid(row=1, column=0, sticky=W, pady=(6, 12))
        self._grid_labeled_combo(right, 2, "Status", self.review_status_edit, ["open", "accepted", "rejected", "resolved"])
        self._grid_labeled_entry(right, 4, "Override title", self.review_title_edit)
        self._grid_labeled_entry(right, 6, "Override domain", self.review_domain_edit)
        ttk.Label(right, text="Resolution note", style="Caption.TLabel").grid(row=8, column=0, sticky=W, pady=(10, 4))
        self.review_note_text = ScrolledText(right, height=9, width=36)
        style_scrolled_text(self.review_note_text, self.palette, self.type_scale)
        self.review_note_text.grid(row=9, column=0, sticky="nsew")
        actions = ttk.Frame(right, style="PanelAlt.TFrame")
        actions.grid(row=10, column=0, sticky=W, pady=(12, 0))
        ttk.Button(actions, text="Apply Edit", style="Primary.TButton", command=self.on_apply_review_edit).pack(side=LEFT)
        ttk.Button(actions, text="Accept", style="Ghost.TButton", command=self.on_mark_review_accepted).pack(side=LEFT, padx=(8, 0))
        ttk.Button(actions, text="Reject", style="Ghost.TButton", command=self.on_mark_review_rejected).pack(side=LEFT, padx=(8, 0))
        ttk.Button(actions, text="Approve All", style="Ghost.TButton", command=self.on_approve_all).pack(side=LEFT, padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(9, weight=1)

        self._refresh_review_display(self._current_project_dir(optional=True))

    def _render_export_view(self) -> None:
        state = load_state(self._current_project_dir(optional=True)) if self.view_state.has_project else {"exports": [], "documents": {}}
        latest = (state.get("exports") or [])[-1] if state.get("exports") else None

        hero = ttk.Frame(self.content_frame, style="PanelAlt.TFrame", padding=18)
        hero.pack(fill=X)
        ttk.Label(hero, text="Export Readiness", style="Section.TLabel").pack(anchor=W)
        ttk.Label(hero, textvariable=self.export_summary_var, style="Muted.TLabel", wraplength=860, justify=LEFT).pack(anchor=W, pady=(8, 0))
        actions = ttk.Frame(hero, style="PanelAlt.TFrame")
        actions.pack(fill=X, pady=(14, 0))
        ttk.Checkbutton(actions, text="Create zip beside package", variable=self.zip_pack).pack(side=LEFT)
        ttk.Button(actions, text="Validate Project", style="Ghost.TButton", command=self.on_validate).pack(side=LEFT, padx=(10, 0))
        ttk.Button(actions, text="Export Package", style="Primary.TButton", command=self.on_export).pack(side=LEFT, padx=(10, 0))
        ttk.Button(actions, text="Open Output Folder", style="Ghost.TButton", command=self.on_open_output).pack(side=LEFT, padx=(10, 0))

        artifact_row = ttk.Frame(self.content_frame, style="Panel.TFrame")
        artifact_row.pack(fill=X, pady=(18, 0))
        for label, detail in self._build_export_cards(latest):
            build_metric_card(artifact_row, MetricCardModel(label, detail[0], detail[1], detail[2]), self.palette)

        lower = ttk.Frame(self.content_frame, style="Panel.TFrame")
        lower.pack(fill=BOTH, expand=True, pady=(18, 0))
        left = ttk.Frame(lower, style="PanelAlt.TFrame", padding=16)
        left.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
        right = ttk.Frame(lower, style="PanelAlt.TFrame", padding=16)
        right.pack(side=LEFT, fill=BOTH, expand=True)

        ttk.Label(left, text="Artifacts", style="Section.TLabel").pack(anchor=W)
        artifact_list = ScrolledText(left, height=18)
        style_scrolled_text(artifact_list, self.palette, self.type_scale)
        artifact_list.pack(fill=BOTH, expand=True, pady=(10, 0))
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

    def _labeled_entry(self, parent, label: str, variable: StringVar, show: str | None = None) -> None:
        ttk.Label(parent, text=label, style="Caption.TLabel").pack(anchor=W, pady=(10, 4))
        ttk.Entry(parent, textvariable=variable, show=show or "").pack(fill=X)

    def _labeled_combo(self, parent, label: str, variable: StringVar, values: list[str]) -> None:
        ttk.Label(parent, text=label, style="Caption.TLabel").pack(anchor=W, pady=(10, 4))
        ttk.Combobox(parent, textvariable=variable, values=values, state="readonly").pack(fill=X)

    def _grid_labeled_entry(self, parent, row: int, label: str, variable: StringVar) -> None:
        ttk.Label(parent, text=label, style="Caption.TLabel").grid(row=row, column=0, sticky=W, pady=(10, 4))
        ttk.Entry(parent, textvariable=variable).grid(row=row + 1, column=0, sticky="ew")

    def _grid_labeled_combo(self, parent, row: int, label: str, variable: StringVar, values: list[str]) -> None:
        ttk.Label(parent, text=label, style="Caption.TLabel").grid(row=row, column=0, sticky=W, pady=(10, 4))
        ttk.Combobox(parent, textvariable=variable, values=values, state="readonly").grid(row=row + 1, column=0, sticky="ew")

    def _browse_project_dir(self) -> None:
        path = filedialog.askdirectory(title="Select project folder")
        if path:
            self.project_dir.set(path)

    def _browse_source_dir(self) -> None:
        path = filedialog.askdirectory(title="Select source folder")
        if path:
            self.source_dir.set(path)
            if not self.project_name.get().strip():
                self.project_name.set(Path(path).name)

    def _browse_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_dir.set(path)

    def on_create_project(self) -> None:
        project_dir = Path(self.project_dir.get().strip())
        source_dir = Path(self.source_dir.get().strip())
        output_dir = Path(self.output_dir.get().strip())
        if not source_dir.exists():
            messagebox.showerror("Create Project", f"Source folder not found:\n{source_dir}")
            return
        init_project(
            project_root=project_dir,
            project_name=self.project_name.get().strip() or source_dir.name,
            source_roots=[source_dir],
            output_root=output_dir,
            preset=self.preset.get().strip(),
            export_profile=self.export_profile.get().strip(),
            model_enabled=self.model_enabled.get(),
        )
        self._persist_project_settings(project_dir)
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

    def on_scan(self) -> None:
        self._run_async("scan", lambda: scan_project(self._require_project_dir(), force=self.force_scan.get()))

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

    def on_mark_review_rejected(self) -> None:
        self.review_status_edit.set("rejected")
        self.on_apply_review_edit()

    def on_validate(self) -> None:
        self._run_async("validate", lambda: {"issues": validate_project(self._require_project_dir())})

    def on_export(self) -> None:
        self._run_async("export", lambda: export_project(self._require_project_dir(), zip_pack=self.zip_pack.get()))

    def on_save_ai_settings(self) -> None:
        project_dir = self._require_project_dir()
        self._persist_project_settings(project_dir)
        self.banner_var.set("Settings saved for this project.")
        self._refresh_shell()

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
        os.startfile(output_dir)

    def _run_async(self, kind: str, fn) -> None:
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
                elif kind == "export":
                    self._handle_export_complete(payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(150, self._pump_events)

    def _handle_scan_complete(self, payload) -> None:
        self.processing_summary_var.set(
            f"Scan complete: scanned={payload['scanned']} processed={payload['processed']} "
            f"skipped={payload['skipped']} flagged={payload['flagged']} removed={payload['removed']}"
        )
        self._append_process_log(self.processing_summary_var.get())
        self.banner_var.set("Scan complete.")
        if self.view_state.has_project:
            self._refresh_review_display(self._require_project_dir())
        self._refresh_shell()

    def _handle_review_complete(self, payload) -> None:
        self.review_summary_var.set(
            f"Review updated: open={payload['open']} accepted={payload['accepted']} "
            f"rejected={payload['rejected']} changed={payload['changed']}"
        )
        self.banner_var.set("Review queue updated.")
        if self.view_state.has_project:
            self._refresh_review_display(self._require_project_dir())
        self._refresh_shell()

    def _handle_review_edit_complete(self, payload) -> None:
        self.banner_var.set(f"Review item updated: {payload.get('review_id', '')}")
        self._append_process_log(f"Review edit saved for {payload.get('review_id', '')}")
        if self.view_state.has_project:
            self._refresh_review_display(self._require_project_dir())
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
        self._refresh_shell()

    def _load_project(self, project_dir: Path) -> None:
        config = load_project_config(project_dir)
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
            self.source_dir.set(str(resolve_project_path(project_dir, config.source_roots[0])))
        self.output_dir.set(str(resolve_project_path(project_dir, config.output_root)))
        secrets = load_secrets(project_dir)
        saved_key = ((secrets.get("providers") or {}).get("openai") or {}).get("api_key", "")
        self.api_key_value.set(saved_key)
        self.save_api_key.set(bool(saved_key))
        self.view_state.has_project = True
        self.home_summary_var.set(f"Loaded project {config.project_name} with preset {config.preset} and export profile {config.export_profile}.")
        self.processing_summary_var.set("Project loaded. Run scan to refresh corpus state.")
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
                self.review_tree.insert(
                    "",
                    END,
                    iid=tree_id,
                    values=(
                        item.get("status"),
                        item.get("severity"),
                        item.get("kind"),
                        Path(item.get("source_path", "")).name,
                    ),
                )

        all_reviews = load_reviews(project_dir).get("items", []) if project_dir else []
        open_count = sum(1 for item in all_reviews if item.get("status") == "open")
        self.review_summary_var.set(f"{open_count} open review item(s), {len(all_reviews)} total. Filter: {self.review_filter.get()}.")
        if items:
            selected_review_id = self.selected_review_id.get() if self.selected_review_id.get() in {item.get("review_id") for item in items} else items[0].get("review_id")
            self.selected_review_id.set(str(selected_review_id))
            selected_item = next(item for item in items if item.get("review_id") == selected_review_id)
            if self.review_tree is not None:
                tree_id = next((iid for iid, review_item in self._review_tree_map.items() if review_item.get("review_id") == selected_review_id), "")
                if tree_id:
                    self.review_tree.selection_set(tree_id)
            self._populate_review_editor(selected_item)
        else:
            self.selected_review_id.set("")
            self.review_title_edit.set("")
            self.review_domain_edit.set("")
            if self.review_note_text:
                self.review_note_text.delete("1.0", END)

    def _refresh_export_display(self, project_dir: Path) -> None:
        state = load_state(project_dir)
        exports = state.get("exports") or []
        if not exports:
            self.export_summary_var.set("No exports yet.")
            return
        latest = exports[-1]
        self.export_summary_var.set(
            f"Latest export: {latest.get('package_dir')} | "
            f"files={len(latest.get('written_files') or [])} | "
            f"validation={len(latest.get('validation_messages') or [])}"
        )

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
        config.preset = self.preset.get().strip() or config.preset
        config.export_profile = self.export_profile.get().strip() or config.export_profile
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
        if self.review_note_text:
            self.review_note_text.delete("1.0", END)
            self.review_note_text.insert(END, str(item.get("resolution_note") or ""))

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
            return items
        if mode == "Open":
            return [item for item in items if item.get("status") == "open"]
        if mode == "Accepted":
            return [item for item in items if item.get("status") == "accepted"]
        if mode == "Rejected":
            return [item for item in items if item.get("status") == "rejected"]
        if mode == "Duplicates":
            return [item for item in items if item.get("kind") == "duplicate"]
        if mode == "AI Low Confidence":
            return [item for item in items if item.get("kind") == "ai_low_confidence"]
        return items

    def _review_counts(self) -> dict[str, int]:
        project_dir = self._current_project_dir(optional=True)
        items = load_reviews(project_dir).get("items", []) if project_dir else []
        return {
            "open": sum(1 for item in items if item.get("status") == "open"),
            "accepted": sum(1 for item in items if item.get("status") == "accepted"),
            "rejected": sum(1 for item in items if item.get("status") == "rejected"),
        }

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
        }

    def _build_next_actions(self, summary: dict[str, int]) -> list[str]:
        if not self.view_state.has_project:
            return [
                "Create a project with a source folder and export directory.",
                "Pick a preset that matches the document mix you expect.",
                "Keep AI disabled until you add a key.",
            ]
        if summary["documents"] == 0:
            return [
                "Run the first scan to populate the corpus state.",
                "Check source roots and output location in Sources.",
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

    def _build_export_cards(self, latest: dict | None) -> list[tuple[str, tuple[str, str, str]]]:
        if not latest:
            return [
                ("knowledge_core", ("0", "muted", "No package exported yet.")),
                ("reference_facts", ("0", "muted", "No package exported yet.")),
                ("glossary", ("0", "muted", "No package exported yet.")),
            ]
        files = [Path(path).name for path in (latest.get("written_files") or [])]
        footprint = sum(Path(path).stat().st_size for path in latest.get("written_files") or [] if Path(path).exists())
        return [
            ("knowledge_core", (str(sum(1 for name in files if name.startswith("knowledge_core"))), "primary", "Core answer files.")),
            ("procedures", (str(sum(1 for name in files if name.startswith("procedures"))), "success", "Actionable workflow pages.")),
            ("footprint", (f"{footprint // 1024} KB", "warn" if latest.get("validation_messages") else "success", "Current package size.")),
        ]

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
