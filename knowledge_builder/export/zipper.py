from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def write_zip(package_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zip_file:
        zip_file.write(package_dir, arcname=f"{package_dir.name}/")
        for path in sorted(package_dir.iterdir()):
            zip_file.write(path, arcname=f"{package_dir.name}/{path.name}")
