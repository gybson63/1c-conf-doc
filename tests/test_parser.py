from pathlib import Path

from onec_conf_doc.parser.scanner import scan_export
from onec_conf_doc.parser.xml_parser import parse_configuration, parse_metadata_file

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


def test_scan_export_finds_objects() -> None:
    refs = scan_export(FIXTURES)
    names = {(r.object_type, r.name) for r in refs}
    assert ("Catalog", "Номенклатура") in names
    assert ("Document", "РеализацияТоваров") in names
    assert ("Enum", "ВидыОпераций") in names
    assert ("Report", "ТестовыйОтчет") in names


def test_parse_catalog() -> None:
    path = FIXTURES / "Catalogs" / "Номенклатура.xml"
    obj = parse_metadata_file(path, "Catalog", source_root=FIXTURES)
    assert obj.name == "Номенклатура"
    assert obj.synonym == "Номенклатура"
    assert obj.comment == "Справочник товаров"
    assert len(obj.attributes) == 1
    assert obj.attributes[0].name == "Артикул"
    assert obj.attributes[0].is_required is True
    assert len(obj.tabular_sections) == 1
    assert obj.tabular_sections[0].attributes[0].name == "Значение"
    assert any(f.name == "ФормаЭлемента" for f in obj.forms)
    assert any(p.title == "Пояснение" for p in obj.help_pages)


def test_parse_document() -> None:
    path = FIXTURES / "Documents" / "РеализацияТоваров.xml"
    obj = parse_metadata_file(path, "Document", source_root=FIXTURES)
    assert obj.name == "РеализацияТоваров"
    assert obj.attributes[0].type_repr == "CatalogRef.Контрагенты"


def test_parse_enum() -> None:
    path = FIXTURES / "Enums" / "ВидыОпераций.xml"
    obj = parse_metadata_file(path, "Enum", source_root=FIXTURES)
    assert len(obj.enum_values) == 1
    assert obj.enum_values[0].name == "Продажа"


def test_parse_report_module_and_dcs_queries() -> None:
    path = FIXTURES / "Reports" / "ТестовыйОтчет.xml"
    obj = parse_metadata_file(path, "Report", source_root=FIXTURES)
    assert obj.name == "ТестовыйОтчет"
    assert "ПриКомпоновкеРезультата" in obj.object_module
    assert obj.main_dcs_name == "ОсновнаяСхемаКомпоновкиДанных"
    assert len(obj.dcs_queries) == 2
    assert obj.dcs_queries[0].dataset_name == "НаборДанных1"
    assert "Справочник.Номенклатура" in obj.dcs_queries[0].query_text
    assert obj.dcs_queries[1].dataset_name == "НаборДанных2"
    assert "Справочник.Контрагенты" in obj.dcs_queries[1].query_text


def test_parse_catalog_has_no_report_fields() -> None:
    path = FIXTURES / "Catalogs" / "Номенклатура.xml"
    obj = parse_metadata_file(path, "Catalog", source_root=FIXTURES)
    assert obj.object_module == ""
    assert obj.dcs_queries == []


def test_parse_configuration() -> None:
    info = parse_configuration(FIXTURES / "Configuration.xml")
    assert info.name == "ТестоваяКонфигурация"
    assert info.synonym == "Тестовая конфигурация"
    assert info.version == "1.0.0.1"
