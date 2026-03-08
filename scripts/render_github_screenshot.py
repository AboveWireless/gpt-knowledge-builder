from __future__ import annotations

import argparse
from pathlib import Path
from tkinter import Tk

from knowledge_builder.gui import App


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch a GUI scene for GitHub screenshot capture.")
    parser.add_argument("--project-file", type=Path, default=None)
    parser.add_argument("--view", choices=["home", "sources", "processing", "review", "export", "settings"], default="home")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=920)
    parser.add_argument("--linger-ms", type=int, default=12000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Tk()
    root.geometry(f"{args.width}x{args.height}")
    root.minsize(args.width, args.height)

    app = App(root, initial_config=args.project_file)
    root.update_idletasks()
    root.lift()
    root.attributes("-topmost", True)
    root.after(1200, lambda: root.attributes("-topmost", False))
    root.after(250, lambda: app._set_active_view(args.view))
    root.after(args.linger_ms, root.destroy)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
