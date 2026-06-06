"""Markdown section templates."""

from __future__ import annotations

from onec_conf_doc.models.metadata import Attribute, TabularSection
from onec_conf_doc.parser.type_registry import TYPE_LABELS_RU


def type_label(object_type: str) -> str:
    return TYPE_LABELS_RU.get(object_type, object_type)


def format_attributes_table(attributes: list[Attribute]) -> str:
    if not attributes:
        return "_Нет реквизитов._\n"
    lines = [
        "| Имя | Тип | Синоним | Комментарий | Обязательный |",
        "|-----|-----|---------|-------------|--------------|",
    ]
    for attr in attributes:
        required = "Да" if attr.is_required else ""
        lines.append(
            f"| {attr.name} | {attr.type_repr} | {attr.synonym} | {attr.comment} | {required} |"
        )
    return "\n".join(lines) + "\n"


def format_tabular_section(section: TabularSection) -> str:
    lines = [f"### {section.name}"]
    if section.synonym:
        lines.append(f"**Синоним:** {section.synonym}  ")
    if section.comment:
        lines.append(f"**Комментарий:** {section.comment}  ")
    lines.append("")
    lines.append(format_attributes_table(section.attributes))
    return "\n".join(lines)
