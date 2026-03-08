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
        padx=10,
        pady=10,
    )


def build_metric_card(parent, model: MetricCardModel, palette: ColorPalette):
    card = ttk.Frame(parent, style="Card.TFrame", padding=14)
    card.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 10))
    ttk.Label(card, text=model.value, style="Metric.TLabel", foreground=tone_color(palette, model.tone)).pack(anchor=W)
    ttk.Label(card, text=model.label, style="MetricLabel.TLabel").pack(anchor=W, pady=(6, 0))
    if model.detail:
        ttk.Label(card, text=model.detail, style="Caption.TLabel", wraplength=220, justify=LEFT).pack(anchor=W, pady=(8, 0))
    return card


def build_status_chip(parent, text: str, palette: ColorPalette, tone: str = "primary"):
    frame = Frame(parent, bg=palette.chip_bg, highlightthickness=1, highlightbackground=tone_color(palette, tone))
    label = ttk.Label(frame, text=text, background=palette.chip_bg, foreground=tone_color(palette, tone), font=("Segoe UI Semibold", 9))
    label.pack(padx=10, pady=5)
    return frame

