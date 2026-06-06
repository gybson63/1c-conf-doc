"""Pydantic models for 1C metadata objects."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, Field


class Attribute(BaseModel):
    name: str
    type_repr: str = ""
    synonym: str = ""
    comment: str = ""
    is_required: bool = False
    uuid: str = ""


class TabularSection(BaseModel):
    name: str
    synonym: str = ""
    comment: str = ""
    uuid: str = ""
    attributes: list[Attribute] = Field(default_factory=list)


class EnumValue(BaseModel):
    name: str
    synonym: str = ""
    comment: str = ""


class FormRef(BaseModel):
    name: str
    synonym: str = ""


class HelpPage(BaseModel):
    title: str = ""
    content_md: str = ""
    source_path: str = ""


class MetadataObject(BaseModel):
    object_type: str
    name: str
    synonym: str = ""
    comment: str = ""
    uuid: str = ""
    source_xml: str = ""
    content_hash: str = ""
    attributes: list[Attribute] = Field(default_factory=list)
    tabular_sections: list[TabularSection] = Field(default_factory=list)
    enum_values: list[EnumValue] = Field(default_factory=list)
    forms: list[FormRef] = Field(default_factory=list)
    help_pages: list[HelpPage] = Field(default_factory=list)

    def compute_hash(self) -> str:
        payload = self.model_dump_json(exclude={"content_hash", "source_xml"})
        return hashlib.sha256(payload.encode()).hexdigest()


class ConfigurationInfo(BaseModel):
    name: str = ""
    synonym: str = ""
    version: str = ""
    comment: str = ""
    uuid: str = ""
    source_path: str = ""
    export_path: str = ""
    content_hash: str = ""

    @staticmethod
    def hash_path(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
