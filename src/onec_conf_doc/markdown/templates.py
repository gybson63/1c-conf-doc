"""Markdown section templates."""

from __future__ import annotations

from collections import defaultdict

from onec_conf_doc.models.metadata import Attribute, RoleObjectRights, RoleRights, TabularSection
from onec_conf_doc.parser.type_registry import TYPE_LABELS_RU

RIGHTS_GROUP_ORDER: dict[str, int] = {
    "Configuration": 0,
    "Subsystem": 1,
    "Catalog": 2,
    "Document": 3,
    "InformationRegister": 4,
    "AccumulationRegister": 5,
    "AccountingRegister": 6,
    "CalculationRegister": 7,
    "Report": 8,
    "DataProcessor": 9,
    "Enum": 10,
    "CommonModule": 11,
    "WebService": 12,
    "HTTPService": 13,
}


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


def _escape_md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _rights_object_label(full_name: str) -> str:
    if "." in full_name:
        return full_name.split(".", 1)[1]
    return full_name


def _rights_group_key(full_name: str) -> str:
    if "." in full_name:
        return full_name.split(".", 1)[0]
    return full_name


def _format_rights_table(objects: list[RoleObjectRights]) -> str:
    lines = [
        "| Объект | Права | RLS |",
        "|--------|-------|-----|",
    ]
    for obj in sorted(objects, key=lambda item: item.name.casefold()):
        granted = [right.name for right in obj.rights if right.value]
        if not granted:
            continue
        restrictions = [
            right.restriction for right in obj.rights if right.value and right.restriction
        ]
        rls = _escape_md_cell("; ".join(dict.fromkeys(restrictions)))
        lines.append(
            f"| {_escape_md_cell(_rights_object_label(obj.name))} | {', '.join(granted)} | {rls} |"
        )
    return "\n".join(lines) + "\n"


def role_rights_sections(role_rights: RoleRights) -> list[tuple[str, str]]:
    """Return markdown sections for role rights: (## title without hashes, body)."""
    sections: list[tuple[str, str]] = []
    flags = [
        f"**Для новых объектов:** {'Да' if role_rights.set_for_new_objects else 'Нет'}  ",
        (
            "**Права реквизитов по умолчанию:** "
            f"{'Да' if role_rights.set_for_attributes_by_default else 'Нет'}  "
        ),
        (
            "**Независимые права подчинённых объектов:** "
            f"{'Да' if role_rights.independent_rights_of_child_objects else 'Нет'}  "
        ),
        f"**Объектов с правами:** {len(role_rights.objects)}  ",
    ]
    sections.append(("Права", "\n".join(flags)))

    grouped: dict[str, list[RoleObjectRights]] = defaultdict(list)
    for obj in role_rights.objects:
        grouped[_rights_group_key(obj.name)].append(obj)

    for group in sorted(
        grouped,
        key=lambda name: (RIGHTS_GROUP_ORDER.get(name, 100), name.casefold()),
    ):
        sections.append((f"Права: {group}", _format_rights_table(grouped[group])))
    return sections
