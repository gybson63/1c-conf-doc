"""Persistent per-configuration export directories (slots)."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

from onec_conf_doc.config import AppConfig
from onec_conf_doc.export_root import (
    UploadError,
    resolve_export_root,
    safe_extract_zip,
    validate_source_path,
)

_IMPORT_SOURCE_MARKER = ".import_source"
_INVALID_SLOT_CHARS = re.compile(r'[<>:"/\\|?*\x00]')
_RESERVED_SLOT_NAMES = frozenset({"jobs", "detect", "index", "upload"})


class ExportSlotError(ValueError):
    """Invalid export slot name or operation."""


def is_reserved_slot_name(name: str) -> bool:
    return name in _RESERVED_SLOT_NAMES


def validate_slot_name(name: str) -> str:
    name = name.strip()
    if not name:
        msg = "Имя конфигурации не может быть пустым"
        raise ExportSlotError(msg)
    if _INVALID_SLOT_CHARS.search(name) or name in {".", ".."}:
        msg = f"Недопустимое имя конфигурации для папки: {name!r}"
        raise ExportSlotError(msg)
    return name


def export_dir_for(config: AppConfig, configuration_name: str) -> Path:
    return config.export_dir_for(validate_slot_name(configuration_name))


def ensure_export_slot(config: AppConfig, configuration_name: str) -> Path:
    slot = export_dir_for(config, configuration_name)
    slot.mkdir(parents=True, exist_ok=True)
    config.exports_dir().mkdir(parents=True, exist_ok=True)
    return slot.resolve()


def _linked_export_root(slot: Path) -> Path | None:
    marker = slot / _IMPORT_SOURCE_MARKER
    if not marker.is_file():
        return None
    try:
        return resolve_export_root(Path(marker.read_text(encoding="utf-8").strip()))
    except (UploadError, OSError):
        return None


def slot_has_export(config: AppConfig, configuration_name: str) -> bool:
    slot = export_dir_for(config, configuration_name)
    if _linked_export_root(slot) is not None:
        return True
    if (slot / "Configuration.xml").is_file():
        return True
    children = [p for p in slot.iterdir() if p.is_dir()] if slot.is_dir() else []
    return len(children) == 1 and (children[0] / "Configuration.xml").is_file()


def slot_export_linked(config: AppConfig, configuration_name: str) -> bool:
    slot = export_dir_for(config, configuration_name)
    return _linked_export_root(slot) is not None


def _force_remove_tree(path: Path) -> None:
    if not path.exists():
        return

    def onerror(func, p, exc_info) -> None:  # noqa: ANN001
        if not os.access(p, os.W_OK):
            os.chmod(p, stat.S_IWUSR | stat.S_IRUSR)
            func(p)
        else:
            raise exc_info[1]

    if os.name != "nt":
        for _ in range(3):
            subprocess.run(["rm", "-rf", str(path)], check=False)
            if not path.exists():
                return
            time.sleep(0.2)

    for _ in range(3):
        try:
            shutil.rmtree(path, onerror=onerror)
        except OSError:
            time.sleep(0.3)
        else:
            if not path.exists():
                return

    if path.exists():
        msg = f"Не удалось очистить каталог: {path}"
        raise UploadError(msg)


def _copy_export_tree(source_root: Path, dest_slot: Path) -> Path:
    dest_slot.parent.mkdir(parents=True, exist_ok=True)
    staging = dest_slot.parent / f".{dest_slot.name}.staging"
    _force_remove_tree(staging)
    try:
        shutil.copytree(source_root, staging)
    except OSError as exc:
        _force_remove_tree(staging)
        msg = f"Не удалось скопировать выгрузку в слот: {exc}"
        raise UploadError(msg) from exc

    _force_remove_tree(dest_slot)
    try:
        staging.rename(dest_slot)
    except OSError:
        try:
            shutil.copytree(staging, dest_slot)
        except OSError as exc:
            _force_remove_tree(staging)
            msg = f"Не удалось перенести выгрузку в слот: {exc}"
            raise UploadError(msg) from exc
        _force_remove_tree(staging)

    return resolve_export_root(dest_slot)


def _link_slot_to_source(slot: Path, export_root: Path) -> Path:
    _force_remove_tree(slot)
    slot.mkdir(parents=True, exist_ok=True)
    marker = slot / _IMPORT_SOURCE_MARKER
    marker.write_text(str(export_root.resolve()), encoding="utf-8")
    return export_root.resolve()


def import_path_to_slot(
    config: AppConfig,
    configuration_name: str,
    source_path: Path,
    *,
    allowed_roots: list[Path],
    mirror: bool = False,
) -> Path:
    """Import staging export into slot: link (default) or full copy."""
    validate_slot_name(configuration_name)
    export_root = validate_source_path(source_path, allowed_roots)
    slot = ensure_export_slot(config, configuration_name)
    if mirror:
        return _copy_export_tree(export_root, slot)
    return _link_slot_to_source(slot, export_root)


def import_zip_to_slot(
    config: AppConfig,
    configuration_name: str,
    zip_path: Path,
) -> Path:
    """Extract ZIP into the configuration slot (replaces existing export)."""
    validate_slot_name(configuration_name)
    slot = ensure_export_slot(config, configuration_name)
    with tempfile.TemporaryDirectory(prefix="conf_doc_zip_") as tmp:
        temp_dest = Path(tmp)
        export_root = safe_extract_zip(zip_path, temp_dest)
        return _copy_export_tree(export_root, slot)


def slot_export_root(config: AppConfig, configuration_name: str) -> Path:
    """Resolved export root inside slot; raises if empty."""
    slot = export_dir_for(config, configuration_name)
    if not slot.is_dir():
        msg = f"Слот выгрузки не найден: {configuration_name}"
        raise UploadError(msg)
    linked = _linked_export_root(slot)
    if linked is not None:
        return linked
    return resolve_export_root(slot)


def needs_export_migration(export_path: str, canonical_slot: Path) -> bool:
    if not export_path:
        return True
    try:
        current = Path(export_path).resolve()
        canonical = canonical_slot.resolve()
    except OSError:
        return True
    if current == canonical:
        return False
    if "_upload_" in current.name or current.name == "export":
        return True
    return current != canonical


def migrate_export_to_slot(
    config: AppConfig,
    configuration_name: str,
    current_export_path: str,
) -> Path | None:
    """Copy legacy export path into canonical slot. Returns new path or None if skipped."""
    canonical = ensure_export_slot(config, configuration_name)
    if not needs_export_migration(current_export_path, canonical):
        return canonical
    if not current_export_path:
        return None
    try:
        source = Path(current_export_path)
        if not source.is_dir():
            return None
        export_root = resolve_export_root(source)
        _copy_export_tree(export_root, canonical)
    except (UploadError, OSError):
        return None
    return canonical.resolve()
