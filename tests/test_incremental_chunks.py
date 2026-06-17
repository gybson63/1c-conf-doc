"""Tests for incremental chunk rebuild."""

from __future__ import annotations

import shutil
from pathlib import Path

from onec_conf_doc.config import AppConfig
from onec_conf_doc.rag.pipeline import Pipeline

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


def _copy_export(tmp_path: Path) -> Path:
    export = tmp_path / "export"
    shutil.copytree(FIXTURES, export)
    return export


def test_second_index_preserves_chunk_ids(tmp_path: Path) -> None:
    export = _copy_export(tmp_path)
    cfg = AppConfig(source=export, output=tmp_path / "output")
    pipeline = Pipeline(cfg)

    pipeline.index_export(skip_embeddings=True)
    config_id = pipeline.active_configuration.id
    chunk_ids_first = pipeline.indexer.get_chunk_ids_for_config(config_id)
    assert chunk_ids_first

    stats = pipeline.index_export(skip_embeddings=True)
    chunk_ids_second = pipeline.indexer.get_chunk_ids_for_config(config_id)

    assert stats.objects_skipped == stats.objects_total
    assert stats.objects_updated == 0
    assert stats.chunks_rebuilt == 0
    assert chunk_ids_first == chunk_ids_second


def test_updated_object_rebuilds_only_its_chunks(tmp_path: Path) -> None:
    export = _copy_export(tmp_path)
    cfg = AppConfig(source=export, output=tmp_path / "output")
    pipeline = Pipeline(cfg)

    pipeline.index_export(skip_embeddings=True)
    config_id = pipeline.active_configuration.id
    chunk_ids_before = pipeline.indexer.get_chunk_ids_for_config(config_id)

    catalog_path = export / "Catalogs" / "Номенклатура.xml"
    text = catalog_path.read_text(encoding="utf-8")
    catalog_path.write_text(
        text.replace("Справочник товаров", "Справочник товаров (обновлено)"),
        encoding="utf-8",
    )

    stats = pipeline.index_export(skip_embeddings=True)
    chunk_ids_after = pipeline.indexer.get_chunk_ids_for_config(config_id)

    assert stats.objects_updated == 1
    assert stats.chunks_rebuilt == 1
    assert len(chunk_ids_after) == len(chunk_ids_before)
    assert chunk_ids_after != chunk_ids_before


def test_deleted_object_removed_from_db(tmp_path: Path) -> None:
    export = _copy_export(tmp_path)
    cfg = AppConfig(source=export, output=tmp_path / "output")
    pipeline = Pipeline(cfg)

    pipeline.index_export(skip_embeddings=True)
    config_id = pipeline.active_configuration.id
    assert pipeline.indexer.get_object_detail("Enum", "ВидыОпераций", config_id=config_id)

    (export / "Enums" / "ВидыОпераций.xml").unlink()

    stats = pipeline.index_export(skip_embeddings=True)

    assert stats.objects_deleted == 1
    assert stats.chunks_rebuilt == 0
    assert pipeline.indexer.get_object_detail("Enum", "ВидыОпераций", config_id=config_id) is None
    assert len(pipeline.indexer.list_objects(config_id=config_id)) == 5
