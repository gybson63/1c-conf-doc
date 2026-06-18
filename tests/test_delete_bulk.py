"""Bulk delete configuration — related SQLite rows are fully removed."""

from __future__ import annotations

from pathlib import Path

from onec_conf_doc.config import AppConfig
from onec_conf_doc.rag.pipeline import Pipeline

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"

_RELATED_TABLES = (
    "metadata_objects",
    "attributes",
    "tabular_sections",
    "enum_values",
    "help_pages",
    "chunks",
    "embedding_cache",
)


def test_delete_configuration_bulk_cleans_related_rows(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    pipeline = Pipeline(cfg)
    pipeline.index_export(skip_embeddings=True)

    config_name = "ТестоваяКонфигурация"
    config_id = pipeline.indexer.get_configuration_id(config_name)
    assert config_id is not None

    with pipeline.indexer.connect() as conn:
        before_objects = int(
            conn.execute(
                "SELECT count(*) FROM metadata_objects WHERE config_id = ?",
                (config_id,),
            ).fetchone()[0]
        )
        assert before_objects > 0

    pipeline.delete_configuration(config_name, remove_files=False)

    with pipeline.indexer.connect() as conn:
        assert int(conn.execute("SELECT count(*) FROM configurations").fetchone()[0]) == 0
        for table in _RELATED_TABLES:
            count = int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            assert count == 0, f"expected empty {table}, got {count}"


def test_delete_configuration_with_index_runs(tmp_path: Path) -> None:
    cfg = AppConfig(source=FIXTURES, output=tmp_path / "output")
    pipeline = Pipeline(cfg)
    pipeline.index_export(skip_embeddings=True)

    config_name = "ТестоваяКонфигурация"
    config_id = pipeline.indexer.get_configuration_id(config_name)
    assert config_id is not None

    with pipeline.indexer.connect() as conn:
        conn.execute(
            """
            INSERT INTO index_runs (config_id, started_at, status)
            VALUES (?, '2020-01-01', 'completed')
            """,
            (config_id,),
        )

    pipeline.delete_configuration(config_name, remove_files=False)

    with pipeline.indexer.connect() as conn:
        assert int(conn.execute("SELECT count(*) FROM configurations").fetchone()[0]) == 0
        assert int(conn.execute("SELECT count(*) FROM index_runs").fetchone()[0]) == 0
