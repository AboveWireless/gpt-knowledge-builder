from __future__ import annotations

from pathlib import Path

from ..utils import ensure_dir
from .store import load_state, save_state, state_root


def render_document_preview(project_root: Path, source_path: str, unit_index: int = 0) -> dict:
    project_root = project_root.resolve()
    state = load_state(project_root)
    record = (state.get("documents") or {}).get(str(Path(source_path).resolve())) or {}
    document = record.get("document") or {}
    units = list(document.get("preview_units") or [])
    if not units:
        return {
            "label": "Preview",
            "text": str(document.get("preview_excerpt") or "No preview available."),
            "image_path": "",
            "unit_index": 0,
            "unit_count": 0,
            "mode": str(document.get("preview_mode") or "text"),
            "error": str(document.get("last_preview_error") or ""),
        }

    index = max(0, min(unit_index, len(units) - 1))
    payload = dict(units[index])
    payload["unit_index"] = index
    payload["unit_count"] = len(units)
    payload["mode"] = str(document.get("preview_mode") or "text")
    payload["image_path"] = str(payload.get("image_path") or "")
    payload["error"] = str(document.get("last_preview_error") or "")

    if payload["mode"] == "pdf_image":
        image_path, error = _ensure_pdf_preview_image(project_root, state, source_path, document, int(payload.get("page_number") or (index + 1)))
        payload["image_path"] = image_path
        payload["error"] = error

    return payload


def render_document_preview_strip(project_root: Path, source_path: str) -> list[dict]:
    project_root = project_root.resolve()
    state = load_state(project_root)
    record = (state.get("documents") or {}).get(str(Path(source_path).resolve())) or {}
    document = record.get("document") or {}
    units = list(document.get("preview_units") or [])
    return [render_document_preview(project_root, source_path, index) for index in range(len(units))]


def _ensure_pdf_preview_image(
    project_root: Path,
    state: dict,
    source_path: str,
    document: dict,
    page_number: int,
) -> tuple[str, str]:
    cache = document.setdefault("preview_cache", {})
    cache_key = str(page_number)
    cached = str(cache.get(cache_key) or "")
    if cached and Path(cached).exists():
        return cached, ""

    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        message = f"PDF preview unavailable: {exc}"
        document["last_preview_error"] = message
        _persist_preview_state(project_root, state, str(Path(source_path).resolve()), document)
        return "", message

    try:
        pdf = fitz.open(str(source_path))
        page = pdf[page_number - 1]
        width = max(float(getattr(getattr(page, "rect", None), "width", 0.0) or 0.0), 1.0)
        scale = 1.5 if width >= 700 else max(1.5, 900.0 / width)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        preview_dir = state_root(project_root) / "cache" / "previews"
        ensure_dir(preview_dir)
        checksum_prefix = str(document.get("checksum") or Path(source_path).stem)[:16]
        target = preview_dir / f"{checksum_prefix}__page_{page_number:03d}.png"
        pixmap.save(str(target))
        cache[cache_key] = str(target)
        document["preview_cache"] = cache
        document["last_preview_error"] = ""
        _persist_preview_state(project_root, state, str(Path(source_path).resolve()), document)
        return str(target), ""
    except Exception as exc:
        message = str(exc)
        document["last_preview_error"] = message
        _persist_preview_state(project_root, state, str(Path(source_path).resolve()), document)
        return "", message


def _persist_preview_state(project_root: Path, state: dict, source_key: str, document: dict) -> None:
    record = (state.get("documents") or {}).get(source_key) or {}
    record["document"] = document
    state.setdefault("documents", {})[source_key] = record
    save_state(project_root, state)
