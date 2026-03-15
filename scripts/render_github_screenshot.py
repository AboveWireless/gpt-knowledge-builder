from __future__ import annotations

import argparse
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from tkinter import Tk

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageOps
except Exception:  # pragma: no cover - optional runtime helper
    Image = None
    ImageDraw = None
    ImageFilter = None
    ImageFont = None
    ImageGrab = None
    ImageOps = None

from knowledge_builder.gui import App
from knowledge_builder.project.pipeline import export_project, review_project, scan_project
from knowledge_builder.project.store import PROJECT_FILE, init_project


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "images"
REPO_ASSET_SIZE = (1400, 850)
RAW_SCREENSHOT_FILENAMES = [
    "github-home.png",
    "github-sources.png",
    "github-processing.png",
    "github-review.png",
    "github-export.png",
]
PRESENTATION_FILENAMES = [
    "repo-hero.png",
    "repo-tour.png",
    "repo-review-detail.png",
    "repo-export-detail.png",
]
HERO_CONTENT_CROP = (0.24, 0.06, 0.985, 0.95)
TOUR_CARD_CROPS = {
    "sources": (0.38, 0.15, 0.985, 0.73),
    "processing": (0.31, 0.26, 0.98, 0.95),
    "review": (0.34, 0.10, 0.98, 0.96),
    "export": (0.36, 0.10, 0.99, 0.96),
}
DETAIL_CROPS = {
    "review": (0.34, 0.09, 0.97, 0.96),
    "export": (0.35, 0.09, 0.99, 0.96),
}


@dataclass(frozen=True)
class SceneSpec:
    filename: str
    view: str
    scenario: str
    width: int
    height: int
    prep: str = "default"
    y_anchor: str = "top"


