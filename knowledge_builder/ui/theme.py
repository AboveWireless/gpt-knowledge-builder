from __future__ import annotations

from tkinter import Tk, ttk

from .models import ColorPalette, SpacingScale, TypeScale


def configure_theme(root: Tk, palette: ColorPalette, type_scale: TypeScale) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(background=palette.bg)
    style.configure(".", background=palette.bg, foreground=palette.ink, font=type_scale.body)
    style.configure("App.TFrame", background=palette.bg)
    style.configure("Sidebar.TFrame", background=palette.bg_alt)
    style.configure("Panel.TFrame", background=palette.panel)
    style.configure("PanelAlt.TFrame", background=palette.panel_alt)
    style.configure("Card.TFrame", background=palette.panel_alt, relief="flat")
    style.configure("Header.TLabel", background=palette.bg, foreground=palette.ink, font=type_scale.title)
    style.configure("Heading.TLabel", background=palette.panel, foreground=palette.ink, font=type_scale.heading)
    style.configure("Section.TLabel", background=palette.panel, foreground=palette.primary, font=type_scale.subheading)
    style.configure("Body.TLabel", background=palette.panel, foreground=palette.ink, font=type_scale.body)
    style.configure("Muted.TLabel", background=palette.panel, foreground=palette.ink_muted, font=type_scale.body)
    style.configure("Caption.TLabel", background=palette.panel, foreground=palette.ink_muted, font=type_scale.caption)
    style.configure("Metric.TLabel", background=palette.panel_alt, foreground=palette.ink, font=type_scale.metric)
    style.configure("MetricLabel.TLabel", background=palette.panel_alt, foreground=palette.ink_muted, font=type_scale.caption)
    style.configure(
        "Primary.TButton",
        background=palette.primary,
        foreground="#06131f",
        borderwidth=0,
        focusthickness=0,
        padding=(20, 12),
        font=type_scale.subheading,
    )
    style.map(
        "Primary.TButton",
        background=[("active", palette.primary_active), ("disabled", palette.panel_soft)],
        foreground=[("disabled", palette.ink_muted)],
    )
    style.configure(
        "Ghost.TButton",
        background=palette.panel_alt,
        foreground=palette.ink,
        borderwidth=1,
        bordercolor=palette.line,
        focusthickness=0,
        padding=(18, 12),
        font=type_scale.body,
    )
    style.map(
        "Ghost.TButton",
        background=[("active", palette.panel_soft), ("disabled", palette.panel)],
        foreground=[("disabled", palette.ink_muted)],
    )
    style.configure(
        "Nav.TButton",
        background=palette.bg_alt,
        foreground=palette.ink_muted,
        borderwidth=0,
        focusthickness=0,
        anchor="w",
        padding=(16, 14),
        font=type_scale.subheading,
    )
    style.map(
        "Nav.TButton",
        background=[("active", palette.nav_active), ("disabled", palette.bg_alt)],
        foreground=[("active", palette.ink), ("disabled", palette.ink_muted)],
    )
    style.configure(
        "NavActive.TButton",
        background=palette.nav_active,
        foreground=palette.ink,
        borderwidth=0,
        focusthickness=0,
        anchor="w",
        padding=(16, 14),
        font=type_scale.subheading,
    )
    style.configure("TEntry", fieldbackground=palette.panel_soft, foreground=palette.ink, bordercolor=palette.line)
    style.configure("TCombobox", fieldbackground=palette.panel_soft, foreground=palette.ink, bordercolor=palette.line)
    style.configure("TCheckbutton", background=palette.panel, foreground=palette.ink)
    style.configure("Treeview", background=palette.panel_alt, fieldbackground=palette.panel_alt, foreground=palette.ink, bordercolor=palette.line, rowheight=36)
    style.configure("Treeview.Heading", background=palette.panel_soft, foreground=palette.ink, font=type_scale.subheading)
    style.map("Treeview", background=[("selected", palette.nav_active)], foreground=[("selected", palette.ink)])
    return style


def tone_color(palette: ColorPalette, tone: str) -> str:
    tones = {
        "primary": palette.primary,
        "success": palette.success,
        "warn": palette.warn,
        "danger": palette.danger,
        "muted": palette.ink_muted,
    }
    return tones.get(tone, palette.primary)


def default_theme() -> tuple[ColorPalette, TypeScale, SpacingScale]:
    return ColorPalette(), TypeScale(), SpacingScale()
