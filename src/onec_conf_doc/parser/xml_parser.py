"""Parse 1C metadata XML files from configurator export."""

from __future__ import annotations

import re
from pathlib import Path

import html2text
from lxml import etree

from onec_conf_doc.models.metadata import (
    Attribute,
    ConfigurationInfo,
    EnumValue,
    FormRef,
    HelpPage,
    MetadataObject,
    TabularSection,
)
from onec_conf_doc.parser.dcs_parser import extract_dcs_queries
from onec_conf_doc.parser.rights_parser import parse_role_rights, role_rights_path
from onec_conf_doc.parser.scanner import (
    find_help_files,
    object_subdirectory,
    read_object_module,
    resolve_main_dcs_template,
    template_name_from_dcs_ref,
)

NS = {
    "md": "http://v8.1c.ru/8.3/MDClasses",
    "v8": "http://v8.1c.ru/8.1/data/core",
    "xr": "http://v8.1c.ru/8.3/xcf/readable",
}

OBJECT_TAGS = {
    "Catalog",
    "Document",
    "Enum",
    "InformationRegister",
    "AccumulationRegister",
    "AccountingRegister",
    "CalculationRegister",
    "Report",
    "DataProcessor",
    "CommonModule",
    "ChartOfAccounts",
    "ChartOfCharacteristicTypes",
    "ChartOfCalculationTypes",
    "BusinessProcess",
    "Task",
    "ExchangePlan",
    "DocumentJournal",
    "Sequence",
    "Constant",
    "DefinedType",
    "Role",
    "Subsystem",
    "CommonForm",
    "CommonCommand",
    "CommonAttribute",
    "FunctionalOption",
    "ScheduledJob",
    "WebService",
    "HTTPService",
}

_HTML_CONVERTER = html2text.HTML2Text()
_HTML_CONVERTER.ignore_links = False
_HTML_CONVERTER.body_width = 0


def _text(node: etree._Element | None) -> str:
    if node is None:
        return ""
    return (node.text or "").strip()


def _synonym(parent: etree._Element) -> str:
    syn = parent.find(".//md:Synonym", NS)
    if syn is None:
        return ""
    items = syn.findall(".//v8:item", NS)
    for item in items:
        lang = item.find("v8:lang", NS)
        content = item.find("v8:content", NS)
        if lang is not None and _text(lang) == "ru" and content is not None:
            return _text(content)
    if items:
        content = items[0].find("v8:content", NS)
        return _text(content)
    return _text(syn)


def _type_repr(type_node: etree._Element | None) -> str:
    if type_node is None:
        return ""
    parts: list[str] = []
    for child in type_node:
        tag = etree.QName(child).localname
        if tag == "Type":
            parts.append(_text(child))
        elif tag == "Types":
            for t in child.findall("v8:Type", NS):
                parts.append(_text(t))
        elif tag == "TypeSet":
            parts.append(_text(child))
        else:
            text = _text(child)
            if text:
                parts.append(text)
    if not parts:
        text = _text(type_node)
        if text:
            parts.append(text)
    cleaned = [p.replace("xs:", "xs:") for p in parts if p]
    return " | ".join(cleaned)


def _parse_attribute(node: etree._Element) -> Attribute:
    props = node.find("md:Properties", NS)
    if props is None:
        props = node
    fill_check = props.find("md:FillChecking", NS)
    is_required = _text(fill_check) == "ShowError"
    return Attribute(
        name=_text(props.find("md:Name", NS)),
        type_repr=_type_repr(props.find("md:Type", NS)),
        synonym=_synonym(props),
        comment=_text(props.find("md:Comment", NS)),
        is_required=is_required,
        uuid=node.get("uuid", ""),
    )


def _parse_tabular_section(node: etree._Element) -> TabularSection:
    props = node.find("md:Properties", NS)
    if props is None:
        props = node
    ts = TabularSection(
        name=_text(props.find("md:Name", NS)),
        synonym=_synonym(props),
        comment=_text(props.find("md:Comment", NS)),
        uuid=node.get("uuid", ""),
    )
    child_objects = node.find("md:ChildObjects", NS)
    if child_objects is not None:
        for attr_node in child_objects.findall("md:Attribute", NS):
            ts.attributes.append(_parse_attribute(attr_node))
    return ts


def _parse_enum_values(child_objects: etree._Element | None) -> list[EnumValue]:
    if child_objects is None:
        return []
    values: list[EnumValue] = []
    for enum_val in child_objects.findall("md:EnumValue", NS):
        props = enum_val.find("md:Properties", NS)
        if props is None:
            continue
        values.append(
            EnumValue(
                name=_text(props.find("md:Name", NS)),
                synonym=_synonym(props),
                comment=_text(props.find("md:Comment", NS)),
            )
        )
    return values


def _parse_forms(child_objects: etree._Element | None) -> list[FormRef]:
    if child_objects is None:
        return []
    forms: list[FormRef] = []
    for form_node in child_objects.findall("md:Form", NS):
        name = _text(form_node)
        if name:
            forms.append(FormRef(name=name))
    return forms


def _parse_help_content(path: Path) -> HelpPage:
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8", errors="replace")
    title = path.stem
    if suffix in {".html", ".htm"}:
        content_md = _HTML_CONVERTER.handle(raw)
    elif suffix == ".xml":
        try:
            root = etree.fromstring(raw.encode("utf-8"))
            paras = root.xpath(".//text()")
            content_md = "\n".join(p.strip() for p in paras if p.strip())
        except etree.XMLSyntaxError:
            content_md = raw
    else:
        content_md = raw
    content_md = content_md.strip().removeprefix("\ufeff")
    return HelpPage(title=title, content_md=content_md, source_path=str(path))


