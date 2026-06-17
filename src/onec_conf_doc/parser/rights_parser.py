"""Parse 1C role rights from Roles/{Name}/Ext/Rights.xml."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from onec_conf_doc.models.metadata import RoleObjectRights, RoleRight, RoleRights

RIGHTS_NS = {"r": "http://v8.1c.ru/8.2/roles"}


def role_rights_path(source_root: Path, role_name: str) -> Path | None:
    path = source_root / "Roles" / role_name / "Ext" / "Rights.xml"
    return path if path.is_file() else None


def _local_text(parent: etree._Element, tag: str) -> str:
    node = parent.find(f"r:{tag}", RIGHTS_NS)
    if node is None:
        for child in parent:
            if etree.QName(child).localname == tag:
                node = child
                break
    if node is None:
        return ""
    return (node.text or "").strip()


def _parse_bool(parent: etree._Element, tag: str, *, default: bool) -> bool:
    text = _local_text(parent, tag)
    if not text:
        return default
    return text.lower() == "true"


def _parse_restriction(right_node: etree._Element) -> str:
    for child in right_node:
        local = etree.QName(child).localname
        if local != "restrictionByCondition":
            continue
        condition = _local_text(child, "condition")
        if condition:
            return condition
    return ""


def _parse_right(right_node: etree._Element) -> RoleRight | None:
    name = _local_text(right_node, "name")
    if not name:
        return None
    value = _parse_bool(right_node, "value", default=False)
    if not value:
        return None
    restriction = _parse_restriction(right_node)
    return RoleRight(name=name, value=value, restriction=restriction)


def _parse_object(obj_node: etree._Element) -> RoleObjectRights | None:
    name = _local_text(obj_node, "name")
    if not name:
        return None
    rights: list[RoleRight] = []
    for child in obj_node:
        if etree.QName(child).localname != "right":
            continue
        parsed = _parse_right(child)
        if parsed is not None:
            rights.append(parsed)
    if not rights:
        return None
    return RoleObjectRights(name=name, rights=rights)


def parse_role_rights(path: Path) -> RoleRights:
    tree = etree.parse(str(path))
    root = tree.getroot()
    objects: list[RoleObjectRights] = []
    for child in root:
        if etree.QName(child).localname != "object":
            continue
        parsed = _parse_object(child)
        if parsed is not None:
            objects.append(parsed)
    return RoleRights(
        set_for_new_objects=_parse_bool(root, "setForNewObjects", default=False),
        set_for_attributes_by_default=_parse_bool(root, "setForAttributesByDefault", default=True),
        independent_rights_of_child_objects=_parse_bool(
            root, "independentRightsOfChildObjects", default=False
        ),
        objects=objects,
    )
