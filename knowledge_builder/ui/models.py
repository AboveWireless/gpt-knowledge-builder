from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ColorPalette:
    bg: str = "#09111f"
    bg_alt: str = "#0d1728"
    panel: str = "#132238"
    panel_alt: str = "#182a44"
    panel_soft: str = "#1d3150"
    ink: str = "#f1f5ff"
    ink_muted: str = "#9cb0cf"
    line: str = "#294263"
    primary: str = "#4ed8ff"
    primary_active: str = "#82e6ff"
    success: str = "#45d7a3"
    warn: str = "#ffca6b"
    danger: str = "#ff7a8a"
    chip_bg: str = "#203350"
    nav_active: str = "#22395a"


@dataclass(frozen=True, slots=True)
class TypeScale:
    title: tuple[str, int, str] = ("Segoe UI Semibold", 24, "normal")
    heading: tuple[str, int, str] = ("Segoe UI Semibold", 16, "normal")
    subheading: tuple[str, int, str] = ("Segoe UI Semibold", 12, "normal")
    body: tuple[str, int, str] = ("Segoe UI", 10, "normal")
    caption: tuple[str, int, str] = ("Segoe UI", 9, "normal")
    metric: tuple[str, int, str] = ("Segoe UI Semibold", 20, "normal")


@dataclass(frozen=True, slots=True)
class SpacingScale:
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32


@dataclass(slots=True)
class ViewState:
    active_view: str = "home"
    has_project: bool = False
    review_filter: str = "All"
    selected_review_id: str = ""


@dataclass(slots=True)
class MetricCardModel:
    label: str
    value: str
    tone: str = "primary"
    detail: str = ""

