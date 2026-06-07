"""Extract query texts from 1C Data Composition Schema (DCS) templates."""

from __future__ import annotations

import html
from pathlib import Path

from lxml import etree

from onec_conf_doc.models.metadata import DcsQuery

_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


def _local_name(elem: etree._Element) -> str:
    return str(etree.QName(elem).localname)


def _child_text(parent: etree._Element, local_name: str) -> str:
    for child in parent:
        if _local_name(child) == local_name:
            return (child.text or "").strip()
    return ""


def _xsi_type(elem: etree._Element) -> str:
    xsi_type = str(elem.get(f"{{{_XSI_NS}}}type", "") or "")
    if xsi_type:
        return str(xsi_type.rsplit(":", maxsplit=1)[-1])
    return ""


def _decode_query_text(text: str) -> str:
    return html.unescape(text).strip()


def _collect_queries_from_node(node: etree._Element, queries: list[DcsQuery]) -> None:
    xsi_type = _xsi_type(node)
    local = _local_name(node)

    if xsi_type == "DataSetQuery" or (local == "dataSet" and _child_text(node, "query")):
        dataset_name = _child_text(node, "name")
        query_text = _decode_query_text(_child_text(node, "query"))
        if query_text:
            queries.append(DcsQuery(dataset_name=dataset_name, query_text=query_text))
        return

    if xsi_type == "DataSetUnion" or local == "dataSet":
        for child in node:
            if _local_name(child) == "item":
                _collect_queries_from_node(child, queries)
        return

    if local == "item":
        for child in node:
            _collect_queries_from_node(child, queries)
        return


def extract_dcs_queries(path: Path) -> list[DcsQuery]:
    """Return all DataSetQuery texts from a DCS Template.xml file."""
    tree = etree.parse(str(path))
    root = tree.getroot()

    queries: list[DcsQuery] = []
    for elem in root:
        if _local_name(elem) == "dataSet":
            _collect_queries_from_node(elem, queries)

    return queries
