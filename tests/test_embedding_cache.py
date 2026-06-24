"""Tests for embedding cache."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from onec_conf_doc.models.metadata import ConfigurationInfo
from onec_conf_doc.rag.embedding_cache import EmbeddingCache
from onec_conf_doc.storage.sqlite import SQLiteIndexer


def _cache(tmp_path: Path) -> tuple[EmbeddingCache, int]:
    db_path = tmp_path / "metadata.db"
    indexer = SQLiteIndexer(db_path)
    indexer.init_schema()
    info = ConfigurationInfo(name="TestConfig", content_hash="abc")
    config_id = indexer.upsert_configuration(info)
    return EmbeddingCache(indexer), config_id


def test_put_and_get_vector(tmp_path: Path) -> None:
    cache, config_id = _cache(tmp_path)
    vector = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    cache.put_batch(config_id, "model-a", 3, [("hash1", vector)])

    loaded = cache.get(config_id, "hash1", "model-a")
    assert loaded is not None
    np.testing.assert_array_almost_equal(loaded, vector)


def test_get_returns_none_for_wrong_model(tmp_path: Path) -> None:
    cache, config_id = _cache(tmp_path)
    vector = np.array([1.0, 2.0], dtype=np.float32)
    cache.put_batch(config_id, "model-a", 2, [("hash1", vector)])

    assert cache.get(config_id, "hash1", "model-b") is None


def test_clear_model(tmp_path: Path) -> None:
    cache, config_id = _cache(tmp_path)
    vector = np.array([1.0, 2.0], dtype=np.float32)
    cache.put_batch(config_id, "model-a", 2, [("hash1", vector)])
    cache.put_batch(config_id, "model-b", 2, [("hash1", vector)])

    cache.clear_model(config_id, "model-a")
    assert cache.get(config_id, "hash1", "model-a") is None
    assert cache.get(config_id, "hash1", "model-b") is not None


def test_get_many_batch_lookup(tmp_path: Path) -> None:
    cache, config_id = _cache(tmp_path)
    v1 = np.array([1.0, 2.0], dtype=np.float32)
    v2 = np.array([3.0, 4.0], dtype=np.float32)
    cache.put_batch(
        config_id,
        "model-a",
        2,
        [("hash1", v1), ("hash2", v2)],
    )

    found = cache.get_many(config_id, ["hash1", "hash2", "hash3"], "model-a")
    assert set(found) == {"hash1", "hash2"}
    np.testing.assert_array_almost_equal(found["hash1"], v1)
    np.testing.assert_array_almost_equal(found["hash2"], v2)


def test_put_batch_rejects_dimension_mismatch(tmp_path: Path) -> None:
    cache, config_id = _cache(tmp_path)
    vector = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    try:
        cache.put_batch(config_id, "model-a", 2, [("hash1", vector)])
    except ValueError:
        return
    raise AssertionError("Expected ValueError for dimension mismatch")
