"""Persistent embedding cache keyed by content hash and model."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from onec_conf_doc.storage.sqlite import SQLiteIndexer


class EmbeddingCache:
    def __init__(self, indexer: SQLiteIndexer) -> None:
        self._indexer = indexer

    def get(self, config_id: int, content_hash: str, model: str) -> np.ndarray | None:
        with self._indexer.connect() as conn:
            row = conn.execute(
                """
                SELECT dimension, vector
                FROM embedding_cache
                WHERE config_id = ? AND content_hash = ? AND model = ?
                """,
                (config_id, content_hash, model),
            ).fetchone()
        if row is None:
            return None
        dimension = int(row["dimension"])
        vector = np.frombuffer(row["vector"], dtype=np.float32)
        if vector.shape[0] != dimension:
            return None
        return vector.copy()

    def put_batch(
        self,
        config_id: int,
        model: str,
        dimension: int,
        items: list[tuple[str, np.ndarray]],
    ) -> None:
        if not items:
            return
        now = datetime.now(UTC).isoformat()
        with self._indexer.connect() as conn:
            for content_hash, vector in items:
                flat = np.asarray(vector, dtype=np.float32).reshape(-1)
                if flat.shape[0] != dimension:
                    msg = f"Vector dimension {flat.shape[0]} != expected {dimension}"
                    raise ValueError(msg)
                conn.execute(
                    """
                    INSERT INTO embedding_cache
                    (config_id, content_hash, model, dimension, vector, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(config_id, content_hash, model) DO UPDATE SET
                        dimension = excluded.dimension,
                        vector = excluded.vector,
                        created_at = excluded.created_at
                    """,
                    (config_id, content_hash, model, dimension, flat.tobytes(), now),
                )

    def clear_config(self, config_id: int) -> None:
        with self._indexer.connect() as conn:
            conn.execute("DELETE FROM embedding_cache WHERE config_id = ?", (config_id,))

    def clear_model(self, config_id: int, model: str) -> None:
        with self._indexer.connect() as conn:
            conn.execute(
                "DELETE FROM embedding_cache WHERE config_id = ? AND model = ?",
                (config_id, model),
            )

    def has_entry(self, config_id: int, content_hash: str, model: str) -> bool:
        with self._indexer.connect() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM embedding_cache
                WHERE config_id = ? AND content_hash = ? AND model = ?
                """,
                (config_id, content_hash, model),
            ).fetchone()
        return row is not None

    def count_uncached_chunks(self, config_id: int, model: str) -> int:
        with self._indexer.connect() as conn:
            row = conn.execute(
                """
                SELECT count(*)
                FROM chunks c
                JOIN metadata_objects o ON o.id = c.object_id
                LEFT JOIN embedding_cache ec
                    ON ec.config_id = o.config_id
                    AND ec.content_hash = c.content_hash
                    AND ec.model = ?
                WHERE o.config_id = ? AND ec.content_hash IS NULL
                """,
                (model, config_id),
            ).fetchone()
        return int(row[0]) if row else 0
