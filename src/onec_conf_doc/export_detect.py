"""Detect configuration from export folder before indexing."""

from __future__ import annotations

from pathlib import Path

from onec_conf_doc.config_names import match_configuration_name
from onec_conf_doc.export_root import UploadError, resolve_export_root
from onec_conf_doc.models.metadata import ConfigurationInfo
from onec_conf_doc.parser.xml_parser import parse_configuration


def detect_export_configuration(source: Path) -> ConfigurationInfo:
    """Read Configuration.xml and return metadata (fast, no object scan)."""
    try:
        export_root = resolve_export_root(source)
    except UploadError:
        raise
    config_path = export_root / "Configuration.xml"
    if not config_path.is_file():
        msg = f"Configuration.xml not found in {export_root}"
        raise UploadError(msg)
    info = parse_configuration(config_path, export_root=export_root)
    if not info.name:
        msg = "Configuration.xml does not contain configuration name (md:Name)"
        raise ValueError(msg)
    info.source_path = str(config_path)
    info.export_path = str(export_root)
    return info


def validate_expected_configuration(
    detected: ConfigurationInfo,
    expected: str | None,
) -> None:
    """Fail fast when export folder contains a different configuration."""
    if not expected:
        return
    if match_configuration_name(expected, [detected.name]) is not None:
        return
    synonym = f" ({detected.synonym})" if detected.synonym else ""
    msg = (
        f"В папке выгрузки конфигурация «{detected.name}»{synonym}, "
        f"ожидалась «{expected}». Проверьте путь или замените выгрузку."
    )
    raise ValueError(msg)


def configuration_matches_expected(detected_name: str, expected: str | None) -> bool:
    if not expected:
        return True
    return match_configuration_name(expected, [detected_name]) is not None
