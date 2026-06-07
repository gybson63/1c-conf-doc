"""Generate markdown documentation from metadata objects."""

from __future__ import annotations

from pathlib import Path

from onec_conf_doc.markdown.templates import (
    format_attributes_table,
    format_tabular_section,
    type_label,
)
from onec_conf_doc.models.metadata import MetadataObject
from onec_conf_doc.parser.type_registry import REGISTER_TYPES
from onec_conf_doc.storage.paths import md_path_for_object


def generate_markdown(
    obj: MetadataObject,
    *,
    configuration_name: str = "",
    configuration_synonym: str = "",
) -> str:
    label = type_label(obj.object_type)
    lines = [
        f"# {label}: {obj.name}",
        "",
    ]
    if configuration_name:
        conf_label = configuration_synonym or configuration_name
        if configuration_synonym and configuration_synonym != configuration_name:
            conf_label = f"{configuration_synonym} ({configuration_name})"
        lines.append(f"**Конфигурация:** {conf_label}  ")
    if obj.synonym:
        lines.append(f"**Синоним:** {obj.synonym}  ")
    if obj.comment:
        lines.append(f"**Комментарий:** {obj.comment}  ")
    if obj.object_type in REGISTER_TYPES:
        if obj.register_periodicity:
            lines.append(f"**Периодичность:** {obj.register_periodicity}  ")
        if obj.register_write_mode:
            lines.append(f"**Режим записи:** {obj.register_write_mode}  ")
    lines.extend(
        [
            f"**Тип:** {obj.object_type}  ",
            f"**UUID:** {obj.uuid}  ",
            "",
        ]
    )

    if obj.dimensions:
        lines.extend(["## Измерения", "", format_attributes_table(obj.dimensions)])

    if obj.resources:
        lines.extend(["## Ресурсы", "", format_attributes_table(obj.resources)])

    if obj.attributes:
        lines.extend(["## Реквизиты", "", format_attributes_table(obj.attributes)])

    if obj.tabular_sections:
        lines.extend(["## Табличные части", ""])
        for section in obj.tabular_sections:
            lines.append(format_tabular_section(section))

    if obj.enum_values:
        lines.extend(
            [
                "## Значения перечисления",
                "",
                "| Имя | Синоним | Комментарий |",
                "|-----|---------|-------------|",
            ]
        )
        for val in obj.enum_values:
            lines.append(f"| {val.name} | {val.synonym} | {val.comment} |")
        lines.append("")

    if obj.forms:
        lines.extend(["## Формы", ""])
        for form in obj.forms:
            synonym = f" ({form.synonym})" if form.synonym else ""
            lines.append(f"- {form.name}{synonym}")
        lines.append("")

    if obj.object_type == "Report":
        if obj.object_module:
            lines.extend(
                [
                    "## Модуль объекта",
                    "",
                    "```bsl",
                    obj.object_module,
                    "```",
                    "",
                ]
            )
        for dcs_query in obj.dcs_queries:
            lines.extend(
                [
                    f"## Запрос СКД: {dcs_query.dataset_name}",
                    "",
                ]
            )
            if obj.main_dcs_name:
                lines.append(f"**Макет:** {obj.main_dcs_name}  ")
                lines.append("")
            lines.extend(
                [
                    "```1c",
                    dcs_query.query_text,
                    "```",
                    "",
                ]
            )

    if obj.help_pages:
        lines.extend(["## Справка", ""])
        for page in obj.help_pages:
            if page.title and page.title != "Пояснение":
                lines.append(f"### {page.title}")
                lines.append("")
            lines.append(page.content_md)
            lines.append("")

    return "\n".join(lines).strip() + "\n"


def write_markdown(
    obj: MetadataObject,
    docs_dir: Path,
    *,
    configuration_name: str = "",
    configuration_synonym: str = "",
) -> Path:
    md_path = md_path_for_object(docs_dir, obj.object_type, obj.name)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(
        generate_markdown(
            obj,
            configuration_name=configuration_name,
            configuration_synonym=configuration_synonym,
        ),
        encoding="utf-8",
    )
    return md_path
