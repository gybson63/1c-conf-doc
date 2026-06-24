"""Resolve 1C configuration export directories (no API imports)."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

MAX_ZIP_BYTES = 500 * 1024 * 1024
MAX_ZIP_FILES = 50_000


class UploadError(ValueError):
    """Invalid upload or export path."""


def resolve_export_root(path: Path) -> Path:
    """Find directory containing Configuration.xml (root or single nested folder)."""
    path = path.resolve()
    if not path.is_dir():
        msg = f"Not a directory: {path}"
        raise UploadError(msg)

    if (path / "Configuration.xml").is_file():
        return path

    children = [p for p in path.iterdir() if p.is_dir()]
    if len(children) == 1 and (children[0] / "Configuration.xml").is_file():
        return children[0]

    msg = f"Configuration.xml not found in {path}"
    raise UploadError(msg)


def _path_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_source_path(path: Path, allowed_roots: list[Path]) -> Path:
    """Validate and return export root inside allowed_roots."""
    resolved = path.expanduser().resolve()
    if not allowed_roots:
        msg = "No import_roots configured"
        raise UploadError(msg)

    allowed = False
    for root in allowed_roots:
        root_resolved = root.expanduser().resolve()
        if _path_under_root(resolved, root_resolved):
            allowed = True
            break

    if not allowed:
        roots_str = ", ".join(str(r) for r in allowed_roots)
        msg = f"Path {resolved} is outside allowed import_roots: {roots_str}"
        raise UploadError(msg)

    return resolve_export_root(resolved)


def safe_extract_zip(zip_path: Path, dest_dir: Path) -> Path:
    """Extract ZIP to dest_dir with zip-slip protection. Returns export root."""
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_str = str(dest_dir)
    file_count = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        total_size = sum(info.file_size for info in zf.infolist())
        if total_size > MAX_ZIP_BYTES:
            msg = f"ZIP uncompressed size exceeds {MAX_ZIP_BYTES} bytes"
            raise UploadError(msg)
        if len(zf.infolist()) > MAX_ZIP_FILES:
            msg = f"ZIP contains more than {MAX_ZIP_FILES} files"
            raise UploadError(msg)

        for info in zf.infolist():
            file_count += 1
            target = (dest_dir / info.filename).resolve()
            if not str(target).startswith(dest_str):
                msg = f"Unsafe path in ZIP: {info.filename}"
                raise UploadError(msg)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

    if file_count == 0:
        msg = "ZIP archive is empty"
        raise UploadError(msg)

    return resolve_export_root(dest_dir)
