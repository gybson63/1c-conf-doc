from pathlib import Path

from onec_conf_doc.config import AppConfig
from onec_conf_doc.markdown.generator import generate_markdown, write_markdown
from onec_conf_doc.parser.xml_parser import parse_metadata_file
from onec_conf_doc.rag.pipeline import Pipeline

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


def test_generate_markdown_contains_sections(tmp_path: Path) -> None:
    path = FIXTURES / "Catalogs" / "Номенклатура.xml"
    obj = parse_metadata_file(path, "Catalog", source_root=FIXTURES)
    md = generate_markdown(obj)
    assert "# Справочник: Номенклатура" in md
    assert "## Реквизиты" in md
    assert "Артикул" in md
    assert "## Табличные части" in md


def test_generate_markdown_report_sections() -> None:
    path = FIXTURES / "Reports" / "ТестовыйОтчет.xml"
    obj = parse_metadata_file(path, "Report", source_root=FIXTURES)
    md = generate_markdown(obj)
    assert "# Отчёт: ТестовыйОтчет" in md
    assert "## Модуль объекта" in md
    assert "```bsl" in md
    assert "ПриКомпоновкеРезультата" in md
    assert "## Запрос СКД: НаборДанных1" in md
    assert "## Запрос СКД: НаборДанных2" in md
    assert "```1c" in md
    assert "Справочник.Номенклатура" in md


def test_generate_markdown_information_register() -> None:
    path = FIXTURES / "InformationRegisters" / "КадроваяИсторияСотрудников.xml"
    obj = parse_metadata_file(path, "InformationRegister", source_root=FIXTURES)
    md = generate_markdown(obj)
    assert "# Регистр сведений: КадроваяИсторияСотрудников" in md
    assert "**Периодичность:** Second" in md
    assert "**Режим записи:** RecorderSubordinate" in md
    assert "## Измерения" in md
    assert "Сотрудник" in md
    assert "ГоловнаяОрганизация" in md


def test_generate_markdown_role_rights() -> None:
    path = FIXTURES / "Roles" / "ТестоваяРоль.xml"
    obj = parse_metadata_file(path, "Role", source_root=FIXTURES)
    md = generate_markdown(obj)
    assert "# Роль: ТестоваяРоль" in md
    assert "## Права" in md
    assert "**Объектов с правами:** 3" in md
    assert "## Права: Catalog" in md
    assert "Номенклатура" in md
    assert "Read, View" in md
    assert "## Права: Document" in md
    assert "ТекущийСотрудник" in md
    assert "## Права: Configuration" in md
    assert "ThinClient" in md


def test_write_markdown_catalog(tmp_path: Path) -> None:
    path = FIXTURES / "Catalogs" / "Номенклатура.xml"
    obj = parse_metadata_file(path, "Catalog", source_root=FIXTURES)
    docs_dir = tmp_path / "docs" / "ТестоваяКонфигурация"
    expected = generate_markdown(obj, configuration_name="ТестоваяКонфигурация")
    out = write_markdown(
        obj,
        docs_dir,
        configuration_name="ТестоваяКонфигурация",
    )
    assert out.exists()
    assert out.read_text(encoding="utf-8") == expected


def test_index_pipeline_without_embeddings(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    pipeline = Pipeline(cfg)
    stats = pipeline.index_export(skip_embeddings=True)

    assert stats.objects_total == 6
    assert stats.objects_updated == 6
    assert stats.configuration_name == "ТестоваяКонфигурация"
    assert (
        tmp_path / "output" / "docs" / "ТестоваяКонфигурация" / "catalogs" / "Номенклатура.md"
    ).exists()
    assert cfg.db_path.exists()

    objects = pipeline.indexer.list_objects(config_id=pipeline.active_configuration.id)
    assert len(objects) == 6

    stats2 = pipeline.index_export(skip_embeddings=True)
    assert stats2.objects_skipped == 6
    assert stats2.objects_updated == 0
    assert stats2.chunks_rebuilt == 0

    config_id = pipeline.active_configuration.id
    chunk_ids_first = pipeline.indexer.get_chunk_ids_for_config(config_id)
    stats3 = pipeline.index_export(skip_embeddings=True)
    chunk_ids_second = pipeline.indexer.get_chunk_ids_for_config(config_id)
    assert chunk_ids_first == chunk_ids_second
    assert stats3.chunks_rebuilt == 0