REPO_SCENES = [
    SceneSpec("github-home.png", "home", "setup", 1560, 980, prep="home", y_anchor="top"),
    SceneSpec("github-sources.png", "sources", "setup", 1680, 1260, prep="sources_detail", y_anchor="top"),
    SceneSpec("github-processing.png", "processing", "processing", 1700, 1320, prep="processing_detail", y_anchor="center"),
    SceneSpec("github-review.png", "review", "review", 1700, 1280, prep="review_focus", y_anchor="center"),
    SceneSpec("github-export.png", "export", "export", 1700, 1320, prep="export_focus", y_anchor="center"),
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


def _pil_required() -> None:
    if None in {Image, ImageDraw, ImageFilter, ImageFont, ImageGrab, ImageOps}:
        raise RuntimeError("Pillow is required to render the GitHub screenshots. Install Pillow or the OCR extras.")


def _resample():
    if hasattr(Image, "Resampling"):
        return Image.Resampling.LANCZOS
    return Image.LANCZOS


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


def _capture_window_image(root: Tk):
    _pil_required()
    root.update()
    root.update_idletasks()
    time.sleep(0.15)
    bbox, used_client_area = _capture_bbox(root)
    image = ImageGrab.grab(bbox=bbox)
    image = _trim_capture_border(image, top_only=used_client_area)
    return image.convert("RGB")


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


def _fit_capture_canvas(image, *, target_size: tuple[int, int] = REPO_ASSET_SIZE, y_anchor: str = "top"):
    _pil_required()
    target_width, target_height = target_size
    width, height = image.size

    if width > target_width:
        x_offset = max(0, (width - target_width) // 2)
        image = image.crop((x_offset, 0, x_offset + target_width, height))
        width = target_width
    elif width < target_width:
        background = image.getpixel((0, min(24, height - 1))) if height else (13, 23, 40)
        padded = Image.new("RGB", (target_width, height), background)
        padded.paste(image, ((target_width - width) // 2, 0))
        image = padded
        width = target_width

    if height > target_height:
        if y_anchor == "bottom":
            y_offset = height - target_height
        elif y_anchor == "center":
            y_offset = max(0, (height - target_height) // 2)
        else:
            y_offset = 0
        image = image.crop((0, y_offset, width, y_offset + target_height))
        height = target_height
    elif height < target_height:
        sample_y = min(height - 1, max(0, height - 24)) if height else 0
        background = image.getpixel((min(32, width - 1), sample_y)) if width and height else (13, 23, 40)
        padded = Image.new("RGB", (width, target_height), background)
        if y_anchor == "bottom":
            y_offset = target_height - height
        elif y_anchor == "center":
            y_offset = (target_height - height) // 2
        else:
            y_offset = 0
        padded.paste(image, (0, y_offset))
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


def _prepare_scene(app: App, prep: str) -> None:
    app.capture_scene = None
    if prep == "sources_detail":
        app.show_beginner_source_details.set(True)
    elif prep == "processing_detail":
        app.show_beginner_processing_details.set(True)
    elif prep == "review_focus":
        app.review_filter.set("Open")
        app.review_queue_mode.set("inbox")
        project_dir = app._current_project_dir(optional=True)
        if project_dir:
            app._refresh_review_display(project_dir)
    elif prep == "capture_review_detail":
        app.capture_scene = "repo_review_detail"
        app.review_filter.set("Open")
        app.review_queue_mode.set("inbox")
    elif prep == "capture_export_detail":
        app.capture_scene = "repo_export_detail"
    elif prep == "export_focus":
        project_dir = app._current_project_dir(optional=True)
        if project_dir:
            app._refresh_export_display(project_dir)
    app._refresh_shell()


def _render_scene_image(
    *,
    project_file: Path | None,
    view: str,
    width: int,
    height: int,
    capture_delay_ms: int,
    prep: str = "default",
):
    root = Tk()
    root.geometry(f"{width}x{height}")
    root.minsize(width, height)

    app = App(root, initial_config=project_file)
    root.update_idletasks()
    app._set_active_view(view)
    _prepare_scene(app, prep)
    root.update()
    root.lift()
    root.attributes("-topmost", True)
    root.update()
    time.sleep(0.2)
    root.attributes("-topmost", False)
    root.update()
    time.sleep(capture_delay_ms / 1000)
    image = _capture_window_image(root)
    _destroy_root(root)
    return image


def _preview_scene(
    *,
    project_file: Path | None,
    view: str,
    width: int,
    height: int,
    linger_ms: int,
    prep: str = "default",
) -> None:
    root = Tk()
    root.geometry(f"{width}x{height}")
    root.minsize(width, height)

    app = App(root, initial_config=project_file)
    root.update_idletasks()
    app._set_active_view(view)
    _prepare_scene(app, prep)
    root.update()
    root.lift()
    root.attributes("-topmost", True)
    root.update()
    time.sleep(0.2)
    root.attributes("-topmost", False)
    root.update()
    root.after(linger_ms, lambda: _destroy_root(root))
    root.mainloop()


def _font(size: int, *, bold: bool = False):
    _pil_required()
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _gradient_canvas(size: tuple[int, int], top_color=(6, 14, 26), bottom_color=(14, 33, 52)):
    _pil_required()
    width, height = size
    strip = Image.new("RGB", (1, height))
    draw = ImageDraw.Draw(strip)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(int(top + (bottom - top) * ratio) for top, bottom in zip(top_color, bottom_color))
        draw.point((0, y), fill=color)
    return strip.resize((width, height))


def _rounded_mask(size: tuple[int, int], radius: int):
    _pil_required()
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask


def _paste_framed_image(canvas, image, box, *, radius: int = 30):
    _pil_required()
    x0, y0, x1, y1 = box
    width = x1 - x0
    height = y1 - y0
    fitted = ImageOps.fit(image.convert("RGB"), (width, height), method=_resample())
    shadow = Image.new("RGBA", (width + 60, height + 60), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((24, 18, width + 24, height + 18), radius=radius, fill=(0, 0, 0, 165))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.alpha_composite(shadow, (x0 - 24, y0 - 14))

    mask = _rounded_mask((width, height), radius)
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    layer.paste(fitted.convert("RGBA"), (0, 0), mask)
    canvas.alpha_composite(layer, (x0, y0))

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=radius, outline=(66, 196, 255, 210), width=2)


def _draw_chip(draw, x: int, y: int, text: str, *, fill=(13, 34, 56, 235), outline=(73, 199, 255, 255), text_color=(237, 247, 255), font=None) -> tuple[int, int, int, int]:
    font = font or _font(24, bold=True)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    pad_x = 18
    pad_y = 10
    box = (x, y, x + text_width + pad_x * 2, y + text_height + pad_y * 2)
    draw.rounded_rectangle(box, radius=22, fill=fill, outline=outline, width=2)
    draw.text((x + pad_x, y + pad_y - 1), text, font=font, fill=text_color)
    return box


def _focus_crop(image, fractions: tuple[float, float, float, float], *, size: tuple[int, int] = REPO_ASSET_SIZE):
    _pil_required()
    width, height = image.size
    left = int(width * fractions[0])
    top = int(height * fractions[1])
    right = int(width * fractions[2])
    bottom = int(height * fractions[3])
    cropped = image.crop((left, top, max(left + 1, right), max(top + 1, bottom)))
    return ImageOps.fit(cropped.convert("RGB"), size, method=_resample())


def _compose_hero(home_image):
    _pil_required()
    canvas = _gradient_canvas(REPO_ASSET_SIZE).convert("RGBA")
    hero_crop = _focus_crop(home_image, HERO_CONTENT_CROP, size=(1180, 690))
    _paste_framed_image(canvas, hero_crop, (110, 82, 1290, 772), radius=34)
    draw = ImageDraw.Draw(canvas)
    chip_font = _font(24, bold=True)
    x = 126
    for label in ("Pick Folders", "Scan Files", "Fix Issues", "Get GPT Files"):
        box = _draw_chip(draw, x, 28, label, font=chip_font)
        x = box[2] + 14
    return canvas.convert("RGB")


def _compose_tour(images: dict[str, object]):
    _pil_required()
    canvas = _gradient_canvas(REPO_ASSET_SIZE, top_color=(7, 15, 25), bottom_color=(10, 26, 42)).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    card_specs = [
        ("Pick Folders", images["github-sources.png"], (66, 84, 678, 392), TOUR_CARD_CROPS["sources"]),
        ("Scan And Triage", images["github-processing.png"], (722, 84, 1334, 392), TOUR_CARD_CROPS["processing"]),
        ("Review Issues", images["review-focus"], (66, 458, 678, 766), TOUR_CARD_CROPS["review"]),
        ("Export Package", images["export-focus"], (722, 458, 1334, 766), TOUR_CARD_CROPS["export"]),
    ]
    label_font = _font(22, bold=True)
    for label, image, box, crop in card_specs:
        target_size = (box[2] - box[0], box[3] - box[1])
        panel = _focus_crop(image, crop, size=target_size)
        _paste_framed_image(canvas, panel, box, radius=24)
        _draw_chip(draw, box[0] + 16, box[1] + 16, label, font=label_font)
    return canvas.convert("RGB")


def _compose_detail(image, *, crop: tuple[float, float, float, float], chip: str):
    _pil_required()
    canvas = _gradient_canvas(REPO_ASSET_SIZE, top_color=(8, 16, 28), bottom_color=(14, 31, 48)).convert("RGBA")
    detail = _focus_crop(image, crop, size=(1180, 690))
    _paste_framed_image(canvas, detail, (110, 104, 1290, 794), radius=30)
    draw = ImageDraw.Draw(canvas)
    _draw_chip(draw, 122, 34, chip, font=_font(24, bold=True))
    return canvas.convert("RGB")


def _save_image(image, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def _render_repo_assets(args: argparse.Namespace) -> int:
    _pil_required()
    output_dir = DEFAULT_OUTPUT_DIR
    raw_assets: dict[str, object] = {}
    scene_assets: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="gptkb-gh-shot-") as temp_root:
        temp_root_path = Path(temp_root)
        for spec in REPO_SCENES:
            project_file = _build_demo_project(temp_root_path / spec.filename.replace(".png", ""), spec.scenario)
            captured = _render_scene_image(
                project_file=project_file,
                view=spec.view,
                width=spec.width,
                height=spec.height,
                capture_delay_ms=args.capture_delay_ms,
                prep=spec.prep,
            )
            scene_assets[spec.filename] = captured
            fitted = _fit_capture_canvas(captured, y_anchor=spec.y_anchor)
            raw_assets[spec.filename] = fitted
            _save_image(fitted, output_dir / spec.filename)

        review_detail_project = _build_demo_project(temp_root_path / "repo-review-detail", "review")
        review_detail_scene = _render_scene_image(
            project_file=review_detail_project,
            view="review",
            width=1560,
            height=980,
            capture_delay_ms=args.capture_delay_ms,
            prep="capture_review_detail",
        )
        export_detail_project = _build_demo_project(temp_root_path / "repo-export-detail", "export")
        export_detail_scene = _render_scene_image(
            project_file=export_detail_project,
            view="export",
            width=1560,
            height=980,
            capture_delay_ms=args.capture_delay_ms,
            prep="capture_export_detail",
        )

    presentation_assets = {
        "repo-hero.png": _compose_hero(raw_assets["github-home.png"]),
        "repo-tour.png": _compose_tour({**scene_assets, "review-focus": review_detail_scene, "export-focus": export_detail_scene}),
        "repo-review-detail.png": _compose_detail(review_detail_scene, crop=DETAIL_CROPS["review"], chip="Review Details"),
        "repo-export-detail.png": _compose_detail(export_detail_scene, crop=DETAIL_CROPS["export"], chip="Export Details"),
    }
    for filename, image in presentation_assets.items():
        _save_image(image, output_dir / filename)
    return 0


def main() -> int:
    args = parse_args()
    if args.render_repo_assets:
        return _render_repo_assets(args)

    project_file = args.project_file
    prep = "default"
    if args.demo_scenario == "processing":
        prep = "processing_detail"
    elif args.demo_scenario == "review":
        prep = "review_focus"
    elif args.demo_scenario == "export":
        prep = "export_focus"

    if args.output is None:
        if project_file is None and args.demo_scenario != "none":
            with tempfile.TemporaryDirectory(prefix="gptkb-shot-") as temp_root:
                project_file = _build_demo_project(Path(temp_root), args.demo_scenario)
                _preview_scene(
                    project_file=project_file,
                    view=args.view,
                    width=args.width,
                    height=args.height,
                    linger_ms=args.linger_ms,
                    prep=prep,
                )
            return 0

        _preview_scene(
            project_file=project_file,
            view=args.view,
            width=args.width,
            height=args.height,
            linger_ms=args.linger_ms,
            prep=prep,
        )
        return 0

    if project_file is None and args.demo_scenario != "none":
        with tempfile.TemporaryDirectory(prefix="gptkb-shot-") as temp_root:
            project_file = _build_demo_project(Path(temp_root), args.demo_scenario)
            image = _render_scene_image(
                project_file=project_file,
                view=args.view,
                width=args.width,
                height=args.height,
                capture_delay_ms=args.capture_delay_ms,
                prep=prep,
            )
    else:
        image = _render_scene_image(
            project_file=project_file,
            view=args.view,
            width=args.width,
            height=args.height,
            capture_delay_ms=args.capture_delay_ms,
            prep=prep,
        )

    _save_image(_fit_capture_canvas(image), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
