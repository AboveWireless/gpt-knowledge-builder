from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path
from tkinter import Tk

try:
    from PIL import ImageGrab
except Exception:  # pragma: no cover - optional runtime helper
    ImageGrab = None

from knowledge_builder.gui import App
from knowledge_builder.project.pipeline import export_project, review_project, scan_project
from knowledge_builder.project.store import PROJECT_FILE, init_project


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "images"


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
        choices=["none", "starter", "review", "export"],
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
        "duplicate-a.txt": duplicate_body,
        "duplicate-b.txt": duplicate_body,
        "faq.md": (
            "# Grounding FAQ\n\n"
            "- What torque should be used?\n"
            "- When should the site be reinspected?\n"
            "- Which failures should block export?\n"
        ),
    }
    for name, body in docs.items():
        (source_dir / name).write_text(body, encoding="utf-8")
    if scenario in {"review", "export"}:
        (source_dir / "broken.json").write_text('{"alpha": 1,,}', encoding="utf-8")


def _build_demo_project(base_dir: Path, scenario: str) -> Path | None:
    if scenario in {"none", "starter"}:
        return None
    source_dir = base_dir / "source"
    output_dir = base_dir / "output"
    project_dir = base_dir / "workspace"
    _write_demo_corpus(source_dir, scenario)
    init_project(project_dir, "Tower Library", [source_dir], output_dir, "mixed-office-documents", "custom-gpt-balanced")
    scan_project(project_dir)
    if scenario == "export":
        review_project(project_dir, approve_all=True)
        export_project(project_dir)
    return project_dir / PROJECT_FILE


def _capture_window(root: Tk, output_path: Path) -> None:
    if ImageGrab is None:
        raise RuntimeError("Pillow is required to capture screenshots. Install Pillow or use the OCR extras.")
    root.update()
    root.update_idletasks()
    time.sleep(0.15)
    bbox, used_client_area = _capture_bbox(root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(bbox=bbox)
    image = _trim_capture_border(image, top_only=used_client_area)
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
    scenes = [
        ("github-home.png", "home", "starter"),
        ("github-review.png", "review", "review"),
        ("github-export.png", "export", "export"),
    ]
    with tempfile.TemporaryDirectory(prefix="gptkb-gh-shot-") as temp_root:
        temp_root_path = Path(temp_root)
        for filename, view, scenario in scenes:
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
