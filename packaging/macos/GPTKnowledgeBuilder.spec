# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from knowledge_builder.version import APP_DESCRIPTION, APP_NAME, APP_VERSION, EXECUTABLE_NAME


project_root = Path.cwd()
launcher = project_root / "packaging" / "macos" / "app_launcher.py"
icon_path = project_root / "packaging" / "macos" / "assets" / "app.icns"
fallback_icon_path = project_root / "packaging" / "windows" / "assets" / "app.ico"

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
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon_path) if icon_path.exists() else (str(fallback_icon_path) if fallback_icon_path.exists() else None),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(icon_path) if icon_path.exists() else (str(fallback_icon_path) if fallback_icon_path.exists() else None),
    bundle_identifier="com.gptknowledgebuilder.desktop",
    info_plist={
        "CFBundleDisplayName": APP_NAME,
        "CFBundleName": APP_NAME,
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "CFBundleGetInfoString": f"{APP_NAME} {APP_VERSION}",
        "CFBundleIdentifier": "com.gptknowledgebuilder.desktop",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": APP_DESCRIPTION,
    },
)
