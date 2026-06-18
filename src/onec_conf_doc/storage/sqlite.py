"""SQLite storage for metadata index."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from onec_conf_doc.models.metadata import ConfigurationInfo, MetadataObject
from onec_conf_doc.rag.embed_policy import EMBED_EXCLUDED_OBJECT_TYPES

SCHEMA = """
CREATE TABLE IF NOT EXISTS configurations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    synonym TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    export_path TEXT NOT NULL DEFAULT '',
    indexed_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    chunking_hash TEXT NOT NULL DEFAULT '',
    UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS metadata_objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER NOT NULL REFERENCES configurations(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL,
    name TEXT NOT NULL,
    synonym TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    uuid TEXT NOT NULL DEFAULT '',
    source_xml TEXT NOT NULL DEFAULT '',
    md_path TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    UNIQUE(config_id, object_type, name)
);

CREATE TABLE IF NOT EXISTS attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES metadata_objects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type_repr TEXT NOT NULL DEFAULT '',
    synonym TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    is_required INTEGER NOT NULL DEFAULT 0,
    parent_kind TEXT NOT NULL DEFAULT 'object',
    parent_name TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tabular_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES metadata_objects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    synonym TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS enum_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES metadata_objects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    synonym TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS help_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES metadata_objects(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    content_md TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES metadata_objects(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    md_path TEXT NOT NULL DEFAULT '',
    token_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL DEFAULT '',
    vector_id INTEGER
);

CREATE TABLE IF NOT EXISTS index_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER REFERENCES configurations(id) ON DELETE SET NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    objects_count INTEGER NOT NULL DEFAULT 0,
    chunks_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_objects_config ON metadata_objects(config_id);
CREATE INDEX IF NOT EXISTS idx_objects_type ON metadata_objects(object_type);
CREATE INDEX IF NOT EXISTS idx_objects_name ON metadata_objects(name);
CREATE INDEX IF NOT EXISTS idx_chunks_object ON chunks(object_id);
CREATE INDEX IF NOT EXISTS idx_attributes_object ON attributes(object_id);
CREATE INDEX IF NOT EXISTS idx_tabular_sections_object ON tabular_sections(object_id);
CREATE INDEX IF NOT EXISTS idx_enum_values_object ON enum_values(object_id);
CREATE INDEX IF NOT EXISTS idx_help_pages_object ON help_pages(object_id);

CREATE TABLE IF NOT EXISTS embedding_cache (
    config_id INTEGER NOT NULL REFERENCES configurations(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (config_id, content_hash, model)
);

CREATE INDEX IF NOT EXISTS idx_embedding_cache_config ON embedding_cache(config_id);
"""

# Child tables of metadata_objects — bulk-deleted before metadata_objects
# to avoid per-row ON DELETE CASCADE during configuration removal.
_CONFIG_OBJECT_CHILD_TABLES = (
    "attributes",
    "tabular_sections",
    "enum_values",
    "help_pages",
    "chunks",
)

_BULK_DELETE_TABLE_LABELS: dict[str, str] = {
    "attributes": "реквизиты",
    "tabular_sections": "табличные части",
    "enum_values": "значения перечислений",
    "help_pages": "справка",
    "chunks": "чанки",
}

_OBJECT_ID_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_attributes_object ON attributes(object_id)",
    "CREATE INDEX IF NOT EXISTS idx_tabular_sections_object ON tabular_sections(object_id)",
    "CREATE INDEX IF NOT EXISTS idx_enum_values_object ON enum_values(object_id)",
    "CREATE INDEX IF NOT EXISTS idx_help_pages_object ON help_pages(object_id)",
)

MIGRATIONS = (
    "ALTER TABLE configurations ADD COLUMN synonym TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE configurations ADD COLUMN export_path TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE index_runs ADD COLUMN config_id INTEGER REFERENCES configurations(id)",
    "ALTER TABLE configurations ADD COLUMN chunking_hash TEXT NOT NULL DEFAULT ''",
)


@dataclass
class StoredConfiguration:
    id: int
    name: str
    synonym: str
    version: str
    export_path: str
    indexed_at: str
    objects_count: int = 0


@dataclass
class StoredObject:
    id: int
    object_type: str
    name: str
    synonym: str
    comment: str
    md_path: str


class SQLiteIndexer:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _connect_bulk_delete(self) -> Iterator[sqlite3.Connection]:
        """Connection for bulk delete: FK checks off before any DML (see SQLite pragma rules)."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA temp_store = MEMORY")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        for sql in MIGRATIONS:
            with suppress(sqlite3.OperationalError):
                conn.execute(sql)
        for sql in _OBJECT_ID_INDEXES:
            conn.execute(sql)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_configurations_name ON configurations(name)"
        )

    def upsert_configuration(self, info: ConfigurationInfo) -> int:
        if not info.name:
            msg = "Configuration name is required (from Configuration.xml Properties/Name)"
            raise ValueError(msg)
        now = datetime.now(UTC).isoformat()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM configurations WHERE name = ?",
                (info.name,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE configurations
                    SET synonym=?, version=?, source_path=?, export_path=?,
                        indexed_at=?, content_hash=?
                    WHERE id=?
                    """,
                    (
                        info.synonym,
                        info.version,
                        info.source_path,
                        info.export_path,
                        now,
                        info.content_hash,
                        row["id"],
                    ),
                )
                return int(row["id"])
            cur = conn.execute(
                """
                INSERT INTO configurations
                (name, synonym, version, source_path, export_path, indexed_at, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    info.name,
                    info.synonym,
                    info.version,
                    info.source_path,
                    info.export_path,
                    now,
                    info.content_hash,
                ),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_object_hash(self, config_id: int, object_type: str, name: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT content_hash FROM metadata_objects
                WHERE config_id=? AND object_type=? AND name=?
                """,
                (config_id, object_type, name),
            ).fetchone()
            return str(row["content_hash"]) if row else None

    def upsert_object(
        self,
        config_id: int,
        obj: MetadataObject,
        md_path: Path,
    ) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM metadata_objects
                WHERE config_id=? AND object_type=? AND name=?
                """,
                (config_id, obj.object_type, obj.name),
            ).fetchone()
            md_str = str(md_path)
            if row:
                object_id = int(row["id"])
                conn.execute(
                    """
                    UPDATE metadata_objects
                    SET synonym=?, comment=?, uuid=?, source_xml=?, md_path=?, content_hash=?
                    WHERE id=?
                    """,
                    (
                        obj.synonym,
                        obj.comment,
                        obj.uuid,
                        obj.source_xml,
                        md_str,
                        obj.content_hash,
                        object_id,
                    ),
                )
                conn.execute("DELETE FROM attributes WHERE object_id=?", (object_id,))
                conn.execute("DELETE FROM tabular_sections WHERE object_id=?", (object_id,))
                conn.execute("DELETE FROM enum_values WHERE object_id=?", (object_id,))
                conn.execute("DELETE FROM help_pages WHERE object_id=?", (object_id,))
            else:
                cur = conn.execute(
                    """
                    INSERT INTO metadata_objects (
                        config_id, object_type, name, synonym, comment,
                        uuid, source_xml, md_path, content_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        config_id,
                        obj.object_type,
                        obj.name,
                        obj.synonym,
                        obj.comment,
                        obj.uuid,
                        obj.source_xml,
                        md_str,
                        obj.content_hash,
                    ),
                )
                assert cur.lastrowid is not None
                object_id = int(cur.lastrowid)

            for attr in obj.attributes:
                conn.execute(
                    """
                    INSERT INTO attributes (
                        object_id, name, type_repr, synonym, comment,
                        is_required, parent_kind, parent_name
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'object', '')
                    """,
                    (
                        object_id,
                        attr.name,
                        attr.type_repr,
                        attr.synonym,
                        attr.comment,
                        int(attr.is_required),
                    ),
                )

            for dim in obj.dimensions:
                conn.execute(
                    """
                    INSERT INTO attributes (
                        object_id, name, type_repr, synonym, comment,
                        is_required, parent_kind, parent_name
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'dimension', '')
                    """,
                    (
                        object_id,
                        dim.name,
                        dim.type_repr,
                        dim.synonym,
                        dim.comment,
                        int(dim.is_required),
                    ),
                )

            for res in obj.resources:
                conn.execute(
                    """
                    INSERT INTO attributes (
                        object_id, name, type_repr, synonym, comment,
                        is_required, parent_kind, parent_name
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'resource', '')
                    """,
                    (
                        object_id,
                        res.name,
                        res.type_repr,
                        res.synonym,
                        res.comment,
                        int(res.is_required),
                    ),
                )

            for ts in obj.tabular_sections:
                conn.execute(
                    """
                    INSERT INTO tabular_sections (object_id, name, synonym, comment)
                    VALUES (?, ?, ?, ?)
                    """,
                    (object_id, ts.name, ts.synonym, ts.comment),
                )
                for attr in ts.attributes:
                    conn.execute(
                        """
                        INSERT INTO attributes (
                            object_id, name, type_repr, synonym, comment,
                            is_required, parent_kind, parent_name
                        )
                        VALUES (?, ?, ?, ?, ?, ?, 'tabular_section', ?)
                        """,
                        (
                            object_id,
                            attr.name,
                            attr.type_repr,
                            attr.synonym,
                            attr.comment,
                            int(attr.is_required),
                            ts.name,
                        ),
                    )

            for val in obj.enum_values:
                conn.execute(
                    """
                    INSERT INTO enum_values (object_id, name, synonym, comment)
                    VALUES (?, ?, ?, ?)
                    """,
                    (object_id, val.name, val.synonym, val.comment),
                )

            for page in obj.help_pages:
                conn.execute(
                    """
                    INSERT INTO help_pages (object_id, title, content_md, source_path)
                    VALUES (?, ?, ?, ?)
                    """,
                    (object_id, page.title, page.content_md, page.source_path),
                )

            return object_id

    def start_index_run(self, config_id: int | None = None) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO index_runs (config_id, started_at, status)
                VALUES (?, ?, 'running')
                """,
                (config_id, datetime.now(UTC).isoformat()),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def finish_index_run(self, run_id: int, objects_count: int, chunks_count: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE index_runs
                SET finished_at=?, status='completed', objects_count=?, chunks_count=?
                WHERE id=?
                """,
                (datetime.now(UTC).isoformat(), objects_count, chunks_count, run_id),
            )

    def list_configurations(self) -> list[StoredConfiguration]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.name, c.synonym, c.version, c.export_path, c.indexed_at,
                       (SELECT count(*) FROM metadata_objects o
                        WHERE o.config_id = c.id) AS objects_count
                FROM configurations c
                ORDER BY c.name
                """
            ).fetchall()
        return [
            StoredConfiguration(
                id=int(r["id"]),
                name=str(r["name"]),
                synonym=str(r["synonym"]),
                version=str(r["version"]),
                export_path=str(r["export_path"]),
                indexed_at=str(r["indexed_at"]),
                objects_count=int(r["objects_count"]),
            )
            for r in rows
        ]

    def get_configuration(self, name: str) -> StoredConfiguration | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT c.id, c.name, c.synonym, c.version, c.export_path, c.indexed_at,
                       (SELECT count(*) FROM metadata_objects o
                        WHERE o.config_id = c.id) AS objects_count
                FROM configurations c
                WHERE c.name = ?
                """,
                (name,),
            ).fetchone()
        if row is None:
            return None
        return StoredConfiguration(
            id=int(row["id"]),
            name=str(row["name"]),
            synonym=str(row["synonym"]),
            version=str(row["version"]),
            export_path=str(row["export_path"]),
            indexed_at=str(row["indexed_at"]),
            objects_count=int(row["objects_count"]),
        )

    def resolve_configuration(self, name: str) -> StoredConfiguration | None:
        """Find configuration by exact or normalized name (Latin/Cyrillic homoglyphs)."""
        cfg = self.get_configuration(name)
        if cfg is not None:
            return cfg
        candidates = [row.name for row in self.list_configurations()]
        from onec_conf_doc.config_names import match_configuration_name

        matched = match_configuration_name(name, candidates)
        if matched is None:
            return None
        return self.get_configuration(matched)

    def get_configuration_id(self, name: str) -> int | None:
        cfg = self.get_configuration(name)
        return cfg.id if cfg else None

    def delete_configuration(
        self,
        config_id: int,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        def step(msg: str) -> None:
            if progress is not None:
                progress(msg)

        with self.connect() as conn:
            row = conn.execute(
                "SELECT count(*) FROM metadata_objects WHERE config_id = ?",
                (config_id,),
            ).fetchone()
            objects_count = int(row[0]) if row else 0

        step(f"Удаление из SQLite ({objects_count} объектов)...")

        with self._connect_bulk_delete() as conn:
            conn.execute(
                "CREATE TEMP TABLE IF NOT EXISTS _del_obj_ids "
                "(object_id INTEGER PRIMARY KEY) WITHOUT ROWID"
            )
            conn.execute("DELETE FROM _del_obj_ids")
            conn.execute(
                "INSERT OR IGNORE INTO _del_obj_ids "
                "SELECT id FROM metadata_objects WHERE config_id = ?",
                (config_id,),
            )

            step("  кэш эмбеддингов")
            conn.execute("DELETE FROM embedding_cache WHERE config_id = ?", (config_id,))

            for table in _CONFIG_OBJECT_CHILD_TABLES:
                step(f"  {_BULK_DELETE_TABLE_LABELS.get(table, table)}")
                conn.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE rowid IN (
                        SELECT t.rowid
                        FROM {table} AS t
                        INNER JOIN _del_obj_ids AS d ON d.object_id = t.object_id
                    )
                    """
                )

            step("  объекты метаданных")
            conn.execute("DELETE FROM metadata_objects WHERE config_id = ?", (config_id,))

            step("  история индексации")
            conn.execute("DELETE FROM index_runs WHERE config_id = ?", (config_id,))

            step("  запись конфигурации")
            conn.execute("DELETE FROM configurations WHERE id = ?", (config_id,))

            conn.execute("DROP TABLE IF EXISTS _del_obj_ids")

    def get_configuration_chunking_hash(self, config_id: int) -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT chunking_hash FROM configurations WHERE id = ?",
                (config_id,),
            ).fetchone()
        if row is None:
            return ""
        return str(row["chunking_hash"] or "")

    def set_configuration_chunking_hash(self, config_id: int, chunking_hash: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE configurations SET chunking_hash = ? WHERE id = ?",
                (chunking_hash, config_id),
            )

    def list_objects(
        self,
        *,
        config_id: int | None = None,
        object_type: str | None = None,
        query: str | None = None,
        limit: int = 50,
    ) -> list[StoredObject]:
        sql = """
            SELECT id, object_type, name, synonym, comment, md_path
            FROM metadata_objects
            WHERE 1=1
        """
        params: list[object] = []
        if config_id is not None:
            sql += " AND config_id = ?"
            params.append(config_id)
        if object_type:
            sql += " AND object_type = ?"
            params.append(object_type)
        if query:
            sql += " AND (name LIKE ? OR synonym LIKE ? OR comment LIKE ?)"
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern])
        sql += " ORDER BY object_type, name LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            StoredObject(
                id=int(r["id"]),
                object_type=str(r["object_type"]),
                name=str(r["name"]),
                synonym=str(r["synonym"]),
                comment=str(r["comment"]),
                md_path=str(r["md_path"]),
            )
            for r in rows
        ]

    def get_all_objects_with_md(self, config_id: int) -> list[tuple[int, str, str, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, object_type, name, md_path
                FROM metadata_objects
                WHERE config_id = ?
                ORDER BY id
                """,
                (config_id,),
            ).fetchall()
        return [
            (int(r["id"]), str(r["object_type"]), str(r["name"]), str(r["md_path"])) for r in rows
        ]

    def clear_chunks(self, config_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM chunks
                WHERE object_id IN (SELECT id FROM metadata_objects WHERE config_id = ?)
                """,
                (config_id,),
            )

    def delete_chunks_for_object(self, object_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM chunks WHERE object_id = ?", (object_id,))

    def delete_objects_not_in_scan(
        self,
        config_id: int,
        keys: set[tuple[str, str]],
    ) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, object_type, name
                FROM metadata_objects
                WHERE config_id = ?
                """,
                (config_id,),
            ).fetchall()
            deleted: list[int] = []
            for row in rows:
                key = (str(row["object_type"]), str(row["name"]))
                if key not in keys:
                    object_id = int(row["id"])
                    conn.execute("DELETE FROM metadata_objects WHERE id = ?", (object_id,))
                    deleted.append(object_id)
            return deleted

    def get_chunk_ids_for_config(self, config_id: int) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id
                FROM chunks c
                JOIN metadata_objects o ON o.id = c.object_id
                WHERE o.config_id = ?
                ORDER BY c.id
                """,
                (config_id,),
            ).fetchall()
        return [int(r["id"]) for r in rows]

    def count_chunks_for_config(self, config_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT count(*)
                FROM chunks c
                JOIN metadata_objects o ON o.id = c.object_id
                WHERE o.config_id = ?
                """,
                (config_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def insert_chunks(
        self,
        object_id: int,
        chunks: list[tuple[int, str, str, int, str]],
    ) -> list[int]:
        ids: list[int] = []
        with self.connect() as conn:
            for chunk_index, text, md_path, token_count, content_hash in chunks:
                cur = conn.execute(
                    """
                    INSERT INTO chunks
                    (object_id, chunk_index, text, md_path, token_count, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (object_id, chunk_index, text, md_path, token_count, content_hash),
                )
                assert cur.lastrowid is not None
                ids.append(int(cur.lastrowid))
        return ids

    def clear_chunk_vector_ids(self, config_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE chunks
                SET vector_id = NULL
                WHERE object_id IN (
                    SELECT id FROM metadata_objects WHERE config_id = ?
                )
                """,
                (config_id,),
            )

    def update_chunk_vector_ids(self, mapping: dict[int, int]) -> None:
        with self.connect() as conn:
            for chunk_id, vector_id in mapping.items():
                conn.execute(
                    "UPDATE chunks SET vector_id=? WHERE id=?",
                    (vector_id, chunk_id),
                )

    def get_chunks_for_embedding(self, config_id: int) -> list[tuple[int, str, str]]:
        excluded = sorted(EMBED_EXCLUDED_OBJECT_TYPES)
        placeholders = ", ".join("?" for _ in excluded)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.id, c.text, c.content_hash
                FROM chunks c
                JOIN metadata_objects o ON o.id = c.object_id
                WHERE o.config_id = ?
                  AND o.object_type NOT IN ({placeholders})
                ORDER BY c.id
                """,
                (config_id, *excluded),
            ).fetchall()
        return [(int(r["id"]), str(r["text"]), str(r["content_hash"])) for r in rows]

    def get_role_chunks_for_search(self, config_id: int) -> list[dict[str, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT o.name AS role, o.synonym, o.md_path, c.text
                FROM metadata_objects o
                JOIN chunks c ON c.object_id = o.id
                WHERE o.config_id = ? AND o.object_type = 'Role'
                ORDER BY o.name, c.chunk_index
                """,
                (config_id,),
            ).fetchall()
        return [
            {
                "role": str(r["role"]),
                "synonym": str(r["synonym"] or ""),
                "md_path": str(r["md_path"] or ""),
                "text": str(r["text"]),
            }
            for r in rows
        ]

    def find_objects_by_exact_name(
        self,
        config_id: int,
        query: str,
    ) -> list[dict[str, object]]:
        q = query.strip().casefold()
        if not q:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT o.id, o.object_type, o.name, o.synonym, o.md_path,
                       cfg.name AS configuration_name, cfg.synonym AS configuration_synonym
                FROM metadata_objects o
                JOIN configurations cfg ON cfg.id = o.config_id
                WHERE o.config_id = ?
                ORDER BY o.object_type, o.name
                """,
                (config_id,),
            ).fetchall()
        matches: list[dict[str, object]] = []
        for row in rows:
            name = str(row["name"])
            synonym = str(row["synonym"] or "")
            if name.casefold() == q or synonym.casefold() == q:
                matches.append(dict(row))
        return matches

    def get_preferred_chunk(self, object_id: int) -> dict[str, object] | None:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.text, c.md_path, c.chunk_index, c.vector_id,
                       o.object_type, o.name, o.synonym,
                       cfg.name AS configuration_name, cfg.synonym AS configuration_synonym
                FROM chunks c
                JOIN metadata_objects o ON o.id = c.object_id
                JOIN configurations cfg ON cfg.id = o.config_id
                WHERE c.object_id = ?
                ORDER BY c.chunk_index
                """,
                (object_id,),
            ).fetchall()
        if not rows:
            return None
        for row in rows:
            if int(row["chunk_index"]) == 0:
                return dict(row)
        for row in rows:
            if "## Справка" in str(row["text"]):
                return dict(row)
        return dict(rows[0])

    def get_chunk_by_id(self, chunk_id: int) -> dict[str, object] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT c.id, c.text, c.md_path, c.chunk_index, c.vector_id,
                       o.object_type, o.name, o.synonym,
                       cfg.name AS configuration_name, cfg.synonym AS configuration_synonym
                FROM chunks c
                JOIN metadata_objects o ON o.id = c.object_id
                JOIN configurations cfg ON cfg.id = o.config_id
                WHERE c.id = ?
                """,
                (chunk_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_latest_config_id(self) -> int | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM configurations ORDER BY indexed_at DESC LIMIT 1"
            ).fetchone()
        return int(row["id"]) if row else None

    def get_object_detail(
        self,
        object_type: str,
        name: str,
        *,
        config_id: int | None = None,
        configuration_name: str | None = None,
    ) -> dict[str, object] | None:
        with self.connect() as conn:
            sql = """
                SELECT o.id, o.object_type, o.name, o.synonym, o.comment, o.uuid,
                       o.source_xml, o.md_path, o.content_hash,
                       cfg.name AS configuration_name, cfg.synonym AS configuration_synonym
                FROM metadata_objects o
                JOIN configurations cfg ON cfg.id = o.config_id
                WHERE o.object_type = ? AND o.name = ?
            """
            params: list[object] = [object_type, name]
            if config_id is not None:
                sql += " AND o.config_id = ?"
                params.append(config_id)
            elif configuration_name:
                sql += " AND cfg.name = ?"
                params.append(configuration_name)
            row = conn.execute(sql, params).fetchone()
            if row is None:
                return None
            object_id = int(row["id"])
            help_pages = conn.execute(
                """
                SELECT id, title, source_path, length(content_md) AS content_len
                FROM help_pages WHERE object_id = ? ORDER BY id
                """,
                (object_id,),
            ).fetchall()
            chunks = conn.execute(
                """
                SELECT id, chunk_index, token_count, length(text) AS text_len, vector_id
                FROM chunks WHERE object_id = ? ORDER BY chunk_index
                """,
                (object_id,),
            ).fetchall()
            attr_count = conn.execute(
                "SELECT count(*) FROM attributes WHERE object_id = ?",
                (object_id,),
            ).fetchone()[0]
            ts_count = conn.execute(
                "SELECT count(*) FROM tabular_sections WHERE object_id = ?",
                (object_id,),
            ).fetchone()[0]
        return {
            "object": dict(row),
            "help_pages": [dict(r) for r in help_pages],
            "chunks": [dict(r) for r in chunks],
            "attributes_count": int(attr_count),
            "tabular_sections_count": int(ts_count),
        }

    def get_object_fields(
        self,
        object_type: str,
        name: str,
        *,
        config_id: int | None = None,
        configuration_name: str | None = None,
    ) -> dict[str, object] | None:
        with self.connect() as conn:
            sql = """
                SELECT o.id
                FROM metadata_objects o
                JOIN configurations cfg ON cfg.id = o.config_id
                WHERE o.object_type = ? AND o.name = ?
            """
            params: list[object] = [object_type, name]
            if config_id is not None:
                sql += " AND o.config_id = ?"
                params.append(config_id)
            elif configuration_name:
                sql += " AND cfg.name = ?"
                params.append(configuration_name)
            row = conn.execute(sql, params).fetchone()
            if row is None:
                return None
            object_id = int(row["id"])

            attributes = conn.execute(
                """
                SELECT name, type_repr, synonym, comment, is_required
                FROM attributes
                WHERE object_id = ? AND parent_kind = 'object'
                ORDER BY id
                """,
                (object_id,),
            ).fetchall()

            dimensions = conn.execute(
                """
                SELECT name, type_repr, synonym, comment, is_required
                FROM attributes
                WHERE object_id = ? AND parent_kind = 'dimension'
                ORDER BY id
                """,
                (object_id,),
            ).fetchall()

            resources = conn.execute(
                """
                SELECT name, type_repr, synonym, comment, is_required
                FROM attributes
                WHERE object_id = ? AND parent_kind = 'resource'
                ORDER BY id
                """,
                (object_id,),
            ).fetchall()

            tabular_rows = conn.execute(
                """
                SELECT name, synonym, comment
                FROM tabular_sections
                WHERE object_id = ?
                ORDER BY id
                """,
                (object_id,),
            ).fetchall()

            tabular_sections: list[dict[str, object]] = []
            for ts in tabular_rows:
                ts_name = str(ts["name"])
                ts_attrs = conn.execute(
                    """
                    SELECT name, type_repr, synonym, comment, is_required
                    FROM attributes
                    WHERE object_id = ? AND parent_kind = 'tabular_section'
                      AND parent_name = ?
                    ORDER BY id
                    """,
                    (object_id, ts_name),
                ).fetchall()
                tabular_sections.append(
                    {
                        "name": ts_name,
                        "synonym": str(ts["synonym"] or ""),
                        "comment": str(ts["comment"] or ""),
                        "attributes": [
                            {
                                "name": str(a["name"]),
                                "type_repr": str(a["type_repr"] or ""),
                                "synonym": str(a["synonym"] or ""),
                                "comment": str(a["comment"] or ""),
                                "is_required": bool(a["is_required"]),
                            }
                            for a in ts_attrs
                        ],
                    }
                )

        return {
            "attributes": [
                {
                    "name": str(a["name"]),
                    "type_repr": str(a["type_repr"] or ""),
                    "synonym": str(a["synonym"] or ""),
                    "comment": str(a["comment"] or ""),
                    "is_required": bool(a["is_required"]),
                }
                for a in attributes
            ],
            "dimensions": [
                {
                    "name": str(d["name"]),
                    "type_repr": str(d["type_repr"] or ""),
                    "synonym": str(d["synonym"] or ""),
                    "comment": str(d["comment"] or ""),
                    "is_required": bool(d["is_required"]),
                }
                for d in dimensions
            ],
            "resources": [
                {
                    "name": str(r["name"]),
                    "type_repr": str(r["type_repr"] or ""),
                    "synonym": str(r["synonym"] or ""),
                    "comment": str(r["comment"] or ""),
                    "is_required": bool(r["is_required"]),
                }
                for r in resources
            ],
            "tabular_sections": tabular_sections,
        }

    def get_chunk_text(
        self,
        object_type: str,
        name: str,
        chunk_index: int = 0,
        *,
        config_id: int | None = None,
        configuration_name: str | None = None,
    ) -> str | None:
        with self.connect() as conn:
            sql = """
                SELECT c.text
                FROM chunks c
                JOIN metadata_objects o ON o.id = c.object_id
                JOIN configurations cfg ON cfg.id = o.config_id
                WHERE o.object_type = ? AND o.name = ? AND c.chunk_index = ?
            """
            params: list[object] = [object_type, name, chunk_index]
            if config_id is not None:
                sql += " AND o.config_id = ?"
                params.append(config_id)
            elif configuration_name:
                sql += " AND cfg.name = ?"
                params.append(configuration_name)
            row = conn.execute(sql, params).fetchone()
        return str(row["text"]) if row else None
