"""Scan 1C configurator export directory for metadata XML files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from onec_conf_doc.parser.type_registry import FOLDER_TO_TYPE


@dataclass(frozen=True)
class MetadataFileRef:
    path: Path
    object_type: str
    name: str


def scan_export(source: Path) -> list[MetadataFileRef]:
    """Return top-level metadata object XML files from export root."""
    if not source.is_dir():
        msg = f"Export directory not found: {source}"
        raise FileNotFoundError(msg)

    refs: list[MetadataFileRef] = []
    for folder_name, object_type in FOLDER_TO_TYPE.items():
        folder = source / folder_name
        if not folder.is_dir():
            continue
        for xml_path in sorted(folder.glob("*.xml")):
            refs.append(
                MetadataFileRef(
                    path=xml_path,
                    object_type=object_type,
                    name=xml_path.stem,
                )
            )
    return refs


def find_help_files(object_dir: Path) -> list[Path]:
    """Find help HTML files under object subdirectory (object + forms)."""
    candidates: list[Path] = []

    for help_dir in (
        object_dir / "Ext" / "Help",
        object_dir / "Help",
    ):
        if help_dir.is_dir():
            candidates.extend(help_dir.rglob("*.html"))
            candidates.extend(help_dir.rglob("*.htm"))

    for form_help in object_dir.rglob("Forms/*/Ext/Help/*.html"):
        candidates.append(form_help)
    for form_help in object_dir.rglob("Forms/*/Ext/Help/*.htm"):
        candidates.append(form_help)

    unique: dict[str, Path] = {}
    for path in sorted(candidates):
        if path.is_file():
            unique[str(path.resolve())] = path
    return list(unique.values())


def read_object_module(object_dir: Path) -> str:
    """Read Ext/ObjectModule.bsl from a metadata object subdirectory."""
    module_path = object_dir / "Ext" / "ObjectModule.bsl"
    if not module_path.is_file():
        return ""
    return module_path.read_text(encoding="utf-8", errors="replace").strip()


def template_name_from_dcs_ref(main_dcs_ref: str) -> str:
    marker = "Template."
    if marker not in main_dcs_ref:
        return ""
    return main_dcs_ref.rsplit(marker, maxsplit=1)[-1].strip()


def resolve_main_dcs_template(object_dir: Path, main_dcs_ref: str) -> Path | None:
    """Resolve path to main DataCompositionSchema Template.xml body."""
    from lxml import etree

    template_name = template_name_from_dcs_ref(main_dcs_ref)
    if not template_name:
        return None

    meta_path = object_dir / "Templates" / f"{template_name}.xml"
    if not meta_path.is_file():
        return None

    try:
        root = etree.parse(str(meta_path)).getroot()
    except etree.XMLSyntaxError:
        return None

    template_type = ""
    for elem in root.iter():
        if etree.QName(elem).localname == "TemplateType":
            template_type = (elem.text or "").strip()
            break

    if template_type != "DataCompositionSchema":
        return None

    body_path = object_dir / "Templates" / template_name / "Ext" / "Template.xml"
    return body_path if body_path.is_file() else None


def object_subdirectory(source: Path, object_type: str, name: str) -> Path | None:
    from onec_conf_doc.parser.type_registry import TYPE_TO_FOLDER

    folder_name = TYPE_TO_FOLDER.get(object_type)
    if not folder_name:
        return None
    sub = source / folder_name / name
    return sub if sub.is_dir() else None
