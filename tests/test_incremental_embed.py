"""Integration tests for incremental embed pipeline."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from onec_conf_doc.config import AppConfig, ChunkingConfig
from onec_conf_doc.rag.faiss_index import FaissIndex
from onec_conf_doc.rag.pipeline import Pipeline

FIXTURES = Path(__file__).parent / "fixtures" / "export_minimal"


@dataclass
class MockEmbeddingProvider:
    dimension: int = 4
    calls: int = 0
    batch_sizes: list[int] = field(default_factory=list)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        self.batch_sizes.append(len(texts))
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


def _copy_export(tmp_path: Path) -> Path:
    export = tmp_path / "export"
    shutil.copytree(FIXTURES, export)
    return export


def _pipeline(tmp_path: Path, export: Path | None = None) -> tuple[Pipeline, MockEmbeddingProvider]:
    source = export or _copy_export(tmp_path)
    cfg = AppConfig(source=source, output=tmp_path / "output")
    pipeline = Pipeline(cfg)
    mock = MockEmbeddingProvider()

    def _provider_for(name: str) -> MockEmbeddingProvider:
        pipeline._embedding_providers[name] = mock
        return mock

    pipeline.embedding_provider_for = _provider_for  # type: ignore[method-assign]
    return pipeline, mock


def _embeddable_count(pipeline: Pipeline) -> int:
    config_id = pipeline.active_configuration.id
    return len(pipeline.indexer.get_chunks_for_embedding(config_id))


def test_second_index_skips_unchanged_embeddings(tmp_path: Path) -> None:
    pipeline, mock = _pipeline(tmp_path)
    pipeline.index_export(skip_embeddings=False)
    first_calls = mock.calls
    embeddable = _embeddable_count(pipeline)

    mock.calls = 0
    stats = pipeline.index_export(skip_embeddings=False)

    assert stats.objects_skipped == stats.objects_total
    assert stats.chunks_rebuilt == 0
    assert stats.embeddings_cached == embeddable
    assert stats.embeddings_computed == 0
    assert mock.calls == 0
    assert first_calls == embeddable
    assert first_calls > 0


def test_single_object_change_embeds_only_changed_chunks(tmp_path: Path) -> None:
    export = _copy_export(tmp_path)
    pipeline, mock = _pipeline(tmp_path, export)
    pipeline.index_export(skip_embeddings=False)
    mock.calls = 0

    catalog_path = export / "Catalogs" / "Номенклатура.xml"
    text = catalog_path.read_text(encoding="utf-8")
    catalog_path.write_text(
        text.replace("Справочник товаров", "Справочник товаров (обновлено)"),
        encoding="utf-8",
    )

    stats = pipeline.index_export(skip_embeddings=False)
    assert stats.objects_updated == 1
    assert stats.embeddings_computed == mock.calls
    assert stats.embeddings_computed > 0
    assert stats.embeddings_computed < stats.chunks_total


def test_force_rebuilds_all_embeddings(tmp_path: Path) -> None:
    pipeline, mock = _pipeline(tmp_path)
    pipeline.index_export(skip_embeddings=False)
    embeddable = _embeddable_count(pipeline)
    mock.calls = 0

    stats = pipeline.index_export(skip_embeddings=False, force=True)
    assert stats.embeddings_computed == embeddable
    assert stats.embeddings_cached == 0
    assert mock.calls == embeddable


def test_embed_command_uses_cache(tmp_path: Path) -> None:
    pipeline, mock = _pipeline(tmp_path)
    pipeline.index_export(skip_embeddings=True)
    mock.calls = 0

    from onec_conf_doc.rag.pipeline import IndexStats

    embed_stats = IndexStats()
    count = pipeline.rebuild_embeddings(show_progress=False, stats=embed_stats)
    assert count > 0
    assert embed_stats.embeddings_computed == count
    assert mock.calls == count

    mock.calls = 0
    embed_stats2 = IndexStats()
    pipeline.rebuild_embeddings(show_progress=False, stats=embed_stats2)
    assert mock.calls == 0
    assert embed_stats2.embeddings_cached == count


def test_chunk_map_saves_model(tmp_path: Path) -> None:
    pipeline, _mock = _pipeline(tmp_path)
    pipeline.config.embeddings.model = "test-model"
    pipeline.index_export(skip_embeddings=False)

    cfg = pipeline.active_configuration
    faiss_idx = pipeline.faiss_index_for(cfg.name)
    assert faiss_idx.load()
    assert faiss_idx.stored_model == "test-model"
    assert faiss_idx.built_at

    data = json.loads(faiss_idx.map_path.read_text(encoding="utf-8"))
    assert data["model"] == "test-model"
    assert "built_at" in data


def test_load_legacy_chunk_map_without_model(tmp_path: Path) -> None:
    from onec_conf_doc.config import FaissConfig

    vectors_dir = tmp_path / "vectors" / "Test"
    faiss_idx = FaissIndex(vectors_dir, FaissConfig(), 4)
    faiss_idx.build(np.array([], dtype=np.float32).reshape(0, 4), [])
    faiss_idx.save()

    reloaded = FaissIndex(vectors_dir, FaissConfig(), 4)
    assert reloaded.load()
    assert reloaded.stored_model is None


def test_chunking_params_change_rebuilds_all_chunks(tmp_path: Path) -> None:
    pipeline, _mock = _pipeline(tmp_path)
    pipeline.index_export(skip_embeddings=True)
    config_id = pipeline.active_configuration.id
    chunk_ids_before = pipeline.indexer.get_chunk_ids_for_config(config_id)

    pipeline.config.chunking = ChunkingConfig(max_tokens=800, overlap_tokens=50)
    stats = pipeline.index_export(skip_embeddings=True)

    chunk_ids_after = pipeline.indexer.get_chunk_ids_for_config(config_id)
    assert stats.chunks_rebuilt == 6
    assert chunk_ids_before != chunk_ids_after


def test_model_change_triggers_full_recompute(tmp_path: Path) -> None:
    pipeline, mock = _pipeline(tmp_path)
    pipeline.config.embeddings.model = "model-a"
    pipeline.index_export(skip_embeddings=False)
    mock.calls = 0

    pipeline.config.embeddings.model = "model-b"
    embeddable = _embeddable_count(pipeline)
    stats = pipeline.index_export(skip_embeddings=False)
    assert stats.embeddings_computed == embeddable
    assert mock.calls == embeddable
