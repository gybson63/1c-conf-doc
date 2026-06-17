"""Structured search for roles by metadata object rights (no vectors)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_RIGHTS_SECTION_RE = re.compile(r"^## Права: (\w+)\s*$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\| (.+?) \| (.+?) \| (.*) \|$")


@dataclass(frozen=True)
class RoleObjectRightHit:
    role: str
    synonym: str
    metadata_type: str
    object_name: str
    rights: tuple[str, ...]
    rls: str
    md_path: str

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "synonym": self.synonym,
            "metadata_type": self.metadata_type,
            "object": self.object_name,
            "rights": list(self.rights),
            "rls": self.rls,
            "md_path": self.md_path,
        }


def split_metadata_object_name(name: str) -> tuple[str | None, str]:
    value = name.strip()
    if "." in value:
        prefix, short = value.split(".", 1)
        return prefix, short
    return None, value


def parse_rights_filter(rights: str | None) -> frozenset[str] | None:
    if not rights or not rights.strip():
        return None
    parts = {part.strip() for part in rights.split(",") if part.strip()}
    return frozenset(parts) if parts else None


def _unescape_md_cell(value: str) -> str:
    return value.replace("\\|", "|").strip()


def _split_granted_rights(cell: str) -> list[str]:
    return [part.strip() for part in cell.split(",") if part.strip()]


def _is_table_header(cells: tuple[str, str, str]) -> bool:
    obj, rights, _rls = cells
    return obj.strip() == "Объект" or rights.strip() == "Права" or obj.strip().startswith("---")


def parse_rights_hits_from_text(
    text: str,
    *,
    role: str,
    synonym: str,
    md_path: str,
    object_query: str,
    required_rights: frozenset[str] | None,
    metadata_type_filter: str | None,
) -> list[RoleObjectRightHit]:
    query_type, query_short = split_metadata_object_name(object_query)
    if not query_short:
        return []

    hits: list[RoleObjectRightHit] = []
    current_type: str | None = None

    for line in text.splitlines():
        section_match = _RIGHTS_SECTION_RE.match(line)
        if section_match:
            current_type = section_match.group(1)
            continue

        if current_type is None:
            continue
        if metadata_type_filter and current_type != metadata_type_filter:
            continue

        row_match = _TABLE_ROW_RE.match(line)
        if not row_match:
            continue

        obj_cell, rights_cell, rls_cell = row_match.groups()
        if _is_table_header((obj_cell, rights_cell, rls_cell)):
            continue

        object_name = _unescape_md_cell(obj_cell)
        if object_name.casefold() != query_short.casefold():
            continue
        if query_type and query_type != current_type:
            continue

        granted = _split_granted_rights(rights_cell)
        if not granted:
            continue
        if required_rights and not required_rights.issubset(granted):
            continue

        hits.append(
            RoleObjectRightHit(
                role=role,
                synonym=synonym,
                metadata_type=current_type,
                object_name=object_name,
                rights=tuple(granted),
                rls=_unescape_md_cell(rls_cell),
                md_path=md_path,
            )
        )
    return hits


def search_roles_by_object(
    role_chunks: list[dict[str, str]],
    *,
    object_name: str,
    rights: str | None = None,
    metadata_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    required = parse_rights_filter(rights)
    merged: dict[tuple[str, str, str], RoleObjectRightHit] = {}

    for row in role_chunks:
        for hit in parse_rights_hits_from_text(
            row["text"],
            role=row["role"],
            synonym=row.get("synonym", ""),
            md_path=row.get("md_path", ""),
            object_query=object_name,
            required_rights=required,
            metadata_type_filter=metadata_type,
        ):
            key = (hit.role, hit.metadata_type, hit.object_name)
            merged.setdefault(key, hit)

    results = [hit.as_dict() for hit in merged.values()]
    results.sort(key=lambda item: (str(item["role"]).casefold(), str(item["metadata_type"])))
    return results[:limit]
