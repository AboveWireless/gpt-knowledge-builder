from __future__ import annotations

from tkinter import BOTH, LEFT, W, X, Frame
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk

from .models import ColorPalette, MetricCardModel, TypeScale
from .theme import tone_color


def style_scrolled_text(widget: ScrolledText, palette: ColorPalette, type_scale: TypeScale) -> None:
    widget.configure(
        wrap="word",
        font=type_scale.body,
        relief="flat",
        borderwidth=0,
        background=palette.panel_alt,
        foreground=palette.ink,
        insertbackground=palette.ink,
        selectbackground=palette.nav_active,
        selectforeground=palette.ink,
        padx=14,
        pady=14,
    )


def build_metric_card(parent, model: MetricCardModel, palette: ColorPalette):
    card = ttk.Frame(parent, style="Card.TFrame", padding=18)
    card.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 12))
    ttk.Label(card, text=model.value, style="Metric.TLabel", foreground=tone_color(palette, model.tone)).pack(anchor=W)
    ttk.Label(card, text=model.label, style="MetricLabel.TLabel").pack(anchor=W, pady=(8, 0))
    if model.detail:
        ttk.Label(card, text=model.detail, style="Caption.TLabel", wraplength=260, justify=LEFT).pack(anchor=W, pady=(10, 0))
    return card


def build_status_chip(parent, text: str, palette: ColorPalette, tone: str = "primary", wraplength: int | None = None):
    frame = Frame(parent, bg=palette.chip_bg, highlightthickness=1, highlightbackground=tone_color(palette, tone))
    label = ttk.Label(
        frame,
        text=text,
        background=palette.chip_bg,
        foreground=tone_color(palette, tone),
        font=("Segoe UI Semibold", 10),
        wraplength=wraplength or 0,
        justify=LEFT,
    )
    label.pack(padx=12, pady=7)
    frame._chip_label = label  # type: ignore[attr-defined]
    frame._chip_palette = palette  # type: ignore[attr-defined]
    return frame


def configure_status_chip(chip, text: str, palette: ColorPalette, tone: str = "primary", wraplength: int | None = None) -> None:
    if chip is None:
        return
    color = tone_color(palette, tone)
    chip.configure(bg=palette.chip_bg, highlightbackground=color)
    label = getattr(chip, "_chip_label", None)
    if label is not None:
        label.configure(text=text, background=palette.chip_bg, foreground=color, wraplength=wraplength or 0)


def build_info_button(parent, help_text: str, palette: ColorPalette):
    button = ttk.Label(
        parent,
        text="?",
        foreground=palette.primary,
        cursor="hand2",
        font=("Segoe UI Semibold", 10),
        padding=(4, 0),
    )
    button._help_text = help_text  # type: ignore[attr-defined]
    return button
