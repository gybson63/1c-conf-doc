"""OData-style field payloads from indexed metadata."""

from __future__ import annotations

from typing import Any


def odata_entity_type(object_type: str, name: str) -> str:
    return f"{object_type}_{name}"


def _field_dict(
    *,
    name: str,
    type_repr: str,
    synonym: str,
    comment: str,
    is_required: bool,
    kind: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": type_repr,
        "title": synonym or name,
        "comment": comment,
        "required": is_required,
        "kind": kind,
    }


def build_odata_fields_payload(
    object_type: str,
    name: str,
    attributes: list[dict[str, Any]],
    tabular_sections: list[dict[str, Any]],
    *,
    dimensions: list[dict[str, Any]] | None = None,
    resources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fields = [
        _field_dict(
            name=str(row["name"]),
            type_repr=str(row.get("type_repr", "")),
            synonym=str(row.get("synonym", "")),
            comment=str(row.get("comment", "")),
            is_required=bool(row.get("is_required")),
            kind="attribute",
        )
        for row in attributes
    ]
    for row in dimensions or []:
        fields.append(
            _field_dict(
                name=str(row["name"]),
                type_repr=str(row.get("type_repr", "")),
                synonym=str(row.get("synonym", "")),
                comment=str(row.get("comment", "")),
                is_required=bool(row.get("is_required")),
                kind="dimension",
            )
        )
    for row in resources or []:
        fields.append(
            _field_dict(
                name=str(row["name"]),
                type_repr=str(row.get("type_repr", "")),
                synonym=str(row.get("synonym", "")),
                comment=str(row.get("comment", "")),
                is_required=bool(row.get("is_required")),
                kind="resource",
            )
        )
    return {
        "entity_type": odata_entity_type(object_type, name),
        "fields": fields,
        "tabular_sections": [
            {
                "name": str(section["name"]),
                "title": str(section.get("synonym") or section["name"]),
                "comment": str(section.get("comment", "")),
                "fields": [
                    _field_dict(
                        name=str(row["name"]),
                        type_repr=str(row.get("type_repr", "")),
                        synonym=str(row.get("synonym", "")),
                        comment=str(row.get("comment", "")),
                        is_required=bool(row.get("is_required")),
                        kind="tabular_attribute",
                    )
                    for row in section.get("attributes", [])
                ],
            }
            for section in tabular_sections
        ],
    }
