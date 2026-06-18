"""Delete configuration performance — indexes and bulk delete path."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from onec_conf_doc.storage.sqlite import SQLiteIndexer

_TEXT = "x" * 2048


def _seed_large_config(db: SQLiteIndexer, *, objects: int, chunks_per_object: int) -> int:
    db.init_schema()
    now = datetime.now(UTC).isoformat()
    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO configurations
            (name, synonym, version, source_path, export_path, indexed_at, content_hash)
            VALUES ('PerfTest', '', '1.0', '/src', '/export', ?, 'hash')
            """,
            (now,),
        )
        config_id = int(cur.lastrowid)
        conn.executemany(
            """
            INSERT INTO metadata_objects (
                config_id, object_type, name, synonym, comment,
                uuid, source_xml, md_path, content_hash
            )
            VALUES (?, 'Catalog', ?, '', '', '', '', '', '')
            """,
            [(config_id, f"Obj{i}") for i in range(objects)],
        )
        object_ids = [
            int(r[0])
            for r in conn.execute(
                "SELECT id FROM metadata_objects WHERE config_id = ? ORDER BY id",
                (config_id,),
            ).fetchall()
        ]
        attr_rows = [
            (oid, f"Attr{j}", "", "", "", 0, "object", "") for oid in object_ids for j in range(3)
        ]
        conn.executemany(
            """
            INSERT INTO attributes (
                object_id, name, type_repr, synonym, comment,
                is_required, parent_kind, parent_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            attr_rows,
        )
        chunk_rows = [
            (oid, ci, _TEXT, "", 512, "chash")
            for oid in object_ids
            for ci in range(chunks_per_object)
        ]
        conn.executemany(
            """
            INSERT INTO chunks
            (object_id, chunk_index, text, md_path, token_count, content_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            chunk_rows,
        )
        cache_rows = [
            (config_id, f"h{i}", "model", 384, b"\x00" * (384 * 4), now)
            for i in range(objects * chunks_per_object)
        ]
        conn.executemany(
            """
            INSERT INTO embedding_cache
            (config_id, content_hash, model, dimension, vector, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            cache_rows,
        )
    return config_id


def test_delete_configuration_completes_quickly_for_large_config(tmp_path) -> None:
    db = SQLiteIndexer(tmp_path / "metadata.db")
    config_id = _seed_large_config(db, objects=1500, chunks_per_object=2)

    started = time.monotonic()
    db.delete_configuration(config_id)
    elapsed = time.monotonic() - started

    assert elapsed < 8.0, f"delete took {elapsed:.1f}s"

    with db.connect() as conn:
        assert int(conn.execute("SELECT count(*) FROM configurations").fetchone()[0]) == 0
        assert int(conn.execute("SELECT count(*) FROM chunks").fetchone()[0]) == 0
        assert int(conn.execute("SELECT count(*) FROM embedding_cache").fetchone()[0]) == 0


def test_object_id_indexes_exist_after_init(tmp_path) -> None:
    db = SQLiteIndexer(tmp_path / "metadata.db")
    db.init_schema()
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%_object'"
        ).fetchall()
    names = {str(r[0]) for r in rows}
    assert "idx_attributes_object" in names
    assert "idx_chunks_object" in names
    assert "idx_help_pages_object" in names
