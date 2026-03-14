from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path
from tkinter import Tk

try:
    from PIL import Image, ImageGrab
except Exception:  # pragma: no cover - optional runtime helper
    Image = None
    ImageGrab = None

from knowledge_builder.gui import App
from knowledge_builder.project.pipeline import export_project, review_project, scan_project
from knowledge_builder.project.store import PROJECT_FILE, init_project


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "images"
REPO_SCREENSHOT_SIZE = (1400, 850)
REPO_SCREENSHOTS = [
    ("github-home.png", "home", "setup"),
    ("github-sources.png", "sources", "setup"),
    ("github-processing.png", "processing", "processing"),
    ("github-review.png", "review", "review"),
    ("github-export.png", "export", "export"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch GUI scenes and capture polished GitHub screenshots.")
    parser.add_argument("--project-file", type=Path, default=None)
    parser.add_argument("--view", choices=["home", "sources", "processing", "review", "export", "settings"], default="home")
    parser.add_argument("--width", type=int, default=1560)
    parser.add_argument("--height", type=int, default=980)
    parser.add_argument("--linger-ms", type=int, default=12000)
    parser.add_argument("--capture-delay-ms", type=int, default=900)
    parser.add_argument("--output", type=Path, default=None, help="Save a screenshot of the rendered window to this path.")
    parser.add_argument(
        "--demo-scenario",
        choices=["none", "starter", "setup", "processing", "review", "export"],
        default="none",
        help="Build a temporary demo workspace when a project file is not supplied.",
    )
    parser.add_argument(
        "--render-repo-assets",
        action="store_true",
        help="Generate the default GitHub screenshots under docs/images.",
    )
    return parser.parse_args()


def _write_demo_corpus(source_dir: Path, scenario: str) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    duplicate_body = "Ground lug torque: 45 Nm.\nDisconnect power before service.\nUse insulated gloves.\n"
    docs = {
        "overview.txt": (
            "Tower grounding overview\n\n"
            "This packet explains grounding safety, inspection timing, and torque checks.\n"
            "Use it as the starting point for field technicians and support teams.\n"
        ),
        "checklist.txt": (
            "Grounding checklist\n\n"
            "1. Inspect all visible grounding straps.\n"
            "2. Confirm lug torque.\n"
            "3. Record the result in the maintenance log.\n"
        ),
        "faq.md": (
            "# Grounding FAQ\n\n"
            "- What torque should be used?\n"
            "- When should the site be reinspected?\n"
            "- Which failures should block export?\n"
        ),
    }
    if scenario == "review":
        docs["duplicate-a.txt"] = duplicate_body
        docs["duplicate-b.txt"] = duplicate_body
        docs["broken.json"] = '{"alpha": 1,,}'
    if scenario == "export":
        docs = {
            "overview.txt": (
                "Tower grounding overview\n\n"
                "This workspace bundles clean reference material for tower grounding maintenance.\n"
                "Teams use it to answer routine service questions and keep field procedures consistent.\n"
            ),
            "maintenance-notes.txt": (
                "Maintenance notes\n\n"
                "Field teams inspect visible grounding straps during each preventive maintenance visit.\n"
                "Any loose hardware is documented and corrected before the site is returned to service.\n"
            ),
            "safety-brief.txt": (
                "Safety brief\n\n"
                "Disconnect site power when required by the procedure and verify the safe condition before touching conductive parts.\n"
                "Wear insulated gloves and record each completed safety check in the maintenance log.\n"
            ),
            "training-summary.txt": (
                "Training summary\n\n"
                "New technicians review grounding basics, inspection timing, and documentation rules before they visit a live site.\n"
                "Supervisors use the summary during onboarding and quarterly refresh sessions.\n"
            ),
            "service-history.txt": (
                "Service history\n\n"
                "Keep torque confirmations, continuity readings, and remediation notes together with the site service history.\n"
                "That record helps the team answer follow-up questions without reopening the raw source folders.\n"
            ),
        }
    for name, body in docs.items():
        (source_dir / name).write_text(body, encoding="utf-8")


def _build_demo_project(base_dir: Path, scenario: str) -> Path | None:
    if scenario == "starter":
        scenario = "setup"
    if scenario == "none":
        return None
    source_dir = base_dir / "source"
    output_dir = base_dir / "output"
    project_dir = base_dir / "workspace"
    corpus_scenario = {
        "processing": "review",
        "review": "review",
        "export": "export",
    }.get(scenario, "setup")
    _write_demo_corpus(source_dir, corpus_scenario)
    init_project(project_dir, "Tower Library", [source_dir], output_dir, "mixed-office-documents", "custom-gpt-balanced")
    if scenario in {"processing", "review", "export"}:
        scan_project(project_dir)
    if scenario == "export":
        review_project(project_dir, approve_all=True)
        export_project(project_dir)
    return project_dir / PROJECT_FILE


def _capture_window(root: Tk, output_path: Path) -> None:
    if ImageGrab is None or Image is None:
        raise RuntimeError("Pillow is required to capture screenshots. Install Pillow or use the OCR extras.")
    root.update()
    root.update_idletasks()
    time.sleep(0.15)
    bbox, used_client_area = _capture_bbox(root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(bbox=bbox)
    image = _trim_capture_border(image, top_only=used_client_area)
    image = _fit_capture_canvas(image)
    image.save(output_path)


def _capture_bbox(root: Tk) -> tuple[tuple[int, int, int, int], bool]:
    client_bbox = _win32_client_bbox(root)
    if client_bbox is not None:
        return client_bbox, True
    left = root.winfo_rootx()
    top = root.winfo_rooty()
    right = left + root.winfo_width()
    bottom = top + root.winfo_height()
    return (left, top, right, bottom), False


def _win32_client_bbox(root: Tk) -> tuple[int, int, int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        hwnd = root.winfo_id()
        rect = RECT()
        if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        top_left = POINT(rect.left, rect.top)
        bottom_right = POINT(rect.right, rect.bottom)
        if not ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
            return None
        if not ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(bottom_right)):
            return None
        return top_left.x, top_left.y, bottom_right.x, bottom_right.y
    except Exception:
        return None


def _trim_capture_border(image, *, top_only: bool = False):
    rgb = image.convert("RGB")
    width, height = rgb.size

    def row_avg(y: int) -> float:
        total = 0
        for x in range(width):
            red, green, blue = rgb.getpixel((x, y))
            total += red + green + blue
        return total / (width * 3)

    def col_avg(x: int, row_limit: int) -> float:
        total = 0
        for y in range(row_limit):
            red, green, blue = rgb.getpixel((x, y))
            total += red + green + blue
        return total / (row_limit * 3)

    top_trim = 0
    bright_band_start = None
    for y in range(min(140, height)):
        if row_avg(y) > 180:
            bright_band_start = y
            break
    if bright_band_start is not None:
        for y in range(bright_band_start, min(bright_band_start + 140, height)):
            if row_avg(y) < 120:
                top_trim = y
                break

    if top_only:
        if top_trim <= 0 or top_trim >= height:
            return image
        return image.crop((0, top_trim, width, height))

    sample_limit = max(40, min(height, top_trim + 120))

    left_trim = 0
    for x in range(min(80, width)):
        if col_avg(x, sample_limit) > 30:
            left_trim = x
            break

    right_trim = width
    for x in range(width - 1, max(width - 80, 0), -1):
        if col_avg(x, sample_limit) > 20:
            right_trim = x + 1
            break

    if left_trim >= right_trim or top_trim >= height:
        return image
    return image.crop((left_trim, top_trim, right_trim, height))


def _fit_capture_canvas(image):
    target_width, target_height = REPO_SCREENSHOT_SIZE
    width, height = image.size

    if width > target_width:
        x_offset = max(0, (width - target_width) // 2)
        image = image.crop((x_offset, 0, x_offset + target_width, height))
        width = target_width
    elif width < target_width:
        canvas = image.copy().convert("RGB")
        background = canvas.getpixel((0, min(24, height - 1))) if height else (13, 23, 40)
        padded = Image.new("RGB", (target_width, height), background)
        padded.paste(canvas, ((target_width - width) // 2, 0))
        image = padded
        width = target_width

    if height > target_height:
        image = image.crop((0, 0, width, target_height))
        height = target_height
    elif height < target_height:
        canvas = image.convert("RGB")
        background = canvas.getpixel((min(32, width - 1), height - 1)) if height else (13, 23, 40)
        padded = Image.new("RGB", (width, target_height), background)
        padded.paste(canvas, (0, 0))
        image = padded

    return image


def _destroy_root(root: Tk) -> None:
    try:
        pending = root.tk.splitlist(root.tk.call("after", "info"))
    except Exception:
        pending = ()
    for after_id in pending:
        try:
            root.after_cancel(after_id)
        except Exception:
            pass
    root.destroy()


def _render_scene(
    *,
    project_file: Path | None,
    view: str,
    width: int,
    height: int,
    linger_ms: int,
    capture_delay_ms: int,
    output: Path | None,
) -> None:
    root = Tk()
    root.geometry(f"{width}x{height}")
    root.minsize(width, height)

    app = App(root, initial_config=project_file)
    root.update_idletasks()
    app._set_active_view(view)
    app._refresh_shell()
    root.update()
    root.lift()
    root.attributes("-topmost", True)
    root.update()
    time.sleep(0.2)
    root.attributes("-topmost", False)
    root.update()

    if output is not None:
        time.sleep(capture_delay_ms / 1000)
        root.update()
        _capture_window(root, output)
        _destroy_root(root)
        return

    root.after(linger_ms, lambda: _destroy_root(root))
    root.mainloop()


def _render_repo_assets(args: argparse.Namespace) -> int:
    output_dir = DEFAULT_OUTPUT_DIR
    with tempfile.TemporaryDirectory(prefix="gptkb-gh-shot-") as temp_root:
        temp_root_path = Path(temp_root)
        for filename, view, scenario in REPO_SCREENSHOTS:
            project_file = _build_demo_project(temp_root_path / filename.replace(".png", ""), scenario)
            _render_scene(
                project_file=project_file,
                view=view,
                width=args.width,
                height=args.height,
                linger_ms=args.linger_ms,
                capture_delay_ms=args.capture_delay_ms,
                output=output_dir / filename,
            )
    return 0


def main() -> int:
    args = parse_args()
    if args.render_repo_assets:
        return _render_repo_assets(args)

    project_file = args.project_file
    if project_file is None and args.demo_scenario != "none":
        with tempfile.TemporaryDirectory(prefix="gptkb-shot-") as temp_root:
            project_file = _build_demo_project(Path(temp_root), args.demo_scenario)
            _render_scene(
                project_file=project_file,
                view=args.view,
                width=args.width,
                height=args.height,
                linger_ms=args.linger_ms,
                capture_delay_ms=args.capture_delay_ms,
                output=args.output,
            )
        return 0

    _render_scene(
        project_file=project_file,
        view=args.view,
        width=args.width,
        height=args.height,
        linger_ms=args.linger_ms,
        capture_delay_ms=args.capture_delay_ms,
        output=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