def _find_object_element(root: etree._Element) -> tuple[str, etree._Element] | None:
    for tag in OBJECT_TAGS:
        elem = root.find(f"md:{tag}", NS)
        if elem is not None:
            return tag, elem
    for child in root:
        local = etree.QName(child).localname
        if local in OBJECT_TAGS:
            return local, child
    return None


def parse_metadata_file(
    path: Path,
    object_type: str,
    *,
    source_root: Path | None = None,
) -> MetadataObject:
    tree = etree.parse(str(path))
    root = tree.getroot()
    found = _find_object_element(root)
    if found is None:
        msg = f"No metadata object found in {path}"
        raise ValueError(msg)
    tag, obj_elem = found
    props = obj_elem.find("md:Properties", NS)
    if props is None:
        msg = f"No Properties in {path}"
        raise ValueError(msg)

    child_objects = obj_elem.find("md:ChildObjects", NS)
    attributes: list[Attribute] = []
    dimensions: list[Attribute] = []
    resources: list[Attribute] = []
    tabular_sections: list[TabularSection] = []
    if child_objects is not None:
        for attr_node in child_objects.findall("md:Attribute", NS):
            attributes.append(_parse_attribute(attr_node))
        for dim_node in child_objects.findall("md:Dimension", NS):
            dimensions.append(_parse_attribute(dim_node))
        for res_node in child_objects.findall("md:Resource", NS):
            resources.append(_parse_attribute(res_node))
        for ts_node in child_objects.findall("md:TabularSection", NS):
            tabular_sections.append(_parse_tabular_section(ts_node))

    resolved_type = object_type or tag
    register_periodicity = ""
    register_write_mode = ""
    if resolved_type == "InformationRegister":
        register_periodicity = _text(props.find("md:InformationRegisterPeriodicity", NS))
        register_write_mode = _text(props.find("md:WriteMode", NS))

    name = _text(props.find("md:Name", NS)) or path.stem
    explanation = _text(props.find("md:Explanation", NS))
    help_pages: list[HelpPage] = []
    if explanation:
        help_pages.append(HelpPage(title="Пояснение", content_md=explanation))

    if source_root is not None:
        obj_dir = source_root / path.parent.name / name
        if obj_dir.is_dir():
            for help_path in find_help_files(obj_dir):
                if help_path.is_file():
                    help_pages.append(_parse_help_content(help_path))

    obj = MetadataObject(
        object_type=resolved_type,
        name=name,
        synonym=_synonym(props),
        comment=_text(props.find("md:Comment", NS)),
        uuid=obj_elem.get("uuid", ""),
        source_xml=str(path),
        attributes=attributes,
        dimensions=dimensions,
        resources=resources,
        register_periodicity=register_periodicity,
        register_write_mode=register_write_mode,
        tabular_sections=tabular_sections,
        enum_values=_parse_enum_values(child_objects),
        forms=_parse_forms(child_objects),
        help_pages=help_pages,
    )

    if resolved_type == "Report" and source_root is not None:
        report_dir = object_subdirectory(source_root, "Report", name)
        if report_dir is not None:
            obj.object_module = read_object_module(report_dir)
            main_dcs_ref = _text(props.find("md:MainDataCompositionSchema", NS))
            if main_dcs_ref:
                dcs_path = resolve_main_dcs_template(report_dir, main_dcs_ref)
                if dcs_path is not None:
                    obj.main_dcs_name = template_name_from_dcs_ref(main_dcs_ref)
                    obj.dcs_queries = extract_dcs_queries(dcs_path)

    if resolved_type == "Role" and source_root is not None:
        rights_file = role_rights_path(source_root, name)
        if rights_file is not None:
            obj.role_rights = parse_role_rights(rights_file)

    obj.content_hash = obj.compute_hash()
    return obj


def parse_configuration(path: Path, *, export_root: Path | None = None) -> ConfigurationInfo:
    tree = etree.parse(str(path))
    root = tree.getroot()
    config_elem = root.find("md:Configuration", NS)
    if config_elem is None:
        for child in root:
            if etree.QName(child).localname == "Configuration":
                config_elem = child
                break
    props = config_elem.find("md:Properties", NS) if config_elem is not None else None
    if props is None:
        props = root.find(".//md:Properties", NS)
    if props is None:
        return ConfigurationInfo(
            source_path=str(path),
            export_path=str(export_root or path.parent),
            content_hash=ConfigurationInfo.hash_path(path),
        )

    version = _text(props.find("md:Version", NS))
    if not version:
        version_node = root.find(".//md:Version", NS)
        version = _text(version_node)
    if not version:
        header = path.read_text(encoding="utf-8", errors="replace")[:500]
        version_match = re.search(r'version="([^"]+)"', header)
        version = version_match.group(1) if version_match else ""

    export_path = str(export_root or path.parent)
    return ConfigurationInfo(
        name=_text(props.find("md:Name", NS)),
        synonym=_synonym(props),
        version=version,
        comment=_text(props.find("md:Comment", NS)),
        uuid=config_elem.get("uuid", "") if config_elem is not None else "",
        source_path=str(path),
        export_path=export_path,
        content_hash=ConfigurationInfo.hash_path(path),
    )
