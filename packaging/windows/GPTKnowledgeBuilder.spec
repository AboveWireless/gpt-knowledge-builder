# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from knowledge_builder.version import APP_NAME, EXECUTABLE_NAME


project_root = Path.cwd()
launcher = project_root / "packaging" / "windows" / "app_launcher.py"
icon_path = project_root / "packaging" / "windows" / "assets" / "app.ico"
version_file = os.environ.get("PYINSTALLER_VERSION_FILE")

datas = [
    (str(project_root / "README.md"), "."),
]

hiddenimports = [
    "tkinter",
    "tkinter.ttk",
    "tkinter.scrolledtext",
    "yaml",
    "openai",
]

a = Analysis(
    [str(launcher)],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXECUTABLE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon_path),
    version=version_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
