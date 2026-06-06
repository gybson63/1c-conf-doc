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

    assert stats.objects_total == 3
    assert stats.objects_updated == 3
    assert stats.configuration_name == "ТестоваяКонфигурация"
    assert (
        tmp_path / "output" / "docs" / "ТестоваяКонфигурация" / "catalogs" / "Номенклатура.md"
    ).exists()
    assert cfg.db_path.exists()

    objects = pipeline.indexer.list_objects(config_id=pipeline.active_configuration.id)
    assert len(objects) == 3

    stats2 = pipeline.index_export(skip_embeddings=True)
    assert stats2.objects_skipped == 3
    assert stats2.objects_updated == 0
