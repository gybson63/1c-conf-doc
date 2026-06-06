"""Output path helpers for generated markdown."""

from __future__ import annotations

from pathlib import Path

from onec_conf_doc.parser.type_registry import TYPE_TO_FOLDER


def object_type_folder(object_type: str) -> str:
    folder = TYPE_TO_FOLDER.get(object_type, object_type)
    return folder.lower()


def md_path_for_object(docs_dir: Path, object_type: str, name: str) -> Path:
    """docs_dir = output/docs/{configuration_name}/"""
    return docs_dir / object_type_folder(object_type) / f"{name}.md"
